"""
Unit tests for cache provider abstraction layer.

Tests all cache implementations: InMemoryCache, RedisCache, and FallbackCache.
"""

import asyncio
import pytest
import time
from unittest.mock import AsyncMock, Mock, patch
from redis.exceptions import ConnectionError, RedisError, TimeoutError

from app.core.cache_provider import (
    InMemoryCache,
    RedisCache,
    FallbackCache,
    init_cache,
    get_cache,
    close_cache,
    _cache_instance
)


class TestInMemoryCache:
    """Tests for InMemoryCache implementation."""

    @pytest.fixture
    async def cache(self):
        """Create InMemoryCache instance for testing."""
        cache = InMemoryCache(max_size=100, default_ttl=3600)
        yield cache
        await cache.close()

    @pytest.mark.asyncio
    async def test_set_and_get(self, cache):
        """Test basic set and get operations."""
        result = await cache.set("test_key", "test_value")
        assert result is True

        value = await cache.get("test_key")
        assert value == "test_value"

    @pytest.mark.asyncio
    async def test_get_nonexistent_key(self, cache):
        """Test getting a key that doesn't exist."""
        value = await cache.get("nonexistent")
        assert value is None

    @pytest.mark.asyncio
    async def test_set_with_ttl(self, cache):
        """Test set with TTL expires correctly."""
        await cache.set("expiring_key", "value", ttl=1)

        # Should exist immediately
        value = await cache.get("expiring_key")
        assert value == "value"

        # Wait for expiration
        await asyncio.sleep(1.1)

        # Should be expired
        value = await cache.get("expiring_key")
        assert value is None

    @pytest.mark.asyncio
    async def test_delete(self, cache):
        """Test delete operation."""
        await cache.set("key_to_delete", "value")
        assert await cache.exists("key_to_delete") is True

        result = await cache.delete("key_to_delete")
        assert result is True

        assert await cache.exists("key_to_delete") is False

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, cache):
        """Test deleting a key that doesn't exist."""
        result = await cache.delete("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_exists(self, cache):
        """Test exists operation."""
        assert await cache.exists("test_key") is False

        await cache.set("test_key", "value")
        assert await cache.exists("test_key") is True

    @pytest.mark.asyncio
    async def test_incr(self, cache):
        """Test increment operation."""
        # First increment initializes to 1
        value = await cache.incr("counter")
        assert value == 1

        # Subsequent increments
        value = await cache.incr("counter")
        assert value == 2

        value = await cache.incr("counter")
        assert value == 3

    @pytest.mark.asyncio
    async def test_incr_non_integer_raises_error(self, cache):
        """Test incrementing a non-integer value raises error."""
        await cache.set("not_a_number", "abc")

        with pytest.raises(ValueError, match="not an integer"):
            await cache.incr("not_a_number")

    @pytest.mark.asyncio
    async def test_expire(self, cache):
        """Test setting expiration on existing key."""
        await cache.set("key", "value")

        result = await cache.expire("key", ttl=1)
        assert result is True

        # Should exist immediately
        assert await cache.exists("key") is True

        # Wait for expiration
        await asyncio.sleep(1.1)

        # Should be expired
        assert await cache.exists("key") is False

    @pytest.mark.asyncio
    async def test_expire_nonexistent_key(self, cache):
        """Test setting expiration on key that doesn't exist."""
        result = await cache.expire("nonexistent", ttl=60)
        assert result is False

    @pytest.mark.asyncio
    async def test_ttl(self, cache):
        """Test TTL operation."""
        # Key doesn't exist
        assert await cache.ttl("nonexistent") == -2

        # Key with no expiration
        await cache.set("no_expiry", "value", ttl=None)
        assert await cache.ttl("no_expiry") == -1

        # Key with expiration
        await cache.set("with_expiry", "value", ttl=60)
        ttl = await cache.ttl("with_expiry")
        assert 55 < ttl <= 60  # Should be close to 60 seconds

    @pytest.mark.asyncio
    async def test_keys_with_pattern(self, cache):
        """Test keys operation with glob patterns."""
        await cache.set("user:1", "alice")
        await cache.set("user:2", "bob")
        await cache.set("session:1", "xyz")
        await cache.set("session:2", "abc")

        # Match all user keys
        user_keys = await cache.keys("user:*")
        assert set(user_keys) == {"user:1", "user:2"}

        # Match all session keys
        session_keys = await cache.keys("session:*")
        assert set(session_keys) == {"session:1", "session:2"}

        # Match all keys
        all_keys = await cache.keys("*")
        assert len(all_keys) == 4

    @pytest.mark.asyncio
    async def test_lru_eviction(self, cache):
        """Test LRU eviction when max size reached."""
        small_cache = InMemoryCache(max_size=3, default_ttl=None)

        # Fill cache to max size
        await small_cache.set("key1", "value1")
        await small_cache.set("key2", "value2")
        await small_cache.set("key3", "value3")

        # All keys should exist
        assert await small_cache.exists("key1") is True
        assert await small_cache.exists("key2") is True
        assert await small_cache.exists("key3") is True

        # Add one more - should evict key1 (oldest)
        await small_cache.set("key4", "value4")

        assert await small_cache.exists("key1") is False  # Evicted
        assert await small_cache.exists("key2") is True
        assert await small_cache.exists("key3") is True
        assert await small_cache.exists("key4") is True

        await small_cache.close()

    @pytest.mark.asyncio
    async def test_lru_access_updates_order(self, cache):
        """Test that accessing a key marks it as recently used."""
        small_cache = InMemoryCache(max_size=3, default_ttl=None)

        await small_cache.set("key1", "value1")
        await small_cache.set("key2", "value2")
        await small_cache.set("key3", "value3")

        # Access key1 to mark as recently used
        await small_cache.get("key1")

        # Add key4 - should evict key2 (now oldest), not key1
        await small_cache.set("key4", "value4")

        assert await small_cache.exists("key1") is True  # Still exists
        assert await small_cache.exists("key2") is False  # Evicted
        assert await small_cache.exists("key3") is True
        assert await small_cache.exists("key4") is True

        await small_cache.close()

    @pytest.mark.asyncio
    async def test_is_healthy(self, cache):
        """Test health check always returns True for in-memory cache."""
        assert await cache.is_healthy() is True

    @pytest.mark.asyncio
    async def test_get_stats(self, cache):
        """Test getting cache statistics."""
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")

        stats = cache.get_stats()
        assert stats["type"] == "in_memory"
        assert stats["size"] == 2
        assert stats["max_size"] == 100
        assert 0 < stats["utilization"] < 1

    @pytest.mark.asyncio
    async def test_concurrent_incr(self, cache):
        """Test that concurrent incr operations are thread-safe."""
        import asyncio

        async def increment():
            for _ in range(100):
                await cache.incr("counter")

        # Run 10 concurrent incrementers
        await asyncio.gather(*[increment() for _ in range(10)])

        # Should be exactly 1000 (10 * 100)
        result = await cache.get("counter")
        assert int(result) == 1000

    @pytest.mark.asyncio
    async def test_concurrent_set_get(self):
        """Test that concurrent set/get operations are thread-safe."""
        import asyncio
        # Use larger cache to avoid eviction during test
        large_cache = InMemoryCache(max_size=500, default_ttl=3600)

        async def writer(key_prefix: str):
            for i in range(50):
                await large_cache.set(f"{key_prefix}_{i}", f"value_{i}")

        async def reader(key_prefix: str):
            for i in range(50):
                # May get None if not yet written, but shouldn't error
                await large_cache.get(f"{key_prefix}_{i}")

        # Run all writers first, then verify
        await asyncio.gather(
            writer("a"), writer("b"), writer("c")
        )

        # Run readers concurrently with verification
        await asyncio.gather(
            reader("a"), reader("b"), reader("c")
        )

        # Verify values were written correctly
        assert await large_cache.get("a_49") == "value_49"
        assert await large_cache.get("b_49") == "value_49"

        await large_cache.close()

    @pytest.mark.asyncio
    async def test_concurrent_lru_eviction(self, cache):
        """Test that LRU eviction is thread-safe under concurrent load."""
        import asyncio
        small_cache = InMemoryCache(max_size=10, default_ttl=None)

        async def writer():
            for i in range(50):
                await small_cache.set(f"key_{i}", f"value_{i}")

        # Run concurrent writers that will cause frequent evictions
        await asyncio.gather(*[writer() for _ in range(5)])

        # Cache should have at most max_size entries
        stats = small_cache.get_stats()
        assert stats["size"] <= 10

        await small_cache.close()


class TestRedisCache:
    """Tests for RedisCache implementation."""

    @pytest.fixture
    async def mock_redis(self):
        """Create mock Redis client."""
        mock = AsyncMock()
        mock.get = AsyncMock()
        mock.set = AsyncMock()
        mock.setex = AsyncMock()
        mock.delete = AsyncMock()
        mock.exists = AsyncMock()
        mock.incr = AsyncMock()
        mock.expire = AsyncMock()
        mock.ttl = AsyncMock()
        mock.keys = AsyncMock()
        mock.ping = AsyncMock()
        mock.close = AsyncMock()
        return mock

    @pytest.fixture
    async def cache(self, mock_redis):
        """Create RedisCache instance with mock client."""
        cache = RedisCache(mock_redis)
        yield cache
        await cache.close()

    @pytest.mark.asyncio
    async def test_get(self, cache, mock_redis):
        """Test get operation delegates to Redis."""
        mock_redis.get.return_value = b"test_value"

        value = await cache.get("test_key")

        assert value == "test_value"
        mock_redis.get.assert_called_once_with("test_key")

    @pytest.mark.asyncio
    async def test_get_none(self, cache, mock_redis):
        """Test get returns None for missing key."""
        mock_redis.get.return_value = None

        value = await cache.get("missing")

        assert value is None

    @pytest.mark.asyncio
    async def test_get_redis_error_raises(self, cache, mock_redis):
        """Test get raises on Redis error."""
        mock_redis.get.side_effect = RedisError("Connection failed")

        with pytest.raises(RedisError):
            await cache.get("test_key")

    @pytest.mark.asyncio
    async def test_set_without_ttl(self, cache, mock_redis):
        """Test set without TTL."""
        mock_redis.set.return_value = True

        result = await cache.set("key", "value")

        assert result is True
        mock_redis.set.assert_called_once_with("key", "value")

    @pytest.mark.asyncio
    async def test_set_with_ttl(self, cache, mock_redis):
        """Test set with TTL uses setex."""
        mock_redis.setex.return_value = True

        result = await cache.set("key", "value", ttl=300)

        assert result is True
        mock_redis.setex.assert_called_once_with("key", 300, "value")

    @pytest.mark.asyncio
    async def test_delete(self, cache, mock_redis):
        """Test delete operation."""
        mock_redis.delete.return_value = 1

        result = await cache.delete("key")

        assert result is True
        mock_redis.delete.assert_called_once_with("key")

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, cache, mock_redis):
        """Test delete returns False for nonexistent key."""
        mock_redis.delete.return_value = 0

        result = await cache.delete("nonexistent")

        assert result is False

    @pytest.mark.asyncio
    async def test_exists(self, cache, mock_redis):
        """Test exists operation."""
        mock_redis.exists.return_value = 1

        result = await cache.exists("key")

        assert result is True
        mock_redis.exists.assert_called_once_with("key")

    @pytest.mark.asyncio
    async def test_incr(self, cache, mock_redis):
        """Test increment operation."""
        mock_redis.incr.return_value = 5

        result = await cache.incr("counter")

        assert result == 5
        mock_redis.incr.assert_called_once_with("counter")

    @pytest.mark.asyncio
    async def test_expire(self, cache, mock_redis):
        """Test expire operation."""
        mock_redis.expire.return_value = 1

        result = await cache.expire("key", 60)

        assert result is True
        mock_redis.expire.assert_called_once_with("key", 60)

    @pytest.mark.asyncio
    async def test_ttl(self, cache, mock_redis):
        """Test TTL operation."""
        mock_redis.ttl.return_value = 45

        result = await cache.ttl("key")

        assert result == 45

    @pytest.mark.asyncio
    async def test_keys(self, cache, mock_redis):
        """Test keys operation."""
        mock_redis.keys.return_value = [b"key1", b"key2", b"key3"]

        result = await cache.keys("key*")

        assert result == ["key1", "key2", "key3"]
        mock_redis.keys.assert_called_once_with("key*")

    @pytest.mark.asyncio
    async def test_is_healthy(self, cache, mock_redis):
        """Test health check with ping."""
        mock_redis.ping.return_value = True

        result = await cache.is_healthy()

        assert result is True
        mock_redis.ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_is_healthy_failure(self, cache, mock_redis):
        """Test health check returns False on error."""
        mock_redis.ping.side_effect = ConnectionError("Connection failed")

        result = await cache.is_healthy()

        assert result is False


