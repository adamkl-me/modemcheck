"""
Tests for init_data module - default admin user creation.

These are pure unit tests that mock all dependencies.

Tests:
- create_default_admin() function
- Idempotency (multiple calls don't create duplicates)
- Environment-specific behavior (test vs production)
- Password security requirements
- Error handling
"""
import pytest
from datetime import datetime
from unittest.mock import patch, AsyncMock, MagicMock

from app.models import User
from app.models.user import UserRole
from app.core.security import hash_password, verify_password


pytestmark = pytest.mark.unit


def create_mock_session():
    """Create a properly configured mock session for testing."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = None  # Default: no users exist
    mock_result.scalars.return_value = mock_scalars
    mock_session.execute.return_value = mock_result
    return mock_session


def create_mock_session_local(mock_session):
    """Create a mock AsyncSessionLocal that returns the mock session."""
    async_session_cm = AsyncMock()
    async_session_cm.__aenter__.return_value = mock_session
    async_session_cm.__aexit__.return_value = None
    return MagicMock(return_value=async_session_cm)


class TestCreateDefaultAdminUnit:
    """Unit tests for create_default_admin function with mocking."""

    @pytest.mark.asyncio
    async def test_creates_admin_when_no_users_exist(self):
        """Test default admin is created when database has no users."""
        from app.core.init_data import create_default_admin

        mock_session = create_mock_session()
        mock_session_local = create_mock_session_local(mock_session)

        # Mock settings for this test
        mock_settings = MagicMock()
        mock_settings.is_test.return_value = True

        # Patch where imports happen: app.core.database.AsyncSessionLocal
        with patch("app.core.database.AsyncSessionLocal", mock_session_local):
            with patch("app.core.config.settings", mock_settings):
                await create_default_admin()

        # Verify a user was added
        mock_session.add.assert_called_once()
        added_user = mock_session.add.call_args[0][0]
        assert added_user.username == "admin"
        assert added_user.role == UserRole.ADMIN
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_create_when_users_exist(self):
        """Test default admin is not created when users already exist."""
        from app.core.init_data import create_default_admin

        mock_session = create_mock_session()

        # Return an existing user
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = User(
            username="existing_user",
            password_hash="hash",
            role=UserRole.BASIC
        )
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        mock_session_local = create_mock_session_local(mock_session)

        with patch("app.core.database.AsyncSessionLocal", mock_session_local):
            await create_default_admin()

        # Verify no user was added
        mock_session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_admin_has_correct_role(self):
        """Test created admin has admin role."""
        from app.core.init_data import create_default_admin

        mock_session = create_mock_session()
        mock_session_local = create_mock_session_local(mock_session)

        mock_settings = MagicMock()
        mock_settings.is_test.return_value = True

        with patch("app.core.database.AsyncSessionLocal", mock_session_local):
            with patch("app.core.config.settings", mock_settings):
                await create_default_admin()

        added_user = mock_session.add.call_args[0][0]
        assert added_user.role == UserRole.ADMIN

    @pytest.mark.asyncio
    async def test_admin_password_is_hashed(self):
        """Test admin password is properly hashed, not stored in plaintext."""
        from app.core.init_data import create_default_admin

        mock_session = create_mock_session()
        mock_session_local = create_mock_session_local(mock_session)

        mock_settings = MagicMock()
        mock_settings.is_test.return_value = True

        with patch("app.core.database.AsyncSessionLocal", mock_session_local):
            with patch("app.core.config.settings", mock_settings):
                await create_default_admin()

        added_user = mock_session.add.call_args[0][0]
        # Password hash should not be plaintext
        assert added_user.password_hash != "AdminPass123!"
        assert added_user.password_hash != "changeme"
        # Password hash should be at least 60 chars (typical for Argon2/bcrypt)
        assert len(added_user.password_hash) >= 60

    @pytest.mark.asyncio
    async def test_admin_has_created_at_timestamp(self):
        """Test admin has created_at timestamp."""
        from app.core.init_data import create_default_admin

        mock_session = create_mock_session()
        mock_session_local = create_mock_session_local(mock_session)

        mock_settings = MagicMock()
        mock_settings.is_test.return_value = True

        before_creation = datetime.utcnow()

        with patch("app.core.database.AsyncSessionLocal", mock_session_local):
            with patch("app.core.config.settings", mock_settings):
                await create_default_admin()

        after_creation = datetime.utcnow()

        added_user = mock_session.add.call_args[0][0]
        assert added_user.created_at is not None
        assert before_creation <= added_user.created_at <= after_creation


class TestEnvironmentSpecificBehavior:
    """Tests for environment-specific default admin behavior."""

    @pytest.mark.asyncio
    async def test_test_env_uses_test_password(self):
        """Test that test environment uses TestPass123! password."""
        from app.core.init_data import create_default_admin

        mock_session = create_mock_session()
        mock_session_local = create_mock_session_local(mock_session)

        mock_settings = MagicMock()
        mock_settings.is_test.return_value = True

        with patch("app.core.database.AsyncSessionLocal", mock_session_local):
            with patch("app.core.config.settings", mock_settings):
                await create_default_admin()

        added_user = mock_session.add.call_args[0][0]
        # Verify test password works (verify_password returns tuple)
        is_valid, _ = verify_password("TestPass123!", added_user.password_hash)
        assert is_valid

    @pytest.mark.asyncio
    async def test_test_env_must_change_password_false(self):
        """Test that test environment sets must_change_password to False."""
        from app.core.init_data import create_default_admin

        mock_session = create_mock_session()
        mock_session_local = create_mock_session_local(mock_session)

        mock_settings = MagicMock()
        mock_settings.is_test.return_value = True

        with patch("app.core.database.AsyncSessionLocal", mock_session_local):
            with patch("app.core.config.settings", mock_settings):
                await create_default_admin()

        added_user = mock_session.add.call_args[0][0]
        assert added_user.must_change_password is False

    @pytest.mark.asyncio
    async def test_production_env_uses_changeme_password(self):
        """Test that production environment uses changeme password."""
        from app.core.init_data import create_default_admin

        mock_session = create_mock_session()
        mock_session_local = create_mock_session_local(mock_session)

        mock_settings = MagicMock()
        mock_settings.is_test.return_value = False

        with patch("app.core.database.AsyncSessionLocal", mock_session_local):
            with patch("app.core.config.settings", mock_settings):
                await create_default_admin()

        added_user = mock_session.add.call_args[0][0]
        # Verify production password works (verify_password returns tuple)
        is_valid, _ = verify_password("changeme", added_user.password_hash)
        assert is_valid
        # Must change password should be True
        assert added_user.must_change_password is True


class TestPasswordSecurity:
    """Tests for password security of default admin."""

    @pytest.mark.asyncio
    async def test_password_can_be_verified(self):
        """Test admin password can be verified after creation."""
        from app.core.init_data import create_default_admin

        mock_session = create_mock_session()
        mock_session_local = create_mock_session_local(mock_session)

        mock_settings = MagicMock()
        mock_settings.is_test.return_value = True

        with patch("app.core.database.AsyncSessionLocal", mock_session_local):
            with patch("app.core.config.settings", mock_settings):
                await create_default_admin()

        added_user = mock_session.add.call_args[0][0]
        # Test environment uses TestPass123! (verify_password returns tuple)
        is_valid, _ = verify_password("TestPass123!", added_user.password_hash)
        assert is_valid

    @pytest.mark.asyncio
    async def test_wrong_password_fails_verification(self):
        """Test wrong password fails verification."""
        from app.core.init_data import create_default_admin

        mock_session = create_mock_session()
        mock_session_local = create_mock_session_local(mock_session)

        mock_settings = MagicMock()
        mock_settings.is_test.return_value = True

        with patch("app.core.database.AsyncSessionLocal", mock_session_local):
            with patch("app.core.config.settings", mock_settings):
                await create_default_admin()

        added_user = mock_session.add.call_args[0][0]
        # verify_password returns (is_valid, needs_upgrade) tuple
        is_valid, _ = verify_password("wrong_password", added_user.password_hash)
        assert not is_valid


class TestErrorHandling:
    """Tests for error handling in create_default_admin."""

    @pytest.mark.asyncio
    async def test_handles_duplicate_key_error_gracefully(self):
        """Test duplicate key errors are handled gracefully."""
        from app.core.init_data import create_default_admin

        mock_session = create_mock_session()

        # Simulate duplicate key error on commit
        mock_session.commit.side_effect = Exception("duplicate key value violates unique constraint")

        mock_session_local = create_mock_session_local(mock_session)

        # Should not raise - handles duplicate key errors
        with patch("app.core.database.AsyncSessionLocal", mock_session_local):
            await create_default_admin()

        # Rollback should have been called
        mock_session.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_on_other_errors(self):
        """Test non-duplicate-key errors are re-raised."""
        from app.core.init_data import create_default_admin

        mock_session = create_mock_session()

        # Simulate a different error
        mock_session.commit.side_effect = Exception("connection refused")

        mock_session_local = create_mock_session_local(mock_session)

        # Should raise the error
        with pytest.raises(Exception, match="connection refused"):
            with patch("app.core.database.AsyncSessionLocal", mock_session_local):
                await create_default_admin()


class TestDatabaseState:
    """Tests for database state verification."""

    @pytest.mark.asyncio
    async def test_only_creates_one_admin(self):
        """Test only one admin is created per call."""
        from app.core.init_data import create_default_admin

        mock_session = create_mock_session()
        mock_session_local = create_mock_session_local(mock_session)

        mock_settings = MagicMock()
        mock_settings.is_test.return_value = True

        with patch("app.core.database.AsyncSessionLocal", mock_session_local):
            with patch("app.core.config.settings", mock_settings):
                await create_default_admin()

        # Should only add one user
        assert mock_session.add.call_count == 1

    @pytest.mark.asyncio
    async def test_checks_for_any_user_not_just_admin(self):
        """Test function checks for any existing user, not just admin."""
        from app.core.init_data import create_default_admin

        mock_session = create_mock_session()
        mock_result = MagicMock()
        mock_scalars = MagicMock()

        # Return a non-admin user
        mock_scalars.first.return_value = User(
            username="regular_user",  # Not "admin"
            password_hash="hash",
            role=UserRole.BASIC
        )
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        mock_session_local = create_mock_session_local(mock_session)

        with patch("app.core.database.AsyncSessionLocal", mock_session_local):
            await create_default_admin()

        # Should not add any user since a user exists
        mock_session.add.assert_not_called()
