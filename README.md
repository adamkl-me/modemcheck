# Modem-Check v5.5.0

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

## What's New in v5.5.0

### 🔐 Enhanced Role-Based Access Control

**New "Elevated" Role**
* Introduced middle-tier role between basic and admin for better permission granularity
* Elevated users can:
  - List and toggle (enable/disable) API keys
  - View client submission logs
  - Access configuration generator
* Elevated users cannot:
  - Delete API keys (admin only)
  - View user activity logs (admin only)
  - Manage users or change roles (admin only)
* Perfect for trusted users who need operational access without full administrative privileges

### ⚙️ Config Generator Enhancements

**Defaults Management**
* New "Defaults" sub-tab in Config Generator for setting default values
* Pre-populate all configuration fields with your preferred defaults
* Defaults automatically applied when creating new configurations
* Saves time when deploying multiple modem-check clients
* Admin-only feature with full audit logging

### 🔄 Client Update Improvements

**Update Lock Mechanism**
* Added cooldown period (5 minutes) after failed update attempts
* Prevents repeated failed update attempts that could cause issues
* Automatically verifies update success on next startup
* Clears lock file when update is confirmed successful
* Better handling of update failures with graceful fallback

### 🧪 Comprehensive Test Suite

**Security & Functional Testing**
* Added 50+ new test cases for cloud server APIs
* Authentication tests (login, logout, session management)
* Role-based access control tests for all three user roles
* Security tests (XSS prevention, SQL injection protection, session security)
* End-to-end workflow tests (upload → view → audit)
* User lifecycle tests (create → use → delete)
* Enhanced quality assurance and security validation

## Previous Updates

### v5.4.0 - MIPS Architecture Support

**Embedded Device & Router Support**
* Added MIPS (little-endian) support for OpenWrt routers and embedded devices
* Added MIPS (big-endian) support for legacy systems
* Compiled with softfloat for compatibility with older MIPS processors (MIPS32 Release 2)
* Perfect for routers with MediaTek MT7621, Atheros, and similar chipsets

**Cleaner Binary Naming**
* Removed version numbers from binary filenames for simpler auto-update
* Consistent naming across releases (e.g., `modem-check-linux-x64`)
* GitHub releases now use stable URLs for latest binaries

**Viewer Improvements**
* Cleaned up ping/latency chart by removing untracked metrics
* Hidden max latency datasets by default (can be toggled in chart legend)
* Removed display of Speed Test DL Latency and UL Jitter (not collected)
* More accurate data visualization

**Platform Coverage**
* Now supports 9 platform targets:
  - Linux x64, ARM, ARM64, MIPS LE, MIPS BE
  - Windows x64
  - FreeBSD x64
  - macOS x64, ARM64 (source build only)

## Previous Updates

### v5.3.1 - Bug Fixes & UI Improvements

**Date Filtering Fix**
* Fixed date filtering on cloud viewer to support epoch timestamp format
* Handles both epoch (integer) and text format timestamps transparently
* Date filters now work correctly regardless of timestamp storage format

**Speed Test UI Reorganization**
* Moved "Speed Test Server" information to info cards section
* Created new "Speed Test Ping" card showing unloaded latency prominently
* Added "Speed Test Enabled?" status card (Yes/Failed/Disabled)
* Improved status messaging for disabled/failed speed tests
* Better visual hierarchy for speed test metrics

**Speed Test Packet Loss Removal**
* Removed non-functional speed test packet loss tracking
* Packet loss now only reported for Google/Cloudflare ping tests (where it works correctly)
* Cleaner, more accurate speed test reporting

**Database Updates**
* Added `speedtest_enabled` column to track test configuration
* Enhanced query logic for mixed timestamp format support
* Migration scripts executed successfully in production

## Previous Updates

### v5.3.0 - Automatic Updates

**🔄 Self-Updating Binary**

**Self-Updating Binary**
* Automatically checks GitHub for new releases on startup
* Downloads and applies updates with zero user interaction
* Creates backup of current version before updating
* Restarts automatically after successful update
* Enabled by default, can be disabled with `-noupdate` flag or `AutoUpdateEnabled: false` in config
* Platform-aware: Downloads correct binary for your OS/architecture
* Graceful fallback: Continues with current version if update fails

### 📊 Enhanced Network Diagnostics (v5.2.0)

**Speed Test Enhancements**
* Server information display (sponsor name and server ID)
* Unloaded latency metrics (average, maximum, jitter, packet loss)
* Loaded latency metrics (download latency, upload jitter)
* More comprehensive network quality assessment

