"""
Error handling tests.

Tests for:
- Invalid action parameters
- Content-Type validation
- Cookie security flags
- HTTP method validation
- Input validation errors
"""
import pytest
import httpx

pytestmark = pytest.mark.api


class TestInvalidActions:
    """Invalid action parameter tests."""

    @pytest.mark.asyncio
    async def test_auth_invalid_action(self, http_client: httpx.AsyncClient):
        """Test authentication endpoint with invalid action."""
        response = await http_client.post("/api/auth/login", json={
            "username": "admin",
            "password": "test",
            "action": "invalid_action"
        })

        # Should reject invalid action or ignore it
        assert response.status_code in [400, 401, 422]

    @pytest.mark.asyncio
    async def test_admin_api_invalid_action(self, admin_client_with_token: httpx.AsyncClient):
        """Test admin API endpoint with invalid action."""
        response = await admin_client_with_token.get("/api/admin/api_keys?action=invalid_action")

        # Should reject or ignore invalid action
        # May return 400 (rejected) or 200 (ignored)
        assert response.status_code in [200, 400, 422]

    @pytest.mark.asyncio
    async def test_user_mgmt_invalid_action(self, admin_client_with_token: httpx.AsyncClient):
        """Test user management endpoint with invalid action."""
        response = await admin_client_with_token.get("/api/users?action=invalid_action")

        # Should reject or ignore invalid action
        assert response.status_code in [200, 400, 422]


