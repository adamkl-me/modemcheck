"""
Unit tests for cache abstraction layer with Redis fallback.

Tests for:
- In-memory cache operations
- LRU eviction
- Expiration handling
- Pipeline operations
- Health checking
"""
import pytest
import asyncio
from datetime import datetime, timedelta, timezone

from app.core.utils import utc_now
from app.core.cache import (
    InMemoryBackend,
    InMemoryCacheEntry,
    InMemoryPipeline
)


pytestmark = pytest.mark.unit


class TestInMemoryCacheEntry:
    """Test cache entry expiration logic."""

    def test_entry_no_expiration(self):
        """Entry without expiration never expires."""
        entry = InMemoryCacheEntry("value", expires_at=None)
        assert entry.is_expired() is False

    def test_entry_not_expired(self):
        """Entry should not be expired before expiration time."""
        future = utc_now() + timedelta(seconds=60)
        entry = InMemoryCacheEntry("value", expires_at=future)
        assert entry.is_expired() is False

    def test_entry_expired(self):
        """Entry should be expired after expiration time."""
        past = utc_now() - timedelta(seconds=1)
        entry = InMemoryCacheEntry("value", expires_at=past)
        assert entry.is_expired() is True


@pytest.mark.asyncio
class TestInMemoryBackendBasicOperations:
    """Test basic cache operations."""

    async def test_set_and_get(self):
        """Set and get value from cache."""
        cache = InMemoryBackend()

        await cache.set("key1", "value1")
        result = await cache.get("key1")

        assert result == "value1"

    async def test_get_nonexistent(self):
        """Get non-existent key returns None."""
        cache = InMemoryBackend()
        result = await cache.get("nonexistent")
        assert result is None

    async def test_set_with_ttl(self):
        """Set value with TTL."""
        cache = InMemoryBackend()

        await cache.set("key1", "value1", ttl=2)
        result = await cache.get("key1")
        assert result == "value1"

        # Wait for expiration
        await asyncio.sleep(2.5)
        result = await cache.get("key1")
        assert result is None

    async def test_setex(self):
        """Test setex (Redis compatibility)."""
        cache = InMemoryBackend()

        await cache.setex("key1", 1, "value1")
        result = await cache.get("key1")
        assert result == "value1"

        await asyncio.sleep(1.5)
        result = await cache.get("key1")
        assert result is None

    async def test_delete(self):
        """Delete key from cache."""
        cache = InMemoryBackend()

        await cache.set("key1", "value1")
        assert await cache.exists("key1") is True

        result = await cache.delete("key1")
        assert result is True
        assert await cache.exists("key1") is False

    async def test_delete_nonexistent(self):
        """Delete non-existent key returns False."""
        cache = InMemoryBackend()
        result = await cache.delete("nonexistent")
        assert result is False

    async def test_exists(self):
        """Check if key exists."""
        cache = InMemoryBackend()

        assert await cache.exists("key1") is False

        await cache.set("key1", "value1")
        assert await cache.exists("key1") is True

    async def test_exists_expired(self):
        """Exists returns False for expired keys."""
        cache = InMemoryBackend()

        await cache.set("key1", "value1", ttl=1)
        assert await cache.exists("key1") is True

        await asyncio.sleep(1.5)
        assert await cache.exists("key1") is False


@pytest.mark.asyncio
class TestInMemoryBackendIncrement:
    """Test increment operations (rate limiting)."""

    async def test_incr_new_key(self):
        """Increment non-existent key starts from 1."""
        cache = InMemoryBackend()

        result = await cache.incr("counter")
        assert result == 1

    async def test_incr_existing_key(self):
        """Increment existing key."""
        cache = InMemoryBackend()

        await cache.set("counter", "5")
        result = await cache.incr("counter")
        assert result == 6

        result = await cache.incr("counter")
        assert result == 7

    async def test_incr_multiple_keys(self):
        """Increment multiple independent counters."""
        cache = InMemoryBackend()

        await cache.incr("counter1")
        await cache.incr("counter1")
        await cache.incr("counter2")

        assert await cache.get("counter1") == "2"
        assert await cache.get("counter2") == "1"

    async def test_incr_expired_key(self):
        """Increment expired key starts from 1."""
        cache = InMemoryBackend()

        await cache.set("counter", "10", ttl=1)
        await asyncio.sleep(1.5)

        result = await cache.incr("counter")
        assert result == 1


@pytest.mark.asyncio
class TestInMemoryBackendExpiration:
    """Test expiration and TTL management."""

    async def test_expire_existing_key(self):
        """Set expiration on existing key."""
        cache = InMemoryBackend()

        await cache.set("key1", "value1")
        result = await cache.expire("key1", 1)
        assert result is True

        await asyncio.sleep(1.5)
        assert await cache.exists("key1") is False

    async def test_expire_nonexistent_key(self):
        """Expire non-existent key returns False."""
        cache = InMemoryBackend()

        result = await cache.expire("nonexistent", 60)
        assert result is False

    async def test_expire_updates_ttl(self):
        """Expire updates TTL on existing key."""
        cache = InMemoryBackend()

        await cache.set("key1", "value1", ttl=10)
        result = await cache.expire("key1", 1)
        assert result is True

        await asyncio.sleep(1.5)
        assert await cache.exists("key1") is False


