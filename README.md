# Modem-Check v4.5.0

Modem-Check is a cross-platform diagnostic tool for cable modems that collects system information, power levels, signal quality, error rates, event logs, and speed test results. Built in Go with native implementations for all diagnostics, it provides comprehensive modem monitoring with optional cloud integration for centralized management.

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
* **Additional Functionality**:
    * Automatic modem detection across common IP addresses
    * Upload queue with automatic retry for failed cloud uploads
    * Optional logging to `modem-check_logs.txt` with automatic cleanup (30 days)
    * Silent mode for automated/scripted execution
    * Clears modem FEC counters after data collection (where supported)
    * Saves timestamped JSON output files for historical tracking
    * No external dependencies - all diagnostics use native Go libraries

## What's New in v4.5.0

### Core Improvements
* **Modular Architecture**: Refactored from monolithic 1,946-line file to clean package structure
* **Native Speed Tests**: Replaced iperf3 with native Go speedtest library (no external dependencies)
* **Native Ping**: Uses go-ping library instead of exec.Command("ping")
* **Auto-detect config.json**: Automatically loads `config.json` from executable directory if present
* **Role Management**: Enhanced admin dashboard with role assignment (admin/basic)
* **Protected Admin Account**: Admin account cannot be deleted or downgraded
* **Database Migration**: User and API key storage migrated from JSON files to SQLite
* **BER Calculation Fixes**: Improved Bit Error Rate calculations for accuracy
* **Time-Based Charts**: Enhanced visualization with time-series data

### Previous Updates

#### v4.4.x - Performance & Quality
* **Code Quality**: Linter warnings fixed, improved performance optimizations
* **Timestamp Standardization**: Consistent timestamp handling across all components
* **Test Infrastructure**: Updated E2E tests for SQLite migration

#### v4.2.x - Security & Storage
* **SQLite Migration**: All storage moved to SQLite for better performance and reliability
* **XSS Protection**: Enhanced security headers and input sanitization
* **Timing-Safe Comparisons**: API key validation uses constant-time comparison
* **File Locking**: Prevents race conditions in concurrent operations

#### v4.1.x - Cross-Platform & Security
* **Windows Ping Support**: Fixed ping tests on Windows (uses `-n` flag)
* **Real IP Tracking**: Admin dashboard shows actual client IPs through Cloudflare tunnels
* **Path Traversal Protection**: Strict validation prevents malicious file path attacks
* **Forced Password Changes**: New users must change password on first login
* **Zero External Dependencies**: Uses only Go standard library
* **Upload Queue**: Failed uploads automatically retry on next run



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
# Build for your current platform
make

# Cross-compile for all platforms
make cross-compile

# Build with optimizations for smaller size
go build -ldflags="-s -w" -o modem-check modem-check.go
```

## Configuration

### Command-Line Flags

```bash
# Basic usage with autodetect (speed tests enabled by default)
./modem-check

# Specify modem address
./modem-check -address 192.168.100.1

# For Xfinity modems with password
./modem-check -xfinitypassword your_password

# Disable speed tests
./modem-check -speedtest=false

# Silent mode (no terminal output)
./modem-check -silent

# Disable log file creation
./modem-check -nologs

# With cloud upload
./modem-check -config config.json -enablecloud

# All options
./modem-check \
  -address autodetect \
  -xfinitypassword password \
  -speedtest=true \
  -silent \
  -nologs \
  -enablecloud
```

### Configuration File

Create a `config.json` file (see `config.json.example` for an example, or use the Admin Dashboard Config Generator):

```json
{
  "ModemAddress": "autodetect",
  "IgnitePassword": "password",
  "SpeedTestEnabled": true,
  "Silent": false,
  "NoLogs": false,
  "EnableCloud": true,
  "CloudHost": "your.cloud.server",
  "CloudPort": "22557",
  "CloudAPIKey": "your-api-key-here"
}
```

**Configuration Options:**
- `ModemAddress`: IP address or "autodetect" to scan common addresses
- `IgnitePassword`: Password for Rogers Xfinity/Ignite modems
- `SpeedTestEnabled`: Enable/disable speed tests using public Ookla servers (default: true)
- `Silent`: Suppress terminal output (default: false)
- `NoLogs`: Disable log file creation (default: false)
- `EnableCloud`: Upload results to cloud server (default: false)
- `CloudHost`: Cloud server hostname/IP
- `CloudPort`: Cloud server port (default: 443)
- `CloudAPIKey`: API key for cloud authentication

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
./modem-check -address 10.0.0.1 -password mypassword

# Run with speed tests enabled
./modem-check -iperf3 -iperf3-server your.iperf3.server

# Silent execution (for cron jobs)
./modem-check --silent --nologs

# Use configuration file
./modem-check -config ~/modem-configs/xb8.json
```

### View Results