class TestFallbackCache:
    """Tests for FallbackCache implementation."""

    @pytest.fixture
    async def mock_redis(self):
        """Create mock Redis client."""
        mock = AsyncMock()
        mock.ping = AsyncMock()
        mock.close = AsyncMock()
        return mock

    @pytest.fixture
    async def fallback_cache(self, mock_redis):
        """Create FallbackCache instance."""
        cache = FallbackCache(
            mock_redis,
            health_check_interval=1,  # Short interval for testing
            reconnect_attempts=3
        )
        yield cache
        await cache.close()

    @pytest.mark.asyncio
    async def test_initial_uses_redis(self, fallback_cache):
        """Test initially uses Redis as primary."""
        assert fallback_cache.using_fallback is False

    @pytest.mark.asyncio
    async def test_switches_to_fallback_on_redis_error(self, fallback_cache):
        """Test automatic fallback on Redis error."""
        # Make Redis operations fail
        fallback_cache.primary.get = AsyncMock(side_effect=ConnectionError("Connection failed"))

        # Try to get a value - should fallback
        value = await fallback_cache.get("test_key")

        # Should have switched to fallback
        assert fallback_cache.using_fallback is True
        assert fallback_cache._failover_time is not None
        assert value is None  # In-memory cache is empty initially

    @pytest.mark.asyncio
    async def test_operations_work_in_fallback_mode(self, fallback_cache):
        """Test cache operations work when using fallback."""
        # Force fallback mode
        fallback_cache.primary.set = AsyncMock(side_effect=RedisError("Error"))

        # Set should work via fallback
        result = await fallback_cache.set("key", "value")
        assert result is True
        assert fallback_cache.using_fallback is True

        # Get should work via fallback
        value = await fallback_cache.get("key")
        assert value == "value"

    @pytest.mark.asyncio
    async def test_recovery_to_redis(self, fallback_cache, mock_redis):
        """Test automatic recovery to Redis when it becomes healthy."""
        # Start in fallback mode
        fallback_cache.using_fallback = True
        fallback_cache._last_health_check = 0  # Force health check

        # Make Redis healthy
        mock_redis.ping.return_value = True
        fallback_cache.primary.is_healthy = AsyncMock(return_value=True)

        # Trigger health check by performing an operation
        await fallback_cache.get("test_key")

        # Should have recovered to Redis
        assert fallback_cache.using_fallback is False
        assert fallback_cache._failover_time is None

    @pytest.mark.asyncio
    async def test_health_check_interval_respected(self, fallback_cache):
        """Test health checks only happen at specified intervals."""
        fallback_cache._last_health_check = time.time()  # Just checked
        fallback_cache.primary.is_healthy = AsyncMock()

        # Perform operation - should not trigger health check
        await fallback_cache.set("key", "value")

        # Health check should not have been called (interval not elapsed)
        fallback_cache.primary.is_healthy.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_stats_redis_mode(self, fallback_cache):
        """Test stats when using Redis."""
        stats = fallback_cache.get_stats()

        assert stats["using_fallback"] is False
        assert stats["type"] == "redis"

    @pytest.mark.asyncio
    async def test_get_stats_fallback_mode(self, fallback_cache):
        """Test stats when using fallback."""
        fallback_cache.using_fallback = True

        stats = fallback_cache.get_stats()

        assert stats["using_fallback"] is True
        assert stats["type"] == "in_memory"

    @pytest.mark.asyncio
    async def test_multiple_operations_maintain_fallback_state(self, fallback_cache):
        """Test that multiple operations in fallback mode remain in fallback."""
        # Force fallback
        fallback_cache.primary.get = AsyncMock(side_effect=RedisError("Error"))
        await fallback_cache.get("key1")
        assert fallback_cache.using_fallback is True

        # Subsequent operations should use fallback without trying Redis
        fallback_cache.primary.set = AsyncMock()  # Reset mock
        await fallback_cache.set("key2", "value2")
        await fallback_cache.get("key2")

        # Should still be in fallback mode
        assert fallback_cache.using_fallback is True


