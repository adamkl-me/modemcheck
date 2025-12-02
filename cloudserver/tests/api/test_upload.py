"""
API tests for upload endpoints (/api/upload).

Tests:
- File upload with valid API key
- HMAC signature validation
- Checksum validation
- Duplicate detection
- File size limits
- Format validation
"""
import pytest
import httpx
import json
import hashlib
import time
import hmac
from typing import Dict, Any
from io import BytesIO

pytestmark = pytest.mark.api


class TestUpload:
    """Tests for POST /api/upload"""
    
    @pytest.mark.asyncio
    async def test_upload_success(self, http_client: httpx.AsyncClient, active_api_key, sample_modem_check_data: Dict[str, Any]):
        """Test successful file upload with valid API key and signature."""
        sysinfo = sample_modem_check_data["sysinfo"]
        modem_id = f"{sysinfo['modemtype']}-{sysinfo['modemmac']}"
        filename = "2024-01-01_12-00-00.json"
        
        # Calculate checksum
        file_content = json.dumps(sample_modem_check_data).encode('utf-8')
        checksum = hashlib.sha256(file_content).hexdigest()
        
        # Create HMAC signature
        timestamp = str(int(time.time()))
        message = f"{timestamp}|{modem_id}|{filename}|{checksum}"
        signature = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        # Create upload request
        files = {"file": (filename, BytesIO(file_content), "application/json")}
        data = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "filename": filename,
            "checksum": checksum
        }
        headers = {
            "X-Request-Timestamp": timestamp,
            "X-Request-Signature": signature
        }
        
        response = await http_client.post("/api/upload", files=files, data=data, headers=headers)
        
        assert response.status_code == 200
        result = response.json()
        assert result["success"] is True
        assert result["modem_id"] == modem_id
        assert "database_id" in result
    
    @pytest.mark.asyncio
    async def test_upload_invalid_api_key(self, http_client: httpx.AsyncClient, sample_modem_check_data: Dict[str, Any]):
        """Test upload with invalid API key (but valid signature format)."""
        sysinfo = sample_modem_check_data["sysinfo"]
        modem_id = f"{sysinfo['modemtype']}-{sysinfo['modemmac']}"
        filename = "2024-01-01_12-00-00.json"

        file_content = json.dumps(sample_modem_check_data).encode('utf-8')
        checksum = hashlib.sha256(file_content).hexdigest()

        # Generate valid HMAC signature with the invalid key
        invalid_api_key = "invalid_key_12345"
        timestamp = str(int(time.time()))
        message = f"{timestamp}|{modem_id}|{filename}|{checksum}"
        signature = hmac.new(
            invalid_api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        files = {"file": (filename, BytesIO(file_content), "application/json")}
        data = {
            "api_key": invalid_api_key,
            "modem_id": modem_id,
            "filename": filename,
            "checksum": checksum
        }
        headers = {
            "X-Request-Timestamp": timestamp,
            "X-Request-Signature": signature
        }

        response = await http_client.post("/api/upload", files=files, data=data, headers=headers)

        assert response.status_code == 401
        result = response.json()
        assert "Invalid or inactive API key" in result["detail"]
    
    @pytest.mark.asyncio
    async def test_upload_inactive_api_key(self, http_client: httpx.AsyncClient, inactive_api_key, sample_modem_check_data: Dict[str, Any]):
        """Test upload with inactive API key (but valid signature)."""
        sysinfo = sample_modem_check_data["sysinfo"]
        modem_id = f"{sysinfo['modemtype']}-{sysinfo['modemmac']}"
        filename = "2024-01-01_12-00-00.json"

        file_content = json.dumps(sample_modem_check_data).encode('utf-8')
        checksum = hashlib.sha256(file_content).hexdigest()

        # Generate valid HMAC signature with the inactive key
        timestamp = str(int(time.time()))
        message = f"{timestamp}|{modem_id}|{filename}|{checksum}"
        signature = hmac.new(
            inactive_api_key.api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        files = {"file": (filename, BytesIO(file_content), "application/json")}
        data = {
            "api_key": inactive_api_key.api_key,
            "modem_id": modem_id,
            "filename": filename,
            "checksum": checksum
        }
        headers = {
            "X-Request-Timestamp": timestamp,
            "X-Request-Signature": signature
        }

        response = await http_client.post("/api/upload", files=files, data=data, headers=headers)

        assert response.status_code == 401
        result = response.json()
        assert "Invalid or inactive API key" in result["detail"]
    
    @pytest.mark.asyncio
    async def test_upload_invalid_signature(self, http_client: httpx.AsyncClient, active_api_key, sample_modem_check_data: Dict[str, Any]):
        """Test upload with invalid HMAC signature."""
        sysinfo = sample_modem_check_data["sysinfo"]
        modem_id = f"{sysinfo['modemtype']}-{sysinfo['modemmac']}"
        filename = "2024-01-01_12-00-00.json"
        
        file_content = json.dumps(sample_modem_check_data).encode('utf-8')
        checksum = hashlib.sha256(file_content).hexdigest()
        
        timestamp = str(int(time.time()))
        
        files = {"file": (filename, BytesIO(file_content), "application/json")}
        data = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "filename": filename,
            "checksum": checksum
        }
        headers = {
            "X-Request-Timestamp": timestamp,
            "X-Request-Signature": "invalid_signature_12345"
        }
        
        response = await http_client.post("/api/upload", files=files, data=data, headers=headers)
        
        assert response.status_code == 401
        result = response.json()
        assert "Signature validation failed" in result["detail"]
    
    @pytest.mark.asyncio
    async def test_upload_expired_timestamp(self, http_client: httpx.AsyncClient, active_api_key, sample_modem_check_data: Dict[str, Any]):
        """Test upload with expired timestamp (replay attack prevention)."""
        sysinfo = sample_modem_check_data["sysinfo"]
        modem_id = f"{sysinfo['modemtype']}-{sysinfo['modemmac']}"
        filename = "2024-01-01_12-00-00.json"
        
        file_content = json.dumps(sample_modem_check_data).encode('utf-8')
        checksum = hashlib.sha256(file_content).hexdigest()
        
        # Use timestamp from 10 minutes ago (should fail with 5-minute window)
        timestamp = str(int(time.time()) - 600)
        message = f"{timestamp}|{modem_id}|{filename}|{checksum}"
        signature = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        files = {"file": (filename, BytesIO(file_content), "application/json")}
        data = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "filename": filename,
            "checksum": checksum
        }
        headers = {
            "X-Request-Timestamp": timestamp,
            "X-Request-Signature": signature
        }
        
        response = await http_client.post("/api/upload", files=files, data=data, headers=headers)
        
        assert response.status_code == 401
        result = response.json()
        # Error message includes specific failure reason for debugging
        assert "signature validation failed" in result["detail"].lower() or "expired" in result["detail"].lower()
    
    @pytest.mark.asyncio
    async def test_upload_invalid_checksum(self, http_client: httpx.AsyncClient, active_api_key, sample_modem_check_data: Dict[str, Any]):
        """Test upload with invalid checksum."""
        sysinfo = sample_modem_check_data["sysinfo"]
        modem_id = f"{sysinfo['modemtype']}-{sysinfo['modemmac']}"
        filename = "2024-01-01_12-00-00.json"

        file_content = json.dumps(sample_modem_check_data).encode('utf-8')
        wrong_checksum = "0" * 64  # Invalid checksum

        # Create HMAC signature with wrong checksum
        timestamp = str(int(time.time()))
        message = f"{timestamp}|{modem_id}|{filename}|{wrong_checksum}"
        signature = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        files = {"file": (filename, BytesIO(file_content), "application/json")}
        data = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "filename": filename,
            "checksum": wrong_checksum
        }
        headers = {
            "X-Request-Timestamp": timestamp,
            "X-Request-Signature": signature
        }

        response = await http_client.post("/api/upload", files=files, data=data, headers=headers)

        assert response.status_code == 400
        result = response.json()
        assert "Checksum validation failed" in result["detail"]
    
    @pytest.mark.asyncio
    async def test_upload_missing_checksum(self, http_client: httpx.AsyncClient, active_api_key, sample_modem_check_data: Dict[str, Any]):
        """Test upload without checksum field."""
        sysinfo = sample_modem_check_data["sysinfo"]
        modem_id = f"{sysinfo['modemtype']}-{sysinfo['modemmac']}"
        filename = "2024-01-01_12-00-00.json"

        file_content = json.dumps(sample_modem_check_data).encode('utf-8')

        # Create HMAC signature with empty checksum
        timestamp = str(int(time.time()))
        message = f"{timestamp}|{modem_id}|{filename}|"  # Empty checksum
        signature = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        files = {"file": (filename, BytesIO(file_content), "application/json")}
        data = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "filename": filename,
            "checksum": ""  # Empty checksum
        }
        headers = {
            "X-Request-Timestamp": timestamp,
            "X-Request-Signature": signature
        }

        response = await http_client.post("/api/upload", files=files, data=data, headers=headers)

        assert response.status_code == 400
        result = response.json()
        assert "Missing checksum" in result["detail"]
    
    @pytest.mark.asyncio
    async def test_upload_invalid_json(self, http_client: httpx.AsyncClient, active_api_key):
        """Test upload with invalid JSON data."""
        modem_id = "XB8-AA:BB:CC:DD:EE:FF"
        filename = "2024-01-01_12-00-00.json"

        file_content = b"{ invalid json }"
        checksum = hashlib.sha256(file_content).hexdigest()

        # Create HMAC signature
        timestamp = str(int(time.time()))
        message = f"{timestamp}|{modem_id}|{filename}|{checksum}"
        signature = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        files = {"file": (filename, BytesIO(file_content), "application/json")}
        data = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "filename": filename,
            "checksum": checksum
        }
        headers = {
            "X-Request-Timestamp": timestamp,
            "X-Request-Signature": signature
        }

        response = await http_client.post("/api/upload", files=files, data=data, headers=headers)

        assert response.status_code == 400
        result = response.json()
        assert "Invalid JSON" in result["detail"]
    
    @pytest.mark.asyncio
    async def test_upload_invalid_modem_id_format(self, http_client: httpx.AsyncClient, active_api_key, sample_modem_check_data: Dict[str, Any]):
        """Test upload with invalid modem_id format."""
        filename = "2024-01-01_12-00-00.json"
        modem_id = "invalid modem id with spaces"  # Invalid format

        file_content = json.dumps(sample_modem_check_data).encode('utf-8')
        checksum = hashlib.sha256(file_content).hexdigest()

        # Create HMAC signature
        timestamp = str(int(time.time()))
        message = f"{timestamp}|{modem_id}|{filename}|{checksum}"
        signature = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        files = {"file": (filename, BytesIO(file_content), "application/json")}
        data = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "filename": filename,
            "checksum": checksum
        }
        headers = {
            "X-Request-Timestamp": timestamp,
            "X-Request-Signature": signature
        }

        response = await http_client.post("/api/upload", files=files, data=data, headers=headers)

        assert response.status_code == 400
        result = response.json()
        assert "Invalid modem_id format" in result["detail"]
    
    @pytest.mark.asyncio
    async def test_upload_invalid_filename_format(self, http_client: httpx.AsyncClient, active_api_key, sample_modem_check_data: Dict[str, Any]):
        """Test upload with invalid filename format."""
        modem_id = "XB8-AA:BB:CC:DD:EE:FF"
        filename = "invalid-filename.json"  # Invalid format (should be YYYY-MM-DD_HH-MM-SS.json)

        file_content = json.dumps(sample_modem_check_data).encode('utf-8')
        checksum = hashlib.sha256(file_content).hexdigest()

        # Create HMAC signature
        timestamp = str(int(time.time()))
        message = f"{timestamp}|{modem_id}|{filename}|{checksum}"
        signature = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        files = {"file": (filename, BytesIO(file_content), "application/json")}
        data = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "filename": filename,
            "checksum": checksum
        }
        headers = {
            "X-Request-Timestamp": timestamp,
            "X-Request-Signature": signature
        }

        response = await http_client.post("/api/upload", files=files, data=data, headers=headers)

        assert response.status_code == 400
        result = response.json()
        assert "Invalid filename format" in result["detail"]
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_upload_file_too_large(self, http_client: httpx.AsyncClient, active_api_key):
        """Test upload with file exceeding size limit."""
        import uuid
        modem_id = "XB8-AA:BB:CC:DD:EE:FF"
        # Use unique filename to avoid duplicate conflicts
        unique_id = uuid.uuid4().hex[:8]
        filename = f"2024-01-01_12-00-00_{unique_id}.json"

        # Create file larger than test environment limit (50MB in docker-compose.test.yml)
        # Using 51MB to ensure it exceeds the test limit
        large_data = {"data": "x" * (51 * 1024 * 1024)}  # 51MB
        file_content = json.dumps(large_data).encode('utf-8')
        checksum = hashlib.sha256(file_content).hexdigest()

        # Create HMAC signature
        timestamp = str(int(time.time()))
        message = f"{timestamp}|{modem_id}|{filename}|{checksum}"
        signature = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        files = {"file": (filename, BytesIO(file_content), "application/json")}
        data = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "filename": filename,
            "checksum": checksum
        }
        headers = {
            "X-Request-Timestamp": timestamp,
            "X-Request-Signature": signature
        }

        response = await http_client.post("/api/upload", files=files, data=data, headers=headers)

        assert response.status_code == 413
        result = response.json()
        assert "File size exceeds" in result["detail"]
    
    @pytest.mark.asyncio
    async def test_upload_duplicate_check(self, http_client: httpx.AsyncClient, active_api_key, sample_modem_check):
        """Test uploading duplicate check."""
        # Try to upload the same check again
        modem_id = sample_modem_check.modem_id
        filename = sample_modem_check.filename.split('/')[-1]  # Get just the filename

        file_content = json.dumps(sample_modem_check.full_data).encode('utf-8')
        checksum = hashlib.sha256(file_content).hexdigest()

        # Create HMAC signature
        timestamp = str(int(time.time()))
        message = f"{timestamp}|{modem_id}|{filename}|{checksum}"
        signature = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        files = {"file": (filename, BytesIO(file_content), "application/json")}
        data = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "filename": filename,
            "checksum": checksum
        }
        headers = {
            "X-Request-Timestamp": timestamp,
            "X-Request-Signature": signature
        }

        response = await http_client.post("/api/upload", files=files, data=data, headers=headers)

        assert response.status_code == 409
        result = response.json()
        assert "already exists" in result["detail"].lower()
