"""
Unit tests for CSRF token one-time use and rotation.

Tests for:
- CSRF tokens are deleted after validation (one-time use)
- Token reuse is prevented
- Tokens expire after TTL
"""
import pytest
import time

from app.core.security import (
    generate_csrf_token,
    validate_csrf_token,
    get_redis
)


pytestmark = pytest.mark.unit


@pytest.mark.asyncio
class TestCSRFTokenOneTimeUse:
    """Test CSRF token one-time use functionality."""

    async def test_csrf_token_single_use(self, test_cache):
        """CSRF token should only be valid once."""
        session_id = "test-session-123"

        # Generate token
        csrf_token = await generate_csrf_token(session_id)
        assert csrf_token is not None

        # First validation should succeed
        is_valid = await validate_csrf_token(csrf_token, session_id)
        assert is_valid is True

        # Second validation with same token should fail (token was deleted)
        is_valid_second = await validate_csrf_token(csrf_token, session_id)
        assert is_valid_second is False

    async def test_csrf_token_reuse_prevention(self, test_cache):
        """Same CSRF token cannot be reused even immediately."""
        session_id = "test-session-456"

        # Generate token
        csrf_token = await generate_csrf_token(session_id)

        # Validate once
        is_valid = await validate_csrf_token(csrf_token, session_id)
        assert is_valid is True

        # Try to reuse immediately (should fail)
        is_valid_reuse = await validate_csrf_token(csrf_token, session_id)
        assert is_valid_reuse is False

    async def test_csrf_token_deleted_from_cache(self, test_cache):
        """CSRF token should be deleted from cache after validation."""
        session_id = "test-session-789"

        # Generate token
        csrf_token = await generate_csrf_token(session_id)
        csrf_key = f"csrf:{csrf_token}"

        # Verify token exists in cache
        stored_value = await test_cache.current_backend.get(csrf_key)
        assert stored_value is not None
        assert stored_value == session_id

        # Validate (this should delete the token)
        await validate_csrf_token(csrf_token, session_id)

        # Verify token was deleted from cache
        stored_value_after = await test_cache.current_backend.get(csrf_key)
        assert stored_value_after is None

    async def test_multiple_tokens_independent(self, test_cache):
        """Multiple CSRF tokens for same session should be independent."""
        session_id = "test-session-multi"

        # Generate three tokens
        token1 = await generate_csrf_token(session_id)
        token2 = await generate_csrf_token(session_id)
        token3 = await generate_csrf_token(session_id)

        # Validate token2 (should not affect token1 or token3)
        is_valid_2 = await validate_csrf_token(token2, session_id)
        assert is_valid_2 is True

        # token1 should still be valid
        is_valid_1 = await validate_csrf_token(token1, session_id)
        assert is_valid_1 is True

        # token3 should still be valid
        is_valid_3 = await validate_csrf_token(token3, session_id)
        assert is_valid_3 is True

        # token2 should not be reusable
        is_valid_2_reuse = await validate_csrf_token(token2, session_id)
        assert is_valid_2_reuse is False


@pytest.mark.asyncio
class TestCSRFTokenRotation:
    """Test CSRF token rotation after validation."""

    async def test_token_rotation_pattern(self, test_cache):
        """Simulates token rotation pattern: generate -> validate -> generate new."""
        session_id = "test-session-rotation"

        # Initial token
        token1 = await generate_csrf_token(session_id)

        # Use token1 for request
        is_valid_1 = await validate_csrf_token(token1, session_id)
        assert is_valid_1 is True

        # Generate new token for next request (rotation)
        token2 = await generate_csrf_token(session_id)

        # token1 should not be reusable
        is_valid_1_reuse = await validate_csrf_token(token1, session_id)
        assert is_valid_1_reuse is False

        # token2 should be valid
        is_valid_2 = await validate_csrf_token(token2, session_id)
        assert is_valid_2 is True

        # token2 should not be reusable
        is_valid_2_reuse = await validate_csrf_token(token2, session_id)
        assert is_valid_2_reuse is False

    async def test_token_rotation_new_token_different(self, test_cache):
        """Each rotated token should be unique."""
        session_id = "test-session-unique"

        tokens = []
        for _ in range(5):
            token = await generate_csrf_token(session_id)
            tokens.append(token)

            # Validate to trigger one-time use
            await validate_csrf_token(token, session_id)

        # All tokens should be unique
        assert len(tokens) == len(set(tokens))


@pytest.mark.asyncio
class TestCSRFTokenSecurity:
    """Test CSRF token security properties."""

    async def test_csrf_token_wrong_session(self, test_cache):
        """CSRF token from different session should fail and be consumed."""
        session1 = "session-1"
        session2 = "session-2"

        # Generate token for session1
        csrf_token = await generate_csrf_token(session1)

        # Try to validate with session2 (should fail)
        is_valid = await validate_csrf_token(csrf_token, session2)
        assert is_valid is False

        # Security: Token is consumed even on failed validation (prevents brute force)
        # Trying with correct session should now also fail
        is_valid_after = await validate_csrf_token(csrf_token, session1)
        assert is_valid_after is False  # Token already consumed

    async def test_csrf_token_empty_inputs(self, test_cache):
        """Empty/None inputs should fail validation."""
        session_id = "test-session-empty"

        # Generate valid token
        csrf_token = await generate_csrf_token(session_id)

        # Empty token should fail
        is_valid = await validate_csrf_token("", session_id)
        assert is_valid is False

        # Empty session should fail
        is_valid = await validate_csrf_token(csrf_token, "")
        assert is_valid is False

        # None token should fail
        is_valid = await validate_csrf_token(None, session_id)
        assert is_valid is False

        # None session should fail
        is_valid = await validate_csrf_token(csrf_token, None)
        assert is_valid is False

        # Original token should still be valid (not deleted)
        is_valid_original = await validate_csrf_token(csrf_token, session_id)
        assert is_valid_original is True

    async def test_csrf_token_nonexistent(self, test_cache):
        """Validating nonexistent token should fail."""
        session_id = "test-session-nonexistent"

        # Try to validate token that was never generated
        is_valid = await validate_csrf_token("fake-token-12345", session_id)
        assert is_valid is False


@pytest.mark.asyncio
class TestCSRFTokenAtomicity:
    """Test atomic check-and-delete prevents race conditions."""

    async def test_atomic_validation_prevents_double_use(self, test_cache):
        """Atomic pipeline prevents token from being used twice simultaneously."""
        session_id = "test-session-atomic"

        # Generate token
        csrf_token = await generate_csrf_token(session_id)

        # First validation
        is_valid_1 = await validate_csrf_token(csrf_token, session_id)
        assert is_valid_1 is True

        # Second validation should fail (atomic delete occurred)
        is_valid_2 = await validate_csrf_token(csrf_token, session_id)
        assert is_valid_2 is False

    async def test_pipeline_execution_order(self, test_cache):
        """Verify pipeline executes GET before DELETE."""
        session_id = "test-session-pipeline"

        # Generate token
        csrf_token = await generate_csrf_token(session_id)

        # Validate (GET then DELETE)
        is_valid = await validate_csrf_token(csrf_token, session_id)
        assert is_valid is True  # GET returned the session_id

        # Token should be gone from cache
        csrf_key = f"csrf:{csrf_token}"
        stored_value = await test_cache.current_backend.get(csrf_key)
        assert stored_value is None  # DELETE executed
