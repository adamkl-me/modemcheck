"""
Rate limiting configuration for ModemCheck Cloud v2.

Configured with Redis backend for distributed rate limiting.
"""
import os
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# Initialize rate limiter with Redis backend
# Disable rate limiting in test environment to avoid fixture login failures
# Check both settings.is_test() and TESTING environment variable for extra safety
_is_testing = settings.is_test() or os.getenv("TESTING", "").lower() in ("true", "1", "yes")

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=f"redis://{settings.redis_host}:{settings.redis_port}/1",  # Use DB 1 for rate limits
    default_limits=[] , # No default limits - apply per-endpoint
    enabled=not _is_testing  # Disable rate limiting during tests
)
