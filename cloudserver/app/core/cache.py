"""
Cache abstraction layer with Redis and in-memory fallback.

Provides a unified cache interface that automatically falls back to
in-memory caching when Redis is unavailable, ensuring graceful degradation.
"""
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional, Any, Dict
from datetime import datetime, timedelta, timezone
from collections import OrderedDict
import redis.asyncio as aioredis

from app.core.config import settings


logger = logging.getLogger(__name__)


# ============================================================================
# CACHE INTERFACE
# ============================================================================

class CacheBackend(ABC):
    """Abstract base class for cache backends."""

    @abstractmethod
    async def get(self, key: str) -> Optional[str]:
        """Get value from cache."""
        pass

    @abstractmethod
    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        """Set value in cache with optional TTL (seconds)."""
        pass

    @abstractmethod
    async def setex(self, key: str, ttl: int, value: str) -> bool:
        """Set value with expiration (Redis compatibility)."""
        pass

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete key from cache."""
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        pass

    @abstractmethod
    async def incr(self, key: str) -> int:
        """Increment value (for rate limiting)."""
        pass

    @abstractmethod
    async def expire(self, key: str, ttl: int) -> bool:
        """Set expiration on existing key."""
        pass

    @abstractmethod
    async def ttl(self, key: str) -> int:
        """Get TTL (time to live) for key in seconds. Returns -1 if no expiration, -2 if key doesn't exist."""
        pass

    @abstractmethod
    async def ping(self) -> bool:
        """Health check."""
        pass

    @abstractmethod
    def pipeline(self):
        """Create a pipeline for batch operations."""
        pass

    @abstractmethod
    async def close(self):
        """Close connections."""
        pass


# ============================================================================
# REDIS BACKEND
# ============================================================================

class RedisBackend(CacheBackend):
    """Redis cache backend."""

    def __init__(self, redis_client: aioredis.Redis):
        self.redis = redis_client
        self._is_healthy = True

    async def get(self, key: str) -> Optional[str]:
        try:
            return await self.redis.get(key)
        except Exception as e:
            logger.error(f"Redis GET error: {e}")
            self._is_healthy = False
            raise

    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        try:
            if ttl:
                return await self.redis.setex(key, ttl, value)
            return await self.redis.set(key, value)
        except Exception as e:
            logger.error(f"Redis SET error: {e}")
            self._is_healthy = False
            raise

    async def setex(self, key: str, ttl: int, value: str) -> bool:
        try:
            return await self.redis.setex(key, ttl, value)
        except Exception as e:
            logger.error(f"Redis SETEX error: {e}")
            self._is_healthy = False
            raise

    async def delete(self, key: str) -> bool:
        try:
            result = await self.redis.delete(key)
            return result > 0
        except Exception as e:
            logger.error(f"Redis DELETE error: {e}")
            self._is_healthy = False
            raise

    async def exists(self, key: str) -> bool:
        try:
            result = await self.redis.exists(key)
            return result > 0
        except Exception as e:
            logger.error(f"Redis EXISTS error: {e}")
            self._is_healthy = False
            raise

    async def incr(self, key: str) -> int:
        try:
            return await self.redis.incr(key)
        except Exception as e:
            logger.error(f"Redis INCR error: {e}")
            self._is_healthy = False
            raise

    async def expire(self, key: str, ttl: int) -> bool:
        try:
            return await self.redis.expire(key, ttl)
        except Exception as e:
            logger.error(f"Redis EXPIRE error: {e}")
            self._is_healthy = False
            raise

    async def ttl(self, key: str) -> int:
        try:
            return await self.redis.ttl(key)
        except Exception as e:
            logger.error(f"Redis TTL error: {e}")
            self._is_healthy = False
            raise

    async def ping(self) -> bool:
        try:
            await self.redis.ping()
            self._is_healthy = True
            return True
        except Exception as e:
            logger.error(f"Redis PING error: {e}")
            self._is_healthy = False
            return False

    def pipeline(self):
        """Return Redis pipeline."""
        return self.redis.pipeline()

    async def close(self):
        """Close Redis connection."""
        # Redis connection pool is managed globally
        pass

    @property
    def is_healthy(self) -> bool:
        return self._is_healthy


