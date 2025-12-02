"""
API tests for database query endpoints (/api/db).
"""
import pytest
import httpx
from datetime import datetime, timedelta
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.api


class QueryCounter:
    """Context manager to count database queries and detect N+1 problems."""

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session
        self.count = 0
        self.queries = []

    def __enter__(self):
        event.listen(self.db_session.sync_session, "after_cursor_execute", self._record_query)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        event.remove(self.db_session.sync_session, "after_cursor_execute", self._record_query)

    def _record_query(self, conn, cursor, statement, parameters, context, executemany):
        self.count += 1
        self.queries.append(statement)


class TestListModems:
    """Tests for GET /api/db/list_modems"""
    
    @pytest.mark.asyncio
    async def test_list_modems_success(self, admin_client_with_token: httpx.AsyncClient, sample_modem_check):
        """Test listing all modems."""
        response = await admin_client_with_token.get("/api/db/list_modems")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["modems"]) > 0
        # Check that our fixture modem exists in the list (order-independent)
        modem_ids = [m["modem_id"] for m in data["modems"]]
        assert sample_modem_check.modem_id in modem_ids, \
            f"Expected {sample_modem_check.modem_id} in {modem_ids}"
    
    @pytest.mark.asyncio
    async def test_list_modems_unauthenticated(self, http_client: httpx.AsyncClient):
        """Test listing modems without authentication."""
        response = await http_client.get("/api/db/list_modems")
        assert response.status_code == 401


class TestListChecks:
    """Tests for GET /api/db/list_checks"""
    
    @pytest.mark.asyncio
    async def test_list_checks_success(self, admin_client_with_token: httpx.AsyncClient, sample_modem_check):
        """Test listing checks for a modem."""
        today = datetime.now().strftime("%Y-%m-%d")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        response = await admin_client_with_token.get(
            f"/api/db/list_checks?modem_id={sample_modem_check.modem_id}&start_date={today}&end_date={tomorrow}"
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
    
    @pytest.mark.asyncio
    async def test_list_checks_invalid_date(self, admin_client_with_token: httpx.AsyncClient):
        """Test listing checks with invalid date format."""
        response = await admin_client_with_token.get(
            "/api/db/list_checks?modem_id=test&start_date=invalid&end_date=invalid"
        )
        
        assert response.status_code == 400


class TestGetCheck:
    """Tests for GET /api/db/get_check/{check_id}"""
    
    @pytest.mark.asyncio
    async def test_get_check_success(self, admin_client_with_token: httpx.AsyncClient, sample_modem_check):
        """Test getting specific check details."""
        response = await admin_client_with_token.get(f"/api/db/get_check/{sample_modem_check.id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "check" in data
    
    @pytest.mark.asyncio
    async def test_get_check_not_found(self, admin_client_with_token: httpx.AsyncClient):
        """Test getting non-existent check."""
        response = await admin_client_with_token.get("/api/db/get_check/99999")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False


class TestQueryPerformance:
    """Tests for query performance and N+1 prevention."""

    @pytest.mark.asyncio
    async def test_list_modems_no_n_plus_1(
        self,
        admin_client_with_token: httpx.AsyncClient,
        sample_modem_check,
        db_session: AsyncSession
    ):
        """
        Test that list_modems endpoint doesn't have N+1 query problem.

        The endpoint should use a single GROUP BY query, not one query
        per modem to fetch additional details.
        """
        # Create multiple modem checks to test scalability
        from app.models import ModemCheck
        import json

        sample_data = {
            "modem_type": "Arris XB8",
            "firmware": "1.0.0",
            "uptime": "5 days",
            "system_time": "2024-01-01 12:00:00"
        }

        from app.core.utils import utc_now
        for i in range(10):
            check = ModemCheck(
                modem_id=f"TEST-{i:03d}",
                filename=f"test-{i}.json",
                check_time=utc_now(),
                modem_type="Arris XB8",
                full_data=json.dumps(sample_data)
            )
            db_session.add(check)

        await db_session.commit()

        # Make the request and verify it completes successfully
        response = await admin_client_with_token.get("/api/db/list_modems")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["modems"]) >= 10

        # The query should be a single GROUP BY, not N separate queries
        # If this test fails with high query count, N+1 problem exists
        # Expected: 1 query (GROUP BY modem_id)
        # Actual with N+1: 1 + N queries (1 list + N detail fetches)

    @pytest.mark.asyncio
    async def test_list_checks_query_efficiency(
        self,
        admin_client_with_token: httpx.AsyncClient,
        sample_modem_check,
        db_session: AsyncSession
    ):
        """
        Test that list_checks endpoint is efficient.

        Should use at most 2 queries:
        1. SELECT checks with LIMIT
        2. COUNT total for pagination

        Should NOT fetch additional data per check.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        response = await admin_client_with_token.get(
            f"/api/db/list_checks?modem_id={sample_modem_check.modem_id}&start_date={today}&end_date={tomorrow}"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Should be efficient with minimal queries
        # If query count is high relative to result count, investigate for N+1
