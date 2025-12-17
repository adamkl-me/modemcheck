"""
Unit tests for upload service layer.

These tests demonstrate the improved testability from extracting business logic
into service functions that can be tested independently of HTTP concerns.
"""
import pytest
import json
import hashlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.services.upload_service import (
    InputValidator,
    FileProcessor,
    UploadPersistenceService,
    UploadService,
    UploadValidationError
)
from app.core.utils import utc_now


class TestInputValidator:
    """Test input validation logic."""

    def test_validate_modem_id_valid(self):
        """Valid modem_id formats should pass."""
        valid_ids = [
            "XB8-AA:BB:CC:DD:EE:FF",
            "SB8200-00:11:22:33:44:55",
            "CM1000-ab:cd:ef:01:23:45",
            "Model_123-A1:B2:C3:D4:E5:F6",
            "XB8-AABBCCDDEEFF",  # MAC without colons is also valid
        ]
        validator = InputValidator()
        for modem_id in valid_ids:
            validator.validate_modem_id(modem_id)  # Should not raise

    def test_validate_modem_id_missing(self):
        """Missing modem_id should raise error."""
        validator = InputValidator()
        with pytest.raises(UploadValidationError, match="Missing modem_id"):
            validator.validate_modem_id("")

    def test_validate_modem_id_invalid_format(self):
        """Invalid modem_id formats should raise error."""
        invalid_ids = [
            "XB8",  # No MAC address
            "AA:BB:CC:DD:EE:FF",  # No model
            "XB8/AA:BB:CC:DD:EE:FF",  # Wrong separator
            "XB8-ZZ:BB:CC:DD:EE:FF",  # Invalid hex characters
        ]
        validator = InputValidator()
        for modem_id in invalid_ids:
            with pytest.raises(UploadValidationError, match="Invalid modem_id format"):
                validator.validate_modem_id(modem_id)

    def test_validate_filename_valid(self):
        """Valid filename formats should pass."""
        valid_filenames = [
            "2024-01-01_12-00-00.json",
            "2024-12-31_23-59-59.json",
            "2024-01-01_12-00-00_123.json",
            "2024-01-01_12-00-00_abc123def.json",
        ]
        validator = InputValidator()
        for filename in valid_filenames:
            validator.validate_filename(filename)  # Should not raise

    def test_validate_filename_missing(self):
        """Missing filename should raise error."""
        validator = InputValidator()
        with pytest.raises(UploadValidationError, match="Missing filename"):
            validator.validate_filename("")

    def test_validate_filename_path_traversal(self):
        """Path traversal attempts should be blocked."""
        malicious_filenames = [
            "../2024-01-01_12-00-00.json",
            "../../etc/passwd",
            "2024-01-01_12-00-00.json/../file.json",
            "sub/dir/2024-01-01_12-00-00.json",
            "c:\\windows\\system32\\file.json",
        ]
        validator = InputValidator()
        for filename in malicious_filenames:
            with pytest.raises(UploadValidationError, match="path traversal"):
                validator.validate_filename(filename)

    def test_validate_filename_invalid_format(self):
        """Invalid filename formats should raise error."""
        invalid_filenames = [
            "file.json",  # No timestamp
            "2024-01-01.json",  # Missing time
            "2024-01-01_12-00.json",  # Incomplete time
            "2024-01-01_12-00-00.txt",  # Wrong extension
            "01-01-2024_12-00-00.json",  # Wrong date format
        ]
        validator = InputValidator()
        for filename in invalid_filenames:
            with pytest.raises(UploadValidationError, match="Invalid filename format"):
                validator.validate_filename(filename)

    def test_validate_file_size_within_limit(self):
        """Files within size limit should pass."""
        validator = InputValidator()
        file_data = b"test data"
        max_size = 1024
        validator.validate_file_size(file_data, max_size)  # Should not raise

    def test_validate_file_size_exceeds_limit(self):
        """Files exceeding size limit should raise error."""
        validator = InputValidator()
        file_data = b"x" * (11 * 1024 * 1024)  # 11 MB
        max_size = 10 * 1024 * 1024  # 10 MB
        with pytest.raises(UploadValidationError, match="exceeds.*MB limit"):
            validator.validate_file_size(file_data, max_size)


