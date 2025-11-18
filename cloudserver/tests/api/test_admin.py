"""API tests for admin endpoints (/api/admin)."""
import pytest
import httpx

pytestmark = pytest.mark.api

class TestAPIKeys:
    @pytest.mark.asyncio
    async def test_create_api_key(self, admin_client_with_token: httpx.AsyncClient):
        session_check = await admin_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")
        response = await admin_client_with_token.post("/api/admin/api_keys", json={"name": "test_key"}, headers={"X-CSRF-Token": csrf})
        assert response.status_code == 200
        data = response.json()
        assert "api_key" in data
    
    @pytest.mark.asyncio
    async def test_list_api_keys(self, admin_client_with_token: httpx.AsyncClient):
        response = await admin_client_with_token.get("/api/admin/api_keys")
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_delete_api_key(self, admin_client_with_token: httpx.AsyncClient, active_api_key):
        session_check = await admin_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")
        preview = f"{active_api_key.api_key[:4]}...{active_api_key.api_key[-4:]}"
        response = await admin_client_with_token.request("DELETE", "/api/admin/api_keys", json={"api_key_preview": preview}, headers={"X-CSRF-Token": csrf})
        assert response.status_code == 200

class TestLogs:
    @pytest.mark.asyncio
    async def test_get_user_activity_logs(self, admin_client_with_token: httpx.AsyncClient):
        response = await admin_client_with_token.get("/api/admin/logs/user_activity")
        assert response.status_code == 200
        data = response.json()
        assert "logs" in data
    
    @pytest.mark.asyncio
    async def test_get_client_submission_logs(self, admin_client_with_token: httpx.AsyncClient):
        response = await admin_client_with_token.get("/api/admin/logs/client_submissions")
        assert response.status_code == 200
