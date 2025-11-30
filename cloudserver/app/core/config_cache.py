"""
Redis caching for client configurations with stampede prevention.

Caches encrypted configuration blobs to reduce database load during
high-frequency sync operations. Features:

- Cache stampede prevention via per-key locking
- Jittered TTLs to prevent thundering herd
- Automatic cache invalidation on updates
- Fallback to database if cache miss

Cache key format: "config:{api_key}"
TTL: 300±30 seconds (jittered to prevent synchronized expiration)
"""

import asyncio
import logging
import random
import json
import hashlib
from typing import Optional, Dict, Any, Tuple
from datetime import datetime

from app.core.cache import get_cache

logger = logging.getLogger(__name__)
from app.core.errors import ConfigCacheError


# Cache configuration
DEFAULT_TTL = 300  # 5 minutes
TTL_JITTER = 30    # ±30 seconds to prevent thundering herd
LOCK_TIMEOUT = 5   # Maximum time to wait for lock (seconds)
LOCK_TTL = 10      # Lock expiration (seconds)


def _get_config_cache_key(api_key: str, version: Optional[int] = None) -> str:
    """
    Generate cache key for configuration with optional version.

    Versioned keys prevent race conditions during updates:
    - Old: config:{api_key} - stale data possible during invalidation
    - New: config:{api_key}:v{version} - each version has unique key

    Args:
        api_key: Client API key
        version: Optional version number for versioned cache keys

    Returns:
        Redis cache key

    Example:
        >>> _get_config_cache_key("api_123")
        'config:api_123'
        >>> _get_config_cache_key("api_123", 5)
        'config:api_123:v5'
    """
    if version is not None:
        return f"config:{api_key}:v{version}"
    return f"config:{api_key}"


def _get_lock_key(cache_key: str) -> str:
    """
    Generate lock key for cache stampede prevention.

    Args:
        cache_key: Configuration cache key

    Returns:
        Redis lock key

    Example:
        >>> _get_lock_key("config:api_123:ARRIS-AABBCC")
        'lock:config:api_123:ARRIS-AABBCC'
    """
    return f"lock:{cache_key}"


def _calculate_jittered_ttl() -> int:
    """
    Calculate TTL with random jitter to prevent thundering herd.

    Returns:
        TTL in seconds (DEFAULT_TTL ± TTL_JITTER)

    Example:
        >>> ttl = _calculate_jittered_ttl()
        >>> 270 <= ttl <= 330  # 300 ± 30
        True
    """
    return DEFAULT_TTL + random.randint(-TTL_JITTER, TTL_JITTER)


async def get_cached_config(
    api_key: str,
    version: Optional[int] = None
) -> Optional[Dict[str, Any]]:
    """
    Retrieve configuration from cache.

    Args:
        api_key: Client API key
        version: Optional version number for versioned cache lookup

    Returns:
        Cached config dict if found, None if cache miss

    Raises:
        ConfigCacheError: If cache operation fails critically

    Example:
        >>> config = await get_cached_config("api_123", version=5)
        >>> config
        {
            "encrypted_blob": "ab12cd34...",
            "salt": "1234567890abcdef...",
            "hash": "sha256...",
            "mode": "locked",
            "version": 5
        }
    """
    cache_key = _get_config_cache_key(api_key, version)

    try:
        cache = await get_cache()
        cached_value = await cache.get(cache_key)

        if cached_value is None:
            return None

        # Deserialize from JSON
        config_data = json.loads(cached_value)
        return config_data

    except json.JSONDecodeError as e:
        # Cache corruption - delete and return None
        logger.warning(f"Cache corruption detected for key {cache_key}, deleting: {e}")
        try:
            await cache.delete(cache_key)
        except Exception as delete_err:
            logger.debug(f"Failed to delete corrupted cache key {cache_key}: {delete_err}")
        return None

    except Exception as e:
        # Non-critical cache error - log and return None (will hit database)
        # Don't raise ConfigCacheError for reads - graceful degradation
        logger.debug(f"Cache read error for key {cache_key}, falling back to database: {e}")
        return None


