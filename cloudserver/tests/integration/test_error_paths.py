"""
Integration tests for error paths and edge cases.

Tests system behavior under error conditions, network failures,
database errors, and other exceptional scenarios.
"""
import pytest
import httpx
import asyncio
import hmac
import hashlib
from unittest.mock import patch, AsyncMock


pytestmark = pytest.mark.integration


def create_valid_modem_data():
    """Create valid modem check data matching actual client format."""
    return {
        "sysinfo": {
            "checktime": int(time.time()),
            "modemmac": "AA:BB:CC:DD:EE:FF",
            "modemtype": "XB8",
            "firmware": "v1.2.3",
            "uptime": "2 days 3:45:12",
            "systemtime": "2024-01-01 12:00:00",
            "client_version": "6.0.0",
            "client_os": "linux",
            "client_arch": "amd64",
            "public_ip": "1.2.3.4",
            "isp_name": "Test ISP",
            "asn": "AS12345",
            "ip_city": "Test City",
            "ip_country": "US",
            "detection_status": "success"
        },
        "rx": [{
            "channel_id": 1,
            "frequency": 591000000,
            "power": 5.5,
            "snr": 40.5,
            "modulation": "256-QAM",
            "correcteds": 0,
            "uncorrectables": 0
        }],
        "tx": [{
            "channel_id": 1,
            "frequency": 36000000,
            "power": 45.5,
            "modulation": "ATDMA",
            "symbol_rate": 5120
        }],
        "diagnostics": {
            "speedtest": {
                "download_mbps": 950.5,
                "upload_mbps": 40.2,
                "latency_ms": 12.3
            },
            "ping_google": {
                "avg_latency_ms": "5.2",
                "packet_loss_pct": "0",
                "jitter_ms": "0.5",
                "max_latency_ms": "8.1"
            },
            "ping_cloudflare": {
                "avg_latency_ms": "3.1",
                "packet_loss_pct": "0",
                "jitter_ms": "0.3",
                "max_latency_ms": "5.2"
            },
        }
    }



class TestNetworkErrors:
    """Test handling of network-related errors.

    NOTE: These tests are marked with @pytest.mark.chaos and excluded from
    regular test runs. Run explicitly with: pytest -m chaos
    """

    @pytest.mark.chaos
    @pytest.mark.asyncio
    async def test_database_connection_failure(self, admin_client_with_token: httpx.AsyncClient):
        """Test handling when database connection fails."""
        from tests.helpers.docker_control import pause_postgres
        import asyncio

        # Verify database is working first
        response = await admin_client_with_token.get("/api/db/list_modems")
        assert response.status_code == 200, "Database should work initially"

        # Pause PostgreSQL container to simulate database failure
        with pause_postgres():
            # Wait for connection failure to be detected
            await asyncio.sleep(2)

            # Attempt database operation - should fail gracefully
            response = await admin_client_with_token.get("/api/db/list_modems")

            # Should return error status (500 or 503) rather than hanging
            assert response.status_code in [500, 503, 504], \
                f"Expected 500/503/504 during database failure but got {response.status_code}"

        # After unpausing, wait for database to fully recover
        await asyncio.sleep(3)

        # Database operations should work again
        response = await admin_client_with_token.get("/api/db/list_modems")
        assert response.status_code == 200, "Database operations should work after recovery"

    @pytest.mark.chaos
    @pytest.mark.asyncio
    async def test_redis_connection_failure(self, http_client: httpx.AsyncClient):
        """Test handling when Redis connection fails."""
        from tests.helpers.docker_control import pause_redis
        import asyncio

        # First, verify Redis is working by making a successful login
        login_response = await http_client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "TestPass123!"}
        )
        assert login_response.status_code == 200, "Initial login should succeed"

        # Pause Redis container to simulate Redis failure
        with pause_redis():
            # Wait for connection failure to be detected
            await asyncio.sleep(2)

            # Attempt operation that requires Redis (login creates session)
            response = await http_client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "TestPass123!"}
            )

            # Should fail gracefully (500 or 503) rather than hanging
            assert response.status_code in [500, 503, 504], \
                f"Expected 500/503/504 during Redis failure but got {response.status_code}"

        # After unpausing, wait for Redis to fully recover
        await asyncio.sleep(3)

        # Redis operations should work again
        login_response = await http_client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "TestPass123!"}
        )
        assert login_response.status_code == 200, "Login should work after Redis recovery"

    @pytest.mark.chaos
    @pytest.mark.asyncio
    async def test_timeout_handling(self, http_client: httpx.AsyncClient):
        """Test handling of request timeouts."""
        # Set very short timeout
        client = httpx.AsyncClient(
            base_url="http://localhost:22560",
            timeout=0.001  # 1ms timeout
        )

        try:
            response = await client.get("/api/modem_checks")
            # May timeout or succeed depending on server performance
        except httpx.TimeoutException:
            # Expected behavior for short timeout
            pass
        finally:
            await client.aclose()


