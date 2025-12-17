"""
API Key caching module for performance optimization.

This module provides cache-based (with automatic Redis fallback) caching
for API keys to avoid repeated database queries during high-frequency
upload operations.
"""

import json
import logging
import secrets
import hashlib
from typing import Optional, Dict, List, Tuple
from app.core.cache_provider import get_cache
from app.core.utils import utc_now
from app.core.config import settings

logger = logging.getLogger(__name__)


class APIKeyCache:
    """
    Hash-based API key cache for optimizing upload endpoint performance (v7.1+).

    SECURITY ENHANCEMENT:
    - Stores ONLY HASHES in Redis (no plaintext exposure)
    - Fixes CRITICAL vulnerability: Redis compromise no longer exposes API keys
    - Uses SHA-256 hash for validation (one-way, cannot reverse)

    Cache strategy:
    - Active API key HASHES are cached with configurable TTL (default: 5 minutes)
    - Keys stored as JSON list: [{'api_key_hash': hash, 'name': name}, ...]
    - Timing-safe comparison used for hash validation
    - Cache invalidated when keys are created/modified/deleted
    - Automatic fallback to in-memory cache if Redis unavailable

    Migration:
    - During migration, cache stores both hash (new) and plaintext (legacy)
    - After Phase 8 cleanup, only hash is stored
    """

    CACHE_KEY = "api_keys:active"

    @staticmethod
    async def get_cached_keys() -> Optional[List[Dict[str, str]]]:
        """
        Get cached API key hashes from cache (with automatic fallback).

        Returns:
            List of dicts with 'api_key_hash' and 'name' fields, or None if not cached

        Security:
            Returns ONLY HASHES (no plaintext in Redis)
        """
        try:
            cache = await get_cache()
            cached_data = await cache.get(APIKeyCache.CACHE_KEY)
            if cached_data:
                return json.loads(cached_data)
        except Exception as e:
            # If cache read fails, fallback to database
            logger.debug(f"API key cache read failed, falling back to database: {type(e).__name__}: {e}")

        return None

    @staticmethod
    async def set_cached_keys(keys: List[Dict[str, str]]) -> None:
        """
        Cache API key hashes in cache (with automatic fallback).

        Args:
            keys: List of dicts with 'api_key_hash' and 'name' fields

        Security:
            Stores ONLY HASHES (no plaintext written to Redis)
        """
        try:
            cache = await get_cache()
            await cache.set(
                APIKeyCache.CACHE_KEY,
                json.dumps(keys),
                ttl=settings.api_key_cache_ttl
            )
        except Exception as e:
            # If cache write fails, continue without caching
            logger.debug(f"API key cache write failed: {type(e).__name__}: {e}")

    @staticmethod
    async def invalidate_cache() -> None:
        """Invalidate the API key cache."""
        try:
            cache = await get_cache()
            await cache.delete(APIKeyCache.CACHE_KEY)
        except Exception as e:
            logger.debug(f"API key cache invalidation failed: {type(e).__name__}: {e}")

    @staticmethod
    async def validate_api_key_cached(
        api_key: str,
        db_fallback_func
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate API key using hash-based cache with database fallback (v7.1+).

        Security flow:
        1. Client sends plaintext API key
        2. Server hashes it (SHA-256)
        3. Server looks up hash in cache/database
        4. Timing-safe comparison prevents timing attacks

        Args:
            api_key: The plaintext API key from client
            db_fallback_func: Async function to query database if cache miss

        Returns:
            (is_valid, key_name) tuple
        """
        # Hash the API key for validation (SHA-256, 64 hex chars)
        api_key_hash = hashlib.sha256(api_key.encode('utf-8')).hexdigest()

        # Try to get from cache first
        cached_keys = await APIKeyCache.get_cached_keys()

        if cached_keys is not None:
            # Use cached HASHES for validation (timing-safe)
            for stored_key in cached_keys:
                # Compare hashes (not plaintext) - timing-safe
                if secrets.compare_digest(api_key_hash, stored_key['api_key_hash']):
                    return True, stored_key['name']
            return False, None

        # Cache miss - query database
        active_keys = await db_fallback_func()

        # Build cache data with HASHES ONLY (security fix)
        cache_data = [
            {'api_key_hash': key.api_key_hash, 'name': key.name}
            for key in active_keys
            if key.api_key_hash  # Only cache migrated keys with hashes
        ]

        # Store in cache for next time (HASHES ONLY, no plaintext)
        await APIKeyCache.set_cached_keys(cache_data)

        # Validate against fetched keys (hash comparison)
        for stored_key in active_keys:
            if stored_key.api_key_hash and secrets.compare_digest(api_key_hash, stored_key.api_key_hash):
                return True, stored_key.name

        return False, None

    @staticmethod
    async def update_last_used_by_hash(api_key_hash: str) -> None:
        """
        Update the last_used timestamp for an API key using hash-based lookup (v7.1+).

        Security: Uses hash lookup to prevent plaintext exposure in queries.

        This is done asynchronously using its own database session to avoid
        conflicts with the request's session lifecycle.

        Performance: Reduces upload latency by 10-50ms by not waiting
        for the database commit to complete.

        Args:
            api_key_hash: SHA-256 hash of the API key (64 hex chars)
        """
        from sqlalchemy import update
        from app.models.api_key import APIKey
        from app.core.database import get_db_context

        try:
            # Create a new session for this background task
            # This prevents IllegalStateChangeError when the request's session closes
            async with get_db_context() as session:
                await session.execute(
                    update(APIKey)
                    .where(APIKey.api_key_hash == api_key_hash)
                    .values(last_used=utc_now())
                )
                # Commit is handled by the context manager
        except Exception as e:
            # Log but don't fail - last_used timestamp is not critical
            # Upload should succeed even if timestamp update fails
            logger.debug(f"API key last_used update failed (hash-based): {type(e).__name__}: {e}")


class APIKeyCacheStats:
    """Track cache hit/miss statistics for monitoring."""

    def __init__(self):
        self.hits = 0
        self.misses = 0
        self.last_reset = utc_now()

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return self.hits / total * 100

    def record_hit(self):
        """Record a cache hit."""
        self.hits += 1

    def record_miss(self):
        """Record a cache miss."""
        self.misses += 1

    def reset(self):
        """Reset statistics."""
        self.hits = 0
        self.misses = 0
        self.last_reset = utc_now()


# Global stats instance
api_key_cache_stats = APIKeyCacheStats()