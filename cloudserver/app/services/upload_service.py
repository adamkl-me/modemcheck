"""
Upload service layer for processing modem check uploads.

This module extracts business logic from the upload router into testable,
reusable service functions that can be unit tested independently.
"""
import re
import json
import hashlib
import secrets
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ModemCheck
from app.core.metric_extraction import extract_metrics


class UploadValidationError(Exception):
    """Raised when upload validation fails."""
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class InputValidator:
    """Validates upload input formats and constraints."""

    @staticmethod
    def validate_modem_id(modem_id: str) -> None:
        """
        Validate modem_id format: MODEL-MACADDRESS.

        Examples:
        - XB8-AA:BB:CC:DD:EE:FF
        - SB8200-00:11:22:33:44:55

        Args:
            modem_id: Modem identifier string

        Raises:
            UploadValidationError: If format is invalid
        """
        if not modem_id:
            raise UploadValidationError("Missing modem_id")

        # Length limit to prevent database issues
        if len(modem_id) > 64:
            raise UploadValidationError("modem_id too long (max 64 characters)")

        # Model can be alphanumeric with underscores, MAC address uses hex digits and colons
        if not re.match(r'^[a-zA-Z0-9_]+-[A-Fa-f0-9:]+$', modem_id):
            raise UploadValidationError(
                "Invalid modem_id format (expected: MODEL-MACADDRESS)"
            )

    @staticmethod
    def validate_filename(filename: str) -> None:
        """
        Validate filename format for timestamps.

        Valid formats:
        - 2024-01-01_12-00-00.json
        - 2024-01-01_12-00-00_123.json (with UUID suffix)
        - 2024-01-01_12-00-00_a1b2c3d4.json

        Args:
            filename: Upload filename

        Raises:
            UploadValidationError: If format is invalid or contains path traversal
        """
        if not filename:
            raise UploadValidationError("Missing filename")

        # Security: Prevent path traversal attacks
        if '..' in filename or '/' in filename or '\\' in filename:
            raise UploadValidationError(
                "Invalid filename format (path traversal attempt detected)"
            )

        # Validate timestamp format with optional UUID suffix
        if not re.match(r'^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(_[a-zA-Z0-9]+)?\.json$', filename):
            raise UploadValidationError("Invalid filename format")

    @staticmethod
    def validate_file_size(file_data: bytes, max_size: int) -> None:
        """
        Validate uploaded file size is within limits.

        Args:
            file_data: File content as bytes
            max_size: Maximum allowed size in bytes

        Raises:
            UploadValidationError: If file exceeds size limit
        """
        if len(file_data) > max_size:
            max_mb = max_size // (1024 * 1024)
            raise UploadValidationError(
                f"File size exceeds {max_mb}MB limit",
                status_code=413
            )


class FileProcessor:
    """Processes uploaded file data."""

    @staticmethod
    def validate_checksum(file_data: bytes, expected_checksum: str) -> None:
        """
        Validate file checksum matches expected SHA-256 hash.

        Args:
            file_data: File content as bytes
            expected_checksum: Expected SHA-256 hex digest

        Raises:
            UploadValidationError: If checksum doesn't match or is missing
        """
        if not expected_checksum:
            raise UploadValidationError(
                "Missing checksum field (upgrade client to v6.0.0+)"
            )

        server_checksum = hashlib.sha256(file_data).hexdigest()
        if not secrets.compare_digest(expected_checksum.lower(), server_checksum.lower()):
            raise UploadValidationError("Checksum validation failed")

    @staticmethod
    def parse_json_data(file_data: bytes) -> Dict[str, Any]:
        """
        Parse JSON data from file bytes.

        Args:
            file_data: File content as bytes

        Returns:
            Parsed JSON data as dictionary

        Raises:
            UploadValidationError: If JSON parsing fails
        """
        try:
            return json.loads(file_data.decode('utf-8'))
        except Exception as e:
            raise UploadValidationError(f"Invalid JSON data: {str(e)}")

    @staticmethod
    def extract_sysinfo(json_data: Dict[str, Any]) -> Tuple[str, str, Optional[datetime], Optional[str]]:
        """
        Extract system information from JSON data.

        Args:
            json_data: Parsed JSON data

        Returns:
            Tuple of (modem_type, modem_mac, check_time, check_time_str)
        """
        sysinfo = json_data.get('sysinfo', {})
        modem_type = sysinfo.get('modemtype', 'unknown')
        modem_mac = sysinfo.get('modemmac', 'unknown')
        check_time_raw = sysinfo.get('checktime')

        # Parse check_time (handle both Unix timestamp and ISO string formats)
        check_time = None
        check_time_str = None
        if check_time_raw:
            try:
                # If it's a Unix timestamp (integer), convert to datetime and ISO string
                if isinstance(check_time_raw, int):
                    check_time = datetime.utcfromtimestamp(check_time_raw)
                    check_time_str = check_time.isoformat() + 'Z'
                else:
                    # If it's already an ISO string
                    check_time_str = str(check_time_raw)
                    check_time = datetime.fromisoformat(check_time_str.replace('Z', '+00:00'))
            except Exception:
                check_time = None
                check_time_str = None

        return modem_type, modem_mac, check_time, check_time_str


