# Modem-Check

[![Latest Release](https://img.shields.io/github/v/release/adamkl-me/modemcheck)](https://github.com/adamkl-me/modemcheck/releases/latest)
[![License](https://img.shields.io/badge/license-Personal%20%26%20Educational-blue.svg)](LICENSE)

Modem-Check is a cross-platform diagnostic tool for cable modems that collects system information, power levels, signal quality, error rates, event logs, and speed test results. Built in Go with native implementations for all diagnostics, it provides comprehensive modem monitoring with optional cloud integration for centralized management.

**[View Changelog & Release History →](https://github.com/adamkl-me/modemcheck/releases)**

## Table of Contents
- [Features](#features)
- [Recent Highlights](#recent-highlights)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Cloud Mode](#cloud-mode-optional)
- [Automated Execution](#automated-execution)
- [Troubleshooting](#troubleshooting)
- [Output Data Structure](#output-data-structure)
- [Security](#security)
- [Project Structure](#project-structure)
- [Contributing](#contributing)
- [License](#license)

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
    * Event logs (not available on Xfinity modems)
    * Ping test results (google.ca and one.one.one.one) - native Go implementation
    * Speed test results using public Ookla servers - native Go implementation (enabled by default)
    * Public IP and network information (IP address, ASN, ISP name, geolocation)
* **Additional Functionality**:
    * Automatic modem detection across common IP addresses
    * Failed detection tracking - records checks even when modem detection fails (using last successful modem info)
    * Upload queue with automatic retry for failed cloud uploads
    * Optional logging to `modem-check_logs.txt` with automatic cleanup (30 days)
    * Silent mode for automated/scripted execution
    * Clears modem FEC counters after data collection (where supported)
    * Saves timestamped JSON output files for historical tracking
    * No external dependencies - all diagnostics use native Go libraries

## Recent Highlights

* **Network Information Tracking**: Automatically detects and records public IP, ASN, ISP name, and geolocation for each check
* **Failed Detection Handling**: Records checks even when modem detection fails, maintaining continuity with last successful modem info
* **Speed Test Interval Control**: Run speed tests every N runs instead of every time, with automatic retry on failures
* **Local File Cleanup**: Automatic removal of old JSON files with configurable retention (default: 90 days)
* **Data Management API**: Bulk upload/download of modem check data with filtering and ZIP export
* **Self-Updating Binary**: Automatically checks GitHub for updates and applies them with zero user interaction
* **Enhanced RBAC**: Three-tier role system (basic/elevated/admin) with granular permissions
* **Multi-Architecture Support**: Runs on x64, ARM, ARM64, MIPS devices including routers and embedded systems
* **Config Generator**: Point-and-click interface for creating config.json files with live preview and defaults management
* **Native Diagnostics**: All speed tests and ping operations use native Go libraries - no external dependencies



## Requirements

### Runtime
* **None** - The compiled Go binary is completely self-contained with no external dependencies
* All diagnostics (ping, speed test) use native Go implementations

### Build Time (only if compiling from source)
* Go 1.24 or later (download from https://go.dev)

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
# Build for your current platform (with version injection)
make build

# Cross-compile for all platforms
make cross-compile

# Or build manually (replace VERSION with actual version)
cd modemcheck-client
go build -ldflags "-X main.Version=VERSION" -o ../modem-check .
```

## Configuration

### Configuration File

Create a `config.json` file using the Admin Dashboard Config Generator (recommended), or create it manually:

```json
{
  "ModemAddress": "autodetect",
  "IgnitePassword": "password",
  "SpeedTestEnabled": true,
  "AutoUpdateEnabled": true,
  "Silent": false,
  "NoLogs": false,
  "EnableCloud": true,
  "CloudHost": "your.cloud.server",
  "CloudPort": "22557",
  "CloudAPIKey": "your-api-key-here"
}
```

Then run: `./modem-check -config config.json`

See "Cloud Mode" section below for API key generation.

### Command-Line Flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `-address` | string | autodetect | Modem IP address or 'autodetect' |
| `-xfinitypassword` | string | password | Password for Rogers Xfinity modems |
| `-speedtest` | bool | true | Enable native Go speed tests using Ookla servers |
| `-noupdate` | bool | false | Disable automatic updates (default: false, updates enabled) |
| `-silent` | bool | false | Suppress output to terminal |
| `-nologs` | bool | false | Disable log file creation |
| `-config` | string | | Path to JSON configuration file |
| `-enablecloud` | bool | false | Enable cloud upload (requires config file) |

## Usage

### Basic Examples

```bash
# Automatic detection with default settings (auto-update & speed tests enabled)
./modem-check

# Disable automatic updates
./modem-check -noupdate

# Specify modem IP manually
./modem-check -address 192.168.100.1

# Xfinity modem with password
./modem-check -address 10.0.0.1 -xfinitypassword mypassword

# Run without speed tests
./modem-check -speedtest=false

# Silent execution (for cron jobs, disable updates to avoid mid-run changes)
./modem-check -silent -nologs -noupdate

# Use configuration file
./modem-check -config ~/modem-configs/xb8.json
```

### View Results

**Local Viewer** (`checkviewer.html`):
- **Single View Mode**: Upload one JSON file for detailed diagnostics with timeline navigation
- **Trends Mode**: Upload multiple files for historical visualization with interactive Chart.js charts
- Drag and drop multiple JSON files for trend analysis
- Results stored in: `ModemCheck-Results/[MODEL]-[MAC]/[TIMESTAMP].json`

**Cloud Viewer** (port 23890):
- 14-day default date range with automatic loading
- Multi-modem support with searchable selection
- Historical trend analysis and visual tracking
- Session-based authentication
- Config Generator and Data Management tools (admin/elevated users)

For complete cloud features, see [cloudserver/README.md](cloudserver/README.md)

## Cloud Mode (Optional)

Modem-Check can upload results to a self-hosted cloud server for centralized storage and web-based viewing.

### Quick Setup

```bash
cd cloudserver
docker volume create modemcheck-cloud_db
docker volume create modemcheck-cloud_config
docker compose up -d
```

**Access Points:**
- Web Viewer: `http://localhost:23890`
- Admin Dashboard: `http://localhost:23891`
- Upload API: Port 22557 (HTTPS)

**Create API Key:**
1. Open admin dashboard: `http://localhost:23891`
2. Login with: `admin` / `changeme` (change on first login)
3. Navigate to "API Keys" tab → Create new key
4. Or use "Config Generator" tab for complete config.json generation

**Enable Cloud Upload:**

Add to your `config.json`:
```json
{
  "EnableCloud": true,
  "CloudHost": "your.cloud.server",
  "CloudPort": "22557",
  "CloudAPIKey": "your-api-key-here"
}
```

**Key Features:** Centralized storage, multi-modem support, role-based access control, config generator, data management tools (bulk upload/download/delete), audit logging, and automatic retry for failed uploads.

**For complete documentation, see [cloudserver/README.md](cloudserver/README.md)**

## How It Works

1. **Detection & Authentication**: Automatically detects modem model and authenticates using model-specific methods
2. **Data Collection**: Retrieves diagnostics, runs concurrent ping tests (Google, Cloudflare), and optional speed tests
3. **Storage**: Saves JSON locally and uploads to cloud (if enabled) with automatic retry for failures
4. **Cleanup**: Purges old log entries (30+ days) and failed upload queue entries (14+ days)

## Troubleshooting

**Modem Detection**
- Issue: Modem not detected
- Solution: Specify IP with `-address 192.168.100.1`

**Authentication**
- Issue: Xfinity login fails
- Solution: Verify password with `-xfinitypassword your_password`

**Permissions**
- Issue: Permission denied
- Solution: Run `chmod +x modem-check` (Linux/macOS)

**Cloud Upload**
- Issue: Upload fails
- Solution: Verify API key and check `.upload_queue.json` for retry status

**Speed Tests**
- Issue: Speed tests are slow or fail
- Solution: Use `-speedtest=false` to disable, or check firewall/internet connection

**Platform-Specific**
- Windows: Run `.\modem-check.exe` from PowerShell/Command Prompt
- Linux/macOS: Ensure executable: `chmod +x modem-check`

For cloud-specific issues, see [cloudserver/README.md](cloudserver/README.md)

## Output Data Structure

Generated JSON files include:

**System Info**: Firmware, uptime, timestamps, modem type, MAC address
**Downstream Data**: SC-QAM and OFDM channels (power, SNR, errors)
**Upstream Data**: SC-QAM and OFDMA channels (power levels)
**Network Tests**: Ping results (Google, Cloudflare with avg/max/jitter/loss), speed test data (download, upload, latency, server info)
**Event Logs**: Modem event history (not available on Xfinity modems)
**Client Info**: Version, OS, architecture

Files saved to: `ModemCheck-Results/[MODEL]-[MAC]/[TIMESTAMP].json`
Example: `ModemCheck-Results/XB8-AABBCCDDEEFF/2025-11-05_14-30-00.json`

## Security

**Authentication:**
- API keys: 32-byte cryptographically random tokens
- Passwords: PBKDF2-HMAC-SHA256 with 100,000 iterations
- Sessions: HttpOnly, SameSite=Strict cookies (7-day expiry)

**Network:**
- HTTPS enforcement for public deployments
- Security headers enabled

**Input Validation:**
- Path traversal protection
- File size limits (10MB)
- Sanitized error messages

For deployment security details, see [cloudserver/README.md](cloudserver/README.md)

## Automated Execution

### Linux/macOS Cron Job

```bash
# Edit crontab
crontab -e

# Run every hour
0 * * * * /path/to/modem-check --silent --nologs --noupdate

# Run every 15 minutes
*/15 * * * * /path/to/modem-check --silent --nologs --noupdate

# Run with config file
0 * * * * /path/to/modem-check -config /path/to/config.json --silent --noupdate
```

### Windows Task Scheduler

1. Open Task Scheduler
2. Create Basic Task
3. Set trigger (e.g., hourly)
4. Action: Start a program
5. Program: `C:\path\to\modem-check.exe`
6. Arguments: `--silent --nologs --noupdate` or `-config C:\path\to\config.json --silent --noupdate`

## Project Structure

```
modemcheck/
├── Makefile                    # Build automation
├── README.md                   # This file
├── checkviewer.html            # Local web viewer for JSON files
├── dist/                       # Pre-compiled binaries (multiple platforms)
├── modemcheck-client/          # Main application source code
│   ├── README.md               # Client architecture documentation
│   ├── main.go                 # Main entry point and orchestration
│   ├── config.go               # Configuration loading
│   ├── diagnostics.go          # Ping and speed test logic
│   ├── cloud_client.go         # Cloud upload with retry queue
│   ├── go.mod & go.sum         # Go module dependencies
│   └── scraper/                # Modem-specific scrapers
│       ├── scraper.go          # Common interface and utilities
│       ├── coda.go             # Hitron CODA45/56 implementation
│       ├── dm1000.go           # Sercomm DM1000 implementation
│       └── xfinity.go          # Rogers Xfinity XB7/XB8 implementation
├── ModemCheck-Results/         # Local data storage
│   └── [MODEL]-[MAC]/          # Per-modem directories
│       └── *.json              # Timestamped check results
├── tests/                      # Test suite
│   ├── README.md               # Testing documentation
│   ├── test_env_setup.sh       # Test environment orchestration
│   ├── test_cloud_api.py       # Python integration tests
│   └── init_test_data.py       # Test data initialization
└── cloudserver/                # Docker-based cloud server
    ├── Dockerfile              # Alpine-based container
    ├── docker-compose.yml      # Service definition
    ├── nginx.conf              # Web server configuration
    ├── admin.html              # Admin dashboard with Config Generator
    ├── admin-login.html        # Admin login page
    ├── login.html              # Viewer login page
    ├── db-viewer.html          # Cloud data viewer interface
    ├── db-viewer.js            # Data viewer JavaScript
    └── cgi-bin/                # Python CGI backend
        ├── upload.py           # Upload handler with direct DB insertion
        ├── db-api.py           # Database query API
        ├── auth.py             # Authentication and session management
        ├── admin-api.py        # Admin operations and role management
        ├── user-management.py  # User CRUD operations
        ├── db_schema.py        # Main database schema
        └── audit_schema.py     # Audit logging schema
```

## Contributing

Contributions are welcome! Please ensure:
- Code follows existing style and patterns
- Security best practices are maintained
- Documentation is updated for user-facing changes

## Third-Party Libraries & Credits

Modem-Check uses the following open-source libraries:

- **[speedtest-go](https://github.com/showwin/speedtest-go)** by ITO Shogo (MIT License)
  - Provides native Go speed testing using Ookla speedtest.net servers
  - Enables single-binary deployment without external iperf3 dependencies

- **[go-ping](https://github.com/go-ping/ping)** by Cameron Sparr and contributors (MIT License)
  - Provides ICMP ping functionality in pure Go
  - Enables cross-platform network latency testing

- **[google/uuid](https://github.com/google/uuid)** by Google Inc. (BSD-3-Clause License)
  - UUID generation library

- **golang.org/x packages** by The Go Authors (BSD-3-Clause License)
  - Official Go supplementary libraries (net, sync, sys)

Full license texts and detailed attribution information can be found in [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md).

Special thanks to **Ookla** for the speedtest.net infrastructure and to all the maintainers of these excellent open-source projects that make Modem-Check possible.

## License

This project is provided as-is for personal and educational use.

## Support

For issues, questions, or feature requests:
- See [cloudserver/README.md](cloudserver/README.md) for cloud deployment guidance
- Check the [GitHub Issues](https://github.com/adamkl-me/modemcheck/issues) page