**Ping Test Improvements**
* Jitter measurements for both Google and Cloudflare targets
* Maximum latency tracking alongside averages
* System ping fallback for better Linux compatibility
* Works "out of the box" on all platforms without configuration
* Graceful fallback chain: go-ping library → system ping → marked as failed

**Client Tracking**
* Version number automatically recorded in each check
* Operating system and architecture logged for troubleshooting
* Better support diagnostics and compatibility tracking

### 🗄️ Database & Viewer Updates (v5.2.0)

**Database Enhancements**
* 15+ new columns for enhanced metrics
* Speed test server information
* Unloaded and loaded latency data
* Ping jitter and max latency values
* Client version/OS/architecture tracking

**Viewer Improvements**
* New client information card showing version/OS/arch
* Speed test server card with unloaded metrics
* Enhanced ping displays with jitter and max latency
* Loaded latency metrics displayed with upload/download speeds
* 6 new chart datasets for comprehensive latency visualization
* Consistent numeric formatting (1 decimal place)

## Previous Updates

### v5.1.0 - Version Injection & Ping Fallback

**🔧 Automatic Version Injection**
* Version number now automatically updates from Makefile during build
* No more manual version string updates in code
* Build time also injected for better tracking

**🏓 Enhanced Ping Reliability**
* System ping command fallback when go-ping library fails
* Automatic OS detection for proper ping command flags
* No root access or system modifications required

### v5.0.0 - Major Features

**🎨 Config Generator GUI**
* New tab in admin dashboard for creating `config.json` files
* Sub-tabs for Generator and Defaults management
* Defaults sub-tab allows setting default values for all config fields
* Live JSON preview with auto-updates as you type
* Download config.json directly from browser
* Select existing API keys from dropdown
* No more manual JSON editing - point-and-click configuration!

**👥 Role Management**
* Promote/demote users between basic and admin roles
* Admin account protected from modification/deletion
* Full audit logging of all role changes
* Easy user management through admin dashboard

**🔍 Auto-Detect Config**
* modem-check now automatically looks for `config.json` in its directory
* No need to specify `-config` flag if file is in same folder
* Simplifies deployment and automation

**🏗️ Cloud Architecture Improvements**
* Direct database insertion (removed import-daemon)
* Enhanced audit logging with detailed user activity tracking
* Improved API response format with `database_id` field
* Better error handling and reporting

### Bug Fixes
* Fixed viewer displaying epoch timestamps instead of formatted dates
* Fixed role constraint errors (changed 'user' to 'basic')
* Fixed input field styling inconsistencies
* Admin account now properly protected from modification

### Testing Improvements
* Renamed e2e_test.sh to cloud_api_test.sh (more accurate name)
* Fixed test accuracy issues
* All 19 tests passing (10 functional + 9 security)
* Improved test coverage and reliability

### Breaking Changes ⚠️
* Database schema changes for direct insertion model
* API response format now includes `database_id` field
* Removed import-daemon.py architecture
* Refactored client code to modemcheck-client/ structure

### Previous Updates

#### v4.5.0 - Modular Architecture
* Refactored from monolithic 1,946-line file to clean package structure
* Native Speed Tests with Go speedtest library (no iperf3 dependency)
* Native Ping using go-ping library
* Database Migration to SQLite for users and API keys

#### v4.4.x - Performance & Quality
* Code Quality: Linter warnings fixed, improved performance optimizations
* Timestamp Standardization: Consistent timestamp handling across all components
* BER Calculation Fixes: Improved Bit Error Rate calculations for accuracy
* Time-Based Charts: Enhanced visualization with time-series data

#### v4.2.x - Security & Storage
* SQLite Migration: All storage moved to SQLite for better performance
* XSS Protection: Enhanced security headers and input sanitization
* Timing-Safe Comparisons: API key validation uses constant-time comparison
* File Locking: Prevents race conditions in concurrent operations

#### v4.1.x - Cross-Platform & Security
* Windows Ping Support: Fixed ping tests on Windows (uses `-n` flag)
* Real IP Tracking: Admin dashboard shows actual client IPs through Cloudflare tunnels
* Path Traversal Protection: Strict validation prevents malicious file path attacks
* Forced Password Changes: New users must change password on first login
* Upload Queue: Failed uploads automatically retry on next run



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

# Or build manually
cd modemcheck-client
go build -ldflags "-X main.Version=5.3.0" -o ../modem-check .
```

## Configuration

### Command-Line Flags

```bash
# Basic usage with autodetect (speed tests and auto-update enabled by default)
./modem-check

