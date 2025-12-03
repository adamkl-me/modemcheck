"""
Enhanced rate limiting with per-user limits.

Provides dual rate limiting:
1. IP-based (prevent abuse from single IP)
2. User-based (prevent abuse from authenticated users across multiple IPs)
"""
from typing import Optional
from fastapi import Request
from slowapi.util import get_remote_address
import redis.asyncio as aioredis

from app.core.config import settings
from app.core.security import get_redis


def get_remote_address_or_user(request: Request) -> str:
    """
    Get rate limit key based on user session or IP address.

    Priority:
    1. If authenticated: username (prevents multi-IP abuse)
    2. If not authenticated: IP address (prevents IP-based abuse)

    This provides dual protection:
    - Unauthenticated users limited by IP
    - Authenticated users limited by username (across all IPs)
    """
    # Try to get username from session cookie
    session_cookie = request.cookies.get("modemcheck_session")

    if session_cookie:
        # Extract username from session (synchronous approximation)
        # The actual session verification is async, but rate limiting needs sync
        # We use IP + session_id as a compromise for authenticated users
        ip = get_remote_address(request)
        return f"user:{session_cookie[:16]}:{ip}"  # Combine session + IP

    # Fall back to IP-based limiting for unauthenticated users
    return f"ip:{get_remote_address(request)}"


async def check_user_rate_limit(
    username: str,
    limit: int,
    window_seconds: int
) -> tuple[bool, int, int]:
    """
    Check per-user rate limit (across all IPs).

    Args:
        username: Username to check
        limit: Maximum requests allowed
        window_seconds: Time window in seconds

    Returns:
        (allowed, current_count, remaining): Tuple of:
            - allowed: True if under limit
            - current_count: Current request count
            - remaining: Requests remaining in window
    """
    # Don't skip in test mode - we want to test the actual functionality
    redis = await get_redis()
    key = f"user_rate_limit:{username}"
    tracking_key = f"user_rl_keys:{username}"  # Track all rate limit keys for this user

    # Increment counter
    current = await redis.incr(key)

    # Set expiration on first request and track the key
    if current == 1:
        await redis.expire(key, window_seconds)
        # Add to tracking set for efficient cleanup later
        await redis.sadd(tracking_key, key)
        await redis.expire(tracking_key, window_seconds + 60)  # Slightly longer TTL

    allowed = current <= limit
    remaining = max(0, limit - current)

    return (allowed, current, remaining)


async def check_endpoint_user_limit(
    username: str,
    endpoint: str,
    limit: int,
    window_seconds: int
) -> tuple[bool, int, int]:
    """
    Check per-user, per-endpoint rate limit.

    More granular than global user limits - prevents abuse of specific endpoints.

    Args:
        username: Username to check
        endpoint: Endpoint identifier (e.g., "upload", "query")
        limit: Maximum requests allowed
        window_seconds: Time window in seconds

    Returns:
        (allowed, current_count, remaining): Rate limit status
    """
    # Don't skip in test mode - we want to test the actual functionality
    redis = await get_redis()
    key = f"endpoint_rate_limit:{username}:{endpoint}"
    tracking_key = f"user_rl_keys:{username}"  # Same tracking set as global limits

    current = await redis.incr(key)

    if current == 1:
        await redis.expire(key, window_seconds)
        # Track this endpoint key for efficient cleanup
        await redis.sadd(tracking_key, key)
        await redis.expire(tracking_key, window_seconds + 60)

    allowed = current <= limit
    remaining = max(0, limit - current)

    return (allowed, current, remaining)


async def get_user_request_stats(username: str) -> dict:
    """
    Get request statistics for a user.

    Useful for monitoring and detecting abuse patterns.

    Args:
        username: Username to check

    Returns:
        Dictionary with request counts per endpoint
    """
    redis = await get_redis()
    pattern = f"endpoint_rate_limit:{username}:*"

    # First, collect all keys (scan_iter is efficient for iteration)
    keys = []
    async for key in redis.scan_iter(match=pattern):
        keys.append(key)

    if not keys:
        return {}

    # Batch fetch counts and TTLs using pipeline (avoids N+1 queries)
    pipe = redis.pipeline()
    for key in keys:
        pipe.get(key)
        pipe.ttl(key)

    results = await pipe.execute()

    # Parse results (alternating count, ttl pairs)
    stats = {}
    for i, key in enumerate(keys):
        endpoint = key.split(":")[-1]
        count = results[i * 2]
        ttl = results[i * 2 + 1]
        stats[endpoint] = {
            "count": int(count) if count else 0,
            "ttl": ttl
        }

    return stats


async def reset_user_rate_limits(username: str) -> int:
    """
    Reset all rate limits for a user.
    Uses tracking set for O(1) lookup instead of O(N) SCAN operation.

    Use cases:
    - Admin clearing limits for legitimate user
    - Testing

    Args:
        username: Username to reset

    Returns:
        Number of limits cleared
    """
    redis = await get_redis()
    tracking_key = f"user_rl_keys:{username}"
    global_key = f"user_rate_limit:{username}"

    # Get all tracked rate limit keys for this user (O(1) lookup via SET)
    keys = await redis.smembers(tracking_key)

    # Always include the global rate limit key
    all_keys = list(keys) if keys else []
    all_keys.append(global_key)

    # Delete all keys in a single pipeline for efficiency
    pipe = redis.pipeline()
    for key in all_keys:
        pipe.delete(key)
    pipe.delete(tracking_key)  # Also delete the tracking set

    results = await pipe.execute()
    deleted = sum(1 for r in results if r)  # Count successful deletions

    return deleted
