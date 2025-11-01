#!/bin/bash

 ####################################
#### 💻⚙️ Modem-Check v3.2 ⚙️💻 ####
 ####################################

### GENERAL CONFIGURATION ###

# Log function - creates log file and prints to both terminal and log file
function log() {
    local message="$1"
    local log_file="$(dirname "$0")/modem-check_logs.txt"
    echo "$(date): $message" | tee -a "$log_file"
}

# Modem connection settings
modemaddress="autodetect" # Set to "autodetect" or specify IP/hostname directly

ignitepassword="password"  # Only used if Rogers Xfinity modem is detected

# iPerf3 speed test configuration
iperf3enabled="true"   # Set to true or false to enable/disable iPerf3 tests
iperf3server="fillme" # IP or hostname of the iPerf3 server to use
iperf3port="5201"   # Port of the iPerf3 server (default is 5201)
iperf3streams=4          # Number of parallel streams to use for the test
iperf3uploadlimit="150"     # Total allowed upload bandwidth
iperf3downloadlimit="1500"  # Total allowed download bandwidth


### MODEM-SPECIFIC FUNCTIONS ###

#==============================================================================
# Hitron CODA56 Functions
#==============================================================================

# Login function (not required for CODA56, included for compatibility)
function CODA56_login() {
    log "Login not required for Hitron CODA56"
}

# Clear FEC (Forward Error Correction) counters
function CODA56_clearfec() {
    curl "$modemaddress/goform/ResetFECCnt" \
        --data-raw 'model=%7B%22portId%22%3A%221%22%2C%22frequency%22%3A%22591000000%22%2C%22modulation%22%3A%222%22%2C%22signalStrength%22%3A%225.700%22%2C%22snr%22%3A%2237.356%22%2C%22dsoctets%22%3A%221113110%22%2C%22correcteds%22%3A%220%22%2C%22uncorrect%22%3A%220%22%2C%22channelId%22%3A%224%22%2C%22resetval%22%3A%221%22%7D' \
        --insecure \
        > /dev/null 2>&1
}

# Get modem MAC address and validate format
function CODA56_getmac() {
    modemmac=$(curl -s "$modemaddress/data/getSysInfo.asp?" --insecure | jq -r '.[0].rfMac' | tr -d ':')
    if [[ $modemmac =~ ^[0-9A-Fa-f]{12}$ ]]; then
        log "Successfully retrieved modem WAN MAC address: $modemmac"
    else
        log "Unable to get valid modem MAC, exiting script"
        exit 1
    fi
}

# Collect comprehensive modem data and save to JSON
function CODA56_getdata() {
    # System information
    sysinfo_data=$(curl -s "$modemaddress/data/getSysInfo.asp" --insecure |
        jq --arg checktime "$checktime" --arg modemtype "$modemtype" --arg modemmac "$modemmac" \
        '.[0] | {systime: .systemTime, firmware: .swVersion, uptime: .systemUptime, modemtype: $modemtype, modemmac: $modemmac, checktime: $checktime}')
    modemfw=$(echo "$sysinfo_data" | jq -r '.firmware')
    modemuptime=$(echo "$sysinfo_data" | jq -r '.uptime')
    modemsystime=$(echo "$sysinfo_data" | jq -r '.systime')

    # Downstream (RX) channel data
    rx_data=$(curl -s "$modemaddress/data/dsinfo.asp" --insecure |
        jq 'map(del(.modulation, .channelId) |
        .portid = .portId | del(.portId) |
        .power = .signalStrength | del(.signalStrength) |
        .octets = .dsoctets | del(.dsoctets) |
        .uncorrectds = .uncorrect | del(.uncorrect) |
        {portid, frequency, power, snr, octets, correcteds, uncorrectds})')

    # Downstream OFDM channel data
    rxofdm_data=$(curl -s "$modemaddress/data/dsofdminfo.asp" --insecure |
        jq 'map(del(.ffttype) |
        .portid = .receive | del(.receive) |
        .subcarr0freq = .Subcarr0freqFreq | del(.Subcarr0freqFreq) |
        .plcsnr = .SNR | del(.SNR) |
        .octets = .dsoctets | del(.dsoctets) |
        .uncorrectds = .uncorrect | del(.uncorrect) |
        {portid, subcarr0freq, plclock, ncplock, mdc1lock, plcpower, plcsnr, octets, correcteds, uncorrectds})')

    # Upstream (TX) channel data
    tx_data=$(curl -s "$modemaddress/data/usinfo.asp" --insecure |
        jq 'map(del(.bandwidth, .modtype, .scdmaMode, .channelId) |
        .portid = .portId | del(.portId) |
        .power = .signalStrength | del(.signalStrength) |
        {portid, frequency, power})')

    # Upstream OFDM channel data
    txofdm_data=$(curl -s "$modemaddress/data/usofdminfo.asp" --insecure |
        jq 'map(del(.digAtten, .digAttenBo, .channelBw, .repPower, .fftVal) |
        .portid = .uschindex | del(.uschindex) |
        .subcarr0freq = .frequency | del(.frequency) |
        .power = .repPower1_6 | del(.repPower1_6) |
        {portid, state, subcarr0freq, power})')

    # Event log data
    eventlog_data=$(curl -s "$modemaddress/data/status_log.asp" --insecure |
        jq 'map(del(.index, .priority) |
        .id = .type | del(.type) |
        {time, id, event})')

    # Combine all data into single JSON file
    jq -n --argjson sysinfo "$sysinfo_data" --argjson rx "$rx_data" --argjson rxofdm "$rxofdm_data" \
        --argjson tx "$tx_data" --argjson txofdm "$txofdm_data" --argjson eventlog "$eventlog_data" \
        '{sysinfo: $sysinfo, rx: $rx, rxofdm: $rxofdm, tx: $tx, txofdm: $txofdm, eventlog: $eventlog}' > "$checkfile"

    log "Modem data collected and saved to $checkfile"
}

