# Modem-Check v3.2

Modem-Check is a Bash script designed to collect diagnostic data from supported cable modems, including system information, power levels, event logs, and speed test results. It supports multiple modem models and outputs the collected data in JSON format for easy analysis using the included `checkviewer.html`.

## Features

* **Supported Modems**:
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
    * Logs script actions to `modem-check_logs.txt`
    * Clears modem FEC counters after data collection (where supported)
    * Saves timestamped JSON output files for historical tracking
    * Configurable bandwidth-limited iPerf3 speed tests

## Requirements

* Bash shell
* `curl` for HTTP requests
* `jq` for JSON processing
* A supported modem accessible via its web interface
* (Optional) `iperf3` installed for speed testing
* (If using Rogers Xfinity) Username and password configured in the script

## What's New in v3.2

* **Auto-Detection**: Enhanced modem detection that automatically scans common IP addresses (192.168.100.1, 192.168.0.1, 10.0.0.1, 172.20.0.1)
* **Bandwidth Limiting**: iPerf3 tests now support configurable bandwidth limits to prevent network saturation
* **Multi-Stream Testing**: Configurable number of parallel streams for more accurate speed measurements
* **Improved Error Handling**: Better timeout handling and validation for speed tests
* **Enhanced Viewer**: Updated HTML viewer displays bandwidth limit information alongside test results
* **Xfinity Improvements**: Better authentication error handling and detection of XB7/XB8 variants

## Configuration

Edit `modem-check.sh` to customize settings:

### Modem Connection
```bash
modemaddress="autodetect"  # Or specify IP directly (e.g., "192.168.100.1")
ignitepassword="password"  # For Rogers Xfinity modems
```

### iPerf3 Speed Tests
```bash
iperf3enabled="true"           # Enable/disable speed tests
iperf3server="your.server.ip"  # iPerf3 server address
iperf3port="5201"              # Server port
iperf3streams=4                # Number of parallel streams
iperf3uploadlimit="150"        # Upload bandwidth limit (Mbps)
iperf3downloadlimit="1500"     # Download bandwidth limit (Mbps)
```

## Usage

1. **Configure the script** (see Configuration section above)
2. **Make executable**: 
   ```bash
   chmod +x modem-check.sh
   ```
3. **Run the script**: 
   ```bash
   ./modem-check.sh
   ```
4. **View Results**:
    * Open `checkviewer.html` in a web browser
    * Click "Upload JSON File" and select the generated file
    * JSON files are saved in `ModemCheck-[MODEL]-[MAC]/[TIMESTAMP].json`

## How It Works

1. **Detection**: Automatically detects your modem model by checking common IP addresses
2. **Authentication**: Logs into the modem using model-specific methods
3. **Data Collection**: Retrieves diagnostic data from modem's web interface
4. **Speed Testing**: (Optional) Runs bandwidth-limited iPerf3 tests
5. **FEC Reset**: Clears Forward Error Correction counters for next check
6. **Output**: Saves comprehensive JSON file with all collected data

## Troubleshooting

* **Modem not detected**: Manually set `modemaddress` to your modem's IP
* **Xfinity login fails**: Verify `ignitepassword` is correct
* **Speed tests timeout**: Check `iperf3server` connectivity and adjust limits
* **No data in viewer**: Ensure JSON file is complete and not corrupted

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

## License

This project is provided as-is for personal and educational use.