class TestCacheInitialization:
    """Tests for global cache initialization and access."""

    @pytest.mark.asyncio
    async def test_init_cache_with_fallback(self):
        """Test initializing cache with fallback enabled."""
        mock_redis = AsyncMock()

        cache = await init_cache(mock_redis, enable_fallback=True)

        assert isinstance(cache, FallbackCache)
        assert cache is not None

        # Cleanup
        await close_cache()

    @pytest.mark.asyncio
    async def test_init_cache_without_fallback(self):
        """Test initializing cache without fallback."""
        mock_redis = AsyncMock()
        mock_redis.close = AsyncMock()

        cache = await init_cache(mock_redis, enable_fallback=False)

        assert isinstance(cache, RedisCache)
        assert cache is not None

        # Cleanup
        await close_cache()

    @pytest.mark.asyncio
    async def test_get_cache_before_init_raises_error(self):
        """Test getting cache before initialization raises error."""
        # Ensure cache is not initialized
        await close_cache()

        with pytest.raises(RuntimeError, match="Cache not initialized"):
            await get_cache()

    @pytest.mark.asyncio
    async def test_get_cache_after_init_returns_instance(self):
        """Test getting cache after initialization returns the instance."""
        mock_redis = AsyncMock()
        await init_cache(mock_redis, enable_fallback=True)

        cache1 = await get_cache()
        cache2 = await get_cache()

        # Should return same instance
        assert cache1 is cache2

        # Cleanup
        await close_cache()

    @pytest.mark.asyncio
    async def test_close_cache_clears_instance(self):
        """Test closing cache clears global instance."""
        mock_redis = AsyncMock()
        await init_cache(mock_redis, enable_fallback=True)

        cache = await get_cache()
        assert cache is not None

        await close_cache()

        # Should raise error after closing
        with pytest.raises(RuntimeError, match="Cache not initialized"):
            await get_cache()