async def set_cached_config(
    api_key: str,
    encrypted_blob: str,
    salt: str,
    config_hash: str,
    mode: str,
    version: int
) -> bool:
    """
    Store configuration in cache with jittered TTL.

    Uses versioned cache key (config:api_key:v{version}) to prevent
    race conditions during concurrent updates.

    Args:
        api_key: Client API key
        encrypted_blob: Encrypted config blob
        salt: Encryption salt
        config_hash: SHA256 hash of config
        mode: Config mode ("one_time" or "locked")
        version: Config version

    Returns:
        True if cached successfully, False otherwise

    Example:
        >>> await set_cached_config(
        ...     "api_123",
        ...     "encrypted_blob", "salt_hex",
        ...     "hash_hex", "locked", 5
        ... )
        True
    """
    cache_key = _get_config_cache_key(api_key, version)

    # Build cache entry
    cache_entry = {
        "encrypted_blob": encrypted_blob,
        "salt": salt,
        "hash": config_hash,
        "mode": mode,
        "version": version,
        "cached_at": datetime.utcnow().isoformat()
    }

    try:
        cache = await get_cache()
        ttl = _calculate_jittered_ttl()

        # Serialize to JSON
        cache_value = json.dumps(cache_entry)

        # Store in cache
        await cache.setex(cache_key, ttl, cache_value)
        return True

    except Exception as e:
        # Non-critical cache error - don't raise, just return False
        # Database will be the source of truth
        logger.debug(f"Cache write error for key {cache_key}: {e}")
        return False


async def invalidate_config_cache(api_key: str, version: Optional[int] = None) -> bool:
    """
    Invalidate cached configuration.

    With versioned caching, invalidation is less critical since each version
    has its own cache key. This function is kept for backward compatibility
    and can be used to invalidate specific versions.

    Args:
        api_key: Client API key
        version: Optional specific version to invalidate. If None, invalidates
                the base key (for backward compatibility)

    Returns:
        True if invalidated successfully, False otherwise

    Example:
        >>> await invalidate_config_cache("api_123", version=5)
        True
    """
    cache_key = _get_config_cache_key(api_key, version)

    try:
        cache = await get_cache()
        await cache.delete(cache_key)
        return True

    except Exception as e:
        # Non-critical error
        logger.debug(f"Cache invalidation error for key {cache_key}: {e}")
        return False


