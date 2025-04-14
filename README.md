# Modem-Check v2.0

Modem-Check v2.0 is a Bash script designed to collect diagnostic data from supported modems, including system information, power levels, and event logs. It supports multiple modem models and outputs the collected data in JSON format for easy analysis.

## Features

- **Supported Modems**:
  - Hitron CODA56
  - Sercomm DM1000
- **Collected Data**:
  - System information (firmware version, uptime, system time)
  - RX and TX power levels
  - OFDM data
  - Event logs
- **Additional Functionality**:
  - Clears FEC counters
  - Logs all actions to a log file
  - Automatically detects modem model

## Requirements

- Bash shell
- `curl` for HTTP requests
- `jq` for JSON processing
- A supported modem accessible at `http://192.168.100.1` (can modify this to a particular URL/different IP if desired)
