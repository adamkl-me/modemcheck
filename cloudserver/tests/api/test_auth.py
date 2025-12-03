"""
API tests for authentication endpoints (/api/auth).

Tests:
- Login (valid/invalid credentials, account lockout)
- Logout
- Session check
- Password changes
- CSRF token generation
"""
import pytest
import httpx
from typing import Dict

pytestmark = pytest.mark.api


class TestLogin:
    """Tests for POST /api/auth/login"""
    
    @pytest.mark.asyncio
    async def test_login_success(self, http_client: httpx.AsyncClient, admin_user, admin_user_credentials: Dict[str, str]):
        """Test successful login with valid credentials."""
        response = await http_client.post("/api/auth/login", json=admin_user_credentials)
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["username"] == admin_user_credentials["username"]
        assert data["role"] == "admin"
        assert "modemcheck_session" in response.cookies
    
    @pytest.mark.asyncio
    async def test_login_invalid_username(self, http_client: httpx.AsyncClient):
        """Test login with non-existent username."""
        response = await http_client.post("/api/auth/login", json={
            "username": "nonexistent_user",
            "password": "SomePassword123!"
        })

        assert response.status_code == 401
        data = response.json()
        assert data["success"] is False
        assert data["error"]["code"] == "AUTHENTICATION_ERROR"
        assert "Invalid username or password" in data["error"]["message"]
        assert "error_id" in data["error"]  # Correlation ID present
    
    @pytest.mark.asyncio
    async def test_login_invalid_password(self, http_client: httpx.AsyncClient, admin_user, admin_user_credentials: Dict[str, str]):
        """Test login with incorrect password."""
        response = await http_client.post("/api/auth/login", json={
            "username": admin_user_credentials["username"],
            "password": "WrongPassword123!"
        })

        assert response.status_code == 401
        data = response.json()
        assert data["success"] is False
        assert data["error"]["code"] == "AUTHENTICATION_ERROR"
        assert "Invalid username or password" in data["error"]["message"]
        assert "error_id" in data["error"]
    
    @pytest.mark.asyncio
    @pytest.mark.requires_production_settings
    async def test_login_account_lockout(self, http_client: httpx.AsyncClient, admin_user, admin_user_credentials: Dict[str, str]):
        """Test account lockout after 5 failed login attempts.

        NOTE: Account lockout is intentionally disabled in test mode (see app/routers/auth.py:69)
        to avoid interfering with other tests during fixture setup. Run with
        ./scripts/run_security_tests.sh to test with production settings (TESTING=false).
        """
        from app.core.security import clear_failed_logins

        # Clear any existing failed login records for this user
        await clear_failed_logins(admin_user_credentials["username"])

        # Make 5 failed login attempts
        for i in range(5):
            response = await http_client.post("/api/auth/login", json={
                "username": admin_user_credentials["username"],
                "password": "WrongPassword123!"
            })
            assert response.status_code == 401

        # 6th attempt should be locked
        response = await http_client.post("/api/auth/login", json={
            "username": admin_user_credentials["username"],
            "password": "WrongPassword123!"
        })

        assert response.status_code == 429
        data = response.json()
        assert data["success"] is False
        assert data["error"]["code"] == "ACCOUNT_LOCKED"
        assert "locked" in data["error"]["message"].lower()
        assert "remaining_seconds" in data["error"]["details"]
        assert "retry_after_seconds" in data["error"]["details"]

        # Cleanup: Clear failed logins after test
        await clear_failed_logins(admin_user_credentials["username"])
    
    @pytest.mark.asyncio
    async def test_login_missing_fields(self, http_client: httpx.AsyncClient):
        """Test login with missing required fields."""
        # Missing password
        response = await http_client.post("/api/auth/login", json={"username": "test"})
        assert response.status_code == 422
        
        # Missing username
        response = await http_client.post("/api/auth/login", json={"password": "test"})
        assert response.status_code == 422
        
        # Empty body
        response = await http_client.post("/api/auth/login", json={})
        assert response.status_code == 422


class TestLogout:
    """Tests for POST /api/auth/logout"""
    
    @pytest.mark.asyncio
    async def test_logout_success(self, admin_client_with_token: httpx.AsyncClient):
        """Test successful logout."""
        response = await admin_client_with_token.post("/api/auth/logout")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Logout successful"
    
    @pytest.mark.asyncio
    async def test_logout_without_session(self, http_client: httpx.AsyncClient):
        """Test logout without valid session."""
        response = await http_client.post("/api/auth/logout")
        
        # Should fail with 401 (unauthenticated)
        assert response.status_code == 401


