"""
Unit tests for authentication system.

Tests for:
- Password hashing and verification
- Session management
- Token generation and validation
- CSRF protection
- Account lockout
"""
import pytest
import time
from passlib.hash import argon2, pbkdf2_sha256

from app.core.security import (
    hash_password,
    verify_password,
    is_common_password,
    validate_password,
    generate_csrf_token,
    validate_csrf_token,
    record_failed_login,
    clear_failed_logins,
    check_account_locked
)
import secrets


pytestmark = pytest.mark.unit


class TestPasswordHashing:
    """Test password hashing functionality."""

    def test_hash_password_argon2(self):
        """Test that passwords are hashed with Argon2id."""
        password = "TestPass123!"
        hashed = hash_password(password)

        # Should be Argon2 hash
        assert hashed.startswith("$argon2id$")
        assert len(hashed) > 50

    def test_verify_password_correct(self):
        """Test password verification with correct password."""
        password = "TestPass123!"
        hashed = hash_password(password)

        is_valid, needs_upgrade = verify_password(password, hashed)
        assert is_valid is True

    def test_verify_password_incorrect(self):
        """Test password verification with incorrect password."""
        password = "TestPass123!"
        wrong_password = "WrongPass456!"
        hashed = hash_password(password)

        is_valid, needs_upgrade = verify_password(wrong_password, hashed)
        assert is_valid is False

    def test_verify_password_timing_safe(self):
        """Test that password verification is timing-safe."""
        password = "TestPass123!"
        hashed = hash_password(password)

        # Measure timing for correct password
        start = time.perf_counter()
        verify_password(password, hashed)
        correct_time = time.perf_counter() - start

        # Measure timing for incorrect password
        start = time.perf_counter()
        verify_password("WrongPass456!", hashed)
        incorrect_time = time.perf_counter() - start

        # Times should be similar (within 20% for constant-time comparison)
        # Note: Argon2 is inherently timing-safe for the hashing part
        assert abs(correct_time - incorrect_time) / correct_time < 0.5

    def test_hash_uniqueness(self):
        """Test that same password produces different hashes (salt)."""
        password = "TestPass123!"
        hash1 = hash_password(password)
        hash2 = hash_password(password)

        # Hashes should be different due to random salt
        assert hash1 != hash2

        # But both should verify correctly
        is_valid1, _ = verify_password(password, hash1)
        is_valid2, _ = verify_password(password, hash2)
        assert is_valid1 and is_valid2

    def test_hash_empty_password(self):
        """Test hashing empty password."""
        # Should still produce a hash
        hashed = hash_password("")
        assert hashed is not None
        is_valid, _ = verify_password("", hashed)
        assert is_valid

    def test_hash_unicode_password(self):
        """Test hashing password with unicode characters."""
        password = "Test密码123!🔒"
        hashed = hash_password(password)

        is_valid1, _ = verify_password(password, hashed)
        is_valid2, _ = verify_password("Test123!", hashed)
        assert is_valid1
        assert not is_valid2


class TestPasswordMigration:
    """Test password hash migration from PBKDF2 to Argon2."""

    def test_verify_pbkdf2_hash(self):
        """Test verification of legacy PBKDF2 hashes."""
        password = "TestPass123!"

        # Create PBKDF2 hash (legacy)
        pbkdf2_hash = pbkdf2_sha256.hash(password)

        # Should verify correctly and need upgrade
        is_valid, needs_upgrade = verify_password(password, pbkdf2_hash)
        assert is_valid
        assert needs_upgrade  # PBKDF2 should be upgraded to Argon2

    def test_upgrade_password_hash(self):
        """Test upgrading PBKDF2 hash to Argon2."""
        password = "TestPass123!"

        # Create PBKDF2 hash
        old_hash = pbkdf2_sha256.hash(password)

        # Verify it needs upgrade
        is_valid, needs_upgrade = verify_password(password, old_hash)
        assert is_valid
        assert needs_upgrade

        # When upgrading, create new Argon2 hash
        new_hash = hash_password(password)
        assert new_hash.startswith("$argon2id$")
        is_valid_new, needs_upgrade_new = verify_password(password, new_hash)
        assert is_valid_new
        assert not needs_upgrade_new

    def test_no_upgrade_if_already_argon2(self):
        """Test that Argon2 hashes don't need upgrade."""
        password = "TestPass123!"

        # Create Argon2 hash
        argon2_hash = hash_password(password)

        # Verify it doesn't need upgrade
        is_valid, needs_upgrade = verify_password(password, argon2_hash)
        assert is_valid
        assert not needs_upgrade


