"""
ZIP file security validation utilities.

Functions for safely handling ZIP file uploads with protection against:
- ZIP bombs (compression ratio attacks)
- Path traversal attacks
- Malformed ZIP files
- Invalid UTF-8 encoding
"""
import os
import zipfile
from io import BytesIO
from typing import Tuple, Optional


def validate_zip_file(content: bytes) -> Tuple[bool, str]:
    """
    Validate that content is a valid ZIP file.

    Args:
        content: Raw file bytes

    Returns:
        (is_valid, error_message): Tuple of validation result and error message
    """
    # Check for ZIP magic bytes (PK\x03\x04)
    if len(content) < 4:
        return False, "File too small to be a valid ZIP"

    if content[0:4] != b'PK\x03\x04':
        return False, "Invalid ZIP file format (missing magic bytes)"

    # Try to open as ZIP
    try:
        zip_buffer = BytesIO(content)
        with zipfile.ZipFile(zip_buffer, 'r') as zf:
            # Test ZIP integrity
            bad_file = zf.testzip()
            if bad_file is not None:
                return False, f"Corrupted ZIP file (bad file: {bad_file})"
    except zipfile.BadZipFile:
        return False, "Invalid or corrupted ZIP file"
    except Exception as e:
        return False, f"ZIP validation error: {str(e)}"

    return True, ""


def check_zip_bomb(
    zip_buffer: BytesIO,
    max_ratio: float = 100.0,
    max_uncompressed_size: int = 100 * 1024 * 1024  # 100MB
) -> Tuple[bool, str]:
    """
    Check for ZIP bomb attacks based on compression ratio and total size.

    Args:
        zip_buffer: BytesIO object containing ZIP data
        max_ratio: Maximum allowed compression ratio (default 100:1)
        max_uncompressed_size: Maximum total uncompressed size in bytes (default 100MB)

    Returns:
        (is_safe, error_message): Tuple of safety check result and error message
    """
    try:
        with zipfile.ZipFile(zip_buffer, 'r') as zf:
            total_compressed = 0
            total_uncompressed = 0

            for file_info in zf.infolist():
                # Skip directories
                if file_info.is_dir():
                    continue

                total_compressed += file_info.compress_size
                total_uncompressed += file_info.file_size

            # Check total uncompressed size
            if total_uncompressed > max_uncompressed_size:
                return False, f"ZIP file too large when uncompressed ({total_uncompressed} bytes, max {max_uncompressed_size})"

            # Check compression ratio (avoid division by zero)
            if total_compressed > 0:
                ratio = total_uncompressed / total_compressed
                if ratio > max_ratio:
                    return False, f"Suspicious compression ratio ({ratio:.1f}:1, max {max_ratio}:1) - possible ZIP bomb"

    except Exception as e:
        return False, f"ZIP bomb check error: {str(e)}"

    return True, ""


def sanitize_zip_path(path: str) -> Optional[str]:
    """
    Sanitize and validate ZIP file entry paths to prevent path traversal.

    Uses os.path.normpath to properly handle encoded sequences, multiple
    dots, and other edge cases that string matching might miss.

    Args:
        path: Path from ZIP file entry

    Returns:
        Sanitized path if safe, None if unsafe
    """
    if not path:
        return None

    # Block paths with .. BEFORE normalization (prevents traversal attacks)
    # os.path.normpath would resolve these, but we want to reject them entirely
    if '..' in path:
        return None

    # Block paths starting with backslash (Windows absolute/UNC)
    if path.startswith('\\'):
        return None

    # Block Windows drive letters (e.g., "C:\path")
    if len(path) >= 2 and path[1] == ':' and path[0].isalpha():
        return None

    # Remove leading slashes (convert absolute to relative)
    while path.startswith('/'):
        path = path[1:]

    # Normalize the path (resolves ., multiple slashes)
    normalized = os.path.normpath(path) if path else None

    # Empty path after sanitization
    if not normalized:
        return None

    # Final check: reject if normalization resulted in parent traversal
    if normalized.startswith('..'):
        return None

    return normalized


def validate_utf8(content: bytes) -> bool:
    """
    Validate that content is valid UTF-8 encoded text.

    Args:
        content: Raw bytes to validate

    Returns:
        True if valid UTF-8, False otherwise
    """
    try:
        content.decode('utf-8')
        return True
    except (UnicodeDecodeError, AttributeError):
        return False