class TestSessionCheck:
    """Tests for GET /api/auth/session_check"""
    
    @pytest.mark.asyncio
    async def test_session_check_authenticated(self, admin_client_with_token: httpx.AsyncClient, admin_user):
        """Test session check with valid session."""
        response = await admin_client_with_token.get("/api/auth/session_check")
        
        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is True
        assert data["username"] == admin_user.username
        assert data["role"] == "admin"
        assert "csrf_token" in data
        assert len(data["csrf_token"]) > 0
    
    @pytest.mark.asyncio
    async def test_session_check_unauthenticated(self, http_client: httpx.AsyncClient):
        """Test session check without session."""
        response = await http_client.get("/api/auth/session_check")
        
        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is False
        assert "username" not in data
        assert "csrf_token" not in data


class TestChangePassword:
    """Tests for POST /api/auth/change_password"""
    
    @pytest.mark.asyncio
    async def test_change_password_success(self, admin_client_with_token: httpx.AsyncClient, admin_user_credentials: Dict[str, str], csrf_token: str):
        """Test successful password change."""
        response = await admin_client_with_token.post("/api/auth/change_password", json={
            "current_password": admin_user_credentials["password"],
            "new_password": "NewPassword123!"
        }, headers={"X-CSRF-Token": csrf_token})

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "Password changed successfully" in data["message"]
    
    @pytest.mark.asyncio
    async def test_change_password_wrong_current(self, admin_client_with_token: httpx.AsyncClient, csrf_token: str):
        """Test password change with incorrect current password."""
        response = await admin_client_with_token.post("/api/auth/change_password", json={
            "current_password": "WrongPassword123!",
            "new_password": "NewPassword123!"
        }, headers={"X-CSRF-Token": csrf_token})

        assert response.status_code == 401
        data = response.json()
        assert data.get("success") is False
        assert "Current password is incorrect" in data["error"]["message"]
    
    @pytest.mark.asyncio
    async def test_change_password_weak_new_password(self, admin_client_with_token: httpx.AsyncClient, admin_user_credentials: Dict[str, str], csrf_token: str):
        """Test password change with weak new password."""
        response = await admin_client_with_token.post("/api/auth/change_password", json={
            "current_password": admin_user_credentials["password"],
            "new_password": "weak"
        }, headers={"X-CSRF-Token": csrf_token})

        # Pydantic validation returns 422 (Unprocessable Entity) for validation errors
        assert response.status_code == 422
        data = response.json()
        # Check for password validation error in the detail field
        assert "password" in str(data).lower()
    
    @pytest.mark.asyncio
    async def test_change_password_unauthenticated(self, http_client: httpx.AsyncClient):
        """Test password change without authentication."""
        response = await http_client.post("/api/auth/change_password", json={
            "current_password": "SomePassword123!",
            "new_password": "NewPassword123!"
        })
        
        assert response.status_code == 401


class TestChangeOwnPassword:
    """Tests for POST /api/auth/change_own_password"""
    
    @pytest.mark.asyncio
    async def test_change_own_password_success(self, admin_client_with_token: httpx.AsyncClient, csrf_token: str):
        """Test successful password change without current password (forced change)."""
        response = await admin_client_with_token.post("/api/auth/change_own_password", json={
            "new_password": "NewPassword123!"
        }, headers={"X-CSRF-Token": csrf_token})

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "Password changed successfully" in data["message"]
    
    @pytest.mark.asyncio
    async def test_change_own_password_weak(self, admin_client_with_token: httpx.AsyncClient, csrf_token: str):
        """Test forced password change with weak password."""
        response = await admin_client_with_token.post("/api/auth/change_own_password", json={
            "new_password": "weak"
        }, headers={"X-CSRF-Token": csrf_token})

        assert response.status_code == 400
        data = response.json()
        assert data.get("success") is False
        assert "password" in data["error"]["message"].lower()
    
    @pytest.mark.asyncio
    async def test_change_own_password_unauthenticated(self, http_client: httpx.AsyncClient):
        """Test forced password change without authentication."""
        response = await http_client.post("/api/auth/change_own_password", json={
            "new_password": "NewPassword123!"
        })

        assert response.status_code == 401