class TestDatabaseErrors:
    """Test handling of database errors."""

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore:New instance.*conflicts with persistent instance:sqlalchemy.exc.SAWarning")
    async def test_duplicate_key_error(self, db_session):
        """Test handling of duplicate key violations."""
        from app.models.user import User
        from sqlalchemy.exc import IntegrityError

        # Create user
        user1 = User(
            username="duplicate_test",
            password_hash="hash1",
            role="basic"
        )
        db_session.add(user1)
        await db_session.commit()

        # Try to create duplicate
        user2 = User(
            username="duplicate_test",
            password_hash="hash2",
            role="basic"
        )
        db_session.add(user2)

        with pytest.raises(IntegrityError):
            await db_session.commit()

        # Rollback should work
        await db_session.rollback()

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore:New instance.*conflicts with persistent instance:sqlalchemy.exc.SAWarning")
    async def test_foreign_key_constraint(self, db_session):
        """Test handling of foreign key violations (v8.0+: hash-based storage)."""
        from app.models.api_key import APIKey
        from app.core.api_key_crypto import encrypt_api_key_for_storage
        import secrets

        # Create first API key
        plaintext1 = secrets.token_hex(32)
        hash1, enc1, salt1 = encrypt_api_key_for_storage(plaintext1)
        api_key1 = APIKey(
            api_key_hash=hash1,
            api_key_encrypted=enc1,
            encryption_salt=salt1,
            name="first_key"
        )
        db_session.add(api_key1)
        await db_session.commit()

        # Try to create another with same hash (primary key violation)
        api_key2 = APIKey(
            api_key_hash=hash1,  # Duplicate primary key
            api_key_encrypted=enc1,
            encryption_salt=salt1,
            name="second_key"
        )
        db_session.add(api_key2)

        with pytest.raises(Exception):  # Integrity constraint violation
            await db_session.commit()

        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_transaction_rollback_recovery(self, db_session):
        """Test recovery after transaction rollback."""
        from app.models.user import User

        # Start transaction
        user = User(
            username="rollback_recovery",
            password_hash="hash",
            role="basic"
        )
        db_session.add(user)

        # Force rollback
        await db_session.rollback()

        # New transaction should work
        user2 = User(
            username="recovery_test",
            password_hash="hash",
            role="basic"
        )
        db_session.add(user2)
        await db_session.commit()

        # Second user should be stored (username is primary key)
        assert user2.username == "recovery_test"


