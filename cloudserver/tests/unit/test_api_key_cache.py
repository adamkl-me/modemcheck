"""
Unit tests for API key caching functionality.

These tests cover:
- Cache statistics tracking
- Cache hit rate calculations
- Statistics reset functionality
"""
import pytest
from datetime import datetime, timedelta

from app.core.api_key_cache import APIKeyCacheStats


class TestAPIKeyCacheStats:
    """Test cache statistics tracking."""

    def test_initial_stats(self):
        """New stats instance should start at zero."""
        stats = APIKeyCacheStats()
        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.hit_rate == 0.0

    def test_record_hit(self):
        """Recording hits should increment counter."""
        stats = APIKeyCacheStats()
        stats.record_hit()
        assert stats.hits == 1
        assert stats.misses == 0

        stats.record_hit()
        assert stats.hits == 2
        assert stats.misses == 0

    def test_record_miss(self):
        """Recording misses should increment counter."""
        stats = APIKeyCacheStats()
        stats.record_miss()
        assert stats.hits == 0
        assert stats.misses == 1

        stats.record_miss()
        assert stats.hits == 0
        assert stats.misses == 2

    def test_hit_rate_calculation(self):
        """Hit rate should be calculated correctly."""
        stats = APIKeyCacheStats()

        # 100% hit rate
        stats.record_hit()
        assert stats.hit_rate == 100.0

        # 50% hit rate (1 hit, 1 miss)
        stats.record_miss()
        assert stats.hit_rate == 50.0

        # 33.33% hit rate (1 hit, 2 misses)
        stats.record_miss()
        assert abs(stats.hit_rate - 33.33) < 0.1

        # 60% hit rate (3 hits, 2 misses)
        stats.record_hit()
        stats.record_hit()
        assert stats.hit_rate == 60.0

        # 75% hit rate (3 hits, 1 miss) - reset and start fresh
        stats.reset()
        stats.record_hit()
        stats.record_hit()
        stats.record_hit()
        stats.record_miss()
        assert stats.hit_rate == 75.0

    def test_hit_rate_zero_requests(self):
        """Hit rate should be 0 when no requests recorded."""
        stats = APIKeyCacheStats()
        assert stats.hit_rate == 0.0

    def test_reset_stats(self):
        """Reset should clear all counters."""
        stats = APIKeyCacheStats()

        # Record some activity
        stats.record_hit()
        stats.record_hit()
        stats.record_miss()

        initial_reset_time = stats.last_reset

        # Reset
        stats.reset()

        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.hit_rate == 0.0
        assert stats.last_reset > initial_reset_time

    def test_last_reset_timestamp(self):
        """Last reset timestamp should be set on initialization and reset."""
        before = datetime.utcnow()
        stats = APIKeyCacheStats()
        after = datetime.utcnow()

        # Should be set during initialization
        assert before <= stats.last_reset <= after

        # Record activity
        stats.record_hit()

        # Reset and check timestamp updated
        before_reset = datetime.utcnow()
        stats.reset()
        after_reset = datetime.utcnow()

        assert before_reset <= stats.last_reset <= after_reset

    def test_high_volume_stats(self):
        """Stats should handle high volumes correctly."""
        stats = APIKeyCacheStats()

        # Simulate 10,000 requests with 80% hit rate
        for _ in range(8000):
            stats.record_hit()
        for _ in range(2000):
            stats.record_miss()

        assert stats.hits == 8000
        assert stats.misses == 2000
        assert stats.hit_rate == 80.0

    def test_mixed_operations(self):
        """Test realistic mixed hit/miss pattern."""
        stats = APIKeyCacheStats()

        # Simulate realistic usage pattern
        # First request is a miss (cache empty)
        stats.record_miss()
        assert stats.hit_rate == 0.0

        # Next 9 requests are hits (cache warm)
        for _ in range(9):
            stats.record_hit()

        # Should have 90% hit rate (9 hits, 1 miss)
        assert stats.hit_rate == 90.0

        # Cache expires, next request is miss
        stats.record_miss()

        # 9 hits, 2 misses = ~81.8% hit rate
        assert abs(stats.hit_rate - 81.82) < 0.1


class TestAPIKeyCacheStatsConcurrency:
    """Test cache stats behavior under concurrent access patterns."""

    def test_multiple_stats_instances(self):
        """Multiple instances should be independent."""
        stats1 = APIKeyCacheStats()
        stats2 = APIKeyCacheStats()

        stats1.record_hit()
        stats1.record_hit()
        stats2.record_miss()

        assert stats1.hits == 2
        assert stats1.misses == 0
        assert stats2.hits == 0
        assert stats2.misses == 1

    def test_stats_persistence_across_operations(self):
        """Stats should persist across multiple operations."""
        stats = APIKeyCacheStats()

        # Simulate multiple cache validation cycles
        for cycle in range(5):
            stats.record_hit()
            stats.record_hit()
            stats.record_miss()

        assert stats.hits == 10
        assert stats.misses == 5
        assert abs(stats.hit_rate - 66.67) < 0.1


class TestAPIKeyCacheStatsEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_only_hits(self):
        """Stats with only hits should show 100% hit rate."""
        stats = APIKeyCacheStats()
        for _ in range(100):
            stats.record_hit()

        assert stats.hit_rate == 100.0
        assert stats.misses == 0

    def test_only_misses(self):
        """Stats with only misses should show 0% hit rate."""
        stats = APIKeyCacheStats()
        for _ in range(100):
            stats.record_miss()

        assert stats.hit_rate == 0.0
        assert stats.hits == 0

    def test_reset_preserves_instance(self):
        """Reset should not create new instance, just clear data."""
        stats = APIKeyCacheStats()
        original_id = id(stats)

        stats.record_hit()
        stats.reset()

        assert id(stats) == original_id
        assert stats.hits == 0

    def test_hit_rate_precision(self):
        """Hit rate should maintain precision for various ratios."""
        stats = APIKeyCacheStats()

        # Test 1/3 (33.333...)
        stats.record_hit()
        stats.record_miss()
        stats.record_miss()
        assert stats.hit_rate == pytest.approx(33.33, rel=0.01)

        # Reset and test 2/3 (66.666...)
        stats.reset()
        stats.record_hit()
        stats.record_hit()
        stats.record_miss()
        assert abs(stats.hit_rate - 66.67) < 0.1

    def test_very_large_numbers(self):
        """Stats should handle very large counters without overflow."""
        stats = APIKeyCacheStats()

        # Simulate 1 million requests
        large_number = 1_000_000
        stats.hits = large_number
        stats.misses = large_number // 4  # 25% miss rate

        assert stats.hit_rate == 80.0


# Note: Tests for async cache operations (get_cached_keys, set_cached_keys, etc.)
# are covered by integration tests that run against real Redis in the test environment.
# These operations require Redis connectivity and are better tested as part of the
# full API endpoint tests rather than as isolated unit tests.
