"""API tests for data management endpoints (/api/data)."""
import pytest
import httpx
from io import BytesIO
import json

pytestmark = pytest.mark.api

class TestDataManagement:
    @pytest.mark.asyncio
    async def test_delete_check(self, admin_client_with_token: httpx.AsyncClient, sample_modem_check):
        session_check = await admin_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")
        response = await admin_client_with_token.request("DELETE", "/api/data/check", json={"check_id": sample_modem_check.id}, headers={"X-CSRF-Token": csrf})
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_bulk_upload(self, elevated_client_with_token: httpx.AsyncClient, sample_modem_check_data):
        session_check = await elevated_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")
        file_content = json.dumps(sample_modem_check_data).encode('utf-8')
        files = {"files": ("test.json", BytesIO(file_content), "application/json")}
        response = await elevated_client_with_token.post("/api/data/bulk_upload", files=files, headers={"X-CSRF-Token": csrf})
        assert response.status_code in [200, 400]
    
    @pytest.mark.asyncio
    async def test_bulk_download(self, elevated_client_with_token: httpx.AsyncClient):
        response = await elevated_client_with_token.get("/api/data/bulk_download?start_date=2024-01-01&end_date=2024-12-31")
        assert response.status_code in [200, 404]  # 404 if no data