class TestContentTypeValidation:
    """Content-Type header validation tests."""

    @pytest.mark.asyncio
    async def test_upload_wrong_content_type(self, http_client: httpx.AsyncClient, active_api_key):
        """Test upload with wrong Content-Type header."""
        import hashlib
        import json

        modem_id = "XB8-AA:BB:CC:DD:EE:FF"
        filename = "2024-01-01_12-00-00.json"
        file_content = json.dumps({"test": "data"}).encode()
        checksum = hashlib.sha256(file_content).hexdigest()

        # Send JSON but claim it's plain text
        response = await http_client.post(
            "/api/upload",
            content=file_content,
            headers={"Content-Type": "text/plain"},
            params={
                "api_key": active_api_key.api_key,
                "modem_id": modem_id,
                "filename": filename,
                "checksum": checksum
            }
        )

        # Should reject wrong content type or handle gracefully
        assert response.status_code in [400, 415, 422]

    @pytest.mark.asyncio
    async def test_json_endpoint_wrong_content_type(self, http_client: httpx.AsyncClient):
        """Test JSON endpoint with wrong Content-Type."""
        # Send form data to JSON endpoint
        response = await http_client.post(
            "/api/auth/login",
            data={"username": "admin", "password": "test"},  # form data, not JSON
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        # FastAPI should handle this and either parse it or reject it
        assert response.status_code in [400, 415, 422]


class TestHTTPMethodValidation:
    """HTTP method validation tests."""

    @pytest.mark.asyncio
    async def test_get_on_post_endpoint(self, http_client: httpx.AsyncClient):
        """Test GET request on POST-only endpoint."""
        response = await http_client.get("/api/auth/login")

        # Should return 405 Method Not Allowed
        assert response.status_code == 405

    @pytest.mark.asyncio
    async def test_post_on_get_endpoint(self, http_client: httpx.AsyncClient):
        """Test POST request on GET-only endpoint."""
        response = await http_client.post("/api/health")

        # FastAPI returns 404 for non-existent method+path combinations
        # (405 would require explicit route handler for POST)
        assert response.status_code in [404, 405]

    @pytest.mark.asyncio
    async def test_delete_without_permission(self, basic_client_with_token: httpx.AsyncClient, csrf_token_basic: str):
        """Test DELETE request without proper permissions."""
        # Try to delete a check as basic user
        response = await basic_client_with_token.request(
            "DELETE",
            "/api/data/check",
            json={"check_id": 1},
            headers={"X-CSRF-Token": csrf_token_basic}
        )

        # Should be forbidden (basic users can't delete)
        assert response.status_code in [401, 403]


class TestUploadValidation:
    """Upload endpoint input validation tests."""

    @pytest.mark.asyncio
    async def test_upload_invalid_filename_format(self, http_client: httpx.AsyncClient, active_api_key):
        """Test upload with invalid filename format."""
        from io import BytesIO
        import hashlib
        import json

        modem_id = "XB8-AA:BB:CC:DD:EE:FF"
        file_content = json.dumps({"test": "data"}).encode()
        checksum = hashlib.sha256(file_content).hexdigest()

        # Invalid filename formats
        invalid_filenames = [
            "invalid.txt",  # Wrong extension
            "no-timestamp.json",  # Missing timestamp
            "2024/01/01_12-00-00.json",  # Wrong separator
            "../../../etc/passwd",  # Path traversal attempt
        ]

        for filename in invalid_filenames:
            files = {"file": (filename, BytesIO(file_content), "application/json")}
            data = {
                "api_key": active_api_key.api_key,
                "modem_id": modem_id,
                "filename": filename,
                "checksum": checksum
            }

            response = await http_client.post("/api/upload", files=files, data=data)

            # Should reject invalid filename formats
            assert response.status_code in [400, 422], f"Invalid filename accepted: {filename}"

    @pytest.mark.asyncio
    async def test_upload_invalid_modem_id_format(self, http_client: httpx.AsyncClient, active_api_key):
        """Test upload with invalid modem_id format."""
        from io import BytesIO
        import hashlib
        import json

        filename = "2024-01-01_12-00-00.json"
        file_content = json.dumps({"test": "data"}).encode()
        checksum = hashlib.sha256(file_content).hexdigest()

        # Invalid modem_id formats
        invalid_modem_ids = [
            "invalid",  # Missing MAC
            "XB8",  # No MAC
            "AA:BB:CC:DD:EE:FF",  # No model
            "XB8-invalid-mac",  # Invalid MAC format
        ]

        for modem_id in invalid_modem_ids:
            files = {"file": (filename, BytesIO(file_content), "application/json")}
            data = {
                "api_key": active_api_key.api_key,
                "modem_id": modem_id,
                "filename": filename,
                "checksum": checksum
            }

            response = await http_client.post("/api/upload", files=files, data=data)

            # Should reject invalid modem_id formats
            assert response.status_code in [400, 422], f"Invalid modem_id accepted: {modem_id}"

    @pytest.mark.asyncio
    async def test_upload_missing_required_fields(self, http_client: httpx.AsyncClient):
        """Test upload with missing required fields."""
        from io import BytesIO

        # Missing api_key
        files = {"file": ("test.json", BytesIO(b'{"test": "data"}'), "application/json")}
        data = {
            "modem_id": "XB8-AA:BB:CC:DD:EE:FF",
            "filename": "2024-01-01_12-00-00.json",
            "checksum": "abc123"
        }
        response = await http_client.post("/api/upload", files=files, data=data)
        assert response.status_code in [400, 422]

        # Missing modem_id
        files = {"file": ("test.json", BytesIO(b'{"test": "data"}'), "application/json")}
        data = {
            "api_key": "test_key",
            "filename": "2024-01-01_12-00-00.json",
            "checksum": "abc123"
        }
        response = await http_client.post("/api/upload", files=files, data=data)
        assert response.status_code in [400, 422]

        # Missing filename
        files = {"file": ("test.json", BytesIO(b'{"test": "data"}'), "application/json")}
        data = {
            "api_key": "test_key",
            "modem_id": "XB8-AA:BB:CC:DD:EE:FF",
            "checksum": "abc123"
        }
        response = await http_client.post("/api/upload", files=files, data=data)
        assert response.status_code in [400, 422]

        # Missing checksum
        files = {"file": ("test.json", BytesIO(b'{"test": "data"}'), "application/json")}
        data = {
            "api_key": "test_key",
            "modem_id": "XB8-AA:BB:CC:DD:EE:FF",
            "filename": "2024-01-01_12-00-00.json"
        }
        response = await http_client.post("/api/upload", files=files, data=data)
        assert response.status_code in [400, 422]


class TestResponseHeaders:
    """Response header validation tests."""

    @pytest.mark.asyncio
    async def test_security_headers_present(self, http_client: httpx.AsyncClient):
        """Test that security headers are present in responses."""
        response = await http_client.get("/health")

        # Check for security headers
        assert "X-Content-Type-Options" in response.headers
        assert response.headers["X-Content-Type-Options"] == "nosniff"

        assert "X-Frame-Options" in response.headers
        assert response.headers["X-Frame-Options"] == "DENY"

        assert "X-XSS-Protection" in response.headers

        assert "Referrer-Policy" in response.headers

    @pytest.mark.asyncio
    async def test_content_type_json_endpoints(self, http_client: httpx.AsyncClient):
        """Test that JSON endpoints return correct Content-Type."""
        response = await http_client.get("/health")

        # Should return JSON content type
        assert "application/json" in response.headers.get("content-type", "").lower()

    @pytest.mark.asyncio
    async def test_cors_headers_present(self, http_client: httpx.AsyncClient):
        """Test that CORS headers are present for cross-origin requests."""
        # Test CORS headers on GET request to session_check (public endpoint)
        response = await http_client.get(
            "/api/auth/session_check",
            headers={"Origin": "http://localhost:3000"}
        )

        # Should return 200 for session check
        assert response.status_code == 200

        # CORS headers should be present when Origin header is sent
        # Note: CORS middleware adds these headers for all requests with Origin header
        assert "access-control-allow-origin" in response.headers or \
               "Access-Control-Allow-Origin" in response.headers


class TestErrorResponses:
    """Error response format tests."""

    @pytest.mark.asyncio
    async def test_404_error_format(self, http_client: httpx.AsyncClient):
        """Test 404 error response format."""
        response = await http_client.get("/api/nonexistent_endpoint")

        assert response.status_code == 404

        # Check error response structure
        data = response.json()
        assert "error" in data or "detail" in data

    @pytest.mark.asyncio
    async def test_401_error_format(self, http_client: httpx.AsyncClient):
        """Test 401 error response format for unauthorized access."""
        response = await http_client.get("/api/admin/api_keys")

        assert response.status_code == 401

        # Check error response structure
        data = response.json()
        assert "error" in data or "detail" in data

    @pytest.mark.asyncio
    async def test_403_error_format(self, basic_client_with_token: httpx.AsyncClient):
        """Test 403 error response format for forbidden access."""
        response = await basic_client_with_token.get("/api/admin/api_keys")

        assert response.status_code in [401, 403]

        # Check error response structure
        if response.status_code == 403:
            data = response.json()
            assert "error" in data or "detail" in data

    @pytest.mark.asyncio
    async def test_422_error_format(self, http_client: httpx.AsyncClient):
        """Test 422 validation error response format."""
        # Send invalid data to trigger validation error
        response = await http_client.post("/api/auth/login", json={
            "username": "",  # Empty username should fail validation
            "password": ""
        })

        assert response.status_code in [400, 401, 422]

        # FastAPI returns structured validation errors for 422
        if response.status_code == 422:
            data = response.json()
            assert "detail" in data