class UploadPersistenceService:
    """Handles database persistence for uploads."""

    @staticmethod
    async def save_modem_check(
        db: AsyncSession,
        modem_id: str,
        modem_type: str,
        check_time: Optional[datetime],
        filename: str,
        json_data: Dict[str, Any]
    ) -> ModemCheck:
        """
        Create and save ModemCheck to database.

        Args:
            db: Database session
            modem_id: Modem identifier (MODEL-MAC)
            modem_type: Type of modem
            check_time: Check timestamp
            filename: Original filename
            json_data: Full JSON data

        Returns:
            Saved ModemCheck instance

        Raises:
            UploadValidationError: If save fails (duplicate or database error)
        """
        # Extract metrics from JSON data for efficient querying
        extracted_metrics = extract_metrics(json_data)

        # Store with modem_id prefix
        db_filename = f"{modem_id}/{filename}"

        new_check = ModemCheck(
            modem_id=modem_id,
            modem_type=modem_type,
            check_time=check_time or datetime.utcnow(),
            filename=db_filename,
            full_data=json_data,
            created_at=datetime.utcnow(),
            # Extracted metrics for efficient querying
            **extracted_metrics
        )

        try:
            db.add(new_check)
            await db.commit()
            await db.refresh(new_check)
            return new_check
        except Exception as e:
            await db.rollback()
            # Check if duplicate
            if "unique constraint" in str(e).lower() or "duplicate" in str(e).lower():
                raise UploadValidationError("Check already exists", status_code=409)
            else:
                raise UploadValidationError("Database error", status_code=500)


class UploadService:
    """
    High-level upload service orchestrating the upload workflow.

    This service coordinates validation, file processing, and persistence
    for modem check uploads.
    """

    def __init__(self):
        self.input_validator = InputValidator()
        self.file_processor = FileProcessor()
        self.persistence_service = UploadPersistenceService()

    async def process_upload(
        self,
        modem_id: str,
        filename: str,
        checksum: str,
        file_data: bytes,
        max_file_size: int,
        db: AsyncSession
    ) -> Tuple[ModemCheck, str, str, str, Optional[str]]:
        """
        Process complete upload workflow.

        Steps:
        1. Validate input formats (modem_id, filename)
        2. Validate file size
        3. Validate checksum
        4. Parse JSON data
        5. Extract system info
        6. Save to database

        Args:
            modem_id: Modem identifier
            filename: Upload filename
            checksum: Expected SHA-256 checksum
            file_data: File content as bytes
            max_file_size: Maximum allowed file size
            db: Database session

        Returns:
            Tuple of (saved_check, modem_type, modem_mac, filename, check_time_str)

        Raises:
            UploadValidationError: If any validation or processing step fails
        """
        # Step 1: Validate inputs
        self.input_validator.validate_modem_id(modem_id)
        self.input_validator.validate_filename(filename)

        # Step 2: Validate file size
        self.input_validator.validate_file_size(file_data, max_file_size)

        # Step 3: Validate checksum
        self.file_processor.validate_checksum(file_data, checksum)

        # Step 4: Parse JSON
        json_data = self.file_processor.parse_json_data(file_data)

        # Step 5: Extract system info
        modem_type, modem_mac, check_time, check_time_str = self.file_processor.extract_sysinfo(json_data)

        # Step 6: Save to database
        saved_check = await self.persistence_service.save_modem_check(
            db=db,
            modem_id=modem_id,
            modem_type=modem_type,
            check_time=check_time,
            filename=filename,
            json_data=json_data
        )

        return saved_check, modem_type, modem_mac, filename, check_time_str