@pytest.mark.asyncio
class TestInMemoryBackendLRUEviction:
    """Test LRU eviction when max size exceeded."""

    async def test_lru_eviction(self):
        """Oldest entry evicted when max size exceeded."""
        cache = InMemoryBackend(max_size=3)

        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        await cache.set("key3", "value3")

        # All should exist
        assert await cache.exists("key1") is True
        assert await cache.exists("key2") is True
        assert await cache.exists("key3") is True

        # Add 4th key, should evict key1 (oldest)
        await cache.set("key4", "value4")
        assert await cache.exists("key1") is False
        assert await cache.exists("key2") is True
        assert await cache.exists("key3") is True
        assert await cache.exists("key4") is True

    async def test_lru_access_updates_order(self):
        """Accessing a key marks it as recently used."""
        cache = InMemoryBackend(max_size=3)

        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        await cache.set("key3", "value3")

        # Access key1 (moves to end)
        await cache.get("key1")

        # Add key4, should evict key2 (now oldest)
        await cache.set("key4", "value4")
        assert await cache.exists("key1") is True  # Still exists (recently used)
        assert await cache.exists("key2") is False  # Evicted
        assert await cache.exists("key3") is True
        assert await cache.exists("key4") is True

    async def test_lru_set_updates_order(self):
        """Setting existing key marks it as recently used."""
        cache = InMemoryBackend(max_size=3)

        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        await cache.set("key3", "value3")

        # Update key1 (moves to end)
        await cache.set("key1", "updated")

        # Add key4, should evict key2 (now oldest)
        await cache.set("key4", "value4")
        assert await cache.exists("key1") is True
        assert await cache.exists("key2") is False
        assert await cache.exists("key3") is True
        assert await cache.exists("key4") is True


@pytest.mark.asyncio
class TestInMemoryPipeline:
    """Test pipeline operations."""

    async def test_pipeline_get_delete(self):
        """Pipeline can batch get and delete operations."""
        cache = InMemoryBackend()

        await cache.set("key1", "value1")
        await cache.set("key2", "value2")

        pipeline = cache.pipeline()
        pipeline.get("key1")
        pipeline.delete("key2")

        results = await pipeline.execute()

        assert results[0] == "value1"  # GET result
        assert results[1] is True  # DELETE result
        assert await cache.exists("key2") is False

    async def test_pipeline_multiple_gets(self):
        """Pipeline can batch multiple get operations."""
        cache = InMemoryBackend()

        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        await cache.set("key3", "value3")

        pipeline = cache.pipeline()
        pipeline.get("key1")
        pipeline.get("key2")
        pipeline.get("key3")

        results = await pipeline.execute()

        assert results == ["value1", "value2", "value3"]

    async def test_pipeline_nonexistent_key(self):
        """Pipeline returns None for non-existent keys."""
        cache = InMemoryBackend()

        pipeline = cache.pipeline()
        pipeline.get("nonexistent")

        results = await pipeline.execute()
        assert results[0] is None


@pytest.mark.asyncio
class TestInMemoryBackendHealthCheck:
    """Test health check operations."""

    async def test_ping(self):
        """Ping always returns True for in-memory cache."""
        cache = InMemoryBackend()
        assert await cache.ping() is True

    async def test_close(self):
        """Close clears the cache."""
        cache = InMemoryBackend()

        await cache.set("key1", "value1")
        await cache.set("key2", "value2")

        await cache.close()

        # Cache should be empty after close
        assert len(cache.cache) == 0


@pytest.mark.asyncio
class TestInMemoryBackendConcurrency:
    """Test concurrent access to in-memory cache."""

    async def test_concurrent_sets(self):
        """Multiple concurrent sets should work correctly."""
        cache = InMemoryBackend()

        async def set_value(key: str, value: str):
            await cache.set(key, value)

        # Set 10 keys concurrently
        tasks = [set_value(f"key{i}", f"value{i}") for i in range(10)]
        await asyncio.gather(*tasks)

        # All keys should exist
        for i in range(10):
            result = await cache.get(f"key{i}")
            assert result == f"value{i}"

    async def test_concurrent_increments(self):
        """Multiple concurrent increments should work correctly."""
        cache = InMemoryBackend()

        async def increment():
            await cache.incr("counter")

        # Increment 100 times concurrently
        tasks = [increment() for _ in range(100)]
        await asyncio.gather(*tasks)

        result = await cache.get("counter")
        assert result == "100"
