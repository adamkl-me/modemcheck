# Modem Check Client - Refactored

This is a refactored version of the monolithic `modem-check.go` file, organized into a modular package structure for better maintainability and extensibility.

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

```bash
cd modemcheck-client
go build -o modem-check
```

## Usage

The refactored client maintains 100% compatibility with the original `modem-check.go`:

```bash
# Auto-detect modem (speed tests enabled by default)
./modem-check

# Specify modem address
./modem-check -address 192.168.100.1

# Disable speed tests
./modem-check -speedtest=false

# With configuration file
./modem-check -config config.json

# Silent mode (no terminal output)
./modem-check -silent

# See all available flags
./modem-check --help
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

## Migration from Original

The original `modem-check.go` file remains unchanged in the parent directory. This refactored version is a drop-in replacement with the same behavior and command-line interface.

## Version

v4.5.0 - Refactored modular architecture
