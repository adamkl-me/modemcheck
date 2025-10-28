# Modem-Check v3.0

Modem-Check is a Bash script designed to collect diagnostic data from supported cable modems, including system information, power levels, and event logs. It supports multiple modem models and outputs the collected data in JSON format for easy analysis using the included `checkviewer.html`.

## Features

* **Supported Modems**:
    * Hitron CODA56
    * Sercomm DM1000
    * Rogers Xfinity Gateways (Tested on XB7/XB8 - requires credentials)
* **Collected Data**:
    * System information (firmware version, uptime, system time, MAC address)
    * RX/Downstream power levels & SNR (SC-QAM & OFDM/OFDMA)
    * TX/Upstream power levels (SC-QAM & OFDMA)
    * Codeword error counts (Corrected/Uncorrected)
    * Event logs (Not available on Xfinity modems)
* **Additional Functionality**:
    * Automatically detects modem model
    * Logs script actions to `modem-check_logs.txt`
    * Clears modem FEC counters after data collection (where supported)
    * Saves timestamped JSON output files for historical tracking
    * (Optional) Runs iPerf3 upload and download speed tests and adds results to JSON output

## Requirements

* Bash shell
* `curl` for HTTP requests
* `jq` for JSON processing
* A supported modem accessible via its web interface IP address (default is `172.16.0.1`, configurable in the script)
* (Optional) `iperf3` installed if you want to run speed tests.
* (If using Rogers Xfinity) Username and password must be set in the `igniteusername` and `ignitepassword` variables within the script.

## What's New in v3.0

* **Rogers Xfinity Support**: Added ability to log in and parse diagnostic data from Rogers Xfinity gateway pages (`network_setup.jst`, `software.jst`). Tested on XB7 and XB8 models. *Note: Event logs are not available.*
* **iPerf3 Integration**: Added optional iPerf3 upload and download speed tests. Results are appended to the JSON output file. Requires `iperf3` to be installed and server/port variables configured in the script.
* **Improved Modem Detection**: Enhanced logic to identify Xfinity modems based on initial page responses.
* **Refactored Function Handling**: Streamlined how modem-specific functions are called based on detected model.
* **Updated Viewer**: `checkviewer_new.html` (intended to replace `checkviewer.html`) includes a redesigned layout and fields to display the new iPerf3 speed test results.
* **Default IP Change**: Updated default `modemaddress` to `172.16.0.1`.

## Usage

1.  **Configure Script (if needed)**:
    * Edit `modem-check.sh`.
    * Change `modemaddress` if your modem uses a different IP (e.g., `192.168.100.1`).
    * If using a Rogers Xfinity modem, set `igniteusername` and `ignitepassword`.
    * If using iPerf3 tests, ensure `iperf3` is installed and set the `iperf3server` and `iperf3port` variables.
2.  **Make Executable**: `chmod +x modem-check.sh`
3.  **Run the script**: `./modem-check.sh`
4.  **View Results**:
    * Open `checkviewer.html` (or the newer `checkviewer_new.html`) in a web browser.
    * Click the "Upload File" button and select the generated JSON file.
    * The JSON files are saved in a directory named `ModemCheck-[MODEL]-[MAC]/[TIMESTAMP].json`.
