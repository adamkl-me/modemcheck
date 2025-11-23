"""
Unit tests for configuration validation.

Tests for:
- CORS wildcard prevention in production
- Debug mode prevention in production
- Configuration field validation
"""
import os
import pytest
from pydantic import ValidationError

from app.core.config import Settings


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    """
    Clean environment variables that could interfere with Settings instantiation.

    Pydantic's BaseSettings automatically loads environment variables,
    which can override explicit constructor parameters in tests.
    """
    # Remove environment variables that could interfere with tests
    env_vars_to_remove = [
        "DEBUG", "APP_ENV", "ALLOWED_ORIGINS", "SECRET_KEY",
        "CSRF_SECRET_KEY", "DATABASE_URL", "REDIS_HOST", "REDIS_PORT"
    ]
    for var in env_vars_to_remove:
        monkeypatch.delenv(var, raising=False)

    # Create a temporary .env file to prevent loading from /app/.env
    fake_env = tmp_path / ".env"
    fake_env.write_text("")
    monkeypatch.chdir(tmp_path)


class TestCORSValidation:
    """Test CORS configuration validation."""

    def test_cors_wildcard_rejected_in_production(self):
        """CORS wildcard should be rejected in production."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                app_env="production",
                allowed_origins="*",
                secret_key="test-secret",
                csrf_secret_key="test-csrf",
                database_url="postgresql://test"
            )

        assert "CORS wildcard" in str(exc_info.value)

    def test_cors_wildcard_allowed_in_development(self):
        """CORS wildcard should be allowed in development."""
        config = Settings(
            app_env="development",
            allowed_origins="*",
            secret_key="test-secret",
            csrf_secret_key="test-csrf",
            database_url="postgresql://test"
        )

        assert config.allowed_origins == "*"

    def test_cors_wildcard_allowed_in_test(self):
        """CORS wildcard should be allowed in test environment."""
        config = Settings(
            app_env="test",
            allowed_origins="*",
            secret_key="test-secret",
            csrf_secret_key="test-csrf",
            database_url="postgresql://test"
        )

        assert config.allowed_origins == "*"

    def test_cors_specific_origins_in_production(self):
        """Specific CORS origins should be allowed in production."""
        config = Settings(
            app_env="production",
            allowed_origins="https://example.com,https://admin.example.com",
            secret_key="test-secret",
            csrf_secret_key="test-csrf",
            database_url="postgresql://test"
        )

        assert config.allowed_origins == "https://example.com,https://admin.example.com"
        origins_list = config.get_origins_list()
        assert "https://example.com" in origins_list
        assert "https://admin.example.com" in origins_list

    def test_cors_single_origin_in_production(self):
        """Single CORS origin should be allowed in production."""
        config = Settings(
            app_env="production",
            allowed_origins="https://example.com",
            secret_key="test-secret",
            csrf_secret_key="test-csrf",
            database_url="postgresql://test"
        )

        assert config.allowed_origins == "https://example.com"
        origins_list = config.get_origins_list()
        assert origins_list == ["https://example.com"]


class TestDebugModeValidation:
    """Test debug mode validation."""

    def test_debug_mode_rejected_in_production(self):
        """Debug mode should be rejected in production."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                app_env="production",
                debug=True,
                allowed_origins="https://example.com",
                secret_key="test-secret",
                csrf_secret_key="test-csrf",
                database_url="postgresql://test"
            )

        assert "Debug mode cannot be enabled in production" in str(exc_info.value)

    def test_debug_mode_allowed_in_development(self):
        """Debug mode should be allowed in development."""
        config = Settings(
            app_env="development",
            debug=True,
            allowed_origins="*",
            secret_key="test-secret",
            csrf_secret_key="test-csrf",
            database_url="postgresql://test"
        )

        assert config.debug is True

    def test_debug_mode_allowed_in_test(self):
        """Debug mode should be allowed in test environment."""
        config = Settings(
            app_env="test",
            debug=True,
            allowed_origins="*",
            secret_key="test-secret",
            csrf_secret_key="test-csrf",
            database_url="postgresql://test"
        )

        assert config.debug is True

    def test_debug_false_allowed_in_production(self):
        """Debug=false should be allowed in production."""
        config = Settings(
            app_env="production",
            debug=False,
            allowed_origins="https://example.com",
            secret_key="test-secret",
            csrf_secret_key="test-csrf",
            database_url="postgresql://test"
        )

        assert config.debug is False


class TestConfigRequiredFields:
    """Test required field validation."""

    def test_secret_key_required(self):
        """Secret key should be required."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                app_env="production",
                allowed_origins="https://example.com",
                csrf_secret_key="test-csrf",
                database_url="postgresql://test"
            )

        # Should fail due to missing secret_key
        assert "secret_key" in str(exc_info.value).lower()

    def test_csrf_secret_key_required(self):
        """CSRF secret key should be required."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                app_env="production",
                allowed_origins="https://example.com",
                secret_key="test-secret",
                database_url="postgresql://test"
            )

        # Should fail due to missing csrf_secret_key
        assert "csrf_secret_key" in str(exc_info.value).lower()

    def test_database_url_required(self):
        """Database URL should be required."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                app_env="production",
                allowed_origins="https://example.com",
                secret_key="test-secret",
                csrf_secret_key="test-csrf"
            )

        # Should fail due to missing database_url
        assert "database_url" in str(exc_info.value).lower()

    def test_allowed_origins_required(self):
        """Allowed origins should be required."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                app_env="production",
                secret_key="test-secret",
                csrf_secret_key="test-csrf",
                database_url="postgresql://test"
            )

        # Should fail due to missing allowed_origins
        assert "allowed_origins" in str(exc_info.value).lower()


class TestEnvironmentHelpers:
    """Test environment detection helper methods."""

    def test_is_production(self):
        """is_production() should return True in production."""
        config = Settings(
            app_env="production",
            allowed_origins="https://example.com",
            secret_key="test-secret",
            csrf_secret_key="test-csrf",
            database_url="postgresql://test"
        )

        assert config.is_production() is True
        assert config.is_development() is False
        assert config.is_test() is False

    def test_is_development(self):
        """is_development() should return True in development."""
        config = Settings(
            app_env="development",
            allowed_origins="*",
            secret_key="test-secret",
            csrf_secret_key="test-csrf",
            database_url="postgresql://test"
        )

        assert config.is_production() is False
        assert config.is_development() is True
        assert config.is_test() is False

    def test_is_test(self):
        """is_test() should return True in test environment."""
        config = Settings(
            app_env="test",
            allowed_origins="*",
            secret_key="test-secret",
            csrf_secret_key="test-csrf",
            database_url="postgresql://test"
        )

        assert config.is_production() is False
        assert config.is_development() is False
        assert config.is_test() is True
