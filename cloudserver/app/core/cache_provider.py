"""
Cache Provider Abstraction Layer

Provides cache abstraction with automatic fallback from Redis to in-memory cache.
This eliminates Redis as a single point of failure while maintaining performance.

Design:
- ICacheProvider: Abstract interface for cache operations
- RedisCache: Primary cache implementation using Redis
- InMemoryCache: Fallback implementation using Python dict with TTL support
- FallbackCache: Automatic switchover between Redis and in-memory cache

Usage:
    cache = await get_cache()
    await cache.set("key", "value", ttl=300)
    value = await cache.get("key")
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Set
from collections import OrderedDict

import redis.asyncio as aioredis
from redis.exceptions import RedisError, ConnectionError, TimeoutError

logger = logging.getLogger(__name__)


class ICacheProvider(ABC):
    """Abstract interface for cache providers."""

    @abstractmethod
    async def get(self, key: str) -> Optional[str]:
        """Get value from cache."""
        pass

    @abstractmethod
    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        """Set value in cache with optional TTL in seconds."""
        pass

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete key from cache."""
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        pass

    @abstractmethod
    async def incr(self, key: str) -> int:
        """Increment counter."""
        pass

    @abstractmethod
    async def expire(self, key: str, ttl: int) -> bool:
        """Set expiration on key."""
        pass

    @abstractmethod
    async def ttl(self, key: str) -> int:
        """Get time-to-live for key. Returns -1 if no expiration, -2 if key doesn't exist."""
        pass

    @abstractmethod
    async def keys(self, pattern: str) -> list[str]:
        """Get keys matching pattern."""
        pass

    @abstractmethod
    async def is_healthy(self) -> bool:
        """Check if cache is healthy and accessible."""
        pass

    @abstractmethod
    async def setnx(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        """
        Set key to value if key does not exist (atomic SET if Not eXists).
        Returns True if key was set, False if key already existed.
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close cache connection."""
        pass


class InMemoryCache(ICacheProvider):
    """
    In-memory cache implementation with TTL support.

    Used as fallback when Redis is unavailable. Provides similar API
    but data is not shared across workers/processes.

    Features:
    - TTL support with automatic expiration
    - LRU eviction when max size reached
    - Thread-safe operations
    """

    def __init__(self, max_size: int = 10000, default_ttl: int = 3600):
        """
        Initialize in-memory cache.

        Args:
            max_size: Maximum number of keys to store (LRU eviction)
            default_ttl: Default TTL in seconds if not specified
        """
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._data: OrderedDict[str, tuple[str, Optional[float]]] = OrderedDict()
        self._lock = asyncio.Lock()
        logger.warning("InMemoryCache initialized - data NOT shared across workers!")

    async def _cleanup_expired(self) -> None:
        """Remove expired entries."""
        now = time.time()
        expired_keys = [
            key for key, (_, exp) in self._data.items()
            if exp is not None and exp < now
        ]
        for key in expired_keys:
            del self._data[key]

    async def _evict_if_needed(self) -> None:
        """Evict oldest entry if max size exceeded (LRU)."""
        if len(self._data) >= self.max_size:
            # Remove oldest item (first in OrderedDict)
            oldest_key = next(iter(self._data))
            del self._data[oldest_key]
            logger.debug(f"InMemoryCache: Evicted oldest key '{oldest_key}' (LRU)")

    async def get(self, key: str) -> Optional[str]:
        """Get value from cache, returns None if expired or missing."""
        async with self._lock:
            await self._cleanup_expired()

            if key not in self._data:
                return None

            value, expiration = self._data[key]

            # Check if expired
            if expiration is not None and expiration < time.time():
                del self._data[key]
                return None

            # Move to end (mark as recently used for LRU)
            self._data.move_to_end(key)
            return value

    async def set(self, key: str, value: str, ttl: Optional[int] = ...) -> bool:
        """
        Set value with optional TTL.

        Args:
            key: Cache key
            value: Value to store
            ttl: Time-to-live in seconds. If not provided (default), uses default_ttl.
                 If explicitly None, no expiration is set.
        """
        async with self._lock:
            await self._cleanup_expired()
            await self._evict_if_needed()

            expiration = None
            # Use sentinel value (...) to detect when ttl was not provided
            if ttl is ...:
                # Not provided - use default_ttl
                if self.default_ttl is not None:
                    expiration = time.time() + self.default_ttl
            elif ttl is not None:
                # Explicitly provided a value
                expiration = time.time() + ttl
            # else: ttl is explicitly None - no expiration

            self._data[key] = (value, expiration)
            self._data.move_to_end(key)  # Mark as recently used
            return True

    async def delete(self, key: str) -> bool:
        """Delete key from cache."""
        async with self._lock:
            if key in self._data:
                del self._data[key]
                return True
            return False

    async def exists(self, key: str) -> bool:
        """Check if key exists and is not expired."""
        value = await self.get(key)
        return value is not None

    async def incr(self, key: str) -> int:
        """Increment counter, initializes to 1 if key doesn't exist."""
        async with self._lock:
            await self._cleanup_expired()

            # Access data directly to avoid deadlock (don't call get() while holding lock)
            if key in self._data:
                value, expiration = self._data[key]

                # Check if expired
                if expiration is not None and expiration < time.time():
                    del self._data[key]
                    new_value = 1
                else:
                    try:
                        new_value = int(value) + 1
                    except ValueError:
                        raise ValueError(f"Value at '{key}' is not an integer")
            else:
                new_value = 1

            # Set new value directly (avoid calling set() while holding lock)
            await self._evict_if_needed()
            expiration = None
            if self.default_ttl is not None:
                expiration = time.time() + self.default_ttl

            self._data[key] = (str(new_value), expiration)
            self._data.move_to_end(key)
            return new_value

    async def expire(self, key: str, ttl: int) -> bool:
        """Set expiration on existing key."""
        async with self._lock:
            if key not in self._data:
                return False

            value, _ = self._data[key]
            expiration = time.time() + ttl
            self._data[key] = (value, expiration)
            return True

    async def ttl(self, key: str) -> int:
        """Get time-to-live. Returns -1 if no expiration, -2 if key doesn't exist."""
        async with self._lock:
            if key not in self._data:
                return -2

            _, expiration = self._data[key]
            if expiration is None:
                return -1

            remaining = int(expiration - time.time())
            return max(remaining, -2)  # Return -2 if already expired

    async def keys(self, pattern: str) -> list[str]:
        """
        Get keys matching pattern.

        Supports basic glob patterns:
        - * matches any sequence of characters
        - ? matches any single character
        """
        async with self._lock:
            await self._cleanup_expired()

            import fnmatch
            matching_keys = [
                key for key in self._data.keys()
                if fnmatch.fnmatch(key, pattern)
            ]
            return matching_keys

    async def is_healthy(self) -> bool:
        """In-memory cache is always healthy."""
        return True

    async def setnx(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        """Set key to value if key does not exist."""
        async with self._lock:
            await self._cleanup_expired()

            if key in self._data:
                return False  # Key already exists

            # Key doesn't exist, set it
            expiry_time = datetime.now() + timedelta(seconds=ttl) if ttl else None
            self._data[key] = (value, expiry_time)
            return True

    async def close(self) -> None:
        """Close cache (no-op for in-memory)."""
        async with self._lock:
            self._data.clear()
        logger.info("InMemoryCache closed and cleared")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "size": len(self._data),
            "max_size": self.max_size,
            "utilization": len(self._data) / self.max_size if self.max_size > 0 else 0,
            "type": "in_memory"
        }


class RedisCache(ICacheProvider):
    """
    Redis cache implementation.

    Primary cache provider that connects to Redis server.
    Provides all standard cache operations.
    """

    def __init__(self, redis_client: aioredis.Redis):
        """
        Initialize Redis cache.

        Args:
            redis_client: AsyncIO Redis client instance
        """
        self.redis = redis_client
        logger.info("RedisCache initialized")

    async def get(self, key: str) -> Optional[str]:
        """Get value from Redis."""
        try:
            value = await self.redis.get(key)
            if value is None:
                return None
            # Handle both bytes and str (decode_responses=True vs False)
            return value.decode() if isinstance(value, bytes) else value
        except (RedisError, ConnectionError, TimeoutError) as e:
            logger.error(f"RedisCache.get error for key '{key}': {e}")
            raise

    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        """Set value in Redis with optional TTL."""
        try:
            if ttl is not None:
                await self.redis.setex(key, ttl, value)
            else:
                await self.redis.set(key, value)
            return True
        except (RedisError, ConnectionError, TimeoutError) as e:
            logger.error(f"RedisCache.set error for key '{key}': {e}")
            raise

    async def delete(self, key: str) -> bool:
        """Delete key from Redis."""
        try:
            result = await self.redis.delete(key)
            return result > 0
        except (RedisError, ConnectionError, TimeoutError) as e:
            logger.error(f"RedisCache.delete error for key '{key}': {e}")
            raise

    async def exists(self, key: str) -> bool:
        """Check if key exists in Redis."""
        try:
            result = await self.redis.exists(key)
            return result > 0
        except (RedisError, ConnectionError, TimeoutError) as e:
            logger.error(f"RedisCache.exists error for key '{key}': {e}")
            raise

    async def incr(self, key: str) -> int:
        """Increment counter in Redis."""
        try:
            return await self.redis.incr(key)
        except (RedisError, ConnectionError, TimeoutError) as e:
            logger.error(f"RedisCache.incr error for key '{key}': {e}")
            raise

    async def expire(self, key: str, ttl: int) -> bool:
        """Set expiration on key in Redis."""
        try:
            result = await self.redis.expire(key, ttl)
            return result > 0
        except (RedisError, ConnectionError, TimeoutError) as e:
            logger.error(f"RedisCache.expire error for key '{key}': {e}")
            raise

    async def ttl(self, key: str) -> int:
        """Get time-to-live from Redis."""
        try:
            return await self.redis.ttl(key)
        except (RedisError, ConnectionError, TimeoutError) as e:
            logger.error(f"RedisCache.ttl error for key '{key}': {e}")
            raise

    async def keys(self, pattern: str) -> list[str]:
        """Get keys matching pattern from Redis."""
        try:
            keys = await self.redis.keys(pattern)
            return [key.decode() if isinstance(key, bytes) else key for key in keys]
        except (RedisError, ConnectionError, TimeoutError) as e:
            logger.error(f"RedisCache.keys error for pattern '{pattern}': {e}")
            raise

    async def is_healthy(self) -> bool:
        """Check Redis health with ping."""
        try:
            await self.redis.ping()
            return True
        except (RedisError, ConnectionError, TimeoutError) as e:
            logger.error(f"RedisCache health check failed: {e}")
            return False

    async def setnx(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        """Set key to value if key does not exist (atomic operation)."""
        try:
            # Use SET with NX (not exists) and optional EX (expiry) flags
            # Returns True if key was set, None if key already existed
            result = await self.redis.set(key, value, nx=True, ex=ttl)
            return result is not None
        except (RedisError, ConnectionError, TimeoutError) as e:
            logger.error(f"RedisCache.setnx error for key '{key}': {e}")
            raise

    async def close(self) -> None:
        """Close Redis connection."""
        await self.redis.close()
        logger.info("RedisCache connection closed")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "type": "redis",
            "connected": True  # If we can call this, we're connected
        }


class FallbackCache(ICacheProvider):
    """
    Automatic fallback cache provider.

    Attempts to use Redis as primary cache. If Redis fails, automatically
    falls back to in-memory cache. Periodically attempts to reconnect to Redis.

    Features:
    - Automatic failover on Redis errors
    - Periodic health checks and recovery attempts
    - Transparent to callers (same API)
    - Metrics and logging for monitoring
    """

    def __init__(
        self,
        redis_client: aioredis.Redis,
        fallback_cache: Optional[InMemoryCache] = None,
        health_check_interval: int = 30,
        reconnect_attempts: int = 3
    ):
        """
        Initialize fallback cache.

        Args:
            redis_client: AsyncIO Redis client
            fallback_cache: Optional in-memory cache (creates default if None)
            health_check_interval: Seconds between health checks
            reconnect_attempts: Number of reconnect attempts before giving up
        """
        self.primary = RedisCache(redis_client)
        self.fallback = fallback_cache or InMemoryCache()
        self.using_fallback = False
        self.health_check_interval = health_check_interval
        self.reconnect_attempts = reconnect_attempts
        self._last_health_check = 0.0
        self._failover_time: Optional[datetime] = None
        self._failure_count = 0
        self._state_lock = asyncio.Lock()  # Protects failover state transitions
        logger.info("FallbackCache initialized with Redis primary and in-memory fallback")

    async def _check_and_recover(self) -> None:
        """
        Periodic health check and recovery attempt.

        If using fallback, attempts to reconnect to Redis.
        If using Redis, verifies it's still healthy.
        Uses state lock to prevent race conditions during state transitions.
        """
        now = time.time()

        # Only check periodically
        if now - self._last_health_check < self.health_check_interval:
            return

        self._last_health_check = now

        async with self._state_lock:
            if self.using_fallback:
                # Attempt recovery
                logger.info("FallbackCache: Attempting Redis recovery...")
                if await self.primary.is_healthy():
                    logger.warning("FallbackCache: Redis recovered! Switching back to primary.")
                    self.using_fallback = False
                    self._failover_time = None
                    self._failure_count = 0
                else:
                    logger.debug("FallbackCache: Redis still unavailable, continuing with fallback")
            else:
                # Verify primary is still healthy
                if not await self.primary.is_healthy():
                    logger.error("FallbackCache: Redis health check failed during normal operation!")
                    await self._activate_fallback_locked()

    async def _activate_fallback_locked(self) -> None:
        """Activate fallback cache mode. Must be called while holding _state_lock."""
        if not self.using_fallback:
            logger.error(
                "FallbackCache: Switching to in-memory fallback! "
                "Data will NOT be shared across workers."
            )
            self.using_fallback = True
            self._failover_time = datetime.utcnow()
            self._failure_count = 0

    async def _activate_fallback(self) -> None:
        """Activate fallback cache mode with state lock protection."""
        async with self._state_lock:
            await self._activate_fallback_locked()

    async def _execute_with_fallback(self, operation_name: str, primary_fn, fallback_fn):
        """
        Execute operation with automatic fallback.

        Args:
            operation_name: Name of operation for logging
            primary_fn: Coroutine to execute on primary cache
            fallback_fn: Coroutine to execute on fallback cache

        Returns:
            Result from either primary or fallback
        """
        # Periodic health check
        await self._check_and_recover()

        if self.using_fallback:
            # Already in fallback mode
            return await fallback_fn()

        # Try primary
        try:
            result = await primary_fn()
            return result
        except (RedisError, ConnectionError, TimeoutError) as e:
            self._failure_count += 1
            logger.error(
                f"FallbackCache.{operation_name}: Redis error (failure #{self._failure_count}): {e}"
            )

            # Activate fallback after first error
            await self._activate_fallback()

            # Execute on fallback
            return await fallback_fn()

    async def get(self, key: str) -> Optional[str]:
        """Get value with automatic fallback."""
        return await self._execute_with_fallback(
            "get",
            lambda: self.primary.get(key),
            lambda: self.fallback.get(key)
        )

    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        """Set value with automatic fallback."""
        return await self._execute_with_fallback(
            "set",
            lambda: self.primary.set(key, value, ttl),
            lambda: self.fallback.set(key, value, ttl)
        )

    async def delete(self, key: str) -> bool:
        """Delete key with automatic fallback."""
        return await self._execute_with_fallback(
            "delete",
            lambda: self.primary.delete(key),
            lambda: self.fallback.delete(key)
        )

    async def exists(self, key: str) -> bool:
        """Check existence with automatic fallback."""
        return await self._execute_with_fallback(
            "exists",
            lambda: self.primary.exists(key),
            lambda: self.fallback.exists(key)
        )

    async def incr(self, key: str) -> int:
        """Increment with automatic fallback."""
        return await self._execute_with_fallback(
            "incr",
            lambda: self.primary.incr(key),
            lambda: self.fallback.incr(key)
        )

    async def expire(self, key: str, ttl: int) -> bool:
        """Set expiration with automatic fallback."""
        return await self._execute_with_fallback(
            "expire",
            lambda: self.primary.expire(key, ttl),
            lambda: self.fallback.expire(key, ttl)
        )

    async def ttl(self, key: str) -> int:
        """Get TTL with automatic fallback."""
        return await self._execute_with_fallback(
            "ttl",
            lambda: self.primary.ttl(key),
            lambda: self.fallback.ttl(key)
        )

    async def keys(self, pattern: str) -> list[str]:
        """Get keys with automatic fallback."""
        return await self._execute_with_fallback(
            "keys",
            lambda: self.primary.keys(pattern),
            lambda: self.fallback.keys(pattern)
        )

    async def is_healthy(self) -> bool:
        """Check if cache is healthy (either primary or fallback)."""
        if self.using_fallback:
            return await self.fallback.is_healthy()
        else:
            return await self.primary.is_healthy()

    async def setnx(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        """Set key if not exists with automatic fallback."""
        return await self._execute_with_fallback(
            "setnx",
            lambda: self.primary.setnx(key, value, ttl),
            lambda: self.fallback.setnx(key, value, ttl)
        )

    async def close(self) -> None:
        """Close both primary and fallback caches."""
        await self.primary.close()
        await self.fallback.close()
        logger.info("FallbackCache closed")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics and status."""
        stats = {
            "using_fallback": self.using_fallback,
            "failure_count": self._failure_count,
        }

        if self._failover_time:
            stats["failover_time"] = self._failover_time.isoformat()
            stats["failover_duration_seconds"] = (
                datetime.utcnow() - self._failover_time
            ).total_seconds()

        if self.using_fallback:
            stats.update(self.fallback.get_stats())
        else:
            stats.update(self.primary.get_stats())

        return stats


# Global cache instance
_cache_instance: Optional[ICacheProvider] = None


async def get_cache() -> ICacheProvider:
    """
    Get global cache instance.

    Returns the configured cache provider (FallbackCache by default).
    Must be initialized first via init_cache().
    """
    global _cache_instance

    if _cache_instance is None:
        raise RuntimeError("Cache not initialized. Call init_cache() first.")

    return _cache_instance


async def init_cache(redis_client: aioredis.Redis, enable_fallback: bool = True) -> ICacheProvider:
    """
    Initialize global cache instance.

    Args:
        redis_client: AsyncIO Redis client
        enable_fallback: If True, use FallbackCache; if False, use RedisCache only

    Returns:
        Initialized cache instance
    """
    global _cache_instance

    if enable_fallback:
        _cache_instance = FallbackCache(redis_client)
        logger.info("Cache initialized with fallback support (FallbackCache)")
    else:
        _cache_instance = RedisCache(redis_client)
        logger.warning("Cache initialized WITHOUT fallback support (RedisCache only)")

    return _cache_instance


async def close_cache() -> None:
    """Close global cache instance."""
    global _cache_instance

    if _cache_instance is not None:
        await _cache_instance.close()
        _cache_instance = None
        logger.info("Global cache instance closed")