async def acquire_config_lock(
    api_key: str,
    version: Optional[int] = None,
    timeout_seconds: int = LOCK_TIMEOUT
) -> bool:
    """
    Acquire distributed lock for cache stampede prevention.

    When cache expires and multiple requests arrive simultaneously,
    only one should query the database while others wait for the
    cache to be populated.

    Args:
        api_key: Client API key
        version: Optional version number for versioned locking
        timeout_seconds: Maximum time to wait for lock

    Returns:
        True if lock acquired, False if timeout

    Example:
        >>> if await acquire_config_lock("api_123", version=5):
        ...     # Query database and populate cache
        ...     config = query_database()
        ...     await set_cached_config(...)
        ...     await release_config_lock("api_123", version=5)
        ... else:
        ...     # Wait briefly and retry cache
        ...     await asyncio.sleep(0.1)
        ...     config = await get_cached_config(...)
    """
    cache_key = _get_config_cache_key(api_key, version)
    lock_key = _get_lock_key(cache_key)

    try:
        cache = await get_cache()

        # Try to acquire lock with retry using atomic SETNX
        start_time = asyncio.get_running_loop().time()

        while True:
            # Attempt atomic lock acquisition using SETNX
            # This is properly atomic - only one caller will succeed even under contention
            acquired = await cache.setnx(lock_key, "locked", ttl=LOCK_TTL)

            if acquired:
                return True

            # Lock exists - wait and retry
            elapsed = asyncio.get_running_loop().time() - start_time
            if elapsed >= timeout_seconds:
                # Timeout - failed to acquire lock
                # This is OK for cache stampede prevention - caller will hit database
                return False

            # Wait briefly before retry (exponential backoff for less contention)
            wait_time = min(0.05 * (2 ** (elapsed // 1)), 0.5)  # Cap at 500ms
            await asyncio.sleep(wait_time)

    except Exception as e:
        # On error, assume lock not acquired
        # Caller will hit database which is acceptable fallback
        logger.debug(f"Lock acquisition error for api_key {api_key}: {e}")
        return False


async def release_config_lock(api_key: str, version: Optional[int] = None) -> bool:
    """
    Release distributed lock.

    Args:
        api_key: Client API key
        version: Optional version number for versioned locking

    Returns:
        True if released successfully, False otherwise

    Example:
        >>> await release_config_lock("api_123", version=5)
        True
    """
    cache_key = _get_config_cache_key(api_key, version)
    lock_key = _get_lock_key(cache_key)

    try:
        cache = await get_cache()
        await cache.delete(lock_key)
        return True

    except Exception as e:
        # Lock will auto-expire after LOCK_TTL seconds
        logger.debug(f"Lock release error for api_key {api_key}: {e}")
        return False


async def get_or_fetch_config(
    api_key: str,
    fetch_func,
    version: Optional[int] = None
) -> Optional[Dict[str, Any]]:
    """
    Get config from cache, or fetch from database with stampede prevention.

    This is the recommended high-level function for sync operations.
    Implements cache-aside pattern with automatic stampede prevention.

    With versioned caching: if version is provided, looks up that specific
    version in cache. This prevents race conditions during concurrent updates.

    Args:
        api_key: Client API key
        fetch_func: Async function that fetches from database
                   Should return Dict with encrypted_blob, salt, hash, mode, version
        version: Optional version number for versioned cache lookup

    Returns:
        Config dict if found, None if not found in DB

    Raises:
        ConfigCacheError: If fetch_func raises an exception

    Example:
        >>> async def fetch_from_db():
        ...     # Query database
        ...     return {
        ...         "encrypted_blob": "...",
        ...         "salt": "...",
        ...         "hash": "...",
        ...         "mode": "locked",
        ...         "version": 5
        ...     }
        >>> config = await get_or_fetch_config("api_123", fetch_from_db, version=5)
    """
    # Try cache first
    cached = await get_cached_config(api_key, version)
    if cached is not None:
        return cached

    # Cache miss - acquire lock to prevent stampede
    lock_acquired = await acquire_config_lock(api_key, version)

    if lock_acquired:
        try:
            # Double-check cache (another request might have populated it)
            cached = await get_cached_config(api_key, version)
            if cached is not None:
                return cached

            # Fetch from database
            config = await fetch_func()

            if config is None:
                # Not found in database
                return None

            # Populate cache
            await set_cached_config(
                api_key,
                config["encrypted_blob"],
                config["salt"],
                config["hash"],
                config["mode"],
                config["version"]
            )

            return config

        finally:
            # Always release lock
            await release_config_lock(api_key, version)

    else:
        # Failed to acquire lock - another request is fetching
        # Wait briefly and retry cache
        await asyncio.sleep(0.1)
        cached = await get_cached_config(api_key, version)

        if cached is not None:
            return cached

        # Still not cached - fall through to database (without caching)
        return await fetch_func()


async def get_cache_stats() -> Dict[str, Any]:
    """
    Get configuration cache statistics.

    Returns:
        Dict with cache stats

    Example:
        >>> stats = await get_cache_stats()
        >>> stats
        {
            "backend": "redis",
            "redis_available": True,
            "config_cache_enabled": True
        }
    """
    from app.core.cache import get_cache_manager

    try:
        manager = await get_cache_manager()
        stats = await manager.get_stats()
        stats["config_cache_enabled"] = True
        return stats

    except Exception as e:
        return {
            "backend": "unknown",
            "redis_available": False,
            "config_cache_enabled": False,
            "error": str(e)
        }
