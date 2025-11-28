# Modem Check Client

This is the main application source code for modem-check, organized into a clean modular package structure for better maintainability and extensibility.

## Structure

```
/modemcheck-client
├── main.go              # Main entry point and orchestration logic
├── config.go            # Configuration structs and loading logic
├── diagnostics.go       # Ping and Speedtest logic
├── cloud_client.go      # Upload logic and queue management
├── updater.go           # Auto-update system with GitHub integration
└── /scraper
    ├── scraper.go       # ModemScraper interface and common utilities
    ├── coda.go          # CODA45/CODA56 implementation
    ├── dm1000.go        # DM1000 implementation
    └── xfinity.go       # Xfinity/XB7/XB8 implementation
```

## Key Improvements

### 1. Modular Architecture
- **Separation of Concerns**: Each file has a specific responsibility
- **Scraper Interface**: All modem scrapers implement a common `ModemScraper` interface
- **Easy to Extend**: Adding a new modem type only requires implementing the interface

### 2. Package Organization
- **scraper package**: Contains all modem-specific scraping logic
- **main package**: Orchestration, configuration, diagnostics, and cloud upload

### 3. Maintainability
- **Smaller Files**: Each file is focused and easier to understand
- **Clear Dependencies**: Import structure shows relationships clearly
- **Interface-Based**: Enables testing and mocking

### 4. Native Go Implementations with Fallback
- **Native Ping with System Fallback**: Primary implementation uses `github.com/go-ping/ping` library with system ping fallback
  - Tries go-ping library first (fastest, cross-platform)
  - Falls back to system ping command if permissions don't allow go-ping
  - Automatic OS detection for proper command flags (Windows: `-n`, Unix: `-c`)
  - Works "out of the box" on all platforms without configuration
  - Better error handling and timeout control

- **Native Speed Tests**: Uses `github.com/showwin/speedtest-go` library instead of external iperf3
  - Tests against public Ookla speed test servers
  - No need for dedicated iperf3 server or client installation
  - Automatic server selection based on proximity
  - Results in Mbps with 2 decimal precision
  - Enabled by default, can be disabled via flag or config file

- **Network Information Detection**: Automatic detection of public IP and network information
  - Public IP address detection
  - ASN (Autonomous System Number) identification
  - ISP/provider name
  - Geolocation (city, country)
  - Uses ipapi.co free API (no authentication required)

## Building

From the project root directory:

```bash
# Using Makefile (recommended)
make build                    # Build for current platform
make cross-compile           # Build for all platforms

# Or build manually
cd modemcheck-client
go build -o ../modem-check .

# Build with version info
go build -ldflags="-s -w -X main.Version=5.4.0" -o ../modem-check .
```

The resulting binary will be placed in the parent directory as `modem-check` (or `modem-check.exe` on Windows).

## Usage

```bash
# Auto-detect modem (speed tests enabled by default)
./modem-check

# Specify modem address
./modem-check -a 192.168.100.1

# For Xfinity/Ignite modems with password
./modem-check -x your_password

# Disable speed tests
./modem-check -n

# With configuration file (auto-detected if config.json in same directory)
./modem-check -c config.json

# Quiet mode (no terminal output)
./modem-check -q

# Disable log file
./modem-check -l

# Cloud mode bootstrap (first run creates config.json)
./modem-check -s api.example.com -k "your-api-key"

# Cloud mode with custom port
./modem-check -s api.example.com -p 8443 -k "your-api-key"

# Cloud mode with interactive API key prompt
./modem-check -s api.example.com

# Cloud mode with interactive server prompt
./modem-check -k "your-api-key"

# Show version
./modem-check --version

# See all available flags
./modem-check -help
```

## Command-Line Flags

| Flag | Long Form | Description | Default |
|------|-----------|-------------|---------|
| `-a` | `--address` | Modem IP address or hostname | `autodetect` |
| `-c` | `--config` | Path to JSON configuration file | (none) |
| `-s` | `--server` | Cloud server hostname/IP (enables cloud mode) | (none) |
| `-p` | `--port` | Cloud server port | `443` |
| `-k` | `--apikey` | API key for cloud mode | (none) |
| `-q` | `--quiet` | Suppress terminal output | `false` |
| `-l` | `--nologs` | Disable log file creation | `false` |
| `-x` | `--xfinitypassword` | Password for Xfinity/Ignite modems | (none) |
| `-n` | `--nospeedtest` | Disable speed tests | `false` |
| | `--version` | Print version and exit | |

### Cloud Mode Bootstrap

The `-s`, `-p`, and `-k` flags enable easy client deployment without a pre-existing config file:

```bash
# First run: connect to cloud and create config.json
./modem-check -s api.example.com -k "YOUR-API-KEY"

# Subsequent runs: uses saved config.json
./modem-check
```

**Behavior:**
- When `-s` (server) AND `-k` (apikey) are provided → enables cloud mode
- When `-s` (server) provided WITHOUT `-k` → prompts interactively for API key
- When `-k` (apikey) provided WITHOUT `-s` → prompts interactively for server hostname
- These flags override config.json values if both are present
- After first successful run, config is saved to config.json for future runs