#==============================================================================
# Sercomm DM1000 Functions
#==============================================================================

# Login to DM1000 modem with technician credentials
function DM1000_login() {
    local url="$modemaddress/setup.cgi"
    local user="technician"
    local pass="sercommdocsis"
    local data="login_user=$user&pws=$(echo -n "$pass" | base64)&submit=Apply&is_parent_window=1&todo=login&this_file=login.html&next_file=&language=en&message=&passwd=$(echo -n "$pass" | base64)&cur_passwd="
    
    # Perform login request
    curl -s --insecure --data-raw "$data" "$url" > /dev/null 2>&1

    # Verify login was successful
    local response=$(curl -s "$modemaddress/setup.cgi?todo=Cm_Status" --insecure)
    if [[ -n "$response" ]]; then
        log "Login successful"
    else
        log "Login failed, exiting script"
        exit 1
    fi
}

# Clear FEC (Forward Error Correction) counters
function DM1000_clearfec() {
    curl "$modemaddress/setup.cgi" \
        --data-raw 'todo=reset_FEC_Counters&this_file=status.html&next_file=status.html' \
        --insecure \
        > /dev/null 2>&1
}

# Get modem MAC address 
function DM1000_getmac() {
    modemmac=$(curl -s "$modemaddress/setup.cgi?todo=Interface_param" --insecure | \
        grep '"name":"wan0"' | \
        sed 's/.*"mac":"\([^"]*\)".*/\1/' | \
        tr -d ':' | \
        tr '[:lower:]' '[:upper:]')
    
    if [[ $modemmac =~ ^[0-9A-Fa-f]{12}$ ]]; then
        log "Successfully retrieved modem WAN MAC address: $modemmac"
    else
        log "Unable to get valid modem MAC, exiting script"
        exit 1
    fi
}

