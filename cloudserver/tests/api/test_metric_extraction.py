"""
Tests for metric extraction functionality.

Tests that modem check uploads properly extract individual metrics
from JSON data for efficient database querying.
"""
import pytest
from app.core.metric_extraction import extract_metrics, safe_float, safe_int


class TestSafeConversions:
    """Test safe type conversion functions."""

    def test_safe_float_valid(self):
        """Test safe_float with valid inputs."""
        assert safe_float(3.14) == 3.14
        assert safe_float("3.14") == 3.14
        assert safe_float(42) == 42.0
        assert safe_float("42") == 42.0

    def test_safe_float_invalid(self):
        """Test safe_float with invalid inputs."""
        assert safe_float(None) is None
        assert safe_float("") is None
        assert safe_float("invalid") is None
        assert safe_float([]) is None
        assert safe_float({}) is None

    def test_safe_int_valid(self):
        """Test safe_int with valid inputs."""
        assert safe_int(42) == 42
        assert safe_int("42") == 42
        assert safe_int(3.14) == 3
        assert safe_int("100") == 100

    def test_safe_int_invalid(self):
        """Test safe_int with invalid inputs."""
        assert safe_int(None) is None
        assert safe_int("") is None
        assert safe_int("invalid") is None
        assert safe_int([]) is None
        assert safe_int({}) is None


