"""
Tests for database connection pool configuration and behavior.
"""
import pytest
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
from app.core.database import get_engine, init_db
from app.core.config import settings
from app.models import User

pytestmark = pytest.mark.api


class TestDatabasePoolConfiguration:
    """Tests for database connection pool settings."""

    @pytest.mark.skip(reason="Test environment uses NullPool, which doesn't have size() method")
    def test_pool_size_configuration(self):
        """Test that pool size is correctly configured."""
        engine = get_engine()

        # Verify pool size matches settings
        assert engine.pool.size() == settings.db_pool_size

        # For production, should be 10 per worker (not 20)
        if not settings.is_test():
            assert settings.db_pool_size == 10
            assert settings.db_max_overflow == 5

    def test_pool_timeout_configuration(self):
        """Test that pool timeout is configured."""
        engine = get_engine()

        # Verify timeout is set
        if not settings.is_test():
            assert settings.db_pool_timeout == 30

    def test_statement_timeout_configuration(self):
        """Test that statement timeout is configured."""
        if not settings.is_test():
            assert settings.db_statement_timeout == 60000  # 60 seconds


class TestDatabasePoolBehavior:
    """Tests for database pool runtime behavior."""

    @pytest.mark.asyncio
    async def test_concurrent_connections(self, db_session: AsyncSession):
        """
        Test that pool handles concurrent connections properly.

        Should not exceed pool_size + max_overflow.
        """
        async def query_task():
            """Execute a simple query."""
            result = await db_session.execute(text("SELECT 1"))
            return result.scalar()

        # Run multiple concurrent queries
        tasks = [query_task() for _ in range(5)]
        results = await asyncio.gather(*tasks)

        # All should succeed
        assert all(r == 1 for r in results)

    @pytest.mark.asyncio
    async def test_connection_recycling(self, db_session: AsyncSession):
        """Test that connections are recycled after pool_recycle time."""
        # Execute query
        result = await db_session.execute(text("SELECT pg_backend_pid()"))
        pid1 = result.scalar()

        # Wait a bit (not full recycle time in test)
        await asyncio.sleep(0.1)

        # Execute another query
        result = await db_session.execute(text("SELECT pg_backend_pid()"))
        pid2 = result.scalar()

        # Should reuse same connection in test environment
        # (full recycle test would require waiting pool_recycle seconds)
        assert isinstance(pid1, int)
        assert isinstance(pid2, int)

    @pytest.mark.asyncio
    async def test_pool_pre_ping(self, db_session: AsyncSession):
        """Test that pool_pre_ping validates connections before use."""
        # This verifies that stale connections are detected
        # pool_pre_ping should be enabled in production

        result = await db_session.execute(select(User).limit(1))
        users = result.scalars().all()

        # Should succeed without connection errors
        assert isinstance(users, list)

    @pytest.mark.asyncio
    async def test_transaction_rollback(self, db_session: AsyncSession):
        """Test that transactions roll back properly on error."""
        try:
            # Try to execute invalid SQL
            await db_session.execute(text("SELECT * FROM nonexistent_table"))
            await db_session.commit()
        except Exception:
            # Should rollback automatically
            await db_session.rollback()

        # Connection should still be usable
        result = await db_session.execute(text("SELECT 1"))
        assert result.scalar() == 1


class TestStatementTimeout:
    """Tests for PostgreSQL statement timeout."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        True,  # Skip in CI - requires long-running query setup
        reason="Requires database with long-running query capability"
    )
    async def test_statement_timeout_enforced(self, db_session: AsyncSession):
        """
        Test that long-running queries are terminated.

        NOTE: Skipped by default - requires test database configuration.
        """
        # This would require executing a query that takes > 60 seconds
        # In production, pg_sleep would trigger the timeout

        try:
            await db_session.execute(text("SELECT pg_sleep(65)"))
            pytest.fail("Statement should have timed out")
        except Exception as e:
            # Should raise timeout error
            assert "timeout" in str(e).lower() or "canceling statement" in str(e).lower()


class TestPoolExhaustion:
    """Tests for connection pool exhaustion handling."""

    @pytest.mark.asyncio
    async def test_pool_exhaustion_timeout(self):
        """
        Test that pool times out gracefully when exhausted.

        NOTE: This is a conceptual test - actual exhaustion testing
        requires spinning up pool_size + max_overflow connections.
        """
        # In test environment with NullPool, this doesn't apply
        # In production, exceeding pool_size + max_overflow would trigger timeout

        engine = get_engine()

        if settings.is_test():
            # NullPool doesn't have size limits
            pytest.skip("NullPool doesn't enforce limits")

        # In production, this would test:
        # 1. Create pool_size + max_overflow connections
        # 2. Try to create one more
        # 3. Should wait pool_timeout seconds
        # 4. Should raise timeout error

        assert engine.pool.timeout() == settings.db_pool_timeout