class TestFileProcessor:
    """Test file processing logic."""

    def test_validate_checksum_valid(self):
        """Valid checksum should pass."""
        processor = FileProcessor()
        file_data = b"test data"
        expected_checksum = hashlib.sha256(file_data).hexdigest()
        processor.validate_checksum(file_data, expected_checksum)  # Should not raise

    def test_validate_checksum_case_insensitive(self):
        """Checksum validation should be case-insensitive."""
        processor = FileProcessor()
        file_data = b"test data"
        expected_checksum = hashlib.sha256(file_data).hexdigest()

        # Test uppercase
        processor.validate_checksum(file_data, expected_checksum.upper())
        # Test lowercase
        processor.validate_checksum(file_data, expected_checksum.lower())
        # Test mixed case
        processor.validate_checksum(file_data, expected_checksum[:20].upper() + expected_checksum[20:].lower())

    def test_validate_checksum_missing(self):
        """Missing checksum should raise error."""
        processor = FileProcessor()
        with pytest.raises(UploadValidationError, match="Missing checksum"):
            processor.validate_checksum(b"data", "")

    def test_validate_checksum_mismatch(self):
        """Mismatched checksum should raise error."""
        processor = FileProcessor()
        file_data = b"test data"
        wrong_checksum = "0" * 64
        with pytest.raises(UploadValidationError, match="Checksum validation failed"):
            processor.validate_checksum(file_data, wrong_checksum)

    def test_parse_json_data_valid(self):
        """Valid JSON should parse successfully."""
        processor = FileProcessor()
        json_str = json.dumps({"key": "value", "number": 123})
        file_data = json_str.encode('utf-8')

        result = processor.parse_json_data(file_data)
        assert result == {"key": "value", "number": 123}

    def test_parse_json_data_invalid(self):
        """Invalid JSON should raise error."""
        processor = FileProcessor()
        invalid_json = b"not json data {{"
        with pytest.raises(UploadValidationError, match="Invalid JSON"):
            processor.parse_json_data(invalid_json)

    def test_extract_sysinfo_complete(self):
        """Extract sysinfo with all fields present."""
        processor = FileProcessor()
        json_data = {
            "sysinfo": {
                "modemtype": "XB8",
                "modemmac": "AA:BB:CC:DD:EE:FF",
                "checktime": 1704110400  # Unix timestamp: 2024-01-01 12:00:00
            }
        }

        modem_type, modem_mac, check_time, check_time_str = processor.extract_sysinfo(json_data)

        assert modem_type == "XB8"
        assert modem_mac == "AA:BB:CC:DD:EE:FF"
        assert check_time is not None
        assert check_time_str is not None
        assert "2024-01-01" in check_time_str

    def test_extract_sysinfo_iso_timestamp(self):
        """Extract sysinfo with ISO timestamp string."""
        processor = FileProcessor()
        json_data = {
            "sysinfo": {
                "modemtype": "SB8200",
                "modemmac": "11:22:33:44:55:66",
                "checktime": "2024-01-01T12:00:00Z"
            }
        }

        modem_type, modem_mac, check_time, check_time_str = processor.extract_sysinfo(json_data)

        assert modem_type == "SB8200"
        assert modem_mac == "11:22:33:44:55:66"
        assert check_time is not None
        assert check_time_str == "2024-01-01T12:00:00Z"

    def test_extract_sysinfo_missing_fields(self):
        """Extract sysinfo with missing optional fields."""
        processor = FileProcessor()
        json_data = {"sysinfo": {}}

        modem_type, modem_mac, check_time, check_time_str = processor.extract_sysinfo(json_data)

        assert modem_type == "unknown"
        assert modem_mac == "unknown"
        assert check_time is None
        assert check_time_str is None

    def test_extract_sysinfo_no_sysinfo(self):
        """Extract sysinfo when sysinfo key missing."""
        processor = FileProcessor()
        json_data = {"other": "data"}

        modem_type, modem_mac, check_time, check_time_str = processor.extract_sysinfo(json_data)

        assert modem_type == "unknown"
        assert modem_mac == "unknown"


@pytest.mark.asyncio
class TestUploadPersistenceService:
    """Test database persistence logic."""

    async def test_save_modem_check_success(self):
        """Successfully save modem check to database."""
        # Mock database session
        mock_db = AsyncMock()
        mock_db.add = MagicMock()  # db.add() is synchronous in SQLAlchemy
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        service = UploadPersistenceService()
        json_data = {
            "sysinfo": {"modemtype": "XB8", "modemmac": "AA:BB:CC:DD:EE:FF"},
            "downstream": [{"frequency": 609000000}]
        }

        result = await service.save_modem_check(
            db=mock_db,
            modem_id="XB8-AA:BB:CC:DD:EE:FF",
            modem_type="XB8",
            check_time=datetime(2024, 1, 1, 12, 0, 0),
            filename="2024-01-01_12-00-00.json",
            json_data=json_data
        )

        # Verify database operations called
        assert mock_db.add.called
        assert mock_db.commit.called
        assert mock_db.refresh.called

    async def test_save_modem_check_duplicate(self):
        """Duplicate check should raise appropriate error."""
        # Mock database session that raises IntegrityError
        mock_db = AsyncMock()
        mock_db.add = MagicMock()  # db.add() is synchronous in SQLAlchemy
        mock_db.commit.side_effect = IntegrityError("", "", "unique constraint failed")
        mock_db.rollback = AsyncMock()

        service = UploadPersistenceService()
        json_data = {"sysinfo": {}}

        with pytest.raises(UploadValidationError) as exc_info:
            await service.save_modem_check(
                db=mock_db,
                modem_id="XB8-AA:BB:CC:DD:EE:FF",
                modem_type="XB8",
                check_time=utc_now(),
                filename="2024-01-01_12-00-00.json",
                json_data=json_data
            )

        assert exc_info.value.status_code == 409
        assert "already exists" in exc_info.value.message
        assert mock_db.rollback.called

    async def test_save_modem_check_database_error(self):
        """Database error should raise appropriate error."""
        # Mock database session that raises SQLAlchemyError
        # (the service now catches SQLAlchemyError specifically, not generic Exception)
        mock_db = AsyncMock()
        mock_db.add = MagicMock()  # db.add() is synchronous in SQLAlchemy
        mock_db.commit.side_effect = SQLAlchemyError("Database connection failed")
        mock_db.rollback = AsyncMock()

        service = UploadPersistenceService()
        json_data = {"sysinfo": {}}

        with pytest.raises(UploadValidationError) as exc_info:
            await service.save_modem_check(
                db=mock_db,
                modem_id="XB8-AA:BB:CC:DD:EE:FF",
                modem_type="XB8",
                check_time=utc_now(),
                filename="2024-01-01_12-00-00.json",
                json_data=json_data
            )

        assert exc_info.value.status_code == 500
        assert "Database error" in exc_info.value.message


