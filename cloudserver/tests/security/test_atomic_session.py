"""
Tests for atomic session creation with concurrent limit enforcement.

Tests the Lua script implementation that prevents race conditions
when enforcing concurrent session limits.
"""
import pytest
import asyncio
from app.core.security import create_session, get_redis, delete_user_sessions

pytestmark = pytest.mark.security


class TestAtomicSessionCreation:
    """Tests for atomic session creation with Lua script."""

    @pytest.mark.asyncio
    async def test_session_limit_enforced(self):
        """Test that session limit is enforced correctly."""
        username = "test_limit_user"
        redis = await get_redis()

        # Cleanup any existing sessions
        await delete_user_sessions(username)

        # Create sessions up to the limit (5)
        sessions = []
        for i in range(5):
            session_id = await create_session(username, "basic", max_sessions=5)
            sessions.append(session_id)

        # Verify all 5 sessions were created
        assert len(sessions) == 5

        # Try to create 6th session - should fail
        with pytest.raises(ValueError, match="Concurrent session limit exceeded"):
            await create_session(username, "basic", max_sessions=5)

        # Cleanup
        await delete_user_sessions(username)

    @pytest.mark.asyncio
    async def test_concurrent_login_race_condition(self):
        """
        Test that concurrent logins don't bypass limit (race condition prevention).

        This is the critical test - without atomic Lua script, two simultaneous
        logins could both pass the count check and both add sessions.
        """
        username = "test_race_user"
        redis = await get_redis()

        # Cleanup any existing sessions
        await delete_user_sessions(username)

        # Create 4 sessions (one below limit)
        for i in range(4):
            await create_session(username, "basic", max_sessions=5)

        # Attempt 3 concurrent logins (only 1 should succeed)
        async def try_create_session():
            try:
                return await create_session(username, "basic", max_sessions=5)
            except ValueError:
                return None

        # Run 3 concurrent session creations
        results = await asyncio.gather(
            try_create_session(),
            try_create_session(),
            try_create_session(),
            return_exceptions=True
        )

        # Exactly 1 should succeed, 2 should fail
        successes = [r for r in results if r is not None and not isinstance(r, Exception)]
        assert len(successes) == 1, f"Expected 1 success, got {len(successes)}"

        # Verify total session count is exactly 5
        user_sessions_key = f"user_sessions:{username}"
        count = await redis.scard(user_sessions_key)
        assert count == 5, f"Expected 5 total sessions, got {count}"

        # Cleanup
        await delete_user_sessions(username)

    @pytest.mark.asyncio
    async def test_lua_script_atomicity(self):
        """Test that Lua script executes atomically."""
        username = "test_atomic_user"
        redis = await get_redis()

        # Cleanup
        await delete_user_sessions(username)

        # Create sessions up to limit
        for i in range(5):
            await create_session(username, "basic", max_sessions=5)

        # Verify atomic operation - either succeeds completely or fails completely
        # No partial state should exist

        user_sessions_key = f"user_sessions:{username}"
        count_before = await redis.scard(user_sessions_key)

        # Try to add one more (should fail)
        try:
            await create_session(username, "basic", max_sessions=5)
            pytest.fail("Should have raised ValueError")
        except ValueError:
            pass

        # Count should be unchanged (atomic - no partial add)
        count_after = await redis.scard(user_sessions_key)
        assert count_before == count_after == 5

        # Cleanup
        await delete_user_sessions(username)

    @pytest.mark.asyncio
    async def test_session_data_created_after_lua_check(self):
        """Test that session data is created only after Lua check passes."""
        username = "test_order_user"
        redis = await get_redis()

        # Cleanup
        await delete_user_sessions(username)

        # Create 5 sessions (at limit)
        for i in range(5):
            await create_session(username, "basic", max_sessions=5)

        # Try to create 6th - should fail before creating session data
        try:
            session_id = await create_session(username, "basic", max_sessions=5)
            pytest.fail("Should have raised ValueError")
        except ValueError:
            # Session data should NOT exist
            # (Lua script rejects before session data is written)
            pass

        # Verify no orphaned session data exists
        user_sessions_key = f"user_sessions:{username}"
        session_ids = await redis.smembers(user_sessions_key)

        # All sessions should have corresponding data
        for sid in session_ids:
            session_key = f"session:{sid}"
            exists = await redis.exists(session_key)
            assert exists, f"Session data missing for {sid}"

        # Cleanup
        await delete_user_sessions(username)

    @pytest.mark.asyncio
    async def test_custom_session_limit(self):
        """Test that custom session limits work correctly."""
        username = "test_custom_limit_user"
        redis = await get_redis()

        # Cleanup
        await delete_user_sessions(username)

        # Create sessions with custom limit of 3
        for i in range(3):
            await create_session(username, "basic", max_sessions=3)

        # 4th should fail
        with pytest.raises(ValueError, match="max: 3"):
            await create_session(username, "basic", max_sessions=3)

        # Cleanup
        await delete_user_sessions(username)

    @pytest.mark.asyncio
    async def test_session_set_expiration(self):
        """Test that user_sessions set has correct TTL."""
        username = "test_ttl_user"
        redis = await get_redis()

        # Cleanup
        await delete_user_sessions(username)

        # Create one session
        from app.core.config import settings
        await create_session(username, "basic", max_sessions=5)

        # Check TTL on user_sessions set
        user_sessions_key = f"user_sessions:{username}"
        ttl = await redis.ttl(user_sessions_key)

        # Should be approximately settings.session_ttl (3600 seconds)
        assert ttl > settings.session_ttl - 10
        assert ttl <= settings.session_ttl

        # Cleanup
        await delete_user_sessions(username)

    @pytest.mark.asyncio
    async def test_multiple_users_independent_limits(self):
        """Test that different users have independent session limits."""
        redis = await get_redis()

        # Cleanup
        await delete_user_sessions("user1")
        await delete_user_sessions("user2")

        # User1: create 5 sessions
        for i in range(5):
            await create_session("user1", "basic", max_sessions=5)

        # User2: should still be able to create sessions
        for i in range(5):
            await create_session("user2", "basic", max_sessions=5)

        # Both should be at limit
        user1_count = await redis.scard("user_sessions:user1")
        user2_count = await redis.scard("user_sessions:user2")

        assert user1_count == 5
        assert user2_count == 5

        # Cleanup
        await delete_user_sessions("user1")
        await delete_user_sessions("user2")

    @pytest.mark.asyncio
    async def test_high_concurrency_stress(self):
        """
        Stress test with many concurrent login attempts.

        Simulates 20 concurrent login attempts for user with limit of 10.
        Verifies that exactly 10 succeed and limit is never exceeded.
        """
        username = "test_stress_user"
        redis = await get_redis()

        # Cleanup
        await delete_user_sessions(username)

        max_sessions = 10
        concurrent_attempts = 20

        async def try_create():
            try:
                return await create_session(username, "basic", max_sessions=max_sessions)
            except ValueError:
                return None

        # Run concurrent attempts
        results = await asyncio.gather(*[try_create() for _ in range(concurrent_attempts)])

        # Count successes
        successes = [r for r in results if r is not None]
        assert len(successes) == max_sessions, f"Expected {max_sessions} successes, got {len(successes)}"

        # Verify exact count in Redis
        user_sessions_key = f"user_sessions:{username}"
        count = await redis.scard(user_sessions_key)
        assert count == max_sessions, f"Expected {max_sessions} in Redis, got {count}"

        # Cleanup
        await delete_user_sessions(username)