class TestMetricExtraction:
    """Test metric extraction from modem check JSON data."""

    def test_extract_system_info(self):
        """Test extraction of system information."""
        json_data = {
            "sysinfo": {
                "firmware": "v2.0.1",
                "uptime": 86400,
                "systemtime": "2025-01-17T12:00:00Z",
                "client_version": "6.0.0",
                "client_os": "linux",
                "client_arch": "amd64"
            }
        }

        metrics = extract_metrics(json_data)

        assert metrics["firmware"] == "v2.0.1"
        assert metrics["uptime_seconds"] == 86400
        assert metrics["system_time"] is not None
        assert metrics["client_version"] == "6.0.0"
        assert metrics["client_os"] == "linux"
        assert metrics["client_arch"] == "amd64"

    def test_extract_signal_quality(self):
        """Test extraction of signal quality metrics."""
        json_data = {
            "rx": [
                {"power": 5.0, "snr": 40.0, "correcteds": 100, "uncorrectables": 5},
                {"power": 4.5, "snr": 39.5, "correcteds": 150, "uncorrectables": 10},
                {"power": 5.5, "snr": 40.5, "correcteds": 120, "uncorrectables": 3}
            ],
            "tx": [
                {"power": 35.0},
                {"power": 36.0},
                {"power": 35.5}
            ]
        }

        metrics = extract_metrics(json_data)

        # Check averages
        assert metrics["avg_downstream_power"] == pytest.approx(5.0, rel=0.1)
        assert metrics["avg_downstream_snr"] == pytest.approx(40.0, rel=0.1)
        assert metrics["avg_upstream_power"] == pytest.approx(35.5, rel=0.1)

        # Check error totals
        assert metrics["total_corrected_errors"] == 370  # 100 + 150 + 120
        assert metrics["total_uncorrected_errors"] == 18  # 5 + 10 + 3

    def test_extract_speedtest_results(self):
        """Test extraction of speed test results."""
        json_data = {
            "speedtest": {
                "enabled": 1,
                "upload": "45.2 Mbps",
                "download": "950.5 Mbps",
                "server_name": "Comcast",
                "server_id": "12345",
                "latency": 12.5,
                "max_latency": 25.3,
                "jitter": 2.1,
                "packet_loss": 0.0,
                "download_latency": 15.2,
                "upload_jitter": 3.4
            }
        }

        metrics = extract_metrics(json_data)

        assert metrics["speedtest_enabled"] == 1
        assert metrics["iperf3_upload"] == "45.2 Mbps"
        assert metrics["iperf3_download"] == "950.5 Mbps"
        assert metrics["speedtest_server_name"] == "Comcast"
        assert metrics["speedtest_server_id"] == "12345"
        assert metrics["speedtest_latency"] == 12.5
        assert metrics["speedtest_max_latency"] == 25.3
        assert metrics["speedtest_jitter"] == 2.1
        assert metrics["speedtest_packet_loss"] == 0.0
        assert metrics["speedtest_dl_latency"] == 15.2
        assert metrics["speedtest_ul_jitter"] == 3.4

    def test_extract_ping_results(self):
        """Test extraction of ping test results."""
        json_data = {
            "ping_tests": {
                "google": {
                    "avg_latency": 15.2,
                    "packet_loss": 0.0,
                    "jitter": 2.3,
                    "max_latency": 25.1
                },
                "cloudflare": {
                    "avg_latency": 12.8,
                    "packet_loss": 0.5,
                    "jitter": 1.9,
                    "max_latency": 22.4
                }
            }
        }

        metrics = extract_metrics(json_data)

        # Google ping
        assert metrics["ping_google_avg"] == 15.2
        assert metrics["ping_google_loss"] == 0.0
        assert metrics["ping_google_jitter"] == 2.3
        assert metrics["ping_google_max_latency"] == 25.1

        # Cloudflare ping
        assert metrics["ping_cloudflare_avg"] == 12.8
        assert metrics["ping_cloudflare_loss"] == 0.5
        assert metrics["ping_cloudflare_jitter"] == 1.9
        assert metrics["ping_cloudflare_max_latency"] == 22.4

    def test_extract_network_info(self):
        """Test extraction of network information."""
        json_data = {
            "sysinfo": {
                "detection_status": "success",
                "public_ip": "1.2.3.4",
                "asn": "AS7922",
                "isp_name": "Comcast Cable",
                "ip_city": "Philadelphia",
                "ip_country": "US"
            }
        }

        metrics = extract_metrics(json_data)

        assert metrics["detection_status"] == "success"
        assert metrics["public_ip"] == "1.2.3.4"
        assert metrics["asn"] == "AS7922"
        assert metrics["isp_name"] == "Comcast Cable"
        assert metrics["ip_city"] == "Philadelphia"
        assert metrics["ip_country"] == "US"

    def test_extract_missing_data(self):
        """Test extraction handles missing data gracefully."""
        json_data = {
            "sysinfo": {}
        }

        metrics = extract_metrics(json_data)

        # Should return None for missing values, not crash
        assert metrics["firmware"] is None
        assert metrics["uptime_seconds"] is None
        assert metrics["avg_downstream_power"] is None
        assert metrics["speedtest_latency"] is None

    def test_extract_malformed_data(self):
        """Test extraction handles malformed data gracefully."""
        json_data = {
            "downstream": {
                "channels": "not-a-list"  # Should be a list
            },
            "speedtest": {
                "latency": "invalid-number"  # Should be a number
            }
        }

        metrics = extract_metrics(json_data)

        # Should handle gracefully without crashing
        assert metrics["avg_downstream_power"] is None
        assert metrics["speedtest_latency"] is None

    def test_extract_zero_errors(self):
        """Test that zero errors are not stored (only non-zero)."""
        json_data = {
            "downstream": {
                "channels": [
                    {"correcteds": 0, "uncorrectables": 0}
                ]
            }
        }

        metrics = extract_metrics(json_data)

        # Zero errors should result in None, not 0
        assert metrics["total_corrected_errors"] is None
        assert metrics["total_uncorrected_errors"] is None

    def test_extract_speedtest_disabled(self):
        """Test speedtest disabled states."""
        for disabled_value in [-1, -2, 0]:
            json_data = {
                "speedtest": {
                    "enabled": disabled_value
                }
            }

            metrics = extract_metrics(json_data)
            assert metrics["speedtest_enabled"] == 0

    def test_extract_complete_check(self):
        """Test extraction from a complete modem check."""
        json_data = {
            "sysinfo": {
                "modemtype": "XB8",
                "modemmac": "AA:BB:CC:DD:EE:FF",
                "checktime": 1705492800,
                "firmware": "v2.0.1",
                "uptime": 86400,
                "client_version": "6.0.0",
                "client_os": "linux",
                "client_arch": "amd64",
                "detection_status": "success",
                "public_ip": "1.2.3.4",
                "asn": "AS7922"
            },
            "rx": [
                {"power": 5.0, "snr": 40.0, "correcteds": 100, "uncorrectables": 5}
            ],
            "tx": [
                {"power": 35.0}
            ],
            "speedtest": {
                "enabled": 1,
                "latency": 12.5
            },
            "ping_tests": {
                "google": {"avg_latency": 15.2}
            }
        }

        metrics = extract_metrics(json_data)

        # Verify key metrics extracted
        assert metrics["firmware"] == "v2.0.1"
        assert metrics["avg_downstream_power"] == 5.0
        assert metrics["avg_upstream_power"] == 35.0
        assert metrics["speedtest_enabled"] == 1
        assert metrics["ping_google_avg"] == 15.2
        assert metrics["public_ip"] == "1.2.3.4"

    def test_extract_large_corrected_errors(self):
        """Corrected errors exceeding int32 max must be returned as-is (not truncated).

        Regression test: XB10 modem reported 2,992,944,594 correcteds, which exceeds
        the PostgreSQL INTEGER max of 2,147,483,647. Columns must be BIGINT.
        """
        INT32_MAX = 2_147_483_647
        large_value = 2_992_944_594  # Actual value seen from XB10 modem

        json_data = {
            "rx": [
                {
                    "portid": "20",
                    "power": "4.2",
                    "snr": "40.4",
                    "correcteds": str(large_value),
                    "uncorrectds": "1"
                }
            ]
        }

        metrics = extract_metrics(json_data)

        assert metrics["total_corrected_errors"] > INT32_MAX, (
            "total_corrected_errors must exceed int32 max to trigger the overflow bug"
        )
        assert metrics["total_corrected_errors"] == large_value