#### Local Viewer
1. Open `checkviewer.html` in a web browser
2. **Single View Mode**: Upload one JSON file to view detailed diagnostics
3. **Trends Mode**: Upload multiple JSON files to visualize trends over time with interactive charts
4. Navigate through historical checks using the timeline controls
4. JSON files are saved in `ModemCheck-Results/[MODEL]-[MAC]/[TIMESTAMP].json`
   - Example: `ModemCheck-Results/XB8-AABBCCDDEEFF/2025-11-05_14-30-00.json`

#### Cloud Viewer
Access your cloud instance at your configured URL (e.g., `http://localhost:23890`) to view all uploaded data with:
- Automatic 14-day date range selection
- Multiple modem support
- Historical trend analysis
- Searchable modem selection

## Cloud Mode (Optional)

Modem-Check can upload results to a self-hosted cloud server for centralized storage and web-based viewing.

### Setup Cloud Server

See the `cloudserver/` directory for Docker-based cloud server setup:

```bash
cd cloudserver
# Create required volumes
docker volume create modemcheck-cloud_data
docker volume create modemcheck-cloud_config
# Start the server
docker compose up -d
```

The cloud server provides:
- **HTTPS API upload** on port 22557 with API key authentication
- **Web viewer** on port 23890 with session-based authentication
- **Admin dashboard** on port 23891 (local network only) for managing API keys and users
- **Centralized storage** of all modem check results
- **Multi-modem support** with date range filtering
- **Automatic retry** for failed uploads

For detailed setup instructions, see `cloudserver/README.md`.

### Generate an API Key

1. Open the admin dashboard in your browser: `http://localhost:23891`
2. Login with default credentials: `admin` / `changeme` (change on first login)
3. Navigate to "API Keys" tab
4. Enter a descriptive name (e.g., "Home Router", "Office Modem")
5. Click "Create API Key"
6. **Copy the key immediately** - you won't be able to see it again!

### Enable Cloud Mode

Add cloud settings to your `config.json`:

```json
{
  "ModemAddress": "autodetect",
  "EnableCloud": true,
  "CloudHost": "your.cloud.server",
  "CloudPort": "22557",
  "CloudAPIKey": "your-api-key-from-admin-dashboard"
}
```

**Storage Options:**
- `"EnableCloud": false` (default): Results stored locally in `ModemCheck-Results/`, no cloud upload
- `"EnableCloud": true`: Results stored locally AND uploaded to cloud server (recommended)

### Cloud Server Features

- **API Key Management**: Create, view, edit, and delete API keys through web dashboard
- **User Management**: Create viewer and admin users with forced password changes
- **Usage Tracking**: See when each API key was last used
- **Automatic modem detection**: Server recognizes different modem models by MAC
- **Date range filtering**: Select specific time periods to analyze (default: last 14 days)
- **Trend analysis**: View signal quality, speed tests, and error rates over time
- **Multi-modem support**: Track multiple modems from one interface
- **Upload Queue**: Failed uploads automatically retry on next run
- **Security Hardened**: Input validation, path traversal protection, file size limits

### Public Deployment

For secure public access, use a reverse proxy (nginx, Caddy, Apache) or VPN. The admin dashboard should remain on your local network only (port 23891) for security.

See `cloudserver/README.md` for detailed deployment instructions including reverse proxy examples.

## How It Works

1. **Retry Failed Uploads**: Attempts to upload any previously failed files from queue
2. **Cleanup**: Purges old log entries (30+ days) and queue entries (14+ days)
3. **Detection**: Automatically detects your modem model by checking common IP addresses
4. **Authentication**: Logs into the modem using model-specific methods
5. **Data Collection**: Retrieves diagnostic data from modem's web interface
6. **Ping Tests**: Concurrent tests to google.ca and one.one.one.one (25 pings each)
7. **Speed Testing**: (Optional) Runs bandwidth-limited iPerf3 tests
8. **FEC Reset**: Clears Forward Error Correction counters for next check
9. **Save & Upload**: Saves JSON file locally and uploads to cloud (if enabled)
10. **Queue Failed Uploads**: Adds to retry queue if upload fails

## Troubleshooting

### General Issues

* **Modem not detected**: Manually specify the IP address with `-address 192.168.100.1`
* **Xfinity login fails**: Verify password is correct with `-password your_actual_password`
* **Permission denied**: Make sure the binary is executable (`chmod +x modem-check`)
* **Cloud upload fails**: Check API key, verify server is accessible, review upload queue

### Upload Issues

* **Check upload queue**: Look for `.upload_queue.json` in `ModemCheck-Results/` directory
* **Failed uploads retry**: System automatically retries failed uploads on next run
* **Queue cleanup**: Old entries (14+ days) are automatically removed

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
- `sysinfo`: Firmware, uptime, timestamps, modem type, MAC address
- `rx`: Downstream SC-QAM channel data (power, SNR, errors)
- `rxofdm`: Downstream OFDM channel data
- `tx`: Upstream SC-QAM channel data
- `txofdm`: Upstream OFDMA channel data
- `eventlog`: Modem event history (not available on Xfinity modems)
- `ping_google_avg`/`ping_google_loss`: Ping test results to google.ca
- `ping_cloudflare_avg`/`ping_cloudflare_loss`: Ping test results to one.one.one.one
- `iperf3test_ul`/`iperf3test_dl`: Speed test results
- `iperf3uploadlimit`/`iperf3downloadlimit`: Test configuration

