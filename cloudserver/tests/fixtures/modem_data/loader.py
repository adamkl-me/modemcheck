"""
Loader functions for real modem check test fixtures.

These fixtures contain anonymized real-world data from 3 modem types:
- XB8 (Technicolor/Xfinity): 25 checks
- DM1000 (Sercomm/Motorola): 25 checks
- CODA-56 (Hitron): 25 checks

PII has been scrubbed:
- MAC addresses → AA:BB:CC:xx:xx:xx
- Public IPs → 203.0.113.x (RFC 5737 TEST-NET-3)
- ISP names → "Test ISP Alpha/Beta/Gamma"
- ASN → AS64496-64498 (RFC 5398 documentation ASNs)
- City/Country → "Test City", "US"
"""

import json
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(__file__).parent


def load_modem_checks(modem_type: str) -> list[dict[str, Any]]:
    """Load all check files for a specific modem type.

    Args:
        modem_type: One of "xb8", "dm1000", "coda56"

    Returns:
        List of modem check dictionaries
    """
    modem_dir = FIXTURE_DIR / modem_type
    if not modem_dir.exists():
        raise ValueError(f"Unknown modem type: {modem_type}")

    checks = []
    for json_file in sorted(modem_dir.glob("check_*.json")):
        with open(json_file) as f:
            checks.append(json.load(f))

    return checks


def load_all_fixture_data() -> dict[str, list[dict[str, Any]]]:
    """Load all modem check fixtures.

    Returns:
        Dictionary with keys "xb8", "dm1000", "coda56" mapping to lists of checks
    """
    return {
        "xb8": load_modem_checks("xb8"),
        "dm1000": load_modem_checks("dm1000"),
        "coda56": load_modem_checks("coda56"),
    }


def get_modem_ids() -> dict[str, str]:
    """Get the anonymized modem IDs for each type.

    Returns:
        Dictionary mapping modem type to modem_id (type-MAC)
    """
    return {
        "xb8": "XB8-AABBCC010203",
        "dm1000": "DM1000-AABBCC040506",
        "coda56": "CODA56-AABBCC070809",
    }


def get_sample_check(modem_type: str, index: int = 0) -> dict[str, Any]:
    """Get a single sample check for testing.

    Args:
        modem_type: One of "xb8", "dm1000", "coda56"
        index: Which check to return (0-24)

    Returns:
        Single modem check dictionary
    """
    checks = load_modem_checks(modem_type)
    if index >= len(checks):
        raise IndexError(f"Index {index} out of range, only {len(checks)} checks available")
    return checks[index]
