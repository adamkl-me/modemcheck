"""
Unit tests for ZIP file security validation.

These tests cover:
- ZIP file validation
- ZIP bomb detection
- Path traversal protection
- UTF-8 encoding validation
"""
import zipfile
from io import BytesIO
import pytest

from app.core.zip_security import (
    validate_zip_file,
    check_zip_bomb,
    sanitize_zip_path,
    validate_utf8
)


class TestValidateZipFile:
    """Test ZIP file validation."""

    def test_valid_zip_file(self):
        """Valid ZIP file should pass validation."""
        # Create a valid ZIP file
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("test.txt", "Hello World")

        is_valid, error = validate_zip_file(zip_buffer.getvalue())
        assert is_valid is True
        assert error == ""

    def test_file_too_small(self):
        """File smaller than 4 bytes should fail."""
        is_valid, error = validate_zip_file(b"PK")
        assert is_valid is False
        assert "too small" in error

    def test_invalid_magic_bytes(self):
        """File without ZIP magic bytes should fail."""
        is_valid, error = validate_zip_file(b"NOT A ZIP FILE!")
        assert is_valid is False
        assert "magic bytes" in error

    def test_corrupted_zip_file(self):
        """Corrupted ZIP file should fail."""
        # Start with valid ZIP, then corrupt it
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("test.txt", "Hello")

        # Corrupt the middle of the file
        corrupted = bytearray(zip_buffer.getvalue())
        corrupted[len(corrupted) // 2] = 0xFF

        is_valid, error = validate_zip_file(bytes(corrupted))
        assert is_valid is False
        assert "Invalid" in error or "Corrupted" in error

    def test_empty_bytes(self):
        """Empty bytes should fail validation."""
        is_valid, error = validate_zip_file(b"")
        assert is_valid is False
        assert "too small" in error


class TestCheckZipBomb:
    """Test ZIP bomb detection."""

    def test_normal_zip_file(self):
        """Normal ZIP file should pass bomb check."""
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("test.txt", "Hello World" * 100)

        zip_buffer.seek(0)
        is_safe, error = check_zip_bomb(zip_buffer)
        assert is_safe is True
        assert error == ""

    def test_high_compression_ratio(self):
        """ZIP with compression ratio > 100:1 should be detected."""
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Create highly compressible content (all zeros)
            zf.writestr("zeros.txt", b"\x00" * 10_000_000)  # 10MB of zeros

        zip_buffer.seek(0)
        # Use strict limits to trigger detection
        is_safe, error = check_zip_bomb(zip_buffer, max_ratio=50.0, max_uncompressed_size=5_000_000)
        assert is_safe is False
        assert "compression ratio" in error or "too large" in error

    def test_exceeds_max_uncompressed_size(self):
        """ZIP exceeding max uncompressed size should be detected."""
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Create file that exceeds limit
            zf.writestr("large.txt", b"x" * 1_000_000)

        zip_buffer.seek(0)
        is_safe, error = check_zip_bomb(zip_buffer, max_uncompressed_size=500_000)
        assert is_safe is False
        assert "too large" in error

    def test_multiple_files(self):
        """ZIP with multiple files should aggregate sizes correctly."""
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("file1.txt", "x" * 300_000)
            zf.writestr("file2.txt", "y" * 300_000)
            zf.writestr("file3.txt", "z" * 300_000)

        zip_buffer.seek(0)
        # Total = 900KB, should exceed 500KB limit
        is_safe, error = check_zip_bomb(zip_buffer, max_uncompressed_size=500_000)
        assert is_safe is False
        assert "too large" in error

    def test_directory_entries_skipped(self):
        """Directory entries should not count toward size limits."""
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("dir/", "")  # Directory entry
            zf.writestr("dir/file.txt", "Hello")

        zip_buffer.seek(0)
        is_safe, error = check_zip_bomb(zip_buffer)
        assert is_safe is True
        assert error == ""

    def test_empty_zip(self):
        """Empty ZIP file should pass."""
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            pass  # No files

        zip_buffer.seek(0)
        is_safe, error = check_zip_bomb(zip_buffer)
        assert is_safe is True
        assert error == ""


class TestSanitizeZipPath:
    """Test path traversal protection."""

    def test_normal_path(self):
        """Normal relative path should be accepted."""
        assert sanitize_zip_path("dir/file.txt") == "dir/file.txt"
        assert sanitize_zip_path("file.txt") == "file.txt"
        assert sanitize_zip_path("a/b/c/file.txt") == "a/b/c/file.txt"

    def test_parent_directory_traversal(self):
        """Paths with .. should be rejected."""
        assert sanitize_zip_path("../file.txt") is None
        assert sanitize_zip_path("dir/../file.txt") is None
        assert sanitize_zip_path("../../etc/passwd") is None
        assert sanitize_zip_path("a/b/../../../file.txt") is None

    def test_absolute_path_unix(self):
        """Absolute Unix paths should be sanitized to relative."""
        assert sanitize_zip_path("/etc/passwd") == "etc/passwd"
        assert sanitize_zip_path("//absolute") == "absolute"
        assert sanitize_zip_path("/a/b/c") == "a/b/c"

    def test_absolute_path_windows(self):
        """Windows drive letters should be rejected."""
        assert sanitize_zip_path("C:\\Windows\\System32") is None
        assert sanitize_zip_path("D:\\file.txt") is None
        assert sanitize_zip_path("Z:\\") is None

    def test_windows_backslash_prefix(self):
        """Paths starting with backslash should be rejected."""
        assert sanitize_zip_path("\\Windows\\file.txt") is None
        assert sanitize_zip_path("\\\\network\\share") is None

    def test_colon_in_filename(self):
        """Colons in middle of filename (like MAC addresses) should be allowed."""
        # MAC address format
        assert sanitize_zip_path("modem-AA:BB:CC:DD:EE:FF/data.json") == "modem-AA:BB:CC:DD:EE:FF/data.json"
        # Time format
        assert sanitize_zip_path("backup-14:30:00.json") == "backup-14:30:00.json"

    def test_empty_path(self):
        """Empty path should be rejected."""
        assert sanitize_zip_path("") is None

    def test_only_slashes(self):
        """Path with only slashes should be rejected after sanitization."""
        assert sanitize_zip_path("/") is None
        assert sanitize_zip_path("///") is None

    def test_special_characters(self):
        """Paths with special characters should be handled correctly."""
        assert sanitize_zip_path("file name with spaces.txt") == "file name with spaces.txt"
        assert sanitize_zip_path("file-with-dashes.txt") == "file-with-dashes.txt"
        assert sanitize_zip_path("file_with_underscores.txt") == "file_with_underscores.txt"


class TestValidateUtf8:
    """Test UTF-8 encoding validation."""

    def test_valid_utf8_ascii(self):
        """ASCII text (valid UTF-8) should pass."""
        assert validate_utf8(b"Hello World") is True
        assert validate_utf8(b"123456789") is True
        assert validate_utf8(b"!@#$%^&*()") is True

    def test_valid_utf8_unicode(self):
        """Unicode characters should pass."""
        assert validate_utf8("Hello 世界".encode('utf-8')) is True
        assert validate_utf8("Café".encode('utf-8')) is True
        assert validate_utf8("🎉🎊".encode('utf-8')) is True

    def test_invalid_utf8_bytes(self):
        """Invalid UTF-8 byte sequences should fail."""
        # Invalid UTF-8 sequences
        assert validate_utf8(b'\xff\xfe') is False
        assert validate_utf8(b'\x80\x80') is False
        assert validate_utf8(b'\xc0\x80') is False  # Overlong encoding

    def test_latin1_not_utf8(self):
        """Latin-1 encoded text that isn't valid UTF-8 should fail."""
        # Latin-1 'é' (0xE9) is not valid UTF-8
        assert validate_utf8(b'\xe9') is False

    def test_empty_bytes(self):
        """Empty bytes should be valid UTF-8."""
        assert validate_utf8(b"") is True

    def test_mixed_content(self):
        """Mixed valid and invalid UTF-8 should fail."""
        valid = "Hello".encode('utf-8')
        invalid = b'\xff'
        assert validate_utf8(valid + invalid) is False


class TestZipSecurityIntegration:
    """Integration tests for combined ZIP security checks."""

    def test_realistic_modem_check_zip(self):
        """Test with realistic modem check ZIP structure."""
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Realistic modem check structure
            zf.writestr("XB8-AA:BB:CC:DD:EE:FF/2024-01-01_12-00-00.json", '{"sysinfo": {}}')
            zf.writestr("XB8-AA:BB:CC:DD:EE:FF/2024-01-01_13-00-00.json", '{"sysinfo": {}}')

        content = zip_buffer.getvalue()

        # Validate ZIP structure
        is_valid, error = validate_zip_file(content)
        assert is_valid is True

        # Check for ZIP bomb
        zip_buffer.seek(0)
        is_safe, error = check_zip_bomb(zip_buffer)
        assert is_safe is True

    def test_malicious_zip_with_path_traversal(self):
        """Test ZIP with malicious path traversal attempts."""
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            # Attempt path traversal
            zf.writestr("../../etc/passwd", "malicious")

        zip_buffer.seek(0)
        with zipfile.ZipFile(zip_buffer, 'r') as zf:
            for file_info in zf.infolist():
                sanitized = sanitize_zip_path(file_info.filename)
                # Should be rejected
                assert sanitized is None