# Specify modem address
./modem-check -address 192.168.100.1

# For Xfinity modems with password
./modem-check -xfinitypassword your_password

# Disable auto-updates
./modem-check -noupdate

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
  -noupdate \
  -silent \
  -nologs \
  -enablecloud
```

### Configuration File

Create a `config.json` file (see `config.json.example` for an example, or use the Admin Dashboard Config Generator with the Defaults sub-tab to set default values):

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

**Configuration Options:**
- `ModemAddress`: IP address or "autodetect" to scan common addresses
- `IgnitePassword`: Password for Rogers Xfinity/Ignite modems
- `SpeedTestEnabled`: Enable/disable speed tests using public Ookla servers (default: true)
- `AutoUpdateEnabled`: Enable/disable automatic updates from GitHub (default: true)
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
docker volume create modemcheck-cloud_db
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

**Option 1: Using Admin Dashboard**
1. Open the admin dashboard in your browser: `http://localhost:23891`
2. Login with default credentials: `admin` / `changeme` (change on first login)
3. Navigate to "API Keys" tab
4. Enter a descriptive name (e.g., "Home Router", "Office Modem")
5. Click "Create API Key"
6. **Copy the key immediately** - you won't be able to see it again!

**Option 2: Using Config Generator (Recommended)**
1. Open the admin dashboard and navigate to "Config Generator" tab
2. (Optional) Go to the "Defaults" sub-tab to set default values for all fields
3. Return to the "Generator" sub-tab which will be pre-filled with your defaults
4. Fill in your modem details and settings (or use the defaults)
5. Click "Select Existing API Key" to choose from your existing keys
6. Or create a new one directly from the API Keys tab
7. Download the generated `config.json` file
8. Place it in the same directory as your modem-check executable

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

- **Config Generator**: Point-and-click interface to create config.json files with live preview
  - Generator sub-tab for creating configurations
  - Defaults sub-tab for setting default values that auto-populate the generator
- **Data Management**: Comprehensive tools for managing modem check data
  - Bulk Upload: Upload multiple JSON check files at once
  - Bulk Download: Download checks as a ZIP archive with filtering options
  - Delete Checks: Remove individual checks or all checks for a specific modem
- **Role Management**: Promote/demote users between basic, elevated, and admin roles
- **API Key Management**: Create, view, edit, and delete API keys through web dashboard
- **User Management**: Create viewer and admin users with forced password changes
- **Usage Tracking**: See when each API key was last used
- **Audit Logging**: Complete tracking of all user actions and role changes
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

* **Speed tests are slow**: Native Go speed tests use public Ookla servers and may take 30-60 seconds
* **Speed tests fail**: Check your internet connection and firewall settings
* **Disable speed tests**: Use `-speedtest=false` flag or set `"SpeedTestEnabled": false` in config.json

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
- `ping_google_jitter`/`ping_google_max_latency`: Additional ping metrics
- `ping_cloudflare_avg`/`ping_cloudflare_loss`: Ping test results to one.one.one.one
- `ping_cloudflare_jitter`/`ping_cloudflare_max_latency`: Additional ping metrics
- `speedtest_download`/`speedtest_upload`: Native Go speed test results (Mbps)
- `speedtest_latency`: Network latency from speed test (ms)
- `speedtest_server_name`/`speedtest_server_id`: Speed test server information
- `speedtest_max_latency`/`speedtest_jitter`/`speedtest_packet_loss`: Unloaded metrics
- `speedtest_dl_latency`/`speedtest_ul_jitter`: Loaded latency metrics
- `client_version`/`client_os`/`client_arch`: Client information

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
* **Config Generator**: Create config.json files using a GUI with live preview
  - Generator sub-tab for creating configurations
  - Defaults sub-tab for setting and managing default values
* **Role Management**: Admin users can promote/demote other users
* **14-Day Default Date Range**: Automatically pre-populated for quick access
* **Multi-Modem Support**: View data from multiple modems in one dashboard
* **Secure Authentication**: Session-based login with forced password changes
* **Real-Time Loading**: Direct access to all stored data
* **User Activity Tracking**: Comprehensive audit logs of all actions

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
├── config.json.example         # Example configuration
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
- Check `CLAUDE.md` for comprehensive developer documentation
- See `cloudserver/README.md` for deployment guidance
- Review example configs in `ModemCheck-ConfigFiles/`
