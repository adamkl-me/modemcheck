"""
Unit tests for shared timestamp validation functions.

Tests for:
- validate_request_timestamp (Unix epoch validation)
- validate_request_timestamp_datetime (datetime validation)
- TIMESTAMP_WINDOW_SECONDS constant consistency

These functions are used by:
- Upload endpoint (HMAC signature validation)
- Config sync endpoint (nonce + timestamp validation)
"""

import pytest
import time
from datetime import datetime, timedelta, timezone

from app.core.security import (
    validate_request_timestamp,
    validate_request_timestamp_datetime,
    TIMESTAMP_WINDOW_SECONDS
)


pytestmark = pytest.mark.unit


class TestTimestampWindowConstant:
    """Test TIMESTAMP_WINDOW_SECONDS constant."""

    def test_constant_value(self):
        """Timestamp window should be 5 minutes (300 seconds)."""
        assert TIMESTAMP_WINDOW_SECONDS == 300

    def test_constant_used_by_default(self):
        """Default window_seconds should use the constant."""
        # Test that the default argument uses the constant
        current_time = int(time.time())
        is_valid, _ = validate_request_timestamp(current_time)
        assert is_valid


class TestValidateRequestTimestamp:
    """Test Unix epoch timestamp validation."""

    def test_valid_current_timestamp(self):
        """Current timestamp should be valid."""
        current_time = int(time.time())
        is_valid, error = validate_request_timestamp(current_time)
        assert is_valid
        assert error == ""

    def test_valid_timestamp_as_string(self):
        """Timestamp as string should be parsed correctly."""
        current_time = str(int(time.time()))
        is_valid, error = validate_request_timestamp(current_time)
        assert is_valid
        assert error == ""

    def test_valid_within_window(self):
        """Timestamp within window should be valid."""
        # 4 minutes ago (within 5 minute window)
        past_time = int(time.time()) - 240
        is_valid, error = validate_request_timestamp(past_time)
        assert is_valid
        assert error == ""

        # 4 minutes in future (within 5 minute window)
        future_time = int(time.time()) + 240
        is_valid, error = validate_request_timestamp(future_time)
        assert is_valid
        assert error == ""

    def test_invalid_expired_timestamp(self):
        """Timestamp outside window should be invalid."""
        # 10 minutes ago (outside 5 minute window)
        old_time = int(time.time()) - 600
        is_valid, error = validate_request_timestamp(old_time)
        assert not is_valid
        assert "expired" in error.lower()
        assert "diff=" in error

    def test_invalid_future_timestamp(self):
        """Future timestamp outside window should be invalid."""
        # 10 minutes in future
        future_time = int(time.time()) + 600
        is_valid, error = validate_request_timestamp(future_time)
        assert not is_valid
        assert "expired" in error.lower()

    def test_invalid_timestamp_format(self):
        """Invalid timestamp format should return error."""
        is_valid, error = validate_request_timestamp("not-a-number")
        assert not is_valid
        assert "format" in error.lower()

    def test_empty_timestamp(self):
        """Empty string should return format error."""
        is_valid, error = validate_request_timestamp("")
        assert not is_valid
        assert "format" in error.lower()

    def test_custom_window(self):
        """Custom window_seconds should be respected."""
        # 2 minutes ago, with 1 minute window
        old_time = int(time.time()) - 120
        is_valid, error = validate_request_timestamp(old_time, window_seconds=60)
        assert not is_valid

        # Same timestamp with 3 minute window
        is_valid, error = validate_request_timestamp(old_time, window_seconds=180)
        assert is_valid

    def test_boundary_exact_window(self):
        """Timestamp exactly at window boundary should be valid."""
        # Exactly at the window boundary (use window - 1 to be safe)
        boundary_time = int(time.time()) - (TIMESTAMP_WINDOW_SECONDS - 1)
        is_valid, error = validate_request_timestamp(boundary_time)
        assert is_valid

    def test_boundary_past_window(self):
        """Timestamp just past window should be invalid."""
        # Just past the window boundary
        past_boundary = int(time.time()) - (TIMESTAMP_WINDOW_SECONDS + 1)
        is_valid, error = validate_request_timestamp(past_boundary)
        assert not is_valid


class TestValidateRequestTimestampDatetime:
    """Test datetime timestamp validation."""

    def test_valid_current_datetime(self):
        """Current datetime should be valid."""
        current_time = datetime.now(timezone.utc)
        is_valid, error, server_time = validate_request_timestamp_datetime(current_time)
        assert is_valid
        assert error == ""
        assert isinstance(server_time, datetime)

    def test_valid_within_window(self):
        """Datetime within window should be valid."""
        # 4 minutes ago
        past_time = datetime.now(timezone.utc) - timedelta(minutes=4)
        is_valid, error, _ = validate_request_timestamp_datetime(past_time)
        assert is_valid
        assert error == ""

    def test_invalid_clock_skew(self):
        """Datetime outside window should return clock skew error."""
        # 10 minutes ago
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        is_valid, error, server_time = validate_request_timestamp_datetime(old_time)
        assert not is_valid
        assert "clock skew" in error.lower()
        assert "diff=" in error

    def test_server_time_returned(self):
        """Server time should be returned for error reporting."""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        _, _, server_time = validate_request_timestamp_datetime(old_time)

        # Server time should be close to now (within 1 second)
        time_diff = abs((datetime.now(timezone.utc) - server_time).total_seconds())
        assert time_diff < 1

    def test_custom_window(self):
        """Custom window_seconds should be respected."""
        # 2 minutes ago, with 1 minute window
        old_time = datetime.now(timezone.utc) - timedelta(minutes=2)
        is_valid, _, _ = validate_request_timestamp_datetime(old_time, window_seconds=60)
        assert not is_valid

        # Same datetime with 3 minute window
        is_valid, _, _ = validate_request_timestamp_datetime(old_time, window_seconds=180)
        assert is_valid


class TestConsistencyBetweenFunctions:
    """Test consistency between Unix epoch and datetime validation."""

    def test_same_window_behavior(self):
        """Both functions should use the same default window."""
        # A timestamp 4 minutes ago should be valid for both
        past_seconds = 240

        unix_time = int(time.time()) - past_seconds
        is_valid_unix, _ = validate_request_timestamp(unix_time)

        dt_time = datetime.now(timezone.utc) - timedelta(seconds=past_seconds)
        is_valid_dt, _, _ = validate_request_timestamp_datetime(dt_time)

        assert is_valid_unix == is_valid_dt

    def test_same_rejection_behavior(self):
        """Both functions should reject the same out-of-window timestamps."""
        # A timestamp 10 minutes ago should be invalid for both
        past_seconds = 600

        unix_time = int(time.time()) - past_seconds
        is_valid_unix, _ = validate_request_timestamp(unix_time)

        dt_time = datetime.now(timezone.utc) - timedelta(seconds=past_seconds)
        is_valid_dt, _, _ = validate_request_timestamp_datetime(dt_time)

        assert is_valid_unix == is_valid_dt == False
