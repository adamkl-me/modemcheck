"""
Configuration management using Pydantic Settings.

Environment variables are loaded from .env file or system environment.
"""
from typing import List, Optional
from pydantic import Field, validator, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Application
    app_name: str = "ModemCheck Cloud API v2"
    app_env: str = Field(default="production", description="Environment: development, production, test")
    debug: bool = Field(default=False, description="Debug mode")

    # Server
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, description="Server port")
    workers: int = Field(default=4, description="Number of worker processes")

    # Security
    secret_key: str = Field(..., description="Secret key for JWT/sessions (REQUIRED)")
    csrf_secret_key: str = Field(..., description="CSRF protection secret key (REQUIRED)")
    algorithm: str = Field(default="HS256", description="JWT algorithm")

    # Session Management
    session_ttl: int = Field(default=3600, description="Session TTL in seconds (1 hour)")
    session_cookie_name: str = Field(default="modemcheck_session", description="Session cookie name")
    session_cookie_httponly: bool = Field(default=True, description="HttpOnly flag for session cookie")
    session_cookie_samesite: str = Field(default="strict", description="SameSite flag: strict, lax, none")

    # Account Security
    max_failed_logins: int = Field(default=5, description="Max failed login attempts before lockout")
    account_lockout_duration: int = Field(default=1800, description="Account lockout duration in seconds (30 min)")
    min_password_length: int = Field(default=12, description="Minimum password length")

    # Database
    database_url: str = Field(..., description="PostgreSQL database URL (REQUIRED)")
    db_pool_size: int = Field(default=25, description="Database connection pool size per worker (25 × 4 workers = 100 connections)")
    db_max_overflow: int = Field(default=10, description="Max connections beyond pool_size (allows bursts to 140 total)")
    db_pool_recycle: int = Field(default=3600, description="Connection recycle time in seconds")
    db_pool_timeout: int = Field(default=30, description="Timeout waiting for connection from pool")
    db_statement_timeout: int = Field(default=60000, description="Statement timeout in milliseconds")
    db_echo: bool = Field(default=False, description="Echo SQL queries (debug)")

    # Redis
    redis_host: str = Field(default="localhost", description="Redis host")
    redis_port: int = Field(default=6379, description="Redis port")
    redis_db: int = Field(default=0, description="Redis database number")
    redis_password: Optional[str] = Field(default=None, description="Redis password (optional)")
    redis_ssl: bool = Field(default=False, description="Use SSL for Redis connection")

    # CORS
    allowed_origins: str = Field(
        ...,
        description="Allowed CORS origins (REQUIRED - comma-separated, e.g., ALLOWED_ORIGINS=http://localhost:3000,https://example.com)"
    )

    # Rate Limiting
    upload_rate_limit: str = Field(default="60/minute", description="Upload endpoint rate limit")
    auth_rate_limit: str = Field(default="30/minute", description="Auth endpoint rate limit")
    api_query_rate_limit: str = Field(default="300/second", description="API query endpoint rate limit")
    api_admin_rate_limit: str = Field(default="100/minute", description="Admin endpoint rate limit")
    api_data_mgmt_rate_limit: str = Field(default="50/minute", description="Data management endpoint rate limit")

    # File Upload Limits
    max_upload_size: int = Field(default=10 * 1024 * 1024, description="Max upload size in bytes (10MB)")
    max_bulk_upload_files: int = Field(default=1000, description="Max files in bulk upload")
    max_bulk_download_size: int = Field(default=100 * 1024 * 1024, description="Max bulk download size (100MB)")

    # Common Passwords File
    common_passwords_file: str = Field(
        default="/app/common_passwords.txt",
        description="Path to common passwords file"
    )

    # Cache Settings
    api_key_cache_ttl: int = Field(default=300, description="API key cache TTL in seconds (5 minutes)")
    csrf_token_ttl: int = Field(default=3600, description="CSRF token TTL in seconds (1 hour)")

    def get_origins_list(self) -> List[str]:
        """Get CORS origins as a list."""
        if self.allowed_origins == "*":
            return ["*"]
        return [origin.strip() for origin in self.allowed_origins.split(",")]

    @validator("debug", pre=True)
    def parse_debug(cls, v):
        """Parse debug flag from string."""
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes", "on")
        return v

    @validator("debug")
    def validate_production_debug(cls, v, values):
        """
        Prevent debug mode in production environment.

        Security: Debug mode exposes sensitive information:
        - OpenAPI docs at /docs and /redoc show API structure
        - Stack traces leak internal implementation details
        - SQL query echoing may expose sensitive data
        """
        app_env = values.get("app_env", "production")
        if app_env.lower() == "production" and v:
            raise ValueError(
                "Debug mode cannot be enabled in production environment. "
                "Set DEBUG=false or APP_ENV=development"
            )
        return v

    @validator("allowed_origins")
    def validate_cors_wildcard(cls, v, values):
        """
        Prevent CORS wildcard (*) in production environment.

        Security: CORS wildcard allows any origin to make requests:
        - Exposes API to CSRF attacks from any website
        - Allows data exfiltration from malicious sites
        - Bypasses same-origin policy protections

        Test environment is exempt to simplify testing.
        """
        app_env = values.get("app_env", "production")
        if app_env.lower() == "production" and v == "*":
            raise ValueError(
                "CORS wildcard (*) is not allowed in production environment. "
                "Set ALLOWED_ORIGINS to specific domains (e.g., https://example.com,https://admin.example.com)"
            )
        return v

    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.app_env.lower() == "production"

    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.app_env.lower() == "development"

    def is_test(self) -> bool:
        """Check if running in test environment."""
        return self.app_env.lower() == "test"


# Global settings instance
settings = Settings()
