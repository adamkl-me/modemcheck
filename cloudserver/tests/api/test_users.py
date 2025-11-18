"""API tests for user management endpoints (/api/users)."""
import pytest
import httpx

pytestmark = pytest.mark.api

class TestUserManagement:
    @pytest.mark.asyncio
    async def test_list_users(self, admin_client_with_token: httpx.AsyncClient):
        response = await admin_client_with_token.get("/api/users")
        assert response.status_code == 200
        data = response.json()
        assert "users" in data
    
    @pytest.mark.asyncio
    async def test_create_user(self, admin_client_with_token: httpx.AsyncClient):
        session_check = await admin_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")
        response = await admin_client_with_token.post("/api/users", json={
            "username": "new_test_user",
            "password": "TestPass123!",
            "role": "basic",
            "must_change_password": False
        }, headers={"X-CSRF-Token": csrf})
        assert response.status_code in [200, 409]  # 409 if already exists
    
    @pytest.mark.asyncio
    async def test_delete_user(self, admin_client_with_token: httpx.AsyncClient, basic_user):
        session_check = await admin_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")
        response = await admin_client_with_token.request("DELETE", "/api/users", json={"username": basic_user.username}, headers={"X-CSRF-Token": csrf})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_cannot_delete_self(self, admin_client_with_token: httpx.AsyncClient):
        session_check = await admin_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")
        response = await admin_client_with_token.request("DELETE", "/api/users", json={"username": "admin"}, headers={"X-CSRF-Token": csrf})
        assert response.status_code == 400
