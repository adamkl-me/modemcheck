"""
Rate limiting configuration for ModemCheck Cloud v2.

Configured with Redis backend for distributed rate limiting.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# Initialize rate limiter with Redis backend
# Disable rate limiting in test environment to avoid fixture login failures
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=f"redis://{settings.redis_host}:{settings.redis_port}/1",  # Use DB 1 for rate limits
    default_limits=[] , # No default limits - apply per-endpoint
    enabled=not settings.is_test()  # Disable rate limiting during tests
)