# Collect comprehensive modem data and save to JSON
function DM1000_getdata() {
    # Fetch status page
    local status_page=$(curl -s "$modemaddress/status.html")

    # Extract system time
    modemsystime=$(echo "$status_page" | grep -oP '(?<=<td  align="left" id ="time_date">)[^<]+')

    # Extract uptime
    modemuptime=$(echo "$status_page" | \
        awk -F'<td align="left">' '/<th width="20%" height="30" align="left"><script language="javascript" type="text\/javascript">dw\(str_status16\);<\/script>:/ {getline; print $2}' | \
        awk -F'</td>' '{print $1}')

    # Fetch and extract firmware version
    local version_info=$(curl -s "$modemaddress/setup.cgi?todo=Version_Info" --insecure)
    modemfw=$(echo "$version_info" | jq -r '.nodes[] | select(.fwinfo) | .fwinfo')

    # Create system information JSON object
    sysinfo_data=$(jq -n --arg systime "$modemsystime" --arg uptime "$modemuptime" \
        --arg firmware "$modemfw" --arg checktime "$checktime" --arg modemtype "$modemtype" \
        --arg modemmac "$modemmac" \
        '{systime: $systime, firmware: $firmware, uptime: $uptime, modemtype: $modemtype, modemmac: $modemmac, checktime: $checktime}')

    # Downstream (RX) channel data
    rx_data=$(curl -s "$modemaddress/setup.cgi?todo=RF_DS_param" --insecure |
        jq '.nodes | map(del(.DCIDD, .qamD) |
        .portid = .numD | del(.numD) |
        .frequency = .FreqD | del(.FreqD) |
        .power = .PowerD | del(.PowerD) |
        .snr = .SNRD | del(.SNRD) |
        .octets = .octetsD | del(.octetsD) |
        .correcteds = .correctedsD | del(.correctedsD) |
        .uncorrectds = .uncorrectedsD | del(.uncorrectedsD) |
        {portid, frequency, power, snr, octets, correcteds, uncorrectds})')

    # Downstream OFDM channel data
    rxofdm_data=$(curl -s "$modemaddress/setup.cgi?todo=RF_DS_31_param" --insecure |
        jq '.nodes | map(del(.fftType, .AV_Pilot, .AV_Data) |
        .portid = .num | del(.num) |
        .subcarr0freq = .OFDMFreq | del(.OFDMFreq) |
        .plclock = .PLC | del(.PLC) |
        .ncplock = .NCP | del(.NCP) |
        .mdc1lock = .MDC1 | del(.MDC1) |
        .plcpower = .PLC_power | del(.PLC_power) |
        .plcsnr = .AV_PLC | del(.AV_PLC) |
        {portid, subcarr0freq, plclock, ncplock, mdc1lock, plcpower, plcsnr, octets: "n/a", correcteds: "n/a", uncorrectds: "n/a"})')

    # Upstream (TX) channel data
    tx_data=$(curl -s "$modemaddress/setup.cgi?todo=RF_US_param" --insecure |
        jq '.nodes | map(del(.rate, .modulation, .channelType, .upstream) |
        .portid = .num | del(.num) |
        .frequency = .Freq | del(.Freq) |
        .power = .rep_power | del(.rep_power) |
        {portid, frequency, power})')

    # Upstream OFDM channel data
    txofdm_data=$(curl -s "$modemaddress/setup.cgi?todo=RF_US_31_param" --insecure |
        jq '[
        {
            "portid": .nodes[0].index1,
            "state": .nodes[2].index1,
            "subcarr0freq": .nodes[18].index1,
            "power": .nodes[7].index1,
            "activescs": .nodes[21].index1,
            "excludedscs": .nodes[22].index1,
            "notusedscs": .nodes[23].index1,
            "minislots": .nodes[24].index1,
            "interfacespeed": .nodes[25].index1
        },
        {
            "portid": .nodes[0].index2,
            "state": .nodes[2].index2,
            "subcarr0freq": .nodes[18].index2,
            "power": .nodes[7].index2,
            "activescs": .nodes[21].index2,
            "excludedscs": .nodes[22].index2,
            "notusedscs": .nodes[23].index2,
            "minislots": .nodes[24].index2,
            "interfacespeed": .nodes[25].index2
        }
        ]')

    # Event log data
    eventlog_data=$(curl -s "$modemaddress/setup.cgi?todo=Event_Log" --insecure |
        jq '.nodes | map(del(.lv) |
        .time = .d | del(.d) |
        .event = .text | del(.text) |
        {time, id, event})')

    # Combine all data into single JSON file
    jq -n --argjson sysinfo "$sysinfo_data" --argjson rx "$rx_data" --argjson rxofdm "$rxofdm_data" \
        --argjson tx "$tx_data" --argjson txofdm "$txofdm_data" --argjson eventlog "$eventlog_data" \
        '{sysinfo: $sysinfo, rx: $rx, rxofdm: $rxofdm, tx: $tx, txofdm: $txofdm, eventlog: $eventlog}' > "$checkfile"

    log "Modem data collected and saved to $checkfile"
}

#==============================================================================
# Rogers Xfinity Functions
#==============================================================================

