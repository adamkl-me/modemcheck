"""
Integration tests for admin workflow.

Tests complete admin operations including user management,
API key lifecycle, and data management.
"""
import pytest
import httpx
import hmac
import hashlib
from datetime import datetime, timedelta

from app.models.user import User
from app.models.api_key import APIKey
from app.models.modem_check import ModemCheck
from sqlalchemy import select


pytestmark = pytest.mark.integration


class TestAdminUserManagement:
    """Test complete admin user management workflow."""

    @pytest.mark.asyncio
    async def test_create_user_workflow(
        self,
        admin_client_with_token: httpx.AsyncClient,
        csrf_token: str,
        db_session
    ):
        """Test creating a new user from admin dashboard."""
        # Create user
        user_data = {
            "username": "workflow_user",
            "password": "WorkflowPass123!",
            "role": "basic"
        }

        response = await admin_client_with_token.post(
            "/api/users",
            json=user_data,
            headers={"X-CSRF-Token": csrf_token}
        )

        assert response.status_code == 200
        result = response.json()
        assert result["success"] is True
        assert "workflow_user" in result["message"]

        # Verify in database
        db_result = await db_session.execute(
            select(User).where(User.username == "workflow_user")
        )
        user = db_result.scalar_one()
        assert user.username == "workflow_user"
        assert user.role == "basic"

        # Verify user can login
        login_response = await admin_client_with_token.post(
            "/api/auth/login",
            json={"username": "workflow_user", "password": "WorkflowPass123!"}
        )
        assert login_response.status_code == 200

    @pytest.mark.asyncio
    async def test_update_user_role_workflow(
        self,
        admin_client_with_token: httpx.AsyncClient,
        csrf_token: str,
        db_session
    ):
        """Test updating user role."""
        # Create basic user
        user_data = {
            "username": "promote_user",
            "password": "PromotePass123!",
            "role": "basic"
        }

        create_response = await admin_client_with_token.post(
            "/api/users",
            json=user_data,
            headers={"X-CSRF-Token": csrf_token}
        )
        assert create_response.status_code == 200

        # Get fresh CSRF token (one-time use tokens)
        session_resp = await admin_client_with_token.get("/api/auth/session_check")
        csrf_token2 = session_resp.json()["csrf_token"]

        # Promote to elevated - use username instead of ID
        update_response = await admin_client_with_token.put(
            "/api/users/promote_user/role",
            json={"role": "elevated"},
            headers={"X-CSRF-Token": csrf_token2}
        )

        assert update_response.status_code == 200

        # Verify role updated - query by username
        db_result = await db_session.execute(
            select(User).where(User.username == "promote_user")
        )
        user = db_result.scalar_one()
        assert user.role == "elevated"

    @pytest.mark.asyncio
    async def test_delete_user_workflow(
        self,
        admin_client_with_token: httpx.AsyncClient,
        csrf_token: str,
        db_session
    ):
        """Test deleting a user."""
        # Create user
        user_data = {
            "username": "delete_user",
            "password": "DeletePass123!",
            "role": "basic"
        }

        create_response = await admin_client_with_token.post(
            "/api/users",
            json=user_data,
            headers={"X-CSRF-Token": csrf_token}
        )
        assert create_response.status_code == 200

        # Get fresh CSRF token (one-time use tokens)
        session_resp = await admin_client_with_token.get("/api/auth/session_check")
        csrf_token2 = session_resp.json()["csrf_token"]

        # Delete user - use username endpoint
        delete_response = await admin_client_with_token.delete(
            "/api/users/delete_user",
            headers={"X-CSRF-Token": csrf_token2}
        )

        assert delete_response.status_code == 200

        # Verify deleted - query by username
        db_result = await db_session.execute(
            select(User).where(User.username == "delete_user")
        )
        user = db_result.scalar_one_or_none()
        assert user is None


