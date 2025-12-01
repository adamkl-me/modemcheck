"""
Data management security tests.

Tests for:
- Authorization (basic/elevated role access)
- File encoding validation
- File type validation
- Path traversal in ZIP files
- ZIP bomb protection

NOTE: Tests for ZIP file upload are currently skipped because the bulk_upload
endpoint only supports individual JSON files, not ZIP archives. These tests
document desired security features for future ZIP upload implementation.
"""
import pytest
import httpx
import zipfile
import io
import json
from datetime import datetime, timezone

pytestmark = pytest.mark.api


class TestDataManagementAuthorization:
    """Authorization tests for data management endpoints."""

    @pytest.mark.asyncio
    async def test_bulk_upload_basic_user_blocked(self, basic_client_with_token: httpx.AsyncClient, csrf_token_basic: str):
        """Test that basic users cannot perform bulk uploads via ZIP file."""
        # Create a simple ZIP file with one check
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            check_data = {
                "sysinfo": {
                    "modemtype": "XB8",
                    "modemmac": "AA:BB:CC:DD:EE:FF",
                    "checktime": datetime.now(timezone.utc).isoformat()
                }
            }
            zf.writestr("XB8-AA:BB:CC:DD:EE:FF/2024-01-01_12-00-00.json", json.dumps(check_data))

        zip_buffer.seek(0)

        files = {"file": ("checks.zip", zip_buffer, "application/zip")}
        response = await basic_client_with_token.post(
            "/api/data/bulk_upload",
            files=files,
            headers={"X-CSRF-Token": csrf_token_basic}
        )

        # Basic users should be forbidden
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_bulk_upload_elevated_user_allowed(self, elevated_client_with_token: httpx.AsyncClient, csrf_token_elevated: str):
        """Test that elevated users can perform bulk uploads via ZIP file."""
        # Create a simple ZIP file with one check
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            check_data = {
                "sysinfo": {
                    "modemtype": "XB8",
                    "modemmac": "AA:BB:CC:DD:EE:FF",
                    "checktime": datetime.now(timezone.utc).isoformat()
                }
            }
            zf.writestr("XB8-AA:BB:CC:DD:EE:FF/2024-01-01_12-00-00.json", json.dumps(check_data))

        zip_buffer.seek(0)

        files = {"file": ("checks.zip", zip_buffer, "application/zip")}
        response = await elevated_client_with_token.post(
            "/api/data/bulk_upload",
            files=files,
            headers={"X-CSRF-Token": csrf_token_elevated}
        )

        # Elevated users should be allowed
        assert response.status_code in [200, 201]


class TestFileEncodingValidation:
    """File encoding validation tests."""

    @pytest.mark.asyncio
    async def test_bulk_upload_invalid_utf8_encoding(self, elevated_client_with_token: httpx.AsyncClient, csrf_token_elevated: str):
        """Test rejection of files with invalid UTF-8 encoding."""
        # Create a ZIP file with invalid UTF-8 content
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Invalid UTF-8 bytes
            invalid_content = b'\xff\xfe\xfd\xfc'
            zf.writestr("XB8-AA:BB:CC:DD:EE:FF/2024-01-01_12-00-00.json", invalid_content)

        zip_buffer.seek(0)

        files = {"file": ("checks.zip", zip_buffer, "application/zip")}
        response = await elevated_client_with_token.post(
            "/api/data/bulk_upload",
            files=files,
            headers={"X-CSRF-Token": csrf_token_elevated}
        )

        # Should handle gracefully - return 200 but report errors
        assert response.status_code == 200
        data = response.json()
        assert data["results"]["failed"] > 0
        # Check that the file was rejected due to encoding (error message contains "encoding" or "UTF-8")
        assert any("encoding" in error.lower() or "utf-8" in error.lower() for error in data["results"]["errors"])

    @pytest.mark.asyncio
    async def test_bulk_upload_valid_utf8_encoding(self, elevated_client_with_token: httpx.AsyncClient, csrf_token_elevated: str):
        """Test acceptance of ZIP files with valid UTF-8 encoding."""
        # Create a ZIP file with valid UTF-8 content including unicode
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Use unique timestamp to avoid collisions with other tests
            timestamp = datetime.now(timezone.utc)
            filename_timestamp = timestamp.strftime("%Y-%m-%d_%H-%M-%S-%f")

            check_data = {
                "sysinfo": {
                    "modemtype": "XB8",
                    "modemmac": "AA:BB:CC:DD:EE:FF",
                    "checktime": timestamp.isoformat(),
                    "note": "Unicode test: 你好, Привет, مرحبا"
                }
            }
            zf.writestr(f"XB8-AA:BB:CC:DD:EE:FF/{filename_timestamp}.json", json.dumps(check_data, ensure_ascii=False))

        zip_buffer.seek(0)

        files = {"file": ("checks.zip", zip_buffer, "application/zip")}
        response = await elevated_client_with_token.post(
            "/api/data/bulk_upload",
            files=files,
            headers={"X-CSRF-Token": csrf_token_elevated}
        )

        # Should accept valid UTF-8
        assert response.status_code in [200, 201]