Example filename: `ModemCheck-Results/XB8-AABBCCDDEEFF/2025-11-05_14-30-00.json`

## Enhanced Viewer Features

The included `checkviewer.html` provides:

* **Dual-Mode Interface**:
  - Single View: Detailed diagnostics with timeline navigation
  - Trends View: Interactive Chart.js visualizations for historical analysis
* **Multi-File Upload**: Drag and drop multiple JSON files for trend analysis
* **Visual Tracking**: Power levels, SNR, error rates, and channel bonding over time
* **Responsive Design**: Works on desktop and mobile browsers

The cloud viewer additionally includes:
* **14-Day Default Date Range**: Automatically pre-populated for quick access
* **Multi-Modem Support**: View data from multiple modems in one dashboard
* **Secure Authentication**: Session-based login with forced password changes
* **Real-Time Loading**: Direct access to all stored data

## Security

### Public Endpoint Security

**Implemented Protections:**
- ✅ Path traversal attacks blocked via strict input validation
- ✅ File size limits (10MB) prevent DoS attacks
- ✅ Regex-based validation on all file paths and parameters
- ✅ Path resolution checks ensure operations stay in allowed directories
- ✅ Error messages sanitized to prevent information disclosure

**Authentication:**
- ✅ API keys: 32-byte cryptographically random tokens with revocation capability
- ✅ Passwords: PBKDF2-HMAC-SHA256 with 100,000 iterations
- ✅ Sessions: HttpOnly, SameSite=Strict cookies with 7-day expiry
- ✅ Forced password changes for all new users

**Network Security:**
- ✅ HTTPS enforcement via Cloudflare Tunnel for public access
- ✅ Admin dashboard isolated to local network only
- ✅ Docker network isolation (172.25.0.0/16)
- ✅ Security headers: X-Frame-Options, X-Content-Type-Options, X-XSS-Protection

**Note:** The application has undergone security hardening with focus on input validation, path traversal prevention, and secure authentication.

## Automated Execution

### Linux/macOS Cron Job

```bash
# Edit crontab
crontab -e

# Run every hour
0 * * * * /path/to/modem-check --silent --nologs

# Run every 15 minutes
*/15 * * * * /path/to/modem-check --silent --nologs

# Run with config file
0 * * * * /path/to/modem-check -config /path/to/config.json --silent
```

### Windows Task Scheduler

1. Open Task Scheduler
2. Create Basic Task
3. Set trigger (e.g., hourly)
4. Action: Start a program
5. Program: `C:\path\to\modem-check.exe`
6. Arguments: `--silent --nologs` or `-config C:\path\to\config.json --silent`

## Project Structure

```
modemcheck/
├── modem-check.go              # Main application (1945 lines)
├── go.mod                      # Go module definition
├── Makefile                    # Build automation
├── README.md                   # This file
├── CLAUDE.md                   # Developer documentation
├── config.json.example         # Example configuration
├── checkviewer.html            # Local web viewer (1818 lines)
├── dist/                       # Pre-compiled binaries (7 platforms)
├── ModemCheck-Results/         # Local data storage
│   └── [MODEL]-[MAC]/          # Per-modem directories
│       └── *.json              # Timestamped check results
├── ModemCheck-ConfigFiles/     # Example configs for different modems
└── cloudserver/                # Docker-based cloud server
    ├── Dockerfile
    ├── docker-compose.yml
    ├── nginx.conf
    ├── admin.html              # Admin dashboard (1716 lines)
    ├── admin-login.html        # Admin login page
    ├── login.html              # Viewer login page
    ├── db-viewer.html          # Database explorer (dev tool)
    ├── db-viewer.js            # DB explorer frontend (1726 lines)
    └── cgi-bin/                # Python CGI backend
        ├── upload.py           # File upload handler
        ├── db-api.py           # Database API (session auth)
        ├── auth.py             # Authentication library
        ├── admin-api.py        # Admin operations
        ├── user-management.py  # User CRUD operations
        ├── db_schema.py        # Main database schema
        └── audit_schema.py     # Audit logging schema
```

## Contributing

Contributions are welcome! Please ensure:
- Code follows existing style and patterns
- Security best practices are maintained
- Documentation is updated for user-facing changes

## License

This project is provided as-is for personal and educational use.

## Support

For issues, questions, or feature requests:
- Check `CLAUDE.md` for comprehensive developer documentation
- See `cloudserver/README.md` for deployment guidance
- Review example configs in `ModemCheck-ConfigFiles/`
