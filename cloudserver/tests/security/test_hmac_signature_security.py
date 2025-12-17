"""
HMAC signature security tests.

Tests for:
- Signature tampering detection
- Replay attack prevention
- Timestamp validation
- Signature key rotation
"""
import pytest
import time
import hashlib
import hmac
import json
import httpx
from datetime import datetime, timedelta

pytestmark = pytest.mark.security


class TestHMACTampering:
    """Test detection of HMAC signature tampering."""

    @pytest.mark.asyncio
    async def test_signature_tampering_detection(self, http_client: httpx.AsyncClient, active_api_key, test_api_key: str):
        """Test that tampered signatures are rejected."""
        timestamp = str(int(time.time()))
        modem_id = "XB8-AA:BB:CC:DD:EE:FF"
        filename = "test.json"
        file_content = b'{"test": "data"}'
        checksum = hashlib.sha256(file_content).hexdigest()

        # Generate correct signature
        message = f"{timestamp}|{modem_id}|{filename}|{checksum}"
        correct_signature = hmac.new(
            test_api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        # Tamper with the signature
        tampered_signatures = [
            correct_signature[:-1] + "0",  # Change last character
            "0" + correct_signature[1:],  # Change first character
            correct_signature[:32] + "0" * 32,  # Replace second half
            "0" * 64,  # All zeros
            "",  # Empty signature
        ]

        for tampered_sig in tampered_signatures:
            files = {"file": (filename, file_content, "application/json")}
            data = {
                "api_key": test_api_key,
                "modem_id": modem_id,
                "filename": filename,
                "checksum": checksum
            }

            response = await http_client.post(
                "/api/upload",
                files=files,
                data=data,
                headers={
                    "X-Request-Timestamp": timestamp,
                    "X-Request-Signature": tampered_sig
                }
            )

            assert response.status_code in [400, 401, 403], f"Tampered signature should be rejected: {tampered_sig[:10]}..."

    @pytest.mark.asyncio
    async def test_signature_parameter_tampering(self, http_client: httpx.AsyncClient, active_api_key, test_api_key: str):
        """Test that changing any parameter after signing is detected."""
        timestamp = str(int(time.time()))
        modem_id = "XB8-AA:BB:CC:DD:EE:FF"
        filename = "test.json"
        file_content = b'{"test": "data"}'
        checksum = hashlib.sha256(file_content).hexdigest()

        # Generate signature
        message = f"{timestamp}|{modem_id}|{filename}|{checksum}"
        signature = hmac.new(
            test_api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        # Test tampering with each parameter
        tamper_tests = [
            {"modem_id": "XB7-11:22:33:44:55:66"},  # Different modem ID
            {"filename": "different.json"},  # Different filename
            {"checksum": hashlib.sha256(b'{"different": "data"}').hexdigest()},  # Different checksum
            {"api_key": "different_api_key_12345"},  # Different API key
        ]

        for tamper_params in tamper_tests:
            files = {"file": (filename, file_content, "application/json")}
            data = {
                "api_key": test_api_key,
                "modem_id": modem_id,
                "filename": filename,
                "checksum": checksum
            }

            # Apply tampering
            data.update(tamper_params)

            response = await http_client.post(
                "/api/upload",
                files=files,
                data=data,
                headers={
                    "X-Request-Timestamp": timestamp,
                    "X-Request-Signature": signature
                }
            )

            assert response.status_code in [400, 401, 403], f"Parameter tampering should be detected: {tamper_params}"


class TestReplayAttackPrevention:
    """Test prevention of replay attacks."""

    @pytest.mark.asyncio
    async def test_timestamp_validation_window(self, http_client: httpx.AsyncClient, active_api_key, test_api_key: str):
        """Test that old timestamps are rejected to prevent replay attacks."""
        modem_id = "XB8-REPLAY-TEST"
        filename = "test.json"
        file_content = b'{"test": "data"}'
        checksum = hashlib.sha256(file_content).hexdigest()

        # Test various timestamp ages
        timestamp_tests = [
            (time.time() - 3600, False),  # 1 hour old - should fail
            (time.time() - 900, False),   # 15 minutes old - should fail
            (time.time() - 300, True),    # 5 minutes old - might pass (depends on window)
            (time.time(), True),           # Current - should pass
            (time.time() + 60, True),      # 1 minute future - might pass
            (time.time() + 3600, False),   # 1 hour future - should fail
        ]

        for timestamp_value, should_pass in timestamp_tests:
            timestamp = str(int(timestamp_value))
            message = f"{timestamp}|{modem_id}|{filename}|{checksum}"
            signature = hashlib.sha256(f"{test_api_key}{message}".encode()).hexdigest()

            files = {"file": (filename, file_content, "application/json")}
            data = {
                "api_key": test_api_key,
                "modem_id": modem_id,
                "filename": filename,
                "checksum": checksum
            }

            response = await http_client.post(
                "/api/upload",
                files=files,
                data=data,
                headers={
                    "X-Request-Timestamp": timestamp,
                    "X-Request-Signature": signature
                }
            )

            if should_pass:
                # Should either succeed or fail for non-timestamp reasons
                assert response.status_code != 400 or "timestamp" not in response.text.lower(), \
                    f"Recent timestamp {timestamp} should be accepted"
            else:
                # Old/future timestamps should be rejected
                assert response.status_code in [400, 401, 403], \
                    f"Old/future timestamp {timestamp} should be rejected"

    @pytest.mark.asyncio
    async def test_replay_same_request_rejection(self, http_client: httpx.AsyncClient, active_api_key, test_api_key: str):
        """Test that replaying the exact same request is detected."""
        timestamp = str(int(time.time()))
        modem_id = "XB8-REPLAY-EXACT"
        filename = f"replay_test_{timestamp}.json"
        file_content = b'{"test": "replay"}'
        checksum = hashlib.sha256(file_content).hexdigest()

        # Generate signature
        message = f"{timestamp}|{modem_id}|{filename}|{checksum}"
        signature = hmac.new(
            test_api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        files = {"file": (filename, file_content, "application/json")}
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

        # First request (should succeed or fail for non-replay reasons)
        response1 = await http_client.post("/api/upload", files=files, data=data, headers=headers)

        # Immediate replay (exact same request)
        response2 = await http_client.post("/api/upload", files=files, data=data, headers=headers)

        # At least one should fail (duplicate prevention or timestamp)
        assert response1.status_code != 200 or response2.status_code != 200, \
            "Replay attack should be prevented"


class TestSignatureMissingComponents:
    """Test handling of missing signature components."""

    @pytest.mark.asyncio
    async def test_missing_timestamp_header(self, http_client: httpx.AsyncClient, active_api_key, test_api_key: str):
        """Test that missing timestamp header is rejected."""
        modem_id = "XB8-MISSING-TS"
        filename = "test.json"
        file_content = b'{"test": "data"}'
        checksum = hashlib.sha256(file_content).hexdigest()

        # Generate signature (but don't send timestamp header)
        timestamp = str(int(time.time()))
        message = f"{timestamp}|{modem_id}|{filename}|{checksum}"
        signature = hashlib.sha256(f"{test_api_key}{message}".encode()).hexdigest()

        files = {"file": (filename, file_content, "application/json")}
        data = {
            "api_key": test_api_key,
            "modem_id": modem_id,
            "filename": filename,
            "checksum": checksum
        }

        response = await http_client.post(
            "/api/upload",
            files=files,
            data=data,
            headers={
                "X-Request-Signature": signature
                # Missing X-Request-Timestamp
            }
        )

        assert response.status_code in [400, 401, 403], "Missing timestamp should be rejected"

    @pytest.mark.asyncio
    async def test_missing_signature_header(self, http_client: httpx.AsyncClient, active_api_key, test_api_key: str):
        """Test that missing signature header is rejected."""
        timestamp = str(int(time.time()))
        modem_id = "XB8-MISSING-SIG"
        filename = "test.json"
        file_content = b'{"test": "data"}'
        checksum = hashlib.sha256(file_content).hexdigest()

        files = {"file": (filename, file_content, "application/json")}
        data = {
            "api_key": test_api_key,
            "modem_id": modem_id,
            "filename": filename,
            "checksum": checksum
        }

        response = await http_client.post(
            "/api/upload",
            files=files,
            data=data,
            headers={
                "X-Request-Timestamp": timestamp
                # Missing X-Request-Signature
            }
        )

        assert response.status_code in [400, 401, 403], "Missing signature should be rejected"

    @pytest.mark.asyncio
    async def test_malformed_timestamp(self, http_client: httpx.AsyncClient, active_api_key, test_api_key: str):
        """Test that malformed timestamps are rejected."""
        modem_id = "XB8-MALFORMED-TS"
        filename = "test.json"
        file_content = b'{"test": "data"}'
        checksum = hashlib.sha256(file_content).hexdigest()

        malformed_timestamps = [
            "not-a-number",
            "12345.67890",  # Float
            "-1234567890",  # Negative
            "",  # Empty
            "2024-01-01T00:00:00Z",  # ISO format instead of Unix timestamp
        ]

        for bad_timestamp in malformed_timestamps:
            # Generate signature with the malformed timestamp
            message = f"{bad_timestamp}|{modem_id}|{filename}|{checksum}"
            signature = hmac.new(
                test_api_key.encode('utf-8'),
                message.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()

            files = {"file": (filename, file_content, "application/json")}
            data = {
                "api_key": test_api_key,
                "modem_id": modem_id,
                "filename": filename,
                "checksum": checksum
            }

            response = await http_client.post(
                "/api/upload",
                files=files,
                data=data,
                headers={
                    "X-Request-Timestamp": bad_timestamp,
                    "X-Request-Signature": signature
                }
            )

            assert response.status_code in [400, 401, 403], f"Malformed timestamp should be rejected: {bad_timestamp}"


class TestSignatureKeyRotation:
    """
    Test signature security during key rotation.

    Key rotation process (manual):
    1. Create new API key in admin dashboard
    2. Update client configuration with new key
    3. Delete old API key

    Note: No automatic key versioning/overlap - rotation requires
    brief downtime or careful client coordination.
    """

    @pytest.mark.asyncio
    async def test_signature_with_rotated_key(
        self, admin_client_with_token: httpx.AsyncClient,
        csrf_token: str,
        http_client: httpx.AsyncClient
    ):
        """Test that signatures with old keys fail after rotation (delete + recreate)."""
        # Helper to get fresh CSRF token (tokens are one-time use)
        async def get_fresh_csrf_token():
            resp = await admin_client_with_token.get("/api/auth/session_check")
            return resp.json()["csrf_token"]

        # Create a new API key
        create_response = await admin_client_with_token.post(
            "/api/admin/api_keys",
            json={"name": "rotation_sig_test"},
            headers={"X-CSRF-Token": csrf_token}
        )
        assert create_response.status_code == 200
        old_key = create_response.json()["api_key"]

        # Generate signature with old key
        timestamp = str(int(time.time()))
        modem_id = "XB8-ROTATION"
        filename = "test.json"
        file_content = b'{"test": "data"}'
        checksum = hashlib.sha256(file_content).hexdigest()

        message = f"{timestamp}|{modem_id}|{filename}|{checksum}"
        old_signature = hmac.new(
            old_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        # Delete the old key (simulate rotation) - need fresh CSRF token
        csrf_token = await get_fresh_csrf_token()
        preview = f"{old_key[:4]}...{old_key[-4:]}"
        delete_response = await admin_client_with_token.request(
            "DELETE",
            "/api/admin/api_keys",
            json={"api_key_preview": preview},
            headers={"X-CSRF-Token": csrf_token}
        )
        assert delete_response.status_code == 200

        # Create a new key (rotation complete) - need fresh CSRF token
        csrf_token = await get_fresh_csrf_token()
        create_response = await admin_client_with_token.post(
            "/api/admin/api_keys",
            json={"name": "rotation_sig_test_new"},
            headers={"X-CSRF-Token": csrf_token}
        )
        assert create_response.status_code == 200
        new_key = create_response.json()["api_key"]

        # Try to use old signature - should fail
        files = {"file": (filename, file_content, "application/json")}
        data = {
            "api_key": old_key,  # Old key
            "modem_id": modem_id,
            "filename": filename,
            "checksum": checksum
        }

        response = await http_client.post(
            "/api/upload",
            files=files,
            data=data,
            headers={
                "X-Request-Timestamp": timestamp,
                "X-Request-Signature": old_signature  # Old signature
            }
        )

        assert response.status_code in [401, 403], "Old key and signature should be rejected"

        # Generate new signature with new key - should work
        new_timestamp = str(int(time.time()))
        new_message = f"{new_timestamp}|{modem_id}|{filename}|{checksum}"
        new_signature = hmac.new(
            new_key.encode('utf-8'),
            new_message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        data["api_key"] = new_key
        response = await http_client.post(
            "/api/upload",
            files=files,
            data=data,
            headers={
                "X-Request-Timestamp": new_timestamp,
                "X-Request-Signature": new_signature
            }
        )

        # Should work or fail for non-auth reasons
        assert response.status_code != 401, "New key and signature should work"

        # Cleanup - need fresh CSRF token
        csrf_token = await get_fresh_csrf_token()
        preview = f"{new_key[:4]}...{new_key[-4:]}"
        await admin_client_with_token.request(
            "DELETE",
            "/api/admin/api_keys",
            json={"api_key_preview": preview},
            headers={"X-CSRF-Token": csrf_token}
        )


class TestChecksumValidation:
    """Test file checksum validation in signature."""

    @pytest.mark.asyncio
    async def test_checksum_mismatch_detection(self, http_client: httpx.AsyncClient, active_api_key, test_api_key: str):
        """Test that file content checksum mismatches are detected."""
        timestamp = str(int(time.time()))
        modem_id = "XB8-CHECKSUM"
        filename = "test.json"
        file_content = b'{"test": "data"}'
        correct_checksum = hashlib.sha256(file_content).hexdigest()
        wrong_checksum = hashlib.sha256(b'{"different": "content"}').hexdigest()

        # Generate signature with wrong checksum
        message = f"{timestamp}|{modem_id}|{filename}|{wrong_checksum}"
        signature = hmac.new(
            test_api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        files = {"file": (filename, file_content, "application/json")}
        data = {
            "api_key": test_api_key,
            "modem_id": modem_id,
            "filename": filename,
            "checksum": wrong_checksum  # Wrong checksum in data
        }

        response = await http_client.post(
            "/api/upload",
            files=files,
            data=data,
            headers={
                "X-Request-Timestamp": timestamp,
                "X-Request-Signature": signature
            }
        )

        assert response.status_code in [400, 401, 403], "Checksum mismatch should be detected"

    @pytest.mark.asyncio
    async def test_file_content_tampering(self, http_client: httpx.AsyncClient, active_api_key, test_api_key: str):
        """Test that file content tampering after signing is detected."""
        timestamp = str(int(time.time()))
        modem_id = "XB8-TAMPER"
        filename = "test.json"
        original_content = b'{"test": "original"}'
        tampered_content = b'{"test": "tampered"}'
        checksum = hashlib.sha256(original_content).hexdigest()

        # Generate signature with original content checksum
        message = f"{timestamp}|{modem_id}|{filename}|{checksum}"
        signature = hmac.new(
            test_api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        # Send tampered content
        files = {"file": (filename, tampered_content, "application/json")}
        data = {
            "api_key": test_api_key,
            "modem_id": modem_id,
            "filename": filename,
            "checksum": checksum  # Original checksum
        }

        response = await http_client.post(
            "/api/upload",
            files=files,
            data=data,
            headers={
                "X-Request-Timestamp": timestamp,
                "X-Request-Signature": signature
            }
        )

        assert response.status_code in [400, 401, 403], "File tampering should be detected"