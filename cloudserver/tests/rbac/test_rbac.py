"""
Role-Based Access Control (RBAC) tests.

Tests access permissions for:
- basic role
- elevated role
- admin role
"""
import pytest
import httpx

pytestmark = pytest.mark.rbac


class TestBasicRole:
    """Tests for basic role permissions."""
    
    @pytest.mark.asyncio
    async def test_basic_can_view_data(self, basic_client_with_token: httpx.AsyncClient):
        """Basic users can view modem data."""
        response = await basic_client_with_token.get("/api/db/list_modems")
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_basic_cannot_create_api_keys(self, basic_client_with_token: httpx.AsyncClient):
        """Basic users cannot create API keys."""
        # Get CSRF token for basic user
        session_check = await basic_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")

        response = await basic_client_with_token.post(
            "/api/admin/api_keys",
            json={"name": "test"},
            headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code in [401, 403]
    
    @pytest.mark.asyncio
    async def test_basic_cannot_delete_checks(self, basic_client_with_token: httpx.AsyncClient):
        """Basic users cannot delete checks."""
        # Get CSRF token for basic user
        session_check = await basic_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")

        response = await basic_client_with_token.request(
            "DELETE",
            "/api/data/check",
            json={"check_id": 1},
            headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code in [401, 403]
    
    @pytest.mark.asyncio
    async def test_basic_cannot_manage_users(self, basic_client_with_token: httpx.AsyncClient):
        """Basic users cannot manage users."""
        response = await basic_client_with_token.get("/api/users")
        assert response.status_code in [401, 403]


class TestElevatedRole:
    """Tests for elevated role permissions."""
    
    @pytest.mark.asyncio
    async def test_elevated_can_create_api_keys(self, elevated_client_with_token: httpx.AsyncClient):
        """Elevated users can create API keys."""
        # Get CSRF token first
        session_check = await elevated_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")
        
        response = await elevated_client_with_token.post(
            "/api/admin/api_keys",
            json={"name": "test_key"},
            headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code in [200, 400]  # 200 success, 400 if validation fails
    
    @pytest.mark.asyncio
    async def test_elevated_can_bulk_upload(self, elevated_client_with_token: httpx.AsyncClient):
        """Elevated users can perform bulk uploads."""
        # Test will check if endpoint is accessible (may fail validation but not auth)
        response = await elevated_client_with_token.post("/api/data/bulk_upload", files={})
        assert response.status_code != 401  # Not unauthorized
    
    @pytest.mark.asyncio
    async def test_elevated_cannot_delete_checks(self, elevated_client_with_token: httpx.AsyncClient):
        """Elevated users cannot delete checks (admin only)."""
        session_check = await elevated_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")

        response = await elevated_client_with_token.request(
            "DELETE",
            "/api/data/check",
            json={"check_id": 1},
            headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code in [401, 403, 404]  # Not authorized or not found
    
    @pytest.mark.asyncio
    async def test_elevated_cannot_manage_users(self, elevated_client_with_token: httpx.AsyncClient):
        """Elevated users cannot manage users."""
        response = await elevated_client_with_token.get("/api/users")
        assert response.status_code in [401, 403]


class TestAdminRole:
    """Tests for admin role permissions."""
    
    @pytest.mark.asyncio
    async def test_admin_can_create_api_keys(self, admin_client_with_token: httpx.AsyncClient):
        """Admin users can create API keys."""
        session_check = await admin_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")
        
        response = await admin_client_with_token.post(
            "/api/admin/api_keys",
            json={"name": "admin_test_key"},
            headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_admin_can_delete_checks(self, admin_client_with_token: httpx.AsyncClient, sample_modem_check):
        """Admin users can delete checks."""
        session_check = await admin_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")

        response = await admin_client_with_token.request(
            "DELETE",
            "/api/data/check",
            json={"check_id": sample_modem_check.id},
            headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_admin_can_manage_users(self, admin_client_with_token: httpx.AsyncClient):
        """Admin users can manage users."""
        response = await admin_client_with_token.get("/api/users")
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_admin_can_view_logs(self, admin_client_with_token: httpx.AsyncClient):
        """Admin users can view audit logs."""
        response = await admin_client_with_token.get("/api/admin/logs/user_activity")
        assert response.status_code == 200