# Xfinity modem credentials and session management
igniteusername="admin"
cookie_jar="$(dirname "$0")/modem-check_cookies.txt"

# Login to Rogers Xfinity modem and detect specific model (XB7/XB8)
function Xfinity_login() {
    log "Attempting login to Rogers Xfinity Modem at $modemaddress..."

    # Clean up old cookies
    rm -f "$cookie_jar"

    # Build POST data
    local post_data="username=$igniteusername&password=$ignitepassword&locale=false"

    # Perform login request
    curl -s -X POST "$modemaddress/check.jst" \
        -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:144.0) Gecko/20100101 Firefox/144.0" \
        -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" \
        -H "Accept-Language: en-CA,en-US;q=0.7,en;q=0.3" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -H "Sec-GPC: 1" \
        -H "Upgrade-Insecure-Requests: 1" \
        -e "$modemaddress/" \
        --data-raw "$post_data" \
        -c "$cookie_jar" \
        --insecure \
        > /dev/null 2>&1

    # Verify login and detect specific model
    log "Verifying login and detecting model..."
    local network_page_content
    network_page_content=$(curl -s --insecure -b "$cookie_jar" "$modemaddress/network_setup.jst")

    # Check for authentication failure by looking for actual page content
    # A successful login will have the "CM MAC:" label
    if ! echo "$network_page_content" | grep -q "CM MAC:"; then
        log "Rogers Xfinity modem login failed. Check credentials configured in script (ignitepassword) and adjust as needed. Exiting."
        exit 1
    fi

    if [[ -z "$network_page_content" ]]; then
        log "Rogers Xfinity modem login failed. No content received. Exiting."
        exit 1
    else
        log "Rogers Xfinity modem login successful."
        
        # Detect specific model variant
        if echo "$network_page_content" | grep -q "XB8"; then
            modemtype="Xfinity-XB8"
            log "Detected specific model: $modemtype"
        elif echo "$network_page_content" | grep -q "XB7"; then
            modemtype="Xfinity-XB7"
            log "Detected specific model: $modemtype"
        else
            log "Could not detect specific XB7/XB8 model. Using generic '$modemtype'."
        fi
    fi
}

# Clear FEC counters (not implemented for Xfinity modems)
function Xfinity_clearfec() {
    log "FEC clear function not yet implemented for Rogers Xfinity modem."
}

# Get modem MAC address and validate format
function Xfinity_getmac() {
    log "Fetching $modemaddress/network_setup.jst for MAC address..."
    local page_content
    page_content=$(curl -s --insecure -b "$cookie_jar" "$modemaddress/network_setup.jst")

    # Check for authentication failure by looking for actual page content
    # A successful login will have the "CM MAC:" label, failed login will not
    if ! echo "$page_content" | grep -q "CM MAC:"; then
        log "Authentication failed or page structure unexpected. Please check your Xfinity modem password."
        exit 1
    fi

    # Verify we got the page (check for empty content)
    if [[ -z "$page_content" ]]; then
        log "Failed to fetch data for getmac. No content received. Exiting."
        exit 1
    fi

    # Parse HTML to extract CM MAC address
    modemmac=$(echo "$page_content" | \
        grep -A 2 '<span class="readonlyLabel">CM MAC:</span>' | \
        grep 'class="value"' | \
        sed 's/<[^>]*>//g' | \
        tr -d '[:space:]' | \
        tr -d ':')

    if [[ $modemmac =~ ^[0-9A-Fa-f]{12}$ ]]; then
        log "Successfully retrieved modem CM MAC address: $modemmac"
    else
        log "Unable to parse valid modem CM MAC. Page HTML may have changed. Exiting."
        exit 1
    fi
}