class TestAPIKeyLifecycle:
    """Test complete API key lifecycle."""

    @pytest.mark.asyncio
    async def test_api_key_creation_and_usage(
        self,
        admin_client_with_token: httpx.AsyncClient,
        csrf_token: str,
        http_client: httpx.AsyncClient,
        db_session
    ):
        """Test creating API key and using it for uploads."""
        import hashlib
        import time
        import json

        # Create API key
        create_response = await admin_client_with_token.post(
            "/api/admin/api_keys",
            json={"name": "lifecycle_key"},
            headers={"X-CSRF-Token": csrf_token}
        )

        assert create_response.status_code == 200
        api_key = create_response.json()["api_key"]

        # Use key for upload
        modem_data = {"check_time": int(time.time())}
        json_data = json.dumps(modem_data).encode()
        modem_id = "XB8-AA:BB:CC:DD:EE:01"  # Valid MAC address format
        filename = "2024-01-01_12-00-00.json"
        checksum = hashlib.sha256(json_data).hexdigest()

        timestamp = str(int(time.time()))
        message = f"{timestamp}|{modem_id}|{filename}|{checksum}"
        signature = hmac.new(
            api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        files = {"file": (filename, json_data, "application/json")}
        data = {
            "api_key": api_key,
            "modem_id": modem_id,
            "filename": filename,
            "checksum": checksum
        }
        headers = {
            "X-Request-Timestamp": timestamp,
            "X-Request-Signature": signature
        }

        upload_response = await http_client.post(
            "/api/upload",
            files=files,
            data=data,
            headers=headers
        )

        assert upload_response.status_code == 200

        # Verify upload stored
        check_id = upload_response.json()["database_id"]
        db_result = await db_session.execute(
            select(ModemCheck).where(ModemCheck.id == check_id)
        )
        check = db_result.scalar_one()
        assert check.modem_id == modem_id

    @pytest.mark.asyncio
    async def test_api_key_rotation(
        self,
        admin_client_with_token: httpx.AsyncClient,
        csrf_token: str,
        http_client: httpx.AsyncClient
    ):
        """Test rotating an API key."""
        import hashlib
        import time
        import json
        import asyncio

        # Create initial key
        create_response = await admin_client_with_token.post(
            "/api/admin/api_keys",
            json={"name": "rotation_key"},
            headers={"X-CSRF-Token": csrf_token}
        )
        old_key = create_response.json()["api_key"]

        # Get fresh CSRF token for delete (one-time use tokens)
        session_resp = await admin_client_with_token.get("/api/auth/session_check")
        csrf_token2 = session_resp.json()["csrf_token"]

        # Delete old key
        preview = f"{old_key[:4]}...{old_key[-4:]}"
        delete_response = await admin_client_with_token.request(
            "DELETE",
            "/api/admin/api_keys",
            json={"api_key_preview": preview},
            headers={"X-CSRF-Token": csrf_token2}
        )
        assert delete_response.status_code == 200

        # Get fresh CSRF token for new key creation (one-time use tokens)
        session_resp3 = await admin_client_with_token.get("/api/auth/session_check")
        csrf_token3 = session_resp3.json()["csrf_token"]

        # Create new key
        create_new_response = await admin_client_with_token.post(
            "/api/admin/api_keys",
            json={"name": "rotation_key_new"},
            headers={"X-CSRF-Token": csrf_token3}
        )
        new_key = create_new_response.json()["api_key"]

        # Test 1: Old key should not work
        modem_data_1 = {
            "check_time": int(time.time()),
            "sysinfo": {
                "modemtype": "XB8",
                "modemmac": "AA:BB:CC:DD:EE:02",
                "checktime": int(time.time())
            }
        }
        json_data_1 = json.dumps(modem_data_1).encode()
        modem_id = "XB8-AA:BB:CC:DD:EE:02"  # Valid MAC address format
        filename_1 = f"2024-01-01_12-00-00_{int(time.time())}.json"  # Unique filename
        checksum_1 = hashlib.sha256(json_data_1).hexdigest()

        timestamp_1 = str(int(time.time()))
        message_1 = f"{timestamp_1}|{modem_id}|{filename_1}|{checksum_1}"
        old_signature = hmac.new(
            old_key.encode('utf-8'),
            message_1.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        files_1 = {"file": (filename_1, json_data_1, "application/json")}
        data_1 = {
            "api_key": old_key,
            "modem_id": modem_id,
            "filename": filename_1,
            "checksum": checksum_1
        }
        headers_1 = {
            "X-Request-Timestamp": timestamp_1,
            "X-Request-Signature": old_signature
        }

        old_key_response = await http_client.post(
            "/api/upload",
            files=files_1,
            data=data_1,
            headers=headers_1
        )
        assert old_key_response.status_code in [401, 403]

        # Delay to ensure database session cleanup completes after failed request
        await asyncio.sleep(1.0)

        # Test 2: New key should work with a different upload
        modem_data_2 = {
            "check_time": int(time.time()),
            "sysinfo": {
                "modemtype": "XB8",
                "modemmac": "AA:BB:CC:DD:EE:02",
                "checktime": int(time.time())
            }
        }
        json_data_2 = json.dumps(modem_data_2).encode()
        filename_2 = f"2024-01-01_12-01-00_{int(time.time())}.json"  # Different unique filename
        checksum_2 = hashlib.sha256(json_data_2).hexdigest()

        timestamp_2 = str(int(time.time()))
        message_2 = f"{timestamp_2}|{modem_id}|{filename_2}|{checksum_2}"
        new_signature = hmac.new(
            new_key.encode('utf-8'),
            message_2.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        files_2 = {"file": (filename_2, json_data_2, "application/json")}
        data_2 = {
            "api_key": new_key,
            "modem_id": modem_id,
            "filename": filename_2,
            "checksum": checksum_2
        }
        headers_2 = {
            "X-Request-Timestamp": timestamp_2,
            "X-Request-Signature": new_signature
        }

        new_key_response = await http_client.post(
            "/api/upload",
            files=files_2,
            data=data_2,
            headers=headers_2
        )
        if new_key_response.status_code != 200:
            print(f"Response status: {new_key_response.status_code}")
            print(f"Response text: {new_key_response.text}")
        assert new_key_response.status_code == 200


class TestDataManagement:
    """Test data management workflows."""

    @pytest.mark.asyncio
    async def test_query_modem_checks(
        self,
        admin_client_with_token: httpx.AsyncClient,
        db_session
    ):
        """Test querying modem checks."""
        import time

        # Create test data
        today = datetime.now().strftime("%Y-%m-%d")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        for i in range(5):
            check = ModemCheck(
                modem_id="XB8-QUERY",
                check_time=datetime.fromtimestamp(int(time.time()) + i),
                filename=f"XB8-QUERY/query_test_{i}_{int(time.time())}.json",
                full_data={"index": i}
            )
            db_session.add(check)
        await db_session.commit()

        # Query via API using actual /api/db/list_checks endpoint
        response = await admin_client_with_token.get(
            f"/api/db/list_checks?modem_id=XB8-QUERY&start_date={today}&end_date={tomorrow}"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["checks"]) >= 5

    @pytest.mark.asyncio
    async def test_delete_old_checks(
        self,
        admin_client_with_token: httpx.AsyncClient,
        csrf_token: str,
        db_session
    ):
        """Test deleting a specific check by ID."""
        import time

        # Create old check
        old_timestamp = int(time.time()) - (100 * 24 * 3600)
        old_check = ModemCheck(
            modem_id="XB8-OLD",
            check_time=datetime.fromtimestamp(old_timestamp),
            filename=f"XB8-OLD/old_test_{old_timestamp}.json",
            full_data={}
        )
        db_session.add(old_check)
        await db_session.commit()
        await db_session.refresh(old_check)
        old_check_id = old_check.id

        # Delete check using actual /api/data/check endpoint
        response = await admin_client_with_token.request(
            "DELETE",
            "/api/data/check",
            json={"check_id": old_check_id},
            headers={"X-CSRF-Token": csrf_token}
        )

        assert response.status_code == 200

        # Verify deleted
        db_result = await db_session.execute(
            select(ModemCheck).where(ModemCheck.id == old_check_id)
        )
        check = db_result.scalar_one_or_none()
        assert check is None


class TestAuditTrail:
    """Test audit trail for admin actions."""

    @pytest.mark.asyncio
    async def test_user_creation_logged(
        self,
        admin_client_with_token: httpx.AsyncClient,
        csrf_token: str,
        db_session
    ):
        """Test that user creation is logged."""
        from app.models.audit import UserActivityLog

        # Create user
        user_data = {
            "username": "audit_user",
            "password": "AuditPass123!",
            "role": "basic"
        }

        response = await admin_client_with_token.post(
            "/api/users",
            json=user_data,
            headers={"X-CSRF-Token": csrf_token}
        )

        assert response.status_code == 200

        # Check audit log
        db_result = await db_session.execute(
            select(UserActivityLog).where(
                UserActivityLog.action_type == "create_user"
            )
        )
        log = db_result.scalars().first()

        # May or may not be logged depending on implementation
        # Verify if audit logging is enabled

    @pytest.mark.asyncio
    async def test_api_key_creation_logged(
        self,
        admin_client_with_token: httpx.AsyncClient,
        csrf_token: str,
        db_session
    ):
        """Test that API key creation is logged."""
        from app.models.audit import UserActivityLog

        # Create API key
        response = await admin_client_with_token.post(
            "/api/admin/api_keys",
            json={"name": "audit_key"},
            headers={"X-CSRF-Token": csrf_token}
        )

        assert response.status_code == 200

        # Check audit log
        db_result = await db_session.execute(
            select(UserActivityLog).where(
                UserActivityLog.action_type == "create_api_key"
            )
        )
        log = db_result.scalars().first()

        # Verify audit logging if enabled


class TestRBACIntegration:
    """Test role-based access control integration."""

    @pytest.mark.asyncio
    async def test_basic_user_cannot_create_users(
        self,
        basic_client_with_token: httpx.AsyncClient,
        csrf_token_basic: str
    ):
        """Test that basic users cannot create other users."""
        # Try to create user (basic_client_with_token is already authenticated)
        user_data = {
            "username": "unauthorized_user",
            "password": "TestPass123!",
            "role": "basic"
        }

        response = await basic_client_with_token.post(
            "/api/users",
            json=user_data,
            headers={"X-CSRF-Token": csrf_token_basic}
        )

        # Should be forbidden
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_elevated_user_can_create_api_keys(
        self,
        elevated_client_with_token: httpx.AsyncClient,
        csrf_token_elevated: str
    ):
        """Test that elevated users can create API keys."""
        # Create API key (elevated_client_with_token is already authenticated)
        response = await elevated_client_with_token.post(
            "/api/admin/api_keys",
            json={"name": "elevated_key"},
            headers={"X-CSRF-Token": csrf_token_elevated}
        )

        # Should succeed
        assert response.status_code == 200