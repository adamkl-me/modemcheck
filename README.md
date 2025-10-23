# Modem-Check v2.1

Modem-Check is a Bash script designed to collect diagnostic data from supported modems, including system information, power levels, and event logs. It supports multiple modem models and outputs the collected data in JSON format for easy analysis.

## Features

- **Supported Modems**:
  - Hitron CODA56
  - Sercomm DM1000
- **Collected Data**:
  - System information (firmware version, uptime, system time)
  - RX and TX power levels
  - OFDM/OFDMA data (including subcarrier details for DM1000)
  - Event logs
- **Additional Functionality**:
  - Clears FEC counters
  - Logs all actions to a log file
  - Automatically detects modem model
  - Timestamped JSON output files for historical tracking

## Requirements

- Bash shell
- `curl` for HTTP requests
- `jq` for JSON processing
- A supported modem accessible at `http://192.168.100.1` (can be modified to a different IP/URL if desired)

## What's New in v2.1

- **Timestamped output files**: Check results are now saved with timestamps (e.g., `2025-10-23_14-30-45.json`) for better historical tracking
- **Enhanced DM1000 support**: TX OFDMA data now includes active/excluded/not-used subcarriers, minislots, and interface speed
- **Improved viewer**: `checkviewer.html` now handles missing fields gracefully and displays extended TX OFDMA information

## Usage

1. Run the script: `./modem-check.sh`
2. View results using `checkviewer.html` - simply open it in a browser and upload the JSON file

Check results are saved to: `ModemCheck-[MODEL]-[MAC]/[TIMESTAMP].json`