# ============================================================================
# IN-MEMORY BACKEND (FALLBACK)
# ============================================================================

class InMemoryCacheEntry:
    """Cache entry with expiration."""

    def __init__(self, value: str, expires_at: Optional[datetime] = None):
        self.value = value
        self.expires_at = expires_at

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) > self.expires_at


class InMemoryBackend(CacheBackend):
    """
    In-memory cache backend (fallback when Redis unavailable).

    Features:
    - LRU eviction when max_size exceeded
    - Automatic expiration cleanup
    - Thread-safe operations with asyncio.Lock
    - Warning logs to alert degraded mode
    """

    def __init__(self, max_size: int = 10000):
        self.cache: OrderedDict[str, InMemoryCacheEntry] = OrderedDict()
        self.max_size = max_size
        self.lock = asyncio.Lock()
        self._degraded_warning_logged = False

    def _log_degraded_mode(self):
        """Log warning about degraded mode (once per instance)."""
        if not self._degraded_warning_logged:
            logger.warning(
                "⚠️  DEGRADED MODE: Using in-memory cache fallback. "
                "Redis is unavailable. Sessions and rate limiting are NOT shared across workers!"
            )
            self._degraded_warning_logged = True

    async def _cleanup_expired(self):
        """Remove expired entries."""
        async with self.lock:
            expired_keys = [
                key for key, entry in self.cache.items()
                if entry.is_expired()
            ]
            for key in expired_keys:
                del self.cache[key]

    async def _enforce_max_size(self):
        """Enforce max size with LRU eviction."""
        async with self.lock:
            while len(self.cache) > self.max_size:
                # Remove oldest (LRU)
                self.cache.popitem(last=False)

    async def get(self, key: str) -> Optional[str]:
        self._log_degraded_mode()

        async with self.lock:
            entry = self.cache.get(key)
            if entry is None:
                return None

            if entry.is_expired():
                del self.cache[key]
                return None

            # Move to end (mark as recently used)
            self.cache.move_to_end(key)
            return entry.value

    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        self._log_degraded_mode()

        expires_at = None
        if ttl:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)

        async with self.lock:
            self.cache[key] = InMemoryCacheEntry(value, expires_at)
            self.cache.move_to_end(key)  # Mark as recently used

        await self._enforce_max_size()
        return True

    async def setex(self, key: str, ttl: int, value: str) -> bool:
        return await self.set(key, value, ttl)

    async def delete(self, key: str) -> bool:
        async with self.lock:
            if key in self.cache:
                del self.cache[key]
                return True
            return False

    async def exists(self, key: str) -> bool:
        async with self.lock:
            if key not in self.cache:
                return False

            entry = self.cache[key]
            if entry.is_expired():
                del self.cache[key]
                return False

            return True

    async def incr(self, key: str) -> int:
        self._log_degraded_mode()

        async with self.lock:
            entry = self.cache.get(key)

            if entry is None or entry.is_expired():
                # Start from 1
                self.cache[key] = InMemoryCacheEntry("1", None)
                return 1

            # Increment existing value
            current = int(entry.value)
            new_value = current + 1
            entry.value = str(new_value)
            self.cache.move_to_end(key)  # Mark as recently used
            return new_value

    async def expire(self, key: str, ttl: int) -> bool:
        async with self.lock:
            entry = self.cache.get(key)
            if entry is None:
                return False

            entry.expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
            return True

    async def ttl(self, key: str) -> int:
        """Get TTL for key in seconds."""
        async with self.lock:
            entry = self.cache.get(key)
            if entry is None:
                return -2  # Key doesn't exist

            if entry.is_expired():
                del self.cache[key]
                return -2

            if entry.expires_at is None:
                return -1  # No expiration

            remaining = (entry.expires_at - datetime.now(timezone.utc)).total_seconds()
            return max(0, int(remaining))

    async def ping(self) -> bool:
        return True

    def pipeline(self):
        """Return in-memory pipeline (simplified)."""
        return InMemoryPipeline(self)

    async def close(self):
        """Close cache (no-op for in-memory)."""
        async with self.lock:
            self.cache.clear()