@pytest.mark.asyncio
class TestUploadService:
    """Test integrated upload service workflow."""

    async def test_process_upload_success(self):
        """Complete upload workflow should succeed."""
        # Mock database session
        mock_db = AsyncMock()
        mock_db.add = MagicMock()  # db.add() is synchronous in SQLAlchemy
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        # Create valid upload data
        json_data = {
            "sysinfo": {
                "modemtype": "XB8",
                "modemmac": "AA:BB:CC:DD:EE:FF",
                "checktime": 1704110400
            }
        }
        file_data = json.dumps(json_data).encode('utf-8')
        checksum = hashlib.sha256(file_data).hexdigest()

        service = UploadService()
        result = await service.process_upload(
            modem_id="XB8-AA:BB:CC:DD:EE:FF",
            filename="2024-01-01_12-00-00.json",
            checksum=checksum,
            file_data=file_data,
            max_file_size=10 * 1024 * 1024,
            db=mock_db
        )

        saved_check, modem_type, modem_mac, filename, check_time_str = result

        assert modem_type == "XB8"
        assert modem_mac == "AA:BB:CC:DD:EE:FF"
        assert filename == "2024-01-01_12-00-00.json"
        assert check_time_str is not None

    async def test_process_upload_invalid_modem_id(self):
        """Invalid modem_id should fail validation."""
        mock_db = AsyncMock()
        service = UploadService()

        with pytest.raises(UploadValidationError, match="Invalid modem_id"):
            await service.process_upload(
                modem_id="invalid",
                filename="2024-01-01_12-00-00.json",
                checksum="abc123",
                file_data=b"data",
                max_file_size=1024,
                db=mock_db
            )

    async def test_process_upload_invalid_filename(self):
        """Invalid filename should fail validation."""
        mock_db = AsyncMock()
        service = UploadService()

        with pytest.raises(UploadValidationError, match="Invalid filename"):
            await service.process_upload(
                modem_id="XB8-AA:BB:CC:DD:EE:FF",
                filename="invalid.json",
                checksum="abc123",
                file_data=b"data",
                max_file_size=1024,
                db=mock_db
            )

    async def test_process_upload_file_too_large(self):
        """File exceeding size limit should fail."""
        mock_db = AsyncMock()
        service = UploadService()
        large_data = b"x" * (11 * 1024 * 1024)  # 11 MB

        with pytest.raises(UploadValidationError, match="exceeds.*MB"):
            await service.process_upload(
                modem_id="XB8-AA:BB:CC:DD:EE:FF",
                filename="2024-01-01_12-00-00.json",
                checksum="abc123",
                file_data=large_data,
                max_file_size=10 * 1024 * 1024,
                db=mock_db
            )

    async def test_process_upload_checksum_mismatch(self):
        """Mismatched checksum should fail validation."""
        mock_db = AsyncMock()
        service = UploadService()

        with pytest.raises(UploadValidationError, match="Checksum validation failed"):
            await service.process_upload(
                modem_id="XB8-AA:BB:CC:DD:EE:FF",
                filename="2024-01-01_12-00-00.json",
                checksum="0" * 64,
                file_data=b"test data",
                max_file_size=1024,
                db=mock_db
            )

    async def test_process_upload_invalid_json(self):
        """Invalid JSON should fail parsing."""
        mock_db = AsyncMock()
        service = UploadService()
        invalid_json = b"not valid json {{"
        checksum = hashlib.sha256(invalid_json).hexdigest()

        with pytest.raises(UploadValidationError, match="Invalid JSON"):
            await service.process_upload(
                modem_id="XB8-AA:BB:CC:DD:EE:FF",
                filename="2024-01-01_12-00-00.json",
                checksum=checksum,
                file_data=invalid_json,
                max_file_size=1024,
                db=mock_db
            )