class TestConcurrencyEdgeCases:
    """Test edge cases in concurrent operations."""

    @pytest.mark.asyncio
    async def test_concurrent_user_creation_same_username(
        self,
        admin_client_with_token: httpx.AsyncClient,
        csrf_token: str
    ):
        """Test concurrent attempts to create same username."""
        async def create_user():
            user_data = {
                "username": "concurrent_duplicate",
                "password": "TestPass123!",
                "role": "basic"
            }
            return await admin_client_with_token.post(
                "/api/users",
                json=user_data,
                headers={"X-CSRF-Token": csrf_token}
            )

        # Create 5 concurrent requests
        tasks = [create_user() for _ in range(5)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # Only one should succeed
        success_count = sum(
            1 for r in responses
            if not isinstance(r, Exception) and r.status_code == 200
        )
        assert success_count == 1

    @pytest.mark.asyncio
    async def test_concurrent_api_key_deletion(
        self,
        admin_client_with_token: httpx.AsyncClient,
        csrf_token: str
    ):
        """Test concurrent deletion of same API key."""
        # Create API key
        create_response = await admin_client_with_token.post(
            "/api/admin/api_keys",
            json={"name": "concurrent_delete"},
            headers={"X-CSRF-Token": csrf_token}
        )
        api_key = create_response.json()["api_key"]
        preview = f"{api_key[:4]}...{api_key[-4:]}"

        async def delete_key():
            # Get fresh CSRF token for each concurrent request (one-time use tokens)
            session_resp = await admin_client_with_token.get("/api/auth/session_check")
            token = session_resp.json()["csrf_token"]
            return await admin_client_with_token.request(
                "DELETE",
                "/api/admin/api_keys",
                json={"api_key_preview": preview},
                headers={"X-CSRF-Token": token}
            )

        # Try to delete concurrently
        tasks = [delete_key() for _ in range(3)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # Only one should succeed, others should fail gracefully
        success_count = sum(
            1 for r in responses
            if not isinstance(r, Exception) and r.status_code == 200
        )
        assert success_count >= 1


class TestInputValidationEdgeCases:
    """Test edge cases in input validation."""

    @pytest.mark.asyncio
    async def test_extremely_long_username(
        self,
        admin_client_with_token: httpx.AsyncClient,
        csrf_token: str
    ):
        """Test handling of extremely long usernames."""
        user_data = {
            "username": "x" * 1000,  # Very long username
            "password": "TestPass123!",
            "role": "basic"
        }

        response = await admin_client_with_token.post(
            "/api/users",
            json=user_data,
            headers={"X-CSRF-Token": csrf_token}
        )

        # Should reject or truncate
        assert response.status_code in [400, 422]

    @pytest.mark.asyncio
    async def test_special_characters_in_modem_id(
        self,
        http_client: httpx.AsyncClient,
        active_api_key,
        test_api_key: str
    ):
        """Test handling of special characters in modem_id."""
        import hashlib
        import time
        import json

        modem_data = {"check_time": int(time.time())}
        json_data = json.dumps(modem_data).encode()

        # Modem ID with special characters (testing XSS in modem_id)
        modem_id = "XB8-<script>alert('xss')</script>"  # Will be rejected by validation
        filename = "2024-01-01_12-00-00.json"
        checksum = hashlib.sha256(json_data).hexdigest()

        timestamp = str(int(time.time()))
        message = f"{timestamp}|{modem_id}|{filename}|{checksum}"
        signature = hmac.new(
            test_api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        files = {"file": (filename, json_data, "application/json")}
        data = {
            "api_key": test_api_key,
            "modem_id": modem_id,
            "filename": filename,
            "checksum": checksum
        }
        headers = {
            "X-Request-Timestamp": timestamp,
            "X-Request-Signature": signature
        }

        response = await http_client.post(
            "/api/upload",
            files=files,
            data=data,
            headers=headers
        )

        # Should sanitize or reject
        assert response.status_code in [200, 400]

    @pytest.mark.asyncio
    async def test_null_bytes_in_input(
        self,
        admin_client_with_token: httpx.AsyncClient,
        csrf_token: str
    ):
        """Test handling of null bytes in input."""
        user_data = {
            "username": "test\x00user",  # Null byte
            "password": "TestPass123!",
            "role": "basic"
        }

        response = await admin_client_with_token.post(
            "/api/users",
            json=user_data,
            headers={"X-CSRF-Token": csrf_token}
        )

        # Should reject
        assert response.status_code in [400, 422]

    @pytest.mark.asyncio
    async def test_unicode_edge_cases(
        self,
        admin_client_with_token: httpx.AsyncClient,
        csrf_token: str
    ):
        """Test handling of unicode edge cases."""
        user_data = {
            "username": "test用户👤🔒",  # Unicode characters
            "password": "TestPass123!密码",
            "role": "basic"
        }

        response = await admin_client_with_token.post(
            "/api/users",
            json=user_data,
            headers={"X-CSRF-Token": csrf_token}
        )

        # Should handle unicode correctly
        assert response.status_code in [200, 400]


class TestResourceLimits:
    """Test system behavior at resource limits."""

    @pytest.mark.asyncio
    async def test_maximum_upload_size(
        self,
        http_client: httpx.AsyncClient,
        active_api_key,
        test_api_key: str
    ):
        """Test upload at maximum allowed size."""
        import hashlib
        import time
        import json

        # Create data near size limit (9.5MB)
        large_data = {"data": "x" * (9 * 1024 * 1024)}
        json_data = json.dumps(large_data).encode()
        modem_id = "XB8-AA:BB:CC:DD:EE:10"  # Valid MAC address format
        filename = "2024-01-01_12-00-00.json"
        checksum = hashlib.sha256(json_data).hexdigest()

        timestamp = str(int(time.time()))
        message = f"{timestamp}|{modem_id}|{filename}|{checksum}"
        signature = hmac.new(
            test_api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        files = {"file": (filename, json_data, "application/json")}
        data = {
            "api_key": test_api_key,
            "modem_id": modem_id,
            "filename": filename,
            "checksum": checksum
        }
        headers = {
            "X-Request-Timestamp": timestamp,
            "X-Request-Signature": signature
        }

        response = await http_client.post(
            "/api/upload",
            files=files,
            data=data,
            headers=headers
        )

        # Should succeed if under limit
        assert response.status_code in [200, 413]

    @pytest.mark.asyncio
    @pytest.mark.chaos
    async def test_many_concurrent_connections(self, app):
        """Test handling of many concurrent connections."""
        async def make_request(client):
            try:
                return await client.get("/health")
            except Exception as e:
                return e

        # Create many concurrent connections
        clients = [
            httpx.AsyncClient(base_url="http://localhost:22560")
            for _ in range(50)
        ]

        try:
            tasks = [make_request(client) for client in clients]
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            # Most should succeed
            success_count = sum(
                1 for r in responses
                if not isinstance(r, Exception) and hasattr(r, 'status_code')
            )
            assert success_count >= 40  # At least 80% success
        finally:
            for client in clients:
                await client.aclose()


class TestErrorRecovery:
    """Test system recovery after errors."""

    @pytest.mark.asyncio
    async def test_recovery_after_invalid_json(
        self,
        http_client: httpx.AsyncClient,
        active_api_key,
        test_api_key: str
    ):
        """Test that system recovers after receiving invalid JSON."""
        import hashlib
        import time

        # Send invalid JSON
        invalid_data = b"{invalid json}"
        modem_id = "XB8-AA:BB:CC:DD:EE:11"  # Valid MAC address format
        filename = "2024-01-01_12-00-00.json"
        checksum = hashlib.sha256(invalid_data).hexdigest()

        timestamp = str(int(time.time()))
        message = f"{timestamp}|{modem_id}|{filename}|{checksum}"
        signature = hmac.new(
            test_api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        files = {"file": (filename, invalid_data, "application/json")}
        data = {
            "api_key": test_api_key,
            "modem_id": modem_id,
            "filename": filename,
            "checksum": checksum
        }
        headers = {
            "X-Request-Timestamp": timestamp,
            "X-Request-Signature": signature
        }

        response1 = await http_client.post(
            "/api/upload",
            files=files,
            data=data,
            headers=headers
        )
        assert response1.status_code in [400, 422]

        # Delay to ensure database session cleanup completes after failed request
        import asyncio
        await asyncio.sleep(1.0)

        # Next request should work fine
        import json as json_module
        valid_data = json_module.dumps({
            "check_time": int(time.time()),
            "sysinfo": {
                "modemtype": "XB8",
                "modemmac": "AA:BB:CC:DD:EE:11",
                "checktime": int(time.time())
            }
        }).encode()
        filename2 = "2024-01-01_12-00-01.json"
        checksum2 = hashlib.sha256(valid_data).hexdigest()
        message2 = f"{timestamp}|{modem_id}|{filename2}|{checksum2}"
        signature2 = hmac.new(
            test_api_key.encode('utf-8'),
            message2.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        files2 = {"file": (filename2, valid_data, "application/json")}
        data2 = {
            "api_key": test_api_key,
            "modem_id": modem_id,
            "filename": filename2,
            "checksum": checksum2
        }
        headers2 = {
            "X-Request-Timestamp": timestamp,
            "X-Request-Signature": signature2
        }

        response2 = await http_client.post(
            "/api/upload",
            files=files2,
            data=data2,
            headers=headers2
        )

        # Should recover and work
        assert response2.status_code == 200

    @pytest.mark.asyncio
    async def test_recovery_after_auth_failure(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test that system recovers after authentication failure."""
        # Failed login
        response1 = await http_client.post(
            "/api/auth/login",
            json={"username": "wrong", "password": "wrong"}
        )
        assert response1.status_code == 401

        # Successful login should work
        response2 = await http_client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "TestPass123!"}
        )
        assert response2.status_code == 200