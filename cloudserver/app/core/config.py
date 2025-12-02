"""
Configuration management using Pydantic Settings.

Environment variables are loaded from .env file or system environment.
"""
import ipaddress
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

    # Database Connection Pool
    # SCALING LIMITS: With default settings (25 pool + 10 overflow) × 4 workers = 140 max connections
    # PostgreSQL default max_connections is typically 100-200. Before scaling horizontally:
    # 1. Check PostgreSQL max_connections: SHOW max_connections;
    # 2. Consider PgBouncer for connection pooling at scale (1000+ clients)
    # 3. Each additional worker adds (pool_size + max_overflow) connections
    database_url: str = Field(..., description="PostgreSQL database URL (REQUIRED)")
    db_pool_size: int = Field(default=25, description="Connection pool size per worker. Total = pool_size × workers")
    db_max_overflow: int = Field(default=10, description="Burst connections beyond pool_size. Total max = (pool_size + overflow) × workers")
    db_pool_recycle: int = Field(default=3600, description="Connection recycle time in seconds (prevents stale connections)")
    db_pool_timeout: int = Field(default=30, description="Timeout waiting for connection from pool (increase for high concurrency)")
    db_statement_timeout: int = Field(default=60000, description="Statement timeout in milliseconds (prevents long-running queries)")
    db_echo: bool = Field(default=False, description="Echo SQL queries (debug only, disable in production)")

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
    # SCALING CONSIDERATIONS: Rate limits are per-IP. At scale (1000+ clients):
    # - upload_rate_limit: 1000 clients × 60/min = 60k uploads/min capacity
    # - config_sync_rate_limit: 1000 clients × 15/hr = 15000 syncs/hr - increase if clients retry frequently
    # - During deployments or bulk config pushes, temporarily increase limits or disable rate limiting
    # Format: "{count}/{period}" where period is: second, minute, hour, day
    upload_rate_limit: str = Field(default="60/minute", description="Upload endpoint rate limit per IP")
    auth_rate_limit: str = Field(default="30/minute", description="Auth endpoint rate limit (brute-force protection)")
    api_query_rate_limit: str = Field(default="300/second", description="API query endpoint rate limit (high for dashboards)")
    api_admin_rate_limit: str = Field(default="100/minute", description="Admin endpoint rate limit")
    api_data_mgmt_rate_limit: str = Field(default="50/minute", description="Data management endpoint rate limit (bulk ops)")
    config_preflight_rate_limit: str = Field(default="10/hour", description="Config preflight check rate limit per client IP")
    config_sync_rate_limit: str = Field(default="15/hour", description="Config sync endpoint rate limit per client IP")
    config_sse_rate_limit: str = Field(default="10/minute", description="Config SSE stream endpoint rate limit")

    # File Upload Limits
    max_upload_size: int = Field(default=10 * 1024 * 1024, description="Max upload size in bytes (10MB)")
    max_bulk_upload_files: int = Field(default=1000, description="Max files in bulk upload")
    max_bulk_download_size: int = Field(default=100 * 1024 * 1024, description="Max bulk download size (100MB)")

    # Trusted Proxies (for X-Forwarded-For header validation)
    # SECURITY: Only trust X-Forwarded-For from these IP ranges
    # Default includes Docker internal networks and localhost
    # Format: comma-separated CIDR ranges or IPs
    trusted_proxies: str = Field(
        default="127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16",
        description="Trusted proxy IPs/CIDRs that can set X-Forwarded-For (comma-separated)"
    )

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

    def get_trusted_proxy_networks(self) -> List[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        """Parse trusted_proxies into a list of IP networks."""
        networks = []
        for proxy in self.trusted_proxies.split(","):
            proxy = proxy.strip()
            if not proxy:
                continue
            try:
                # Try to parse as network (CIDR notation)
                if "/" in proxy:
                    networks.append(ipaddress.ip_network(proxy, strict=False))
                else:
                    # Single IP - convert to /32 or /128 network
                    addr = ipaddress.ip_address(proxy)
                    if isinstance(addr, ipaddress.IPv4Address):
                        networks.append(ipaddress.ip_network(f"{proxy}/32"))
                    else:
                        networks.append(ipaddress.ip_network(f"{proxy}/128"))
            except ValueError:
                # Skip invalid entries
                pass
        return networks

    def is_trusted_proxy(self, ip: str) -> bool:
        """Check if an IP address is from a trusted proxy."""
        try:
            addr = ipaddress.ip_address(ip)
            for network in self.get_trusted_proxy_networks():
                if addr in network:
                    return True
            return False
        except ValueError:
            # Invalid IP address
            return False


# Global settings instance
settings = Settings()