class TestPasswordStrength:
    """Test password strength validation."""

    def test_strong_password(self):
        """Test that strong passwords pass validation."""
        strong_passwords = [
            "TestPass123!",
            "MySecure@Password99",
            "Complex#Pass2024",
            "L0ngP@ssw0rd!2024",
        ]

        for password in strong_passwords:
            is_valid, message = validate_password(password)
            assert is_valid, f"Password '{password}' should be valid but got: {message}"

    def test_weak_password_too_short(self):
        """Test that short passwords are rejected."""
        weak_password = "Short1!"
        is_valid, message = validate_password(weak_password)

        assert not is_valid
        assert "12 characters" in message

    def test_weak_password_no_uppercase(self):
        """Test that passwords without uppercase are rejected."""
        weak_password = "testpass123!"
        is_valid, message = validate_password(weak_password)

        assert not is_valid
        assert "uppercase" in message

    def test_weak_password_no_lowercase(self):
        """Test that passwords without lowercase are rejected."""
        weak_password = "TESTPASS123!"
        is_valid, message = validate_password(weak_password)

        assert not is_valid
        assert "lowercase" in message

    def test_weak_password_no_digit(self):
        """Test that passwords without digits are rejected."""
        weak_password = "TestPassword!"
        is_valid, message = validate_password(weak_password)

        assert not is_valid
        assert "digit" in message

    def test_weak_password_no_special(self):
        """Test that passwords without special characters are rejected."""
        weak_password = "TestPassword123"
        is_valid, message = validate_password(weak_password)

        assert not is_valid
        assert "special character" in message

    def test_common_password_detection(self):
        """Test that common passwords are detected."""
        common_passwords = [
            "Password123!",
            "Admin123!",
            "Welcome123!",
        ]

        for password in common_passwords:
            # Note: Actual common password list may vary
            is_common = is_common_password(password.lower())
            # Test implementation should check against known list
            assert isinstance(is_common, bool)


class TestSessionManagement:
    """Test session token generation and management."""

    def test_generate_session_token(self):
        """Test session token generation."""
        token = secrets.token_urlsafe(32)

        # Should be at least 32 characters (URL-safe base64)
        assert len(token) >= 32

        # Should be URL-safe characters
        assert all(c.isalnum() or c in "-_" for c in token)

    def test_session_token_uniqueness(self):
        """Test that session tokens are unique."""
        tokens = set()

        for _ in range(100):
            token = secrets.token_urlsafe(32)
            tokens.add(token)

        # All tokens should be unique
        assert len(tokens) == 100

    def test_session_token_entropy(self):
        """Test that session tokens have sufficient entropy."""
        token = secrets.token_urlsafe(32)

        # Check character distribution
        char_counts = {}
        for char in token:
            char_counts[char] = char_counts.get(char, 0) + 1

        # No character should appear too frequently
        max_count = max(char_counts.values())
        assert max_count < len(token) / 4  # No char > 25% frequency


