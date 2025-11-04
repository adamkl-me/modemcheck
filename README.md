# Modem-Check v4.0

Modem-Check is a cross-platform tool designed to collect diagnostic data from supported cable modems, including system information, power levels, event logs, and speed test results. Built in Go for portability and ease of use, it outputs collected data in JSON format for analysis using the included `checkviewer.html`.

## Features

* **Cross-Platform**: Single binary runs on Windows, Linux, macOS, ARM devices - no external dependencies
* **Supported Modems**:
    * Hitron CODA45
    * Hitron CODA56
    * Sercomm DM1000
    * Rogers Xfinity Gateways (XB7/XB8 - requires credentials)
* **Collected Data**:
    * System information (firmware version, uptime, system time, MAC address)
    * RX/Downstream power levels & SNR (SC-QAM & OFDM/OFDMA)
    * TX/Upstream power levels (SC-QAM & OFDMA)
    * Codeword error counts (Corrected/Uncorrected)
    * Event logs (Not available on Xfinity modems)
    * iPerf3 speed test results (optional)
* **Additional Functionality**:
    * Automatic modem detection across common IP addresses
    * Optional logging to `modem-check_logs.txt`
    * Silent mode for automated/scripted execution
    * Clears modem FEC counters after data collection (where supported)
    * Saves timestamped JSON output files for historical tracking
    * Configurable bandwidth-limited iPerf3 speed tests

## What's New in v4.0

* **Complete Go Rewrite**: No dependencies on bash, curl, jq, or other external tools
* **Cross-Platform Support**: Native support for Windows, Linux, macOS, and ARM devices
* **CODA45 Support**: Added detection and support for Hitron CODA45 modems
* **Silent Mode**: `--silent` flag suppresses terminal output for automated execution
* **Disable Logging**: `--nologs` flag disables log file creation
* **Improved Parsing**: Enhanced HTML parsing for better compatibility with XB8 modems
* **Configuration Files**: Support for JSON configuration files
* **Flexible Deployment**: Single binary, easy distribution, no installation required

## Requirements

### Runtime
* **None** - The compiled Go binary is completely self-contained
* (Optional) `iperf3` if you want to run speed tests