class TestPasswordChangeRequiredFlow:
    """Tests for the password change required workflow.

    These tests verify that:
    1. Users with must_change_password=True are blocked from other endpoints
    2. After changing password, they can access endpoints normally
    """

    @pytest.mark.asyncio
    async def test_must_change_password_blocks_api_access(
        self, http_client: httpx.AsyncClient, db_session, test_user_must_change_password
    ):
        """User with must_change_password=True should get 403 on protected endpoints."""
        # Login first
        login_response = await http_client.post("/api/auth/login", json={
            "username": test_user_must_change_password.username,
            "password": "TempPassword123!"  # The fixture password
        })
        assert login_response.status_code == 200
        login_data = login_response.json()
        assert login_data.get("must_change_password") is True

        # Try to access a protected endpoint (e.g., modem list)
        response = await http_client.get("/api/db/list_modems")
        assert response.status_code == 403
        data = response.json()
        assert data.get("success") is False
        assert "password" in data["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_password_change_clears_requirement(
        self, http_client: httpx.AsyncClient, db_session, test_user_must_change_password
    ):
        """After changing password, user should be able to access endpoints."""
        # Login first
        login_response = await http_client.post("/api/auth/login", json={
            "username": test_user_must_change_password.username,
            "password": "TempPassword123!"
        })
        assert login_response.status_code == 200
        assert login_response.json().get("must_change_password") is True

        # Change password using change_own_password endpoint
        change_response = await http_client.post("/api/auth/change_own_password", json={
            "new_password": "NewSecurePassword123!"
        })
        assert change_response.status_code == 200
        assert change_response.json().get("success") is True

        # Now try to access the protected endpoint again
        response = await http_client.get("/api/db/list_modems")
        # Should succeed (200 with empty list, but NOT 403)
        assert response.status_code == 200


class TestCSRFTokenResponseHeader:
    """Tests for X-New-CSRF-Token response header functionality."""

    @pytest.mark.asyncio
    async def test_csrf_token_returned_in_response_header(
        self, admin_client_with_token: httpx.AsyncClient
    ):
        """After a successful CSRF-protected request, a new token should be in the response header."""
        # Get initial CSRF token
        session_check = await admin_client_with_token.get("/api/auth/session_check")
        csrf_token = session_check.json().get("csrf_token")
        assert csrf_token is not None

        # Make a CSRF-protected request (e.g., create API key)
        response = await admin_client_with_token.post(
            "/api/admin/api_keys",
            json={"name": "test-key-csrf-header"},
            headers={"X-CSRF-Token": csrf_token}
        )
        assert response.status_code == 200

        # The response should contain a new CSRF token in the header
        new_csrf_token = response.headers.get("X-New-CSRF-Token")
        assert new_csrf_token is not None
        assert new_csrf_token != csrf_token  # Should be a different token

    @pytest.mark.asyncio
    async def test_new_csrf_token_is_valid(
        self, admin_client_with_token: httpx.AsyncClient
    ):
        """The new CSRF token from response header should be valid for next request."""
        # Get initial CSRF token
        session_check = await admin_client_with_token.get("/api/auth/session_check")
        csrf_token = session_check.json().get("csrf_token")

        # Make first request
        response1 = await admin_client_with_token.post(
            "/api/admin/api_keys",
            json={"name": "test-key-1"},
            headers={"X-CSRF-Token": csrf_token}
        )
        assert response1.status_code == 200

        # Get new token from response header
        new_csrf_token = response1.headers.get("X-New-CSRF-Token")
        assert new_csrf_token is not None

        # Use new token for second request (should succeed)
        response2 = await admin_client_with_token.post(
            "/api/admin/api_keys",
            json={"name": "test-key-2"},
            headers={"X-CSRF-Token": new_csrf_token}
        )
        assert response2.status_code == 200

    @pytest.mark.asyncio
    async def test_original_csrf_token_invalid_after_use(
        self, admin_client_with_token: httpx.AsyncClient
    ):
        """Original CSRF token should be invalid after being used."""
        # Get initial CSRF token
        session_check = await admin_client_with_token.get("/api/auth/session_check")
        csrf_token = session_check.json().get("csrf_token")

        # Use the token
        response1 = await admin_client_with_token.post(
            "/api/admin/api_keys",
            json={"name": "test-key-reuse"},
            headers={"X-CSRF-Token": csrf_token}
        )
        assert response1.status_code == 200

        # Try to reuse the same token (should fail)
        response2 = await admin_client_with_token.post(
            "/api/admin/api_keys",
            json={"name": "test-key-reuse-2"},
            headers={"X-CSRF-Token": csrf_token}
        )
        assert response2.status_code == 403
        assert "CSRF" in response2.json().get("detail", "")

    @pytest.mark.asyncio
    async def test_csrf_token_chain(
        self, admin_client_with_token: httpx.AsyncClient
    ):
        """Should be able to chain multiple requests using tokens from response headers."""
        # Get initial CSRF token
        session_check = await admin_client_with_token.get("/api/auth/session_check")
        current_token = session_check.json().get("csrf_token")

        # Chain multiple requests, each using the token from the previous response
        for i in range(5):
            response = await admin_client_with_token.post(
                "/api/admin/api_keys",
                json={"name": f"test-key-chain-{i}"},
                headers={"X-CSRF-Token": current_token}
            )
            assert response.status_code == 200, f"Request {i} failed"

            # Get next token from response header
            new_token = response.headers.get("X-New-CSRF-Token")
            assert new_token is not None, f"No new token in response {i}"
            assert new_token != current_token, f"Token not rotated in response {i}"
            current_token = new_token