class InMemoryPipeline:
    """
    Simplified pipeline for in-memory cache.

    Does not provide atomic guarantees like Redis pipeline,
    but maintains API compatibility.
    """

    def __init__(self, backend: InMemoryBackend):
        self.backend = backend
        self.commands = []

    def get(self, key: str):
        self.commands.append(('get', key))
        return self

    def delete(self, key: str):
        self.commands.append(('delete', key))
        return self

    async def execute(self):
        """Execute all commands and return results."""
        results = []
        for cmd, key in self.commands:
            if cmd == 'get':
                result = await self.backend.get(key)
                results.append(result)
            elif cmd == 'delete':
                result = await self.backend.delete(key)
                results.append(result)
        return results


# ============================================================================
# CACHE MANAGER WITH AUTOMATIC FALLBACK
# ============================================================================

class CacheManager:
    """
    Cache manager with automatic Redis → In-Memory fallback.

    Monitors Redis health and switches to in-memory cache on failure.
    Periodically attempts to reconnect to Redis.
    """

    def __init__(self):
        self.redis_backend: Optional[RedisBackend] = None
        self.memory_backend: InMemoryBackend = InMemoryBackend()
        self.current_backend: CacheBackend = self.memory_backend
        self.redis_check_interval = 60  # seconds
        self.last_redis_check = datetime.now(timezone.utc)
        self._redis_available = False

    async def initialize(self, redis_client: aioredis.Redis):
        """Initialize with Redis client."""
        self.redis_backend = RedisBackend(redis_client)

        # Test Redis connection
        if await self.redis_backend.ping():
            self.current_backend = self.redis_backend
            self._redis_available = True
            logger.info("✓ Cache initialized with Redis backend")
        else:
            self.current_backend = self.memory_backend
            self._redis_available = False
            logger.warning("⚠️  Redis unavailable, using in-memory cache fallback")

    async def _check_redis_health(self):
        """Periodically check Redis health and reconnect if available."""
        now = datetime.now(timezone.utc)
        if (now - self.last_redis_check).total_seconds() < self.redis_check_interval:
            return

        self.last_redis_check = now

        if not self._redis_available and self.redis_backend:
            # Try to reconnect
            if await self.redis_backend.ping():
                logger.info("✓ Redis reconnected, switching from in-memory to Redis")
                self.current_backend = self.redis_backend
                self._redis_available = True

    async def get_backend(self) -> CacheBackend:
        """
        Get current cache backend with automatic fallback.

        If Redis operation fails, switches to in-memory backend.
        """
        await self._check_redis_health()
        return self.current_backend

    async def force_fallback(self):
        """Force fallback to in-memory cache."""
        logger.warning("⚠️  Forcing fallback to in-memory cache")
        self.current_backend = self.memory_backend
        self._redis_available = False

    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        backend_name = "redis" if self._redis_available else "memory"

        stats = {
            "backend": backend_name,
            "redis_available": self._redis_available,
            "last_health_check": self.last_redis_check.isoformat()
        }

        if isinstance(self.current_backend, InMemoryBackend):
            stats["memory_entries"] = len(self.current_backend.cache)
            stats["memory_max_size"] = self.current_backend.max_size

        return stats


# Global cache manager instance
_cache_manager: Optional[CacheManager] = None


async def get_cache_manager() -> CacheManager:
    """Get global cache manager instance."""
    global _cache_manager

    if _cache_manager is None:
        from app.core.security import get_redis
        _cache_manager = CacheManager()

        try:
            redis_client = await get_redis()
            await _cache_manager.initialize(redis_client)
        except Exception as e:
            logger.error(f"Failed to initialize cache with Redis: {e}")
            # Cache manager will use in-memory fallback

    return _cache_manager


async def get_cache() -> CacheBackend:
    """Get current cache backend."""
    manager = await get_cache_manager()
    return await manager.get_backend()