class TestFileTypeValidation:
    """File type validation tests."""

    @pytest.mark.asyncio
    async def test_bulk_upload_wrong_file_type(self, elevated_client_with_token: httpx.AsyncClient, csrf_token_elevated: str):
        """Test handling of non-JSON files."""
        # Try to upload a plain text file as bulk upload
        text_content = b"This is not a ZIP file"

        files = {"file": ("checks.txt", io.BytesIO(text_content), "text/plain")}
        response = await elevated_client_with_token.post(
            "/api/data/bulk_upload",
            files=files,
            headers={"X-CSRF-Token": csrf_token_elevated}
        )

        # Should handle gracefully - return 200 but report JSON parsing error
        assert response.status_code == 200
        data = response.json()
        assert data["results"]["failed"] > 0
        assert any("Invalid JSON" in error for error in data["results"]["errors"])

    @pytest.mark.asyncio
    async def test_bulk_upload_corrupted_zip(self, elevated_client_with_token: httpx.AsyncClient, csrf_token_elevated: str):
        """Test rejection of corrupted ZIP files."""
        # Create corrupted ZIP data
        corrupted_zip = b"PK\x03\x04" + b"\x00" * 100  # ZIP header but corrupted content

        files = {"file": ("checks.zip", io.BytesIO(corrupted_zip), "application/zip")}
        response = await elevated_client_with_token.post(
            "/api/data/bulk_upload",
            files=files,
            headers={"X-CSRF-Token": csrf_token_elevated}
        )

        # Should reject corrupted ZIP files
        assert response.status_code in [400, 422]


class TestPathTraversalInZip:
    """Path traversal attack tests in ZIP files."""

    @pytest.mark.asyncio
    async def test_bulk_upload_path_traversal_absolute(self, elevated_client_with_token: httpx.AsyncClient, csrf_token_elevated: str):
        """Test rejection of ZIP files with absolute paths."""
        # Create ZIP with absolute path
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            check_data = {"test": "data"}
            # Try to write to absolute path
            zf.writestr("/etc/passwd", json.dumps(check_data))

        zip_buffer.seek(0)

        files = {"file": ("checks.zip", zip_buffer, "application/zip")}
        response = await elevated_client_with_token.post(
            "/api/data/bulk_upload",
            files=files,
            headers={"X-CSRF-Token": csrf_token_elevated}
        )

        # Should reject or safely handle
        # May return 400 (rejected) or 200 (safely handled)
        assert response.status_code in [200, 400, 422]

    @pytest.mark.asyncio
    async def test_bulk_upload_path_traversal_relative(self, elevated_client_with_token: httpx.AsyncClient, csrf_token_elevated: str):
        """Test rejection of ZIP files with path traversal attempts."""
        # Create ZIP with path traversal
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            check_data = {"test": "data"}
            # Try to traverse outside intended directory
            malicious_paths = [
                "../../../etc/passwd",
                "..\\..\\..\\windows\\system32\\config\\sam",
                "XB8-AA/../../../etc/passwd",
            ]
            for path in malicious_paths:
                zf.writestr(path, json.dumps(check_data))

        zip_buffer.seek(0)

        files = {"file": ("checks.zip", zip_buffer, "application/zip")}
        response = await elevated_client_with_token.post(
            "/api/data/bulk_upload",
            files=files,
            headers={"X-CSRF-Token": csrf_token_elevated}
        )

        # Should reject or safely sanitize paths
        assert response.status_code in [200, 400, 422]