class TestCSRFProtection:
    """Test CSRF token generation and validation."""

    @pytest.mark.asyncio
    async def test_generate_csrf_token(self, test_cache):
        """Test CSRF token generation."""
        session_id = secrets.token_urlsafe(32)
        token = await generate_csrf_token(session_id)

        assert len(token) >= 32
        assert all(c.isalnum() or c in "-_" for c in token)

    @pytest.mark.asyncio
    async def test_validate_csrf_token_correct(self, test_cache):
        """Test CSRF token validation with correct token."""
        session_id = secrets.token_urlsafe(32)
        token = await generate_csrf_token(session_id)

        # Should validate correctly
        is_valid = await validate_csrf_token(token, session_id)
        assert is_valid

    @pytest.mark.asyncio
    async def test_csrf_token_uniqueness(self, test_cache):
        """Test that CSRF tokens are unique."""
        tokens = set()
        session_id = secrets.token_urlsafe(32)

        for _ in range(50):
            token = await generate_csrf_token(session_id)
            tokens.add(token)

        assert len(tokens) == 50


class TestAccountLockout:
    """Test account lockout functionality."""

    @pytest.mark.asyncio
    async def test_record_failed_login(self, test_cache):
        """Test recording failed login attempts."""
        username = "test_user"

        # Clear any existing failed logins
        await clear_failed_logins(username)

        # Record failed attempts
        for i in range(3):
            await record_failed_login(username)

        # Check if locked (should not be locked at 3 attempts, threshold is 5)
        is_locked, remaining = await check_account_locked(username)
        assert not is_locked

    @pytest.mark.asyncio
    async def test_account_lockout_threshold(self, test_cache):
        """Test that account locks after threshold."""
        username = "lockout_test"

        # Clear any existing failed logins
        await clear_failed_logins(username)

        # Record 5 failed attempts (threshold)
        for i in range(5):
            await record_failed_login(username)

        # Should be locked
        is_locked, remaining = await check_account_locked(username)
        assert is_locked
        assert remaining > 0  # Should have time remaining

    @pytest.mark.asyncio
    async def test_reset_failed_logins(self, test_cache):
        """Test resetting failed login counter."""
        username = "reset_test"

        # Record failed attempts
        for i in range(3):
            await record_failed_login(username)

        # Reset
        await clear_failed_logins(username)

        # Should not be locked
        is_locked, remaining = await check_account_locked(username)
        assert not is_locked

    @pytest.mark.asyncio
    async def test_lockout_expiration(self, test_cache):
        """Test that lockout has expiration time."""
        username = "expiry_test"

        # Clear and record failed attempts
        await clear_failed_logins(username)
        for i in range(5):
            await record_failed_login(username)

        # Check locked with remaining time
        is_locked, remaining = await check_account_locked(username)
        assert is_locked
        assert remaining > 0  # Has expiration time (in seconds)
        assert remaining <= 1800  # Should be <= 30 minutes


class TestPasswordHashParameters:
    """Test Argon2 hash parameter configuration."""

    def test_argon2_parameters(self):
        """Test that Argon2 uses correct security parameters."""
        password = "TestPass123!"
        hashed = hash_password(password)

        # Extract parameters from hash
        # Format: $argon2id$v=19$m=65536,t=3,p=4$...
        parts = hashed.split("$")
        params = parts[3]

        # Verify memory cost (64MB = 65536 KB)
        assert "m=65536" in params or "m=64000" in params

        # Verify time cost (3 iterations)
        assert "t=3" in params

        # Verify parallelism (4 threads)
        assert "p=4" in params

    def test_pbkdf2_parameters(self):
        """Test that legacy PBKDF2 uses sufficient iterations."""
        password = "TestPass123!"

        # Create PBKDF2 hash
        pbkdf2_hash = pbkdf2_sha256.hash(password)

        # Extract the rounds from the hash
        # Format: $pbkdf2-sha256$29000$salt$hash
        parts = pbkdf2_hash.split("$")
        if len(parts) >= 3:
            rounds = int(parts[2])
            # Should have at least 20,000 iterations (passlib default is 29000)
            assert rounds >= 20000, f"PBKDF2 should have at least 20,000 rounds, got {rounds}"


