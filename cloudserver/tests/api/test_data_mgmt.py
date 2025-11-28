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
        files = {"file": ("test.json", BytesIO(file_content), "application/json")}
        response = await elevated_client_with_token.post("/api/data/bulk_upload", files=files, headers={"X-CSRF-Token": csrf})
        assert response.status_code in [200, 400]

    @pytest.mark.asyncio
    async def test_bulk_download(self, elevated_client_with_token: httpx.AsyncClient):
        response = await elevated_client_with_token.get("/api/data/bulk_download?start_date=2024-01-01&end_date=2024-12-31")
        assert response.status_code in [200, 404]  # 404 if no data


class TestDeletePermissions:
    """Test that delete operations require admin role (not just elevated)."""

    @pytest.mark.asyncio
    async def test_delete_check_as_elevated_user_forbidden(
        self, elevated_client_with_token: httpx.AsyncClient, sample_modem_check
    ):
        """Elevated users should NOT be able to delete checks - admin only."""
        session_check = await elevated_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")
        response = await elevated_client_with_token.request(
            "DELETE",
            "/api/data/check",
            json={"check_id": sample_modem_check.id},
            headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code == 403
        data = response.json()
        assert "admin" in data.get("detail", "").lower()

    @pytest.mark.asyncio
    async def test_delete_check_as_basic_user_forbidden(
        self, basic_client_with_token: httpx.AsyncClient, sample_modem_check, csrf_token_basic: str
    ):
        """Basic users should NOT be able to delete checks - admin only."""
        response = await basic_client_with_token.request(
            "DELETE",
            "/api/data/check",
            json={"check_id": sample_modem_check.id},
            headers={"X-CSRF-Token": csrf_token_basic}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_bulk_delete_as_elevated_user_forbidden(
        self, elevated_client_with_token: httpx.AsyncClient, sample_modem_check
    ):
        """Elevated users should NOT be able to bulk delete - admin only."""
        session_check = await elevated_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")
        response = await elevated_client_with_token.request(
            "DELETE",
            "/api/data/modem_checks",
            json={"modem_id": sample_modem_check.modem_id},
            headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code == 403
        data = response.json()
        assert "admin" in data.get("detail", "").lower()

    @pytest.mark.asyncio
    async def test_bulk_delete_as_admin_success(
        self, admin_client_with_token: httpx.AsyncClient, sample_modem_check
    ):
        """Admin users CAN bulk delete checks."""
        session_check = await admin_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")
        response = await admin_client_with_token.request(
            "DELETE",
            "/api/data/modem_checks",
            json={"modem_id": sample_modem_check.modem_id},
            headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True

    @pytest.mark.asyncio
    async def test_delete_nonexistent_check_404(
        self, admin_client_with_token: httpx.AsyncClient
    ):
        """Deleting a non-existent check should return 404."""
        session_check = await admin_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")
        response = await admin_client_with_token.request(
            "DELETE",
            "/api/data/check",
            json={"check_id": 999999},  # Non-existent ID
            headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code == 404


class TestBulkUploadValidation:
    """Test that bulk upload properly validates modem check files."""

    @pytest.mark.asyncio
    async def test_bulk_upload_rejects_missing_sysinfo(
        self, elevated_client_with_token: httpx.AsyncClient
    ):
        """Files without sysinfo object should be rejected."""
        session_check = await elevated_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")

        invalid_data = {
            "run_count": 2736,
            "last_speed_test": 2736,
            "last_test_success": True
        }
        file_content = json.dumps(invalid_data).encode('utf-8')
        files = {"file": ("invalid.json", BytesIO(file_content), "application/json")}

        response = await elevated_client_with_token.post(
            "/api/data/bulk_upload",
            files=files,
            headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["results"]["failed"] == 1
        assert data["results"]["success"] == 0
        assert any("sysinfo" in error.lower() for error in data["results"]["errors"])

    @pytest.mark.asyncio
    async def test_bulk_upload_rejects_missing_modem_type(
        self, elevated_client_with_token: httpx.AsyncClient
    ):
        """Files without modemtype should be rejected."""
        session_check = await elevated_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")

        invalid_data = {
            "sysinfo": {
                "modemmac": "AABBCC010203",
                "checktime": 1700000000
            },
            "rx": [{"snr": 40}],
            "tx": [{"power": 45}]
        }
        file_content = json.dumps(invalid_data).encode('utf-8')
        files = {"file": ("invalid.json", BytesIO(file_content), "application/json")}

        response = await elevated_client_with_token.post(
            "/api/data/bulk_upload",
            files=files,
            headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["results"]["failed"] == 1
        assert any("modemtype" in error.lower() for error in data["results"]["errors"])

    @pytest.mark.asyncio
    async def test_bulk_upload_rejects_invalid_mac_format(
        self, elevated_client_with_token: httpx.AsyncClient
    ):
        """Files with invalid MAC address format should be rejected."""
        session_check = await elevated_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")

        invalid_data = {
            "sysinfo": {
                "modemtype": "XB8",
                "modemmac": "invalid-mac",
                "checktime": 1700000000
            },
            "rx": [{"snr": 40}],
            "tx": [{"power": 45}]
        }
        file_content = json.dumps(invalid_data).encode('utf-8')
        files = {"file": ("invalid.json", BytesIO(file_content), "application/json")}

        response = await elevated_client_with_token.post(
            "/api/data/bulk_upload",
            files=files,
            headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["results"]["failed"] == 1
        assert any("mac address" in error.lower() for error in data["results"]["errors"])

    @pytest.mark.asyncio
    async def test_bulk_upload_rejects_missing_channel_data(
        self, elevated_client_with_token: httpx.AsyncClient
    ):
        """Files without rx or tx arrays should be rejected."""
        session_check = await elevated_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")

        invalid_data = {
            "sysinfo": {
                "modemtype": "XB8",
                "modemmac": "AABBCC010203",
                "checktime": 1700000000
            }
            # Missing rx and tx arrays
        }
        file_content = json.dumps(invalid_data).encode('utf-8')
        files = {"file": ("invalid.json", BytesIO(file_content), "application/json")}

        response = await elevated_client_with_token.post(
            "/api/data/bulk_upload",
            files=files,
            headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["results"]["failed"] == 1
        assert any("channel data" in error.lower() for error in data["results"]["errors"])

    @pytest.mark.asyncio
    async def test_bulk_upload_accepts_valid_check(
        self, elevated_client_with_token: httpx.AsyncClient
    ):
        """Valid modem check files should be accepted."""
        session_check = await elevated_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")

        valid_data = {
            "sysinfo": {
                "modemtype": "XB8",
                "modemmac": "AABBCC010203",
                "checktime": 1700000000,
                "filename": "test_check.json"
            },
            "rx": [{"snr": 40, "power": -2}],
            "tx": [{"power": 45}]
        }
        file_content = json.dumps(valid_data).encode('utf-8')
        files = {"file": ("valid.json", BytesIO(file_content), "application/json")}

        response = await elevated_client_with_token.post(
            "/api/data/bulk_upload",
            files=files,
            headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["results"]["success"] == 1
        assert data["results"]["failed"] == 0

    @pytest.mark.asyncio
    async def test_bulk_upload_accepts_various_mac_formats(
        self, elevated_client_with_token: httpx.AsyncClient
    ):
        """MAC addresses with separators should be accepted."""
        session_check = await elevated_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")

        # Test with colons
        valid_data = {
            "sysinfo": {
                "modemtype": "XB8",
                "modemmac": "AA:BB:CC:01:02:03",
                "checktime": 1700000001,
                "filename": "test_check_colons.json"
            },
            "rx": [{"snr": 40}],
            "tx": [{"power": 45}]
        }
        file_content = json.dumps(valid_data).encode('utf-8')
        files = {"file": ("valid.json", BytesIO(file_content), "application/json")}

        response = await elevated_client_with_token.post(
            "/api/data/bulk_upload",
            files=files,
            headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["results"]["success"] == 1