# Collect comprehensive modem data and save to JSON
# Note: Event logs are not available on Xfinity modems
function Xfinity_getdata() {
    log "Fetching data from $modemaddress/network_setup.jst..."
    local page_content
    page_content=$(curl -s --insecure -b "$cookie_jar" "$modemaddress/network_setup.jst")

    # Check for authentication failure by looking for actual page content
    if ! echo "$page_content" | grep -q "CM MAC:"; then
        log "Failed to fetch data page. Cookie may be invalid. Re-logging in..."
        Xfinity_login
        page_content=$(curl -s --insecure -b "$cookie_jar" "$modemaddress/network_setup.jst")
        
        # Check for authentication failure after re-login
        if ! echo "$page_content" | grep -q "CM MAC:"; then
            log "Authentication failed after re-login. Please check your Xfinity modem password in the script configuration."
            exit 1
        fi
    fi

    # Verify we got content
    if [[ -z "$page_content" ]]; then
        log "Failed to fetch data. No content received. Exiting."
        exit 1
    fi

    # Helper function to parse simple key-value pairs
    function get_value() {
        local label="$1"
        echo "$page_content" | grep -A 3 "$label" | \
            grep -v "$label" | \
            sed 's/<[^>]*>//g' | \
            sed '/^[ \t]*$/d' | \
            head -n 1 | \
            xargs
    }

    # Helper function to parse table row data
    function get_row() {
        local table_content="$1"
        local row_label="$2"
        echo "$table_content" | \
            grep -A 1 "${row_label}" | \
            grep -v "${row_label}" | \
            perl -nle 'while(m{<div class="netWidth">([^<]+)</div>}g) { print $1 }'
    }

    # Extract system information
    log "Parsing system information..."
    local modemsystime=$(get_value "Local time:")
    local modemuptime=$(get_value "System Uptime:")

    # Fetch software version from software.jst page
    log "Fetching software version from software.jst..."
    local software_page
    software_page=$(curl -s --insecure -b "$cookie_jar" "$modemaddress/software.jst")
    local modemfw=$(echo "$software_page" | tr -d '\n' | grep -oP '(?<=<span class="value" id="software_image">)[^<]+' | xargs)

    if [[ -z "$modemfw" ]]; then
        log "Failed to parse Software Image Name, falling back to Download Version"
        modemfw=$(get_value "Download Version:")
    fi

    # Create system information JSON object
    local sysinfo_data
    sysinfo_data=$(jq -n \
        --arg systime "$modemsystime" \
        --arg uptime "$modemuptime" \
        --arg firmware "$modemfw" \
        --arg checktime "$checktime" \
        --arg modemtype "$modemtype" \
        --arg modemmac "$modemmac" \
        '{systime: $systime, firmware: $firmware, uptime: $uptime, modemtype: $modemtype, modemmac: $modemmac, checktime: $checktime}')

    # Isolate downstream, upstream, and codeword tables from page
    local ds_table us_table cw_table
    ds_table=$(echo "$page_content" | sed -n '/<div class="netWidth">Downstream<\/div>/,/<\/table>/p')
    us_table=$(echo "$page_content" | sed -n '/<div class="netWidth">Upstream<\/div>/,/<\/table>/p')
    cw_table=$(echo "$page_content" | sed -n '/<td class="row-label acs-th" colspan="35">CM Error Codewords<\/td>/,/<\/table>/p')

    # Parse downstream channel data
    log "Parsing downstream channels..."
    local -a ds_ids ds_freqs ds_snrs ds_powers ds_mods
    mapfile -t ds_ids < <(get_row "$ds_table" "Channel ID")
    mapfile -t ds_freqs < <(get_row "$ds_table" "Frequency")
    mapfile -t ds_snrs < <(get_row "$ds_table" "SNR")
    mapfile -t ds_powers < <(get_row "$ds_table" "Power Level")
    mapfile -t ds_mods < <(get_row "$ds_table" "Modulation")

    # Parse codeword error data
    log "Parsing codeword table..."
    local -a cw_ids cw_unerrored cw_correcteds cw_uncorrects
    mapfile -t cw_ids < <(get_row "$cw_table" "Channel ID")
    mapfile -t cw_unerrored < <(get_row "$cw_table" "Unerrored Codewords")
    mapfile -t cw_correcteds < <(get_row "$cw_table" "Correctable Codewords")
    mapfile -t cw_uncorrects < <(get_row "$cw_table" "Uncorrectable Codewords")

    # Process downstream channels
    local num_channels=${#ds_ids[@]}
    local rx_json_array="[]"
    local rxofdm_json_array="[]"

    log "Processing $num_channels downstream channels..."
    for ((i=0; i<$num_channels; i++)); do
        local portid=${ds_ids[i]}
        local mod=$(echo "${ds_mods[i]}" | xargs)

        # Extract numeric values from strings
        local freq_val=$(echo "${ds_freqs[i]}" | sed 's/[^0-9.-]//g')
        local snr_val=$(echo "${ds_snrs[i]}" | sed 's/[^0-9.-]//g')
        local power_val=$(echo "${ds_powers[i]}" | sed 's/[^0-9.-]//g')

        # Find matching codeword data for this channel
        local octets="n/a" correcteds="n/a" uncorrectds="n/a"
        for ((j=0; j<${#cw_ids[@]}; j++)); do
            if [[ "${cw_ids[j]}" == "$portid" ]]; then
                octets=${cw_unerrored[j]}
                correcteds=${cw_correcteds[j]}
                uncorrectds=${cw_uncorrects[j]}
                break
            fi
        done

        # Create JSON object based on modulation type
        if [[ "$mod" == "OFDM" ]]; then
            local new_obj
            new_obj=$(jq -n \
                --arg portid "$portid" \
                --arg subcarr0freq "$freq_val" \
                --arg plclock "n/a" \
                --arg ncplock "n/a" \
                --arg mdc1lock "n/a" \
                --arg plcpower "$power_val" \
                --arg plcsnr "$snr_val" \
                --arg octets "$octets" \
                --arg correcteds "$correcteds" \
                --arg uncorrectds "$uncorrectds" \
                '{portid: $portid, subcarr0freq: $subcarr0freq, plclock: $plclock, ncplock: $ncplock, mdc1lock: $mdc1lock, plcpower: $plcpower, plcsnr: $plcsnr, octets: $octets, correcteds: $correcteds, uncorrectds: $uncorrectds}')
            rxofdm_json_array=$(echo "$rxofdm_json_array" | jq --argjson obj "$new_obj" '. + [$obj]')
        else
            local new_obj
            new_obj=$(jq -n \
                --arg portid "$portid" \
                --arg frequency "$freq_val" \
                --arg power "$power_val" \
                --arg snr "$snr_val" \
                --arg octets "$octets" \
                --arg correcteds "$correcteds" \
                --arg uncorrectds "$uncorrectds" \
                '{portid: $portid, frequency: $frequency, power: $power, snr: $snr, octets: $octets, correcteds: $correcteds, uncorrectds: $uncorrectds}')
            rx_json_array=$(echo "$rx_json_array" | jq --argjson obj "$new_obj" '. + [$obj]')
        fi
    done

    # Parse upstream channel data
    log "Parsing upstream channels..."
    local -a us_ids us_states us_freqs us_powers us_mods
    mapfile -t us_ids < <(get_row "$us_table" "Channel ID")
    mapfile -t us_states < <(get_row "$us_table" "Lock Status")
    mapfile -t us_freqs < <(get_row "$us_table" "Frequency")
    mapfile -t us_powers < <(get_row "$us_table" "Power Level")
    mapfile -t us_mods < <(get_row "$us_table" "Modulation")

    # Process upstream channels
    local num_us_channels=${#us_ids[@]}
    local tx_json_array="[]"
    local txofdm_json_array="[]"

    log "Processing $num_us_channels upstream channels..."
    for ((i=0; i<$num_us_channels; i++)); do
        # Extract numeric values
        local freq_val=$(echo "${us_freqs[i]}" | sed 's/[^0-9.-]//g')
        local power_val=$(echo "${us_powers[i]}" | sed 's/[^0-9.-]//g')

        # Create JSON object based on modulation type
        if [[ "${us_mods[i]}" == "OFDMA" ]]; then
            local new_obj
            new_obj=$(jq -n \
                --arg portid "${us_ids[i]}" \
                --arg state "${us_states[i]}" \
                --arg subcarr0freq "$freq_val" \
                --arg power "$power_val" \
                '{portid: $portid, state: $state, subcarr0freq: $subcarr0freq, power: $power}')
            txofdm_json_array=$(echo "$txofdm_json_array" | jq --argjson obj "$new_obj" '. + [$obj]')
        else
            local new_obj
            new_obj=$(jq -n \
                --arg portid "${us_ids[i]}" \
                --arg frequency "$freq_val" \
                --arg power "$power_val" \
                '{portid: $portid, frequency: $frequency, power: $power}')
            tx_json_array=$(echo "$tx_json_array" | jq --argjson obj "$new_obj" '. + [$obj]')
        fi
    done

    # Event log not available on Xfinity modems
    log "Event log data not available on Xfinity modems."
    local eventlog_data="[]"

    # Combine all data into single JSON file
    log "Combining all parsed data into JSON..."
    jq -n \
        --argjson sysinfo "$sysinfo_data" \
        --argjson rx "$rx_json_array" \
        --argjson rxofdm "$rxofdm_json_array" \
        --argjson tx "$tx_json_array" \
        --argjson txofdm "$txofdm_json_array" \
        --argjson eventlog "$eventlog_data" \
        '{sysinfo: $sysinfo, rx: $rx, rxofdm: $rxofdm, tx: $tx, txofdm: $txofdm, eventlog: $eventlog}' > "$checkfile"

    log "Modem data collected and saved to $checkfile"
}

#==============================================================================
# MAIN SCRIPT
#==============================================================================

# Initialize script
checktime=$(date +%Y-%m-%d_%H-%M-%S)
log "Modem diagnostic script started at $checktime"

#------------------------------------------------------------------------------
# Modem Detection
#------------------------------------------------------------------------------

# Function to detect modem type at a given address
function detect_modem() {
    local test_address="$1"
    local detected_type="Unknown"
    
    # Fetch login page to identify modem type
    local response=$(curl -s --connect-timeout 3 --max-time 5 "$test_address/login.html" 2>/dev/null)
    
    # Check response for modem-specific signatures
    if echo "$response" | grep -q 'This document has moved to a new'; then
        detected_type="CODA56"
    elif echo "$response" | grep -q '<title>DM1000</title>'; then
        detected_type="DM1000"
    elif echo "$response" | grep -q '<title>403 Forbidden</title>'; then
        # 403 on login.html indicates possible Rogers Xfinity modem
        local root_response=$(curl -s --connect-timeout 3 --max-time 5 "http://$test_address" 2>/dev/null)
        
        if echo "$root_response" | grep -q '<title>Rogers</title>'; then
            detected_type="Xfinity"
        fi
    fi
    
    echo "$detected_type"
}

#------------------------------------------------------------------------------
# Modem Address Resolution
#------------------------------------------------------------------------------

# Check if autodetect is enabled
if [[ "$modemaddress" == "autodetect" ]]; then
    log "Autodetect enabled. Scanning common modem addresses..."
    
    # List of common modem IP addresses to check
    common_addresses=("192.168.100.1" "192.168.0.1" "10.0.0.1" "172.20.0.1")
    
    modemtype="Unknown"
    for address in "${common_addresses[@]}"; do
        log "Checking $address..."
        detected=$(detect_modem "$address")
        
        if [[ "$detected" != "Unknown" ]]; then
            modemaddress="$address"
            modemtype="$detected"
            log "Modem detected at $modemaddress: $modemtype"
            break
        fi
    done
    
    # Exit if no modem was found
    if [[ "$modemtype" == "Unknown" ]]; then
        log "No supported modem found at any common address. Tried: ${common_addresses[*]}"
        log "Please set modemaddress manually in the script configuration."
        exit 1
    fi
else
    log "Using configured modem address: $modemaddress"
    log "Attempting to detect modem model..."
    
    modemtype=$(detect_modem "$modemaddress")
    
    # Exit if modem type could not be determined
    if [[ "$modemtype" == "Unknown" ]]; then
        log "Modem model not detected at $modemaddress"
        log "Either no response or response did not match any supported model signatures."
        exit 1
    else
        log "Modem model detected: $modemtype"
    fi
fi

#------------------------------------------------------------------------------
# Function Mapping
#------------------------------------------------------------------------------

# Map modem-specific functions to generic function names
declare -A modem_login=(
    [CODA56]="CODA56_login"
    [DM1000]="DM1000_login"
    [Xfinity]="Xfinity_login"
)

declare -A modem_clearfec=(
    [CODA56]="CODA56_clearfec"
    [DM1000]="DM1000_clearfec"
    [Xfinity]="Xfinity_clearfec"
)

declare -A modem_getmac=(
    [CODA56]="CODA56_getmac"
    [DM1000]="DM1000_getmac"
    [Xfinity]="Xfinity_getmac"
)

declare -A modem_getdata=(
    [CODA56]="CODA56_getdata"
    [DM1000]="DM1000_getdata"
    [Xfinity]="Xfinity_getdata"
)

# Create initial generic wrapper functions
for func in login clearfec getmac getdata; do
    eval "
    function ${func}() {
        \${modem_${func}[\$modemtype]}
    }
    "
done

#------------------------------------------------------------------------------
# Modem Authentication
#------------------------------------------------------------------------------

log "Logging in to modem"
login

# Identify Xfinity model variants (XB7/XB8) if applicable
if [[ "$modemtype" == "Xfinity-XB8" || "$modemtype" == "Xfinity-XB7" ]]; then
    log "Mapping specific Xfinity model functions..."
    modem_getmac[$modemtype]="${modem_getmac[Xfinity]}"
    modem_getdata[$modemtype]="${modem_getdata[Xfinity]}"
    modem_clearfec[$modemtype]="${modem_clearfec[Xfinity]}"
    
    # Recreate generic wrapper functions with updated modemtype
    for func in clearfec getmac getdata; do
        eval "
        function ${func}() {
            \${modem_${func}[\$modemtype]}
        }
        "
    done
fi

#------------------------------------------------------------------------------
# Data Collection
#------------------------------------------------------------------------------

# Get modem MAC address
log "Getting modem MAC address"
getmac

# Create output directory
log "Creating folder to store check results"
checkdir="$(dirname "$0")/ModemCheck-$modemtype-$modemmac"
mkdir -p "$checkdir"
checkfile="$checkdir/$checktime.json"

# Collect modem diagnostic data
log "Collecting modem diagnostic data"
getdata

# Clear FEC counters
log "Clearing FEC counters"
clearfec

#------------------------------------------------------------------------------
# Speed Testing with iPerf3
#------------------------------------------------------------------------------

# Check if iperf3 tests are enabled
if [[ "$iperf3enabled" == "true" ]]; then
    # Calculate per-stream bandwidth (total bandwidth / number of streams)
    iperf3_upload_per_stream=$((iperf3uploadlimit / iperf3streams))
    iperf3_download_per_stream=$((iperf3downloadlimit / iperf3streams))

    # Run upload test
    log "Running iperf3 upload test with ${iperf3streams} streams capped at ${iperf3uploadlimit} Mbps total..."
    iperf3test_ul=$(timeout 5 iperf3 -c "$iperf3server" -p "$iperf3port" -t 1 -P "$iperf3streams" -b "$iperf3_upload_per_stream"M 2>&1 | \
        grep '\[SUM\].*sender' | awk '{print $6, $7}')
    
    upload_exit_code=$?
    if [[ $upload_exit_code -eq 124 ]]; then
        log "Upload test timed out after 5 seconds"
        iperf3test_ul="Failed"
    elif [[ -n "$iperf3test_ul" && "$iperf3test_ul" != "0.00 bits/sec" ]]; then
        log "Upload test result: $iperf3test_ul"
    else
        log "Upload test failed to return a valid result"
        iperf3test_ul="Failed"
    fi

    sleep 1

    # Run download test
    log "Running iperf3 download test with ${iperf3streams} streams capped at ${iperf3downloadlimit} Mbps total..."
    iperf3test_dl=$(timeout 5 iperf3 -c "$iperf3server" -p "$iperf3port" -t 1 -P "$iperf3streams" -R -b "$iperf3_download_per_stream"M 2>&1 | \
        grep '\[SUM\].*sender' | awk '{print $6, $7}')
    
    download_exit_code=$?
    if [[ $download_exit_code -eq 124 ]]; then
        log "Download test timed out after 5 seconds"
        iperf3test_dl="Failed"
    elif [[ -n "$iperf3test_dl" && "$iperf3test_dl" != "0.00 bits/sec" ]]; then
        log "Download test result: $iperf3test_dl"
    else
        log "Download test failed to return a valid result"
        iperf3test_dl="Failed"
    fi
else
    log "iPerf3 tests are disabled"
    iperf3test_ul="Disabled"
    iperf3test_dl="Disabled"
fi

# Add speed test results and configuration to JSON file
log "Adding iperf3 results to $checkfile"
jq --arg ul "$iperf3test_ul" --arg dl "$iperf3test_dl" \
    --arg ul_limit "$iperf3uploadlimit" --arg dl_limit "$iperf3downloadlimit" \
    '. + {iperf3test_ul: $ul, iperf3test_dl: $dl, iperf3uploadlimit: $ul_limit, iperf3downloadlimit: $dl_limit}' "$checkfile" > "$checkfile.tmp" && \
    mv "$checkfile.tmp" "$checkfile"

log "All done! See you next time."
