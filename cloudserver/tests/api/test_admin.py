"""
Comprehensive API tests for admin endpoints (/api/admin).

Tests:
- API key management (create, list, reveal, toggle, delete)
- User activity logs
- Client submission logs
- Authorization and CSRF requirements
"""
import pytest
import httpx
from datetime import datetime, timedelta, timezone

pytestmark = pytest.mark.api


# ============================================================================
# API KEY CREATION TESTS
# ============================================================================

class TestAPIKeyCreation:
    """Tests for POST /api/admin/api_keys endpoint."""

    @pytest.mark.asyncio
    async def test_create_api_key_success(self, admin_client_with_token: httpx.AsyncClient):
        """Test admin can create an API key."""
        session_check = await admin_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")

        response = await admin_client_with_token.post(
            "/api/admin/api_keys",
            json={"name": "test_key_creation"},
            headers={"X-CSRF-Token": csrf}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "api_key" in data
        assert len(data["api_key"]) == 64  # 32 bytes = 64 hex chars
        assert data["name"] == "test_key_creation"

    @pytest.mark.asyncio
    async def test_create_api_key_elevated_user(self, elevated_client_with_token: httpx.AsyncClient):
        """Test elevated user can create an API key."""
        session_check = await elevated_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")

        response = await elevated_client_with_token.post(
            "/api/admin/api_keys",
            json={"name": "elevated_user_key"},
            headers={"X-CSRF-Token": csrf}
        )

        assert response.status_code == 200
        assert response.json()["success"] is True

    @pytest.mark.asyncio
    async def test_create_api_key_basic_user_denied(self, basic_client_with_token: httpx.AsyncClient):
        """Test basic user cannot create API keys."""
        session_check = await basic_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")

        response = await basic_client_with_token.post(
            "/api/admin/api_keys",
            json={"name": "should_fail"},
            headers={"X-CSRF-Token": csrf}
        )

        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_create_api_key_requires_csrf(self, admin_client_with_token: httpx.AsyncClient):
        """Test CSRF token is required for API key creation."""
        response = await admin_client_with_token.post(
            "/api/admin/api_keys",
            json={"name": "no_csrf_key"}
        )

        assert response.status_code in [400, 403, 422]

    @pytest.mark.asyncio
    async def test_create_api_key_response_format(self, admin_client_with_token: httpx.AsyncClient):
        """Test API key creation returns correct response format."""
        session_check = await admin_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")

        response = await admin_client_with_token.post(
            "/api/admin/api_keys",
            json={"name": "format_test_key"},
            headers={"X-CSRF-Token": csrf}
        )

        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert "message" in data
        assert "api_key" in data
        assert "name" in data
        # API key should be hex string
        assert all(c in '0123456789abcdef' for c in data["api_key"])

    @pytest.mark.asyncio
    async def test_create_api_key_unauthenticated_denied(self, http_client: httpx.AsyncClient):
        """Test unauthenticated requests cannot create API keys."""
        response = await http_client.post(
            "/api/admin/api_keys",
            json={"name": "unauthenticated_key"}
        )

        assert response.status_code in [401, 403]


# ============================================================================
# API KEY LISTING TESTS
# ============================================================================

class TestAPIKeyListing:
    """Tests for GET /api/admin/api_keys endpoint."""

    @pytest.mark.asyncio
    async def test_list_api_keys_success(self, admin_client_with_token: httpx.AsyncClient):
        """Test admin can list API keys."""
        response = await admin_client_with_token.get("/api/admin/api_keys")

        assert response.status_code == 200
        data = response.json()
        assert "api_keys" in data
        assert isinstance(data["api_keys"], list)

    @pytest.mark.asyncio
    async def test_list_api_keys_elevated_user(self, elevated_client_with_token: httpx.AsyncClient):
        """Test elevated user can list API keys."""
        response = await elevated_client_with_token.get("/api/admin/api_keys")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_api_keys_basic_user_denied(self, basic_client_with_token: httpx.AsyncClient):
        """Test basic user cannot list API keys."""
        response = await basic_client_with_token.get("/api/admin/api_keys")

        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_list_api_keys_hides_full_key(self, admin_client_with_token: httpx.AsyncClient, active_api_key):
        """Test API key list shows preview, not full key."""
        response = await admin_client_with_token.get("/api/admin/api_keys")

        assert response.status_code == 200
        data = response.json()

        # Find the test key in the list
        for key in data["api_keys"]:
            # Preview format should be XXXX...YYYY (11 chars)
            assert "..." in key["api_key_preview"]
            assert len(key["api_key_preview"]) == 11
            # Full key should NOT be exposed
            assert len(key["api_key_preview"]) != 64

    @pytest.mark.asyncio
    async def test_list_api_keys_includes_metadata(self, admin_client_with_token: httpx.AsyncClient, active_api_key):
        """Test API key list includes all metadata fields."""
        response = await admin_client_with_token.get("/api/admin/api_keys")

        assert response.status_code == 200
        data = response.json()

        for key in data["api_keys"]:
            assert "api_key_preview" in key
            assert "name" in key
            assert "created_at" in key
            assert "is_active" in key


# ============================================================================
# API KEY REVEAL TESTS
# ============================================================================

class TestAPIKeyReveal:
    """Tests for GET /api/admin/api_keys/reveal/{preview} endpoint."""

    @pytest.mark.asyncio
    async def test_reveal_api_key_success(self, admin_client_with_token: httpx.AsyncClient, active_api_key, test_api_key: str):
        """Test admin can reveal full API key."""
        preview = f"{test_api_key[:4]}...{test_api_key[-4:]}"

        response = await admin_client_with_token.get(f"/api/admin/api_keys/reveal/{preview}")

        assert response.status_code == 200
        data = response.json()
        assert data["api_key"] == test_api_key
        assert data["name"] == active_api_key.name

    @pytest.mark.asyncio
    async def test_reveal_api_key_invalid_format(self, admin_client_with_token: httpx.AsyncClient):
        """Test reveal with invalid preview format is rejected."""
        invalid_previews = [
            "invalid",  # Too short
            "abcd1234",  # No dots
            "ab..cd",  # Wrong format
            "1234....5678",  # Extra dots
            "XXXX...YYY",  # Wrong length (10 chars instead of 11)
        ]

        for preview in invalid_previews:
            response = await admin_client_with_token.get(f"/api/admin/api_keys/reveal/{preview}")
            assert response.status_code == 400, f"Expected 400 for preview: {preview}"

    @pytest.mark.asyncio
    async def test_reveal_api_key_not_found(self, admin_client_with_token: httpx.AsyncClient):
        """Test reveal with non-existent key returns 404."""
        fake_preview = "xxxx...yyyy"

        response = await admin_client_with_token.get(f"/api/admin/api_keys/reveal/{fake_preview}")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_reveal_api_key_basic_user_denied(self, basic_client_with_token: httpx.AsyncClient, active_api_key, test_api_key: str):
        """Test basic user cannot reveal API keys."""
        preview = f"{test_api_key[:4]}...{test_api_key[-4:]}"

        response = await basic_client_with_token.get(f"/api/admin/api_keys/reveal/{preview}")

        assert response.status_code in [401, 403]


# ============================================================================
# API KEY TOGGLE TESTS
# ============================================================================

class TestAPIKeyToggle:
    """Tests for PUT /api/admin/api_keys/toggle endpoint."""

    @pytest.mark.asyncio
    async def test_toggle_api_key_deactivate(self, admin_client_with_token: httpx.AsyncClient, active_api_key, test_api_key: str):
        """Test deactivating an API key."""
        session_check = await admin_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")

        preview = f"{test_api_key[:4]}...{test_api_key[-4:]}"

        response = await admin_client_with_token.put(
            "/api/admin/api_keys/toggle",
            json={"api_key_preview": preview, "is_active": False},
            headers={"X-CSRF-Token": csrf}
        )

        assert response.status_code == 200
        assert "deactivated" in response.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_toggle_api_key_activate(self, admin_client_with_token: httpx.AsyncClient, inactive_api_key):
        """Test activating an API key."""
        from app.core.api_key_crypto import decrypt_api_key_from_storage
        session_check = await admin_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")

        # Decrypt the inactive API key to get the plaintext for preview
        inactive_key_plaintext = decrypt_api_key_from_storage(
            inactive_api_key.api_key_encrypted,
            inactive_api_key.encryption_salt
        )
        preview = f"{inactive_key_plaintext[:4]}...{inactive_key_plaintext[-4:]}"

        response = await admin_client_with_token.put(
            "/api/admin/api_keys/toggle",
            json={"api_key_preview": preview, "is_active": True},
            headers={"X-CSRF-Token": csrf}
        )

        assert response.status_code == 200
        assert "activated" in response.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_toggle_api_key_invalid_format(self, admin_client_with_token: httpx.AsyncClient):
        """Test toggle with invalid preview format is rejected."""
        session_check = await admin_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")

        response = await admin_client_with_token.put(
            "/api/admin/api_keys/toggle",
            json={"api_key_preview": "invalid", "is_active": False},
            headers={"X-CSRF-Token": csrf}
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_toggle_api_key_not_found(self, admin_client_with_token: httpx.AsyncClient):
        """Test toggle with non-existent key returns 404."""
        session_check = await admin_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")

        response = await admin_client_with_token.put(
            "/api/admin/api_keys/toggle",
            json={"api_key_preview": "xxxx...yyyy", "is_active": False},
            headers={"X-CSRF-Token": csrf}
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_toggle_api_key_requires_csrf(self, admin_client_with_token: httpx.AsyncClient, active_api_key, test_api_key: str):
        """Test toggle requires CSRF token."""
        preview = f"{test_api_key[:4]}...{test_api_key[-4:]}"

        response = await admin_client_with_token.put(
            "/api/admin/api_keys/toggle",
            json={"api_key_preview": preview, "is_active": False}
        )

        assert response.status_code in [400, 403, 422]


# ============================================================================
# API KEY DELETION TESTS
# ============================================================================

class TestAPIKeyDeletion:
    """Tests for DELETE /api/admin/api_keys endpoint."""

    @pytest.mark.asyncio
    async def test_delete_api_key_success(self, admin_client_with_token: httpx.AsyncClient, active_api_key, test_api_key: str):
        """Test admin can delete an API key."""
        session_check = await admin_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")

        preview = f"{test_api_key[:4]}...{test_api_key[-4:]}"

        response = await admin_client_with_token.request(
            "DELETE",
            "/api/admin/api_keys",
            json={"api_key_preview": preview},
            headers={"X-CSRF-Token": csrf}
        )

        assert response.status_code == 200
        assert response.json()["success"] is True

    @pytest.mark.asyncio
    async def test_delete_api_key_invalid_format(self, admin_client_with_token: httpx.AsyncClient):
        """Test delete with invalid preview format is rejected."""
        session_check = await admin_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")

        response = await admin_client_with_token.request(
            "DELETE",
            "/api/admin/api_keys",
            json={"api_key_preview": "bad_format"},
            headers={"X-CSRF-Token": csrf}
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_api_key_not_found(self, admin_client_with_token: httpx.AsyncClient):
        """Test delete with non-existent key returns 404."""
        session_check = await admin_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")

        response = await admin_client_with_token.request(
            "DELETE",
            "/api/admin/api_keys",
            json={"api_key_preview": "xxxx...yyyy"},
            headers={"X-CSRF-Token": csrf}
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_api_key_basic_user_denied(self, basic_client_with_token: httpx.AsyncClient, active_api_key, test_api_key: str):
        """Test basic user cannot delete API keys."""
        session_check = await basic_client_with_token.get("/api/auth/session_check")
        csrf = session_check.json().get("csrf_token")

        preview = f"{test_api_key[:4]}...{test_api_key[-4:]}"

        response = await basic_client_with_token.request(
            "DELETE",
            "/api/admin/api_keys",
            json={"api_key_preview": preview},
            headers={"X-CSRF-Token": csrf}
        )

        assert response.status_code in [401, 403]


# ============================================================================
# USER ACTIVITY LOGS TESTS
# ============================================================================

class TestUserActivityLogs:
    """Tests for GET /api/admin/logs/user_activity endpoint."""

    @pytest.mark.asyncio
    async def test_get_user_activity_admin_success(self, admin_client_with_token: httpx.AsyncClient):
        """Test admin can retrieve user activity logs."""
        response = await admin_client_with_token.get("/api/admin/logs/user_activity")

        assert response.status_code == 200
        data = response.json()
        assert "logs" in data
        assert isinstance(data["logs"], list)

    @pytest.mark.asyncio
    async def test_user_activity_elevated_denied(self, elevated_client_with_token: httpx.AsyncClient):
        """Test elevated users cannot access user activity logs (admin only)."""
        response = await elevated_client_with_token.get("/api/admin/logs/user_activity")

        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_user_activity_basic_denied(self, basic_client_with_token: httpx.AsyncClient):
        """Test basic users cannot access user activity logs."""
        response = await basic_client_with_token.get("/api/admin/logs/user_activity")

        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_user_activity_filter_by_username(self, admin_client_with_token: httpx.AsyncClient):
        """Test filtering user activity by username."""
        response = await admin_client_with_token.get(
            "/api/admin/logs/user_activity",
            params={"username": "admin"}
        )

        assert response.status_code == 200
        data = response.json()
        # All returned logs should be for the admin user (if any)
        for log in data["logs"]:
            assert log["username"] == "admin"

    @pytest.mark.asyncio
    async def test_user_activity_filter_by_action_type(self, admin_client_with_token: httpx.AsyncClient):
        """Test filtering user activity by action type."""
        response = await admin_client_with_token.get(
            "/api/admin/logs/user_activity",
            params={"action_type": "login"}
        )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_user_activity_pagination(self, admin_client_with_token: httpx.AsyncClient):
        """Test user activity pagination."""
        # First page
        response1 = await admin_client_with_token.get(
            "/api/admin/logs/user_activity",
            params={"limit": 5, "offset": 0}
        )
        assert response1.status_code == 200

        # Second page
        response2 = await admin_client_with_token.get(
            "/api/admin/logs/user_activity",
            params={"limit": 5, "offset": 5}
        )
        assert response2.status_code == 200

    @pytest.mark.asyncio
    async def test_user_activity_date_range(self, admin_client_with_token: httpx.AsyncClient):
        """Test filtering by date range."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

        response = await admin_client_with_token.get(
            "/api/admin/logs/user_activity",
            params={"start_date": yesterday, "end_date": today}
        )

        assert response.status_code == 200


# ============================================================================
# CLIENT SUBMISSION LOGS TESTS
# ============================================================================

class TestClientSubmissionLogs:
    """Tests for GET /api/admin/logs/client_submissions endpoint."""

    @pytest.mark.asyncio
    async def test_get_client_logs_admin_success(self, admin_client_with_token: httpx.AsyncClient):
        """Test admin can retrieve client submission logs."""
        response = await admin_client_with_token.get("/api/admin/logs/client_submissions")

        assert response.status_code == 200
        data = response.json()
        assert "logs" in data

    @pytest.mark.asyncio
    async def test_get_client_logs_elevated_success(self, elevated_client_with_token: httpx.AsyncClient):
        """Test elevated users can access client submission logs."""
        response = await elevated_client_with_token.get("/api/admin/logs/client_submissions")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_client_logs_basic_denied(self, basic_client_with_token: httpx.AsyncClient):
        """Test basic users cannot access client submission logs."""
        response = await basic_client_with_token.get("/api/admin/logs/client_submissions")

        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_client_logs_pagination(self, admin_client_with_token: httpx.AsyncClient):
        """Test client logs pagination."""
        response = await admin_client_with_token.get(
            "/api/admin/logs/client_submissions",
            params={"limit": 10, "offset": 0}
        )

        assert response.status_code == 200


# ============================================================================
# ADMIN SECURITY TESTS
# ============================================================================

class TestAdminSecurity:
    """Security tests for admin endpoints."""

    @pytest.mark.asyncio
    async def test_admin_endpoints_require_auth(self, http_client: httpx.AsyncClient):
        """Test all admin endpoints require authentication."""
        endpoints = [
            ("GET", "/api/admin/api_keys"),
            ("POST", "/api/admin/api_keys"),
            ("GET", "/api/admin/api_keys/reveal/xxxx...yyyy"),
            ("PUT", "/api/admin/api_keys/toggle"),
            ("DELETE", "/api/admin/api_keys"),
            ("GET", "/api/admin/logs/user_activity"),
            ("GET", "/api/admin/logs/client_submissions"),
        ]

        for method, path in endpoints:
            if method == "GET":
                response = await http_client.get(path)
            elif method == "POST":
                response = await http_client.post(path, json={})
            elif method == "PUT":
                response = await http_client.put(path, json={})
            elif method == "DELETE":
                response = await http_client.request("DELETE", path, json={})

            assert response.status_code in [401, 403], f"{method} {path} should require auth"

    @pytest.mark.asyncio
    async def test_mutation_endpoints_require_csrf(self, admin_client_with_token: httpx.AsyncClient):
        """Test mutation endpoints require CSRF token."""
        # POST without CSRF
        response = await admin_client_with_token.post(
            "/api/admin/api_keys",
            json={"name": "no_csrf"}
        )
        assert response.status_code in [400, 403, 422]

        # PUT without CSRF
        response = await admin_client_with_token.put(
            "/api/admin/api_keys/toggle",
            json={"api_key_preview": "xxxx...yyyy", "is_active": False}
        )
        assert response.status_code in [400, 403, 422]

        # DELETE without CSRF
        response = await admin_client_with_token.request(
            "DELETE",
            "/api/admin/api_keys",
            json={"api_key_preview": "xxxx...yyyy"}
        )
        assert response.status_code in [400, 403, 422]

    @pytest.mark.asyncio
    async def test_invalid_csrf_rejected(self, admin_client_with_token: httpx.AsyncClient):
        """Test invalid CSRF tokens are rejected."""
        response = await admin_client_with_token.post(
            "/api/admin/api_keys",
            json={"name": "invalid_csrf"},
            headers={"X-CSRF-Token": "invalid_token_12345"}
        )

        assert response.status_code in [400, 403]