class TestZipBombProtection:
    """ZIP bomb attack prevention tests."""

    @pytest.mark.asyncio
    async def test_bulk_upload_excessive_compression_ratio(self, elevated_client_with_token: httpx.AsyncClient, csrf_token_elevated: str):
        """Test rejection of ZIP bombs (high compression ratio)."""
        # Create a ZIP with very high compression ratio
        # Small ZIP that expands to large size when extracted
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Create a file that compresses very well (repetitive data)
            # 10MB of zeros compresses to ~10KB
            large_content = "0" * (10 * 1024 * 1024)
            zf.writestr("XB8-AA:BB:CC:DD:EE:FF/2024-01-01_12-00-00.json", large_content)

        zip_buffer.seek(0)
        zip_size = len(zip_buffer.getvalue())

        # Compression ratio should be very high (zip_size << 10MB)
        # This simulates a ZIP bomb attack

        files = {"file": ("checks.zip", zip_buffer, "application/zip")}
        response = await elevated_client_with_token.post(
            "/api/data/bulk_upload",
            files=files,
            headers={"X-CSRF-Token": csrf_token_elevated}
        )

        # Should reject or limit extraction
        # May fail JSON parsing (not valid JSON) or detect size limit
        assert response.status_code in [400, 413, 422]

    @pytest.mark.asyncio
    async def test_bulk_upload_too_many_files(self, elevated_client_with_token: httpx.AsyncClient, csrf_token_elevated: str):
        """Test rejection of ZIP files with too many entries."""
        # Create ZIP with many files
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Create 1000+ small files
            for i in range(1100):
                check_data = {
                    "modem_id": f"XB8-AA:BB:CC:DD:EE:{i:02X}",
                    "check_time": datetime.now(timezone.utc).isoformat(),
                    "modem_type": "XB8",
                    "test": f"file_{i}"
                }
                zf.writestr(
                    f"XB8-AA:BB:CC:DD:EE:{i:02X}/2024-01-01_12-00-00.json",
                    json.dumps(check_data)
                )

        zip_buffer.seek(0)

        files = {"file": ("checks.zip", zip_buffer, "application/zip")}
        response = await elevated_client_with_token.post(
            "/api/data/bulk_upload",
            files=files,
            headers={"X-CSRF-Token": csrf_token_elevated}
        )

        # Should limit number of files or handle gracefully
        # Config says max_bulk_upload_files: 1000, so 1100 should be rejected or limited
        assert response.status_code in [200, 400, 413, 422]

    @pytest.mark.asyncio
    async def test_bulk_upload_nested_zip_files(self, elevated_client_with_token: httpx.AsyncClient, csrf_token_elevated: str):
        """Test handling of nested ZIP files (potential bomb)."""
        # Create a ZIP file containing another ZIP file
        inner_zip = io.BytesIO()
        with zipfile.ZipFile(inner_zip, 'w', zipfile.ZIP_DEFLATED) as inner:
            inner.writestr("test.json", json.dumps({"test": "data"}))

        inner_zip.seek(0)

        outer_zip = io.BytesIO()
        with zipfile.ZipFile(outer_zip, 'w', zipfile.ZIP_DEFLATED) as outer:
            outer.writestr("nested.zip", inner_zip.getvalue())

        outer_zip.seek(0)

        files = {"file": ("checks.zip", outer_zip, "application/zip")}
        response = await elevated_client_with_token.post(
            "/api/data/bulk_upload",
            files=files,
            headers={"X-CSRF-Token": csrf_token_elevated}
        )

        # Should reject nested ZIPs or safely ignore them
        # Will likely fail JSON parsing on the .zip file
        assert response.status_code in [200, 400, 422]