## Configuration File

Create a `config.json` file in the same directory as the binary:

```json
{
  "ModemAddress": "autodetect",
  "IgnitePassword": "",
  "SpeedTestEnabled": true,
  "SpeedTestInterval": 1,
  "SpeedTestConnections": 1,
  "PingCount": 100,
  "AutoUpdateEnabled": true,
  "UpdateChannel": "stable",
  "Silent": false,
  "NoLogs": false,
  "LocalCleanupEnabled": true,
  "LocalRetentionDays": 90,
  "EnableCloud": false,
  "CloudHost": "",
  "CloudPort": "443",
  "CloudAPIKey": "",
  "EnforceHTTPS": true,
  "InsecureTLS": false
}
```

### Configuration Options

| Field | Type | Description | Default |
|-------|------|-------------|---------|
| `ModemAddress` | string | Modem IP or `"autodetect"` | `"autodetect"` |
| `IgnitePassword` | string | Password for Ignite/Xfinity modems | `""` |
| `SpeedTestEnabled` | bool | Enable speed tests | `true` |
| `SpeedTestInterval` | int | Run speed test every N runs (1-1000) | `1` |
| `SpeedTestConnections` | int | Parallel connections (1-16) | `1` |
| `PingCount` | int | Number of pings (1-100) | `100` |
| `AutoUpdateEnabled` | bool | Enable automatic updates | `true` |
| `UpdateChannel` | string | `"stable"` or `"beta"` | `"stable"` |
| `Silent` | bool | Suppress console output | `false` |
| `NoLogs` | bool | Disable log file | `false` |
| `LocalCleanupEnabled` | bool | Auto-cleanup old files | `true` |
| `LocalRetentionDays` | int | Days to keep local files | `90` |
| `EnableCloud` | bool | Enable cloud upload | `false` |
| `CloudHost` | string | Cloud server hostname | `""` |
| `CloudPort` | string | Cloud server port | `"443"` |
| `CloudAPIKey` | string | API key for authentication | `""` |
| `EnforceHTTPS` | bool | Always use HTTPS | `true` |
| `InsecureTLS` | bool | Allow self-signed certs (dev) | `false` |

## Adding a New Modem Type

To add support for a new modem:

1. Create a new file in `scraper/` (e.g., `newmodem.go`)
2. Implement the `ModemScraper` interface:
   - `Login() error`
   - `GetMAC() (string, error)`
   - `GetData(checkTime int64) (*ModemData, error)`
   - `ClearFEC() error`
   - `GetModemType() string`
3. Add detection logic to `scraper.DetectModem()`
4. Add case to `createScraper()` in `main.go`

## Testing

The Go client includes ~85 unit tests covering core functionality.

### Running Tests

```bash
cd modemcheck-client

# Run all tests
go test -v ./...

# Run with race detection and coverage
go test -v -race -coverprofile=coverage.txt -covermode=atomic ./...

# View coverage report
go tool cover -html=coverage.txt

# Run specific test file
go test -v -run TestHMAC
```

### Test Files

| File | Tests | Coverage |
|------|-------|----------|
| `cloud_client_test.go` | HMAC signatures, upload queue | Core upload functionality |
| `config_test.go` | Config validation, state management | Configuration loading |
| `updater_test.go` | Version comparison, signature verification | Auto-update system |
| `diagnostics_test.go` | Network diagnostics, IP detection | Ping/speed tests |
| `config_sync_test.go` | Server config sync, encryption | Config management |
| `config_state_test.go` | Local state persistence | State file handling |

### Key Test Categories

**Configuration Tests:**
- Config file loading and validation
- Default value handling
- Range validation (PingCount, SpeedTestInterval)
- Update channel validation (stable/beta/test)

**Cloud Upload Tests:**
- HMAC-SHA256 signature generation
- Upload queue operations (FIFO, 100 max)
- Retry logic with exponential backoff
- Private network detection

**Update System Tests:**
- Version comparison logic
- Ed25519 signature verification
- Update channel filtering
- Rollback protection

**Network Diagnostics Tests:**
- 3-tier IP detection fallback
- Ping test execution
- Speed test interval logic
- Timeout handling

## Version History

- **v7.x** - Client configuration management, server-side config sync, enforced configurations
- **v6.x** - Cloud upload security (HMAC signatures), centralized error handling, stability fixes
- **v5.7.0** - Network information tracking (public IP, ASN, ISP, geolocation), failed detection handling
- **v5.6.0** - Speed test interval control, local file cleanup, enhanced help output
- **v5.5.0** - Enhanced RBAC, config defaults, update improvements
- **v5.4.0** - MIPS architecture support, cleaner binary naming
- **v5.3.0** - Auto-update system with GitHub integration
- **v5.2.0** - Enhanced metrics (speed test server info, latency, jitter)
- **v5.1.0** - Automatic version injection, system ping fallback
- **v5.0.0** - Cloud architecture improvements, role management
