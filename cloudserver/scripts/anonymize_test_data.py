#!/usr/bin/env python3
"""
Anonymize modem check JSON files for safe inclusion in test fixtures.

Usage:
    python anonymize_test_data.py input_dir/ output_dir/ [--count N]

Example:
    python anonymize_test_data.py /path/to/TempData/XB8-xxx ../tests/fixtures/modem_data/xb8 --count 25
"""

import json
import os
import sys
import argparse
import random
from pathlib import Path
from typing import Any


# Anonymization mappings - use RFC 5737 TEST-NET-3 for IPs
ANON_MAP = {
    "xb8": {
        "modemmac": "AA:BB:CC:01:02:03",
        "public_ip": "203.0.113.10",
        "isp_name": "Test ISP Alpha",
        "asn": "AS64496",  # RFC 5398 documentation ASN
        "ip_city": "Test City",
        "ip_country": "US",
    },
    "dm1000": {
        "modemmac": "AA:BB:CC:04:05:06",
        "public_ip": "203.0.113.20",
        "isp_name": "Test ISP Beta",
        "asn": "AS64497",
        "ip_city": "Sample Town",
        "ip_country": "US",
    },
    "coda56": {
        "modemmac": "AA:BB:CC:07:08:09",
        "public_ip": "203.0.113.30",
        "isp_name": "Test ISP Gamma",
        "asn": "AS64498",
        "ip_city": "Example City",
        "ip_country": "US",
    },
}


def detect_modem_type(input_dir: str) -> str:
    """Detect modem type from directory name."""
    dir_name = os.path.basename(input_dir.rstrip("/")).lower()
    if "xb8" in dir_name:
        return "xb8"
    elif "dm1000" in dir_name:
        return "dm1000"
    elif "coda" in dir_name:
        return "coda56"
    else:
        # Try to detect from file content
        json_files = list(Path(input_dir).glob("*.json"))
        if json_files:
            with open(json_files[0]) as f:
                data = json.load(f)
                modem_type = data.get("sysinfo", {}).get("modemtype", "").lower()
                if "xb8" in modem_type:
                    return "xb8"
                elif "dm1000" in modem_type:
                    return "dm1000"
                elif "coda" in modem_type:
                    return "coda56"
    raise ValueError(f"Could not detect modem type from: {input_dir}")


def anonymize_check(data: dict[str, Any], modem_type: str) -> dict[str, Any]:
    """Anonymize a single modem check JSON."""
    anon = ANON_MAP[modem_type]

    # Deep copy to avoid modifying original
    result = json.loads(json.dumps(data))

    # Anonymize sysinfo fields
    if "sysinfo" in result:
        sysinfo = result["sysinfo"]
        if "modemmac" in sysinfo:
            # Store original format (with or without colons)
            original_mac = sysinfo["modemmac"]
            if ":" in original_mac:
                sysinfo["modemmac"] = anon["modemmac"]
            else:
                # Remove colons if original didn't have them
                sysinfo["modemmac"] = anon["modemmac"].replace(":", "")

    # Anonymize top-level network info fields
    for field in ["public_ip", "isp_name", "asn", "ip_city", "ip_country"]:
        if field in result:
            result[field] = anon[field]

    # Anonymize speedtest server name if present (may contain location info)
    if "speedtest_server_name" in result:
        result["speedtest_server_name"] = "Test Speedtest Server"

    return result


def select_diverse_files(json_files: list[Path], count: int) -> list[Path]:
    """Select files to get diverse time coverage."""
    if len(json_files) <= count:
        return json_files

    # Sort by filename (which contains timestamp)
    sorted_files = sorted(json_files, key=lambda p: p.name)

    # Select evenly spaced files to get time coverage
    step = len(sorted_files) / count
    selected = []
    for i in range(count):
        idx = int(i * step)
        selected.append(sorted_files[idx])

    return selected


def main():
    parser = argparse.ArgumentParser(description="Anonymize modem check data")
    parser.add_argument("input_dir", help="Input directory with JSON files")
    parser.add_argument("output_dir", help="Output directory for anonymized files")
    parser.add_argument("--count", type=int, default=25, help="Number of files to process (default: 25)")
    args = parser.parse_args()

    input_path = Path(args.input_dir)
    output_path = Path(args.output_dir)

    if not input_path.exists():
        print(f"Error: Input directory does not exist: {input_path}")
        sys.exit(1)

    # Detect modem type
    modem_type = detect_modem_type(str(input_path))
    print(f"Detected modem type: {modem_type}")

    # Find all JSON files
    json_files = list(input_path.glob("*.json"))
    print(f"Found {len(json_files)} JSON files")

    if not json_files:
        print("Error: No JSON files found")
        sys.exit(1)

    # Select diverse files
    selected = select_diverse_files(json_files, args.count)
    print(f"Selected {len(selected)} files for processing")

    # Create output directory
    output_path.mkdir(parents=True, exist_ok=True)

    # Process files
    processed = 0
    for i, json_file in enumerate(selected, 1):
        try:
            with open(json_file) as f:
                data = json.load(f)

            anonymized = anonymize_check(data, modem_type)

            # Use simple numbered filename
            output_file = output_path / f"check_{i:03d}.json"
            with open(output_file, "w") as f:
                json.dump(anonymized, f, indent=2)

            processed += 1

        except Exception as e:
            print(f"Warning: Failed to process {json_file.name}: {e}")

    print(f"Successfully anonymized {processed} files to {output_path}")


if __name__ == "__main__":
    main()