### Build Time (only if compiling from source)
* Go 1.19 or later (download from https://go.dev)

## Installation

### Option 1: Download Pre-compiled Binary
Download the appropriate binary for your platform from the releases page and make it executable:

```bash
# Linux/macOS
chmod +x modem-check

# Windows - no setup needed, just run modem-check.exe
```

### Option 2: Build from Source

```bash
# Build for your current platform
go build -o modem-check modem-check.go

# Cross-compile for other platforms
GOOS=windows GOARCH=amd64 go build -o modem-check.exe modem-check.go
GOOS=linux GOARCH=amd64 go build -o modem-check-linux modem-check.go
GOOS=darwin GOARCH=arm64 go build -o modem-check-mac modem-check.go

# Build with optimizations for smaller size
go build -ldflags="-s -w" -o modem-check modem-check.go
```

## Configuration

### Command-Line Flags

```bash
# Basic usage with autodetect
./modem-check

# Specify modem address
./modem-check -address 192.168.100.1

# For Xfinity modems with password
./modem-check -password your_password

# Enable speed tests
./modem-check -iperf3 -iperf3-server your.server.ip

# Silent mode (no terminal output)
./modem-check --silent

# Disable log file creation
./modem-check --nologs

# All options
./modem-check \
  -address autodetect \
  -password password \
  -iperf3 \
  -iperf3-server your.server.ip \
  -iperf3-port 5201 \
  -iperf3-streams 4 \
  -iperf3-upload-limit 150 \
  -iperf3-download-limit 1500 \
  --silent \
  --nologs
```

### Configuration File

Create a `config.json` file (see `config.json.example`):

```json
{
  "ModemAddress": "autodetect",
  "IgnitePassword": "password",
  "Iperf3Enabled": false,
  "Iperf3Server": "your.server.ip",
  "Iperf3Port": 5201,
  "Iperf3Streams": 4,
  "Iperf3UploadLimit": 150,
  "Iperf3DownloadLimit": 1500,
  "Silent": false,
  "NoLogs": false
}
```

Then run:
```bash
./modem-check -config config.json
```

### Available Flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `-address` | string | autodetect | Modem IP address or 'autodetect' |
| `-password` | string | password | Password for Rogers Xfinity modems |
| `-iperf3` | bool | false | Enable iPerf3 speed tests |
| `-iperf3-server` | string | fillme | iPerf3 server address |
| `-iperf3-port` | int | 5201 | iPerf3 server port |
| `-iperf3-streams` | int | 4 | Number of parallel iPerf3 streams |
| `-iperf3-upload-limit` | int | 150 | Upload bandwidth limit (Mbps) |
| `-iperf3-download-limit` | int | 1500 | Download bandwidth limit (Mbps) |
| `--silent` | bool | false | Suppress output to terminal |
| `--nologs` | bool | false | Disable log file creation |
| `-config` | string | | Path to JSON configuration file |

## Usage

### Basic Examples

```bash
# Automatic detection with default settings
./modem-check

# Specify modem IP manually
./modem-check -address 192.168.100.1

# Xfinity modem with password
./modem-check -address 172.20.0.1 -password mypassword

# Run with speed tests enabled
./modem-check -iperf3 -iperf3-server 192.168.1.100

# Silent execution (for cron jobs)
./modem-check --silent --nologs
```

### View Results

1. Open `checkviewer.html` in a web browser
2. **Single View Mode**: Upload one JSON file to view detailed diagnostics
3. **Trends Mode**: Upload multiple JSON files to visualize trends over time with interactive charts
4. Navigate through historical checks using the timeline controls
5. JSON files are saved in `ModemCheck-[MODEL]-[MAC]/[TIMESTAMP].json`

## How It Works

1. **Detection**: Automatically detects your modem model by checking common IP addresses
2. **Authentication**: Logs into the modem using model-specific methods
3. **Data Collection**: Retrieves diagnostic data from modem's web interface
4. **Speed Testing**: (Optional) Runs bandwidth-limited iPerf3 tests
5. **FEC Reset**: Clears Forward Error Correction counters for next check
6. **Output**: Saves comprehensive JSON file with all collected data

## Troubleshooting

### General Issues

* **Modem not detected**: Manually specify the IP address with `-address 192.168.100.1`
* **Xfinity login fails**: Verify password is correct with `-password your_actual_password`
* **Permission denied**: Make sure the binary is executable (`chmod +x modem-check`)

### Speed Test Issues

* **iperf3: command not found**: Install iperf3 for your platform:
  ```bash
  # Ubuntu/Debian
  sudo apt install iperf3
  
  # macOS
  brew install iperf3
  
  # Windows - download from https://iperf.fr/iperf-download.php
  ```

* **Speed tests timeout**: Check that your iperf3 server is accessible and adjust limits

### Platform-Specific

* **Windows**: Run from PowerShell or Command Prompt: `.\modem-check.exe`
* **Linux/macOS**: Ensure executable permission: `chmod +x modem-check`

## Output Data Structure

The generated JSON includes:
- `sysinfo`: Firmware, uptime, timestamps
- `rx`: Downstream SC-QAM channel data
- `rxofdm`: Downstream OFDM channel data
- `tx`: Upstream SC-QAM channel data
- `txofdm`: Upstream OFDMA channel data
- `eventlog`: Modem event history
- `iperf3test_ul`/`iperf3test_dl`: Speed test results
- `iperf3uploadlimit`/`iperf3downloadlimit`: Test configuration

## Enhanced Viewer Features

The included `checkviewer.html` provides:

* **Dual-Mode Interface**:
  - Single View: Detailed diagnostics with timeline navigation
  - Trends View: Interactive Chart.js visualizations for historical analysis
* **Multi-File Upload**: Drag and drop multiple JSON files for trend analysis
* **Visual Tracking**: Power levels, SNR, error rates, and channel bonding over time
* **Responsive Design**: Works on desktop and mobile browsers

## Automated Execution

### Linux/macOS Cron Job

```bash
# Edit crontab
crontab -e

# Run every hour
0 * * * * /path/to/modem-check --silent --nologs

# Run every 15 minutes
*/15 * * * * /path/to/modem-check --silent --nologs
```

### Windows Task Scheduler

1. Open Task Scheduler
2. Create Basic Task
3. Set trigger (e.g., hourly)
4. Action: Start a program
5. Program: `C:\path\to\modem-check.exe`
6. Arguments: `--silent --nologs`

## License

This project is provided as-is for personal and educational use.