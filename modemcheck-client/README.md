# Modem Check Client v5.0.0

This is the modular implementation of modem-check, refactored from the original monolithic `modem-check.go` file into a clean package structure for better maintainability and extensibility.

## Structure

```
/modemcheck-client
├── main.go              # Main entry point and orchestration logic
├── config.go            # Configuration structs and loading logic
├── diagnostics.go       # Ping and Speedtest logic
├── cloud_client.go      # Upload logic and queue management
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

### 4. Native Go Implementations
- **Native Ping**: Uses `github.com/go-ping/ping` library instead of `exec.Command("ping")`
  - Cross-platform compatible without OS-specific command flags
  - More reliable and consistent results
  - Better error handling and timeout control
  - No dependency on system ping command

- **Native Speed Tests**: Uses `github.com/showwin/speedtest-go` library instead of external iperf3
  - Tests against public Ookla speed test servers
  - No need for dedicated iperf3 server or client installation
  - Automatic server selection based on proximity
  - Results in Mbps with 2 decimal precision
  - Enabled by default, can be disabled via flag or config file

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
go build -ldflags="-s -w -X main.Version=5.0.0" -o ../modem-check .
```

The resulting binary will be placed in the parent directory as `modem-check` (or `modem-check.exe` on Windows).

## Usage

The modular client is the current implementation and maintains backward compatibility:

```bash
# Auto-detect modem (speed tests enabled by default)
./modem-check

# Specify modem address
./modem-check -address 192.168.100.1

# For Xfinity modems with password
./modem-check -xfinitypassword your_password

# Disable speed tests
./modem-check -speedtest=false

# With configuration file (auto-detected if in same directory)
./modem-check -config config.json

# Enable cloud upload
./modem-check -config config.json -enablecloud

# Silent mode (no terminal output)
./modem-check -silent

# See all available flags
./modem-check -help
```

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

## Relationship to Legacy Code

The original monolithic `modem-check.go` file is kept in the parent directory for reference. This modular version is the current active implementation used by the build system.

## Version History

- **v5.0.0** - Cloud architecture improvements, config generator, role management
- **v4.5.0** - Initial refactored modular architecture with native speed tests
