"""
Tests for configuration defaults API endpoints.

Tests:
- GET /api/admin/config_defaults - Retrieve defaults
- POST /api/admin/config_defaults - Save defaults
- Authorization (admin only for POST, elevated/admin for GET)
- Data validation and persistence
"""
import pytest
import httpx

pytestmark = pytest.mark.api


class TestGetConfigDefaults:
    """Tests for GET /api/admin/config_defaults endpoint."""

    @pytest.mark.asyncio
    async def test_get_config_defaults_success(
        self,
        admin_client_with_token: httpx.AsyncClient
    ):
        """Test admin can retrieve config defaults."""
        response = await admin_client_with_token.get("/api/admin/config_defaults")

        assert response.status_code == 200
        data = response.json()
        assert "defaults" in data
        assert "success" in data
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_get_config_defaults_elevated_access(
        self,
        elevated_client_with_token: httpx.AsyncClient
    ):
        """Test elevated users can retrieve config defaults."""
        response = await elevated_client_with_token.get("/api/admin/config_defaults")

        assert response.status_code == 200
        data = response.json()
        assert "defaults" in data

    @pytest.mark.asyncio
    async def test_get_config_defaults_basic_denied(
        self,
        basic_client_with_token: httpx.AsyncClient
    ):
        """Test basic users cannot retrieve config defaults."""
        response = await basic_client_with_token.get("/api/admin/config_defaults")

        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_get_config_defaults_unauthenticated_denied(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test unauthenticated requests are denied."""
        response = await http_client.get("/api/admin/config_defaults")

        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_get_config_defaults_returns_empty_when_no_defaults(
        self,
        admin_client_with_token: httpx.AsyncClient,
        db_session
    ):
        """Test returns empty defaults when none are saved."""
        from app.models.config_defaults import ConfigDefaults
        from sqlalchemy import delete

        # Clear any existing defaults
        await db_session.execute(delete(ConfigDefaults))
        await db_session.commit()

        response = await admin_client_with_token.get("/api/admin/config_defaults")

        assert response.status_code == 200
        data = response.json()
        # Should return empty dict or None for defaults
        assert data["defaults"] is None or data["defaults"] == {}


class TestSaveConfigDefaults:
    """Tests for POST /api/admin/config_defaults endpoint."""

    @pytest.mark.asyncio
    async def test_save_config_defaults_success(
        self,
        admin_client_with_token: httpx.AsyncClient,
        csrf_token: str
    ):
        """Test admin can save config defaults."""
        test_defaults = {
            "PingCount": 25,
            "UpdateChannel": "stable",
            "EnableCloud": True,
            "CloudServerURL": "https://modemcheck.example.com",
            "CloudServerPort": 443
        }

        response = await admin_client_with_token.post(
            "/api/admin/config_defaults",
            json=test_defaults,
            headers={"X-CSRF-Token": csrf_token}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "saved successfully" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_save_config_defaults_persists(
        self,
        admin_client_with_token: httpx.AsyncClient,
        csrf_token: str
    ):
        """Test saved defaults persist and can be retrieved."""
        test_defaults = {
            "PingCount": 50,
            "UpdateChannel": "beta",
            "EnableSpeedtest": False
        }

        # Save defaults
        save_response = await admin_client_with_token.post(
            "/api/admin/config_defaults",
            json=test_defaults,
            headers={"X-CSRF-Token": csrf_token}
        )
        assert save_response.status_code == 200

        # Retrieve and verify
        get_response = await admin_client_with_token.get("/api/admin/config_defaults")
        assert get_response.status_code == 200
        data = get_response.json()
        assert data["defaults"]["PingCount"] == 50
        assert data["defaults"]["UpdateChannel"] == "beta"
        assert data["defaults"]["EnableSpeedtest"] is False

    @pytest.mark.asyncio
    async def test_save_config_defaults_updates_existing(
        self,
        admin_client_with_token: httpx.AsyncClient
    ):
        """Test saving defaults updates existing row, not creates new."""
        # Get first CSRF token
        session_resp = await admin_client_with_token.get("/api/auth/session_check")
        csrf_token1 = session_resp.json()["csrf_token"]

        first_defaults = {"PingCount": 10}
        await admin_client_with_token.post(
            "/api/admin/config_defaults",
            json=first_defaults,
            headers={"X-CSRF-Token": csrf_token1}
        )

        # Get new CSRF token
        session_resp = await admin_client_with_token.get("/api/auth/session_check")
        csrf_token2 = session_resp.json()["csrf_token"]

        second_defaults = {"PingCount": 20}
        await admin_client_with_token.post(
            "/api/admin/config_defaults",
            json=second_defaults,
            headers={"X-CSRF-Token": csrf_token2}
        )

        # Verify only one set of defaults and it's the latest
        get_response = await admin_client_with_token.get("/api/admin/config_defaults")
        data = get_response.json()
        assert data["defaults"]["PingCount"] == 20

    @pytest.mark.asyncio
    async def test_save_config_defaults_elevated_denied(
        self,
        elevated_client_with_token: httpx.AsyncClient
    ):
        """Test elevated users cannot save config defaults (admin only)."""
        # Get CSRF token
        session_resp = await elevated_client_with_token.get("/api/auth/session_check")
        csrf_token = session_resp.json()["csrf_token"]

        test_defaults = {"PingCount": 25}
        response = await elevated_client_with_token.post(
            "/api/admin/config_defaults",
            json=test_defaults,
            headers={"X-CSRF-Token": csrf_token}
        )

        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_save_config_defaults_basic_denied(
        self,
        basic_client_with_token: httpx.AsyncClient
    ):
        """Test basic users cannot save config defaults."""
        # Get CSRF token
        session_resp = await basic_client_with_token.get("/api/auth/session_check")
        csrf_token = session_resp.json()["csrf_token"]

        test_defaults = {"PingCount": 25}
        response = await basic_client_with_token.post(
            "/api/admin/config_defaults",
            json=test_defaults,
            headers={"X-CSRF-Token": csrf_token}
        )

        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_save_config_defaults_requires_csrf(
        self,
        admin_client_with_token: httpx.AsyncClient
    ):
        """Test CSRF token is required for saving defaults."""
        test_defaults = {"PingCount": 25}
        response = await admin_client_with_token.post(
            "/api/admin/config_defaults",
            json=test_defaults
            # No CSRF token
        )

        assert response.status_code in [400, 403, 422]

    @pytest.mark.asyncio
    async def test_save_config_defaults_invalid_csrf(
        self,
        admin_client_with_token: httpx.AsyncClient
    ):
        """Test invalid CSRF token is rejected."""
        test_defaults = {"PingCount": 25}
        response = await admin_client_with_token.post(
            "/api/admin/config_defaults",
            json=test_defaults,
            headers={"X-CSRF-Token": "invalid_token_12345"}
        )

        assert response.status_code in [400, 403]


class TestConfigDefaultsAuditLogging:
    """Tests for audit logging of config defaults operations."""

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="NullPool limitation - test session cannot see server's audit log writes due to connection isolation")
    async def test_save_defaults_creates_audit_log(
        self,
        admin_client_with_token: httpx.AsyncClient,
        csrf_token: str,
        db_session
    ):
        """Test saving defaults creates an audit log entry.

        Note: This test is skipped due to NullPool connection isolation.
        The test's db_session and the server's session use separate connections,
        so the test cannot verify the audit log entry was created.
        Audit logging is verified by integration tests that query the API.
        """
        from app.models.audit import UserActivityLog
        from sqlalchemy import select

        test_defaults = {"PingCount": 75}
        response = await admin_client_with_token.post(
            "/api/admin/config_defaults",
            json=test_defaults,
            headers={"X-CSRF-Token": csrf_token}
        )
        assert response.status_code == 200

        # Check for audit log entry
        result = await db_session.execute(
            select(UserActivityLog).where(
                UserActivityLog.action_type == "update_config_defaults"
            ).order_by(UserActivityLog.timestamp.desc())
        )
        log_entry = result.scalar_one_or_none()

        assert log_entry is not None
        assert log_entry.success is True


class TestConfigDefaultsEdgeCases:
    """Edge case tests for config defaults."""

    @pytest.mark.asyncio
    async def test_save_empty_defaults(
        self,
        admin_client_with_token: httpx.AsyncClient,
        csrf_token: str
    ):
        """Test saving empty defaults object."""
        response = await admin_client_with_token.post(
            "/api/admin/config_defaults",
            json={},
            headers={"X-CSRF-Token": csrf_token}
        )

        # Should accept empty defaults
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_save_nested_defaults(
        self,
        admin_client_with_token: httpx.AsyncClient,
        csrf_token: str
    ):
        """Test saving defaults with nested objects."""
        nested_defaults = {
            "PingCount": 25,
            "DiagnosticsConfig": {
                "EnablePing": True,
                "PingTargets": ["8.8.8.8", "1.1.1.1"]
            }
        }

        response = await admin_client_with_token.post(
            "/api/admin/config_defaults",
            json=nested_defaults,
            headers={"X-CSRF-Token": csrf_token}
        )
        assert response.status_code == 200

        # Verify nested structure preserved
        get_response = await admin_client_with_token.get("/api/admin/config_defaults")
        data = get_response.json()
        assert data["defaults"]["DiagnosticsConfig"]["EnablePing"] is True
        assert len(data["defaults"]["DiagnosticsConfig"]["PingTargets"]) == 2

    @pytest.mark.asyncio
    async def test_save_defaults_with_special_characters(
        self,
        admin_client_with_token: httpx.AsyncClient,
        csrf_token: str
    ):
        """Test saving defaults with special characters in strings."""
        special_defaults = {
            "Description": "Test with special chars: <>&\"'",
            "CustomPath": "/path/with spaces/and-dashes"
        }

        response = await admin_client_with_token.post(
            "/api/admin/config_defaults",
            json=special_defaults,
            headers={"X-CSRF-Token": csrf_token}
        )
        assert response.status_code == 200

        # Verify special characters preserved
        get_response = await admin_client_with_token.get("/api/admin/config_defaults")
        data = get_response.json()
        assert "<>&" in data["defaults"]["Description"]
