#!/bin/bash

####################################
####💻⚙️ Modem-Check v3.0 ⚙️💻####
####################################

### GENERAL FUNCTIONS ###

  # Function to create log file and print logs in both terminal and log file
      function log() {
          local message="$1"
          local log_file="$(dirname "$0")/modem-check_logs.txt"
          echo "$(date): $message" | tee -a "$log_file"
      }

  # Define modem address (IP or domain)
    modemaddress="192.168.100.1"

  # Define password for Rogers modem if using one
  ignitepassword="password"

  #iPerf3 test stuff

    iperf3server="IPADDRESS"
    iperf3port="PORT"

### MODEM SPECIFIC FUNCTIONS ###

  # Hitron CODA56 - basic functions

    # Login - not needed for CODA56 but added for compatibility
    function CODA56_login {
        log "Login not required for Hitron CODA56"
    }

    # Function to clear FEC counters in modem
    function CODA56_clearfec() {
        curl ''$modemaddress'/goform/ResetFECCnt' \
      --data-raw 'model=%7B%22portId%22%3A%221%22%2C%22frequency%22%3A%22591000000%22%2C%22modulation%22%3A%222%22%2C%22signalStrength%22%3A%225.700%22%2C%22snr%22%3A%2237.356%22%2C%22dsoctets%22%3A%221113110%22%2C%22correcteds%22%3A%220%22%2C%22uncorrect%22%3A%220%22%2C%22channelId%22%3A%224%22%2C%22resetval%22%3A%221%22%7D' \
      --insecure \
      > /dev/null 2>&1
    }

    # Function to get modem MAC address and set variable $modemmac
    function CODA56_getmac() {
        modemmac=$(curl -s ''$modemaddress'/data/getSysInfo.asp?' --insecure | jq -r '.[0].rfMac' | tr -d ':')
        if [[ $modemmac =~ ^[0-9A-Fa-f]{12}$ ]]; then
            log "Successfully retrieved modem WAN MAC address: $modemmac"
        else
            log "Unable to get valid modem MAC, exiting script"
            exit 1
        fi
    }

  # Hitron CODA56 - Create JSON object with modem sysinfo, power levels, and event logs

    function CODA56_getdata() {
      # Modem sysinfo + model and check run time
        sysinfo_data=$(curl -s $modemaddress/data/getSysInfo.asp --insecure |
        jq --arg checktime "$checktime" --arg modemtype "$modemtype" --arg modemmac "$modemmac" \
         '.[0] | {systime: .systemTime, firmware: .swVersion, uptime: .systemUptime, modemtype: $modemtype, modemmac: $modemmac, checktime: $checktime}')
        modemfw=$(echo "$sysinfo_data" | jq -r '.firmware')
        modemuptime=$(echo "$sysinfo_data" | jq -r '.uptime')
        modemsystime=$(echo "$sysinfo_data" | jq -r '.systime')

      # RX Data
        rx_data=$(curl -s $modemaddress/data/dsinfo.asp --insecure |
        jq 'map(del(.modulation, .channelId) |
          .portid = .portId | del(.portId) |
          .power = .signalStrength | del(.signalStrength) |
          .octets = .dsoctets | del(.dsoctets) |
          .uncorrectds = .uncorrect | del(.uncorrect) |
          {portid, frequency, power, snr, octets, correcteds, uncorrectds})')

      # RX OFDM Data
        rxofdm_data=$(curl -s $modemaddress/data/dsofdminfo.asp --insecure |
        jq 'map(del(.ffttype) |
          .portid = .receive | del(.receive) |
          .subcarr0freq = .Subcarr0freqFreq | del(.Subcarr0freqFreq) |
          .plcsnr = .SNR | del(.SNR) |
          .octets = .dsoctets | del(.dsoctets) |
          .uncorrectds = .uncorrect | del(.uncorrect) |
          {portid, subcarr0freq, plclock, ncplock, mdc1lock, plcpower, plcsnr, octets, correcteds, uncorrectds})')

      # TX Data
        tx_data=$(curl -s $modemaddress/data/usinfo.asp --insecure |
        jq 'map(del(.bandwidth, .modtype, .scdmaMode, .channelId) |
          .portid = .portId | del(.portId) |
          .power = .signalStrength | del(.signalStrength) |
          {portid, frequency, power})')

      # TX OFDM Data
        txofdm_data=$(curl -s $modemaddress/data/usofdminfo.asp --insecure |
        jq 'map(del(.digAtten, .digAttenBo, .channelBw, .repPower, .fftVal) |
          .portid = .uschindex | del(.uschindex) |
          .subcarr0freq = .frequency | del(.frequency) |
          .power = .repPower1_6 | del(.repPower1_6) |
          {portid, state, subcarr0freq, power})')

      # Event Log Data
        eventlog_data=$(curl -s $modemaddress/data/status_log.asp --insecure |
        jq 'map(del(.index, .priority) |
          .id = .type | del(.type) |
          {time, id, event})')

      # Combine all data into a single JSON object
        jq -n --argjson sysinfo "$sysinfo_data" --argjson rx "$rx_data" --argjson rxofdm "$rxofdm_data" --argjson tx "$tx_data" --argjson txofdm "$txofdm_data" --argjson eventlog "$eventlog_data" \
            '{sysinfo: $sysinfo, rx: $rx, rxofdm: $rxofdm, tx: $tx, txofdm: $txofdm, eventlog: $eventlog}' > "$checkfile"

      log "Modem data collected and saved to $checkfile"
    }

  # Sercomm DM1000 - basic functions

    function DM1000_login {
        # Define variables
        url="$modemaddress/setup.cgi"
        user="technician"
        pass="sercommdocsis"
        data="login_user=$user&pws=$(echo -n "$pass" | base64)&submit=Apply&is_parent_window=1&todo=login&this_file=login.html&next_file=&language=en&message=&passwd=$(echo -n "$pass" | base64)&cur_passwd="
        # Perform login request
        curl -s --insecure --data-raw "$data" "$url" > /dev/null 2>&1

        # Check if login was successful
        response=$(curl -s ''$modemaddress'/setup.cgi?todo=Cm_Status' --insecure)
        if [[ -n "$response" ]]; then
            log "Login successful"
        else
            log "Login failed, exiting script"
            exit 1
        fi
    }

    function DM1000_clearfec() {
        curl ''$modemaddress'/setup.cgi' \
        --data-raw 'todo=reset_FEC_Counters&this_file=status.html&next_file=status.html' \
        --insecure \
        > /dev/null 2>&1
    }

    function DM1000_getmac() {
        modemmac=$(curl -s ''$modemaddress'/setup.cgi?todo=Interface_param' --insecure | grep '"name":"wan0"' | sed 's/.*"mac":"\([^"]*\)".*/\1/' | tr -d ':' | tr '[:lower:]' '[:upper:]')
        if [[ $modemmac =~ ^[0-9A-Fa-f]{12}$ ]]; then
            log "Successfully retrieved modem WAN MAC address: $modemmac"
        else
            log "Unable to get valid modem MAC, exiting script"
            exit 1
        fi
    }

  # Sercomm DM1000 - Create JSON object with modem sysinfo, power levels, and event logs

    function DM1000_getdata() {
        # Fetch the status.html page
        status_page=$(curl -s $modemaddress/status.html)

        # Extract the time_date value
        modemsystime=$(echo "$status_page" | grep -oP '(?<=<td  align="left" id ="time_date">)[^<]+')

        # Extract the uptime value using awk
        modemuptime=$(echo "$status_page" | awk -F'<td align="left">' '/<th width="20%" height="30" align="left"><script language="javascript" type="text\/javascript">dw\(str_status16\);<\/script>:/ {getline; print $2}' | awk -F'</td>' '{print $1}')

        # Fetch the Version_Info JSON
        version_info=$(curl -s ''$modemaddress'/setup.cgi?todo=Version_Info' --insecure)

        # Extract the fwinfo value
        modemfw=$(echo "$version_info" | jq -r '.nodes[] | select(.fwinfo) | .fwinfo')

        # Create sysinfo JSON object
        sysinfo_data=$(jq -n --arg systime "$modemsystime" --arg uptime "$modemuptime" --arg firmware "$modemfw" --arg checktime "$checktime" --arg modemtype "$modemtype" --arg modemmac "$modemmac" \
            '{systime: $systime, firmware: $firmware, uptime: $uptime, modemtype: $modemtype, modemmac: $modemmac, checktime: $checktime}')

        # RX Data
        rx_data=$(curl -s $modemaddress/setup.cgi?todo=RF_DS_param --insecure |
        jq '.nodes | map(del(.DCIDD, .qamD) |
            .portid = .numD | del(.numD) |
            .frequency = .FreqD | del(.FreqD) |
            .power = .PowerD | del(.PowerD) |
            .snr = .SNRD | del(.SNRD) |
            .octets = .octetsD | del(.octetsD) |
            .correcteds = .correctedsD | del(.correctedsD) |
            .uncorrectds = .uncorrectedsD | del(.uncorrectedsD) |
            {portid, frequency, power, snr, octets, correcteds, uncorrectds})')

        # RX OFDM Data
        rxofdm_data=$(curl -s $modemaddress/setup.cgi?todo=RF_DS_31_param --insecure |
        jq '.nodes | map(del(.fftType, .AV_Pilot, .AV_Data) |
            .portid = .num | del(.num) |
            .subcarr0freq = .OFDMFreq | del(.OFDMFreq) |
            .plclock = .PLC | del(.PLC) |
            .ncplock = .NCP | del(.NCP) |
            .mdc1lock = .MDC1 | del(.MDC1) |
            .plcpower = .PLC_power | del(.PLC_power) |
            .plcsnr = .AV_PLC | del(.AV_PLC) |
            {portid, subcarr0freq, plclock, ncplock, mdc1lock, plcpower, plcsnr, octets: "n/a", correcteds: "n/a", uncorrectds: "n/a"})')

        # TX Data
        tx_data=$(curl -s $modemaddress/setup.cgi?todo=RF_US_param --insecure |
        jq '.nodes | map(del(.rate, .modulation, .channelType, .upstream) |
            .portid = .num | del(.num) |
            .frequency = .Freq | del(.Freq) |
            .power = .rep_power | del(.rep_power) |
            {portid, frequency, power})')

        # TX OFDM Data
        txofdm_data=$(curl -s $modemaddress/setup.cgi?todo=RF_US_31_param --insecure |
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

        # Event Log Data
        eventlog_data=$(curl -s $modemaddress/setup.cgi?todo=Event_Log --insecure |
        jq '.nodes | map(del(.lv) |
            .time = .d | del(.d) |
            .event = .text | del(.text) |
            {time, id, event})')

        # Combine all data into a single JSON object
        jq -n --argjson sysinfo "$sysinfo_data" --argjson rx "$rx_data" --argjson rxofdm "$rxofdm_data" --argjson tx "$tx_data" --argjson txofdm "$txofdm_data" --argjson eventlog "$eventlog_data" \
            '{sysinfo: $sysinfo, rx: $rx, rxofdm: $rxofdm, tx: $tx, txofdm: $txofdm, eventlog: $eventlog}' > "$checkfile"

        log "Modem data collected and saved to $checkfile"
    }

  # Rogers Xfinity - basic functions

      # Variables
      igniteusername="admin"
      cookie_jar="$(dirname "$0")/modem-check_cookies.txt"

    function Xfinity_login {
        log "Attempting login to Rogers Xfinity Modem at $modemaddress..."

        # Clean up old cookies if they exist
        rm -f "$cookie_jar"

        # Build the POST data from variables
        local post_data="username=$igniteusername&password=$ignitepassword&locale=false"

        # Perform the login request using curl
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

        log "Verifying login and detecting model by checking network_setup.jst..."
        local network_page_content
        # Use network_setup.jst to verify login and get model info
        network_page_content=$(curl -s --insecure -b "$cookie_jar" "$modemaddress/network_setup.jst")

        if [[ -z "$network_page_content" || $(echo "$network_page_content" | grep -iq "login") ]]; then
             log "Rogers Xfinity modem login failed. Check credentials or modem IP. Exiting."
             exit 1
        else
             log "Rogers Xfinity modem login successful."
             
             # Now check for specific model and update modemtype
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

    function Xfinity_clearfec() {
        log "FEC clear function not yet implemented for Rogers Xfinity modem."
    }

    function Xfinity_getmac() {
        # Fetch the network setup page using our session cookie
        log "Fetching $modemaddress/network_setup.jst for MAC address..."
        local page_content
        page_content=$(curl -s --insecure -b "$cookie_jar" "$modemaddress/network_setup.jst")

        # Check if we got the page, or if we got a login redirect
        if [[ -z "$page_content" || $(echo "$page_content" | grep -iq "login") ]]; then
            log "Failed to fetch data for getmac. Cookie may be invalid. Exiting."
            exit 1
        fi

        # Parse the HTML to find the CM MAC
        modemmac=$(echo "$page_content" | \
            grep -A 2 '<span class="readonlyLabel">CM MAC:</span>' | \
            grep 'class="value"' | \
            sed 's/<[^>]*>//g' | \
            tr -d '[:space:]' | \
            tr -d ':')

        if [[ $modemmac =~ ^[0-9A-Fa-f]{12}$ ]]; then
            log "Successfully retrieved modem CM MAC address: $modemmac"
        else
            log "Unable to parse valid modem CM MAC from network_setup.jst. Page HTML may have changed. Exiting script."
            exit 1
        fi
    }

# Rogers Xfinity Modem - Create JSON object with modem sysinfo + power levels (no logs available on Xfinity modems)

    function Xfinity_getdata() {
        log "Fetching data from $modemaddress/network_setup.jst..."
        local page_content
        page_content=$(curl -s --insecure -b "$cookie_jar" "$modemaddress/network_setup.jst")

        # Check if we got content, otherwise, the cookie might be invalid
        if [[ -z "$page_content" || $(echo "$page_content" | grep -iq "login") ]]; then
            log "Failed to fetch data page. Cookie may be invalid. Re-logging in..."
            Xfinity_login # Try to log in again
            page_content=$(curl -s --insecure -b "$cookie_jar" "$modemaddress/network_setup.jst")
            if [[ -z "$page_content" || $(echo "$page_content" | grep -iq "login") ]]; then
                 log "Failed to fetch data after re-login. Exiting."
                 exit 1
            fi
        fi

        # --- 1. Helper Functions ---

        # Helper to parse simple key-value pairs (for sysinfo)
        function get_value() {
            local label="$1"
            echo "$page_content" | grep -A 3 "$label" | \
                grep -v "$label" | \
                sed 's/<[^>]*>//g' | \
                sed '/^[ \t]*$/d' | \
                head -n 1 | \
                xargs
        }

        # Helper to parse a pivoted table row
        function get_row() {
            local table_content="$1"
            local row_label="$2"
            echo "$table_content" | \
                grep -A 1 "${row_label}" | \
                grep -v "${row_label}" | \
                perl -nle 'while(m{<div class="netWidth">([^<]+)</div>}g) { print $1 }'
        }

        # --- 2. System Info ---
        log "Parsing System Info..."
        local modemsystime=$(get_value "Local time:")
        local modemuptime=$(get_value "System Uptime:")

        # Fetch software.jst page for Software Image Name
        log "Fetching software version from software.jst..."
        local software_page
        software_page=$(curl -s --insecure -b "$cookie_jar" "$modemaddress/software.jst")
        local modemfw=$(echo "$software_page" | tr -d '\n' | grep -oP '(?<=<span class="value" id="software_image">)[^<]+' | xargs)

        if [[ -z "$modemfw" ]]; then
            log "Failed to parse Software Image Name, falling back to Download Version"
            modemfw=$(get_value "Download Version:")
        fi

        local sysinfo_data
        sysinfo_data=$(jq -n \
            --arg systime "$modemsystime" \
            --arg uptime "$modemuptime" \
            --arg firmware "$modemfw" \
            --arg checktime "$checktime" \
            --arg modemtype "$modemtype" \
            --arg modemmac "$modemmac" \
            '{systime: $systime, firmware: $firmware, uptime: $uptime, modemtype: $modemtype, modemmac: $modemmac, checktime: $checktime}')

        # --- 3. Isolate Tables ---
        local ds_table
        local us_table
        local cw_table
        ds_table=$(echo "$page_content" | sed -n '/<div class="netWidth">Downstream<\/div>/,/<\/table>/p')
        us_table=$(echo "$page_content" | sed -n '/<div class="netWidth">Upstream<\/div>/,/<\/table>/p')
        cw_table=$(echo "$page_content" | sed -n '/<td class="row-label acs-th" colspan="35">CM Error Codewords<\/td>/,/<\/table>/p')

        # --- 4. Process Downstream & Codewords ---
        log "Parsing Downstream channels..."
        local -a ds_ids;       mapfile -t ds_ids       < <(get_row "$ds_table" "Channel ID")
        local -a ds_freqs;     mapfile -t ds_freqs     < <(get_row "$ds_table" "Frequency")
        local -a ds_snrs;      mapfile -t ds_snrs      < <(get_row "$ds_table" "SNR")
        local -a ds_powers;    mapfile -t ds_powers    < <(get_row "$ds_table" "Power Level")
        local -a ds_mods;      mapfile -t ds_mods      < <(get_row "$ds_table" "Modulation")

        log "Parsing Codeword table..."
        local -a cw_ids;         mapfile -t cw_ids         < <(get_row "$cw_table" "Channel ID")
        local -a cw_unerrored;   mapfile -t cw_unerrored   < <(get_row "$cw_table" "Unerrored Codewords")
        local -a cw_correcteds;  mapfile -t cw_correcteds  < <(get_row "$cw_table" "Correctable Codewords")
        local -a cw_uncorrects;  mapfile -t cw_uncorrects  < <(get_row "$cw_table" "Uncorrectable Codewords")

        local num_channels=${#ds_ids[@]}
        local rx_json_array="[]"
        local rxofdm_json_array="[]"

        log "Processing $num_channels Downstream channels..."
        for ((i=0; i<$num_channels; i++)); do
            local portid=${ds_ids[i]}
            local mod=${ds_mods[i]}

            # Trim whitespace from mod variable
            mod=$(echo "$mod" | xargs)

            # --- UPDATED SED COMMANDS ---
            local freq_val=$(echo "${ds_freqs[i]}" | sed 's/[^0-9.-]//g')
            local snr_val=$(echo "${ds_snrs[i]}" | sed 's/[^0-9.-]//g')
            local power_val=$(echo "${ds_powers[i]}" | sed 's/[^0-9.-]//g')

            # Find matching codeword data
            local octets="n/a"
            local correcteds="n/a"
            local uncorrectds="n/a"
            for ((j=0; j<${#cw_ids[@]}; j++)); do
                if [[ "${cw_ids[j]}" == "$portid" ]]; then
                    octets=${cw_unerrored[j]}
                    correcteds=${cw_correcteds[j]}
                    uncorrectds=${cw_uncorrects[j]}
                    break
                fi
            done

            if [[ "$mod" == "OFDM" ]]; then
                # This is an OFDM channel
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
                # This is a regular SC-QAM channel
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

        # --- 5. Process Upstream ---
        log "Parsing Upstream channels..."
        local -a us_ids;     mapfile -t us_ids     < <(get_row "$us_table" "Channel ID")
        local -a us_states;  mapfile -t us_states  < <(get_row "$us_table" "Lock Status")
        local -a us_freqs;   mapfile -t us_freqs   < <(get_row "$us_table" "Frequency")
        local -a us_powers;  mapfile -t us_powers  < <(get_row "$us_table" "Power Level")
        local -a us_mods;    mapfile -t us_mods    < <(get_row "$us_table" "Modulation")

        local num_us_channels=${#us_ids[@]}
        local tx_json_array="[]"
        local txofdm_json_array="[]"

        log "Processing $num_us_channels Upstream channels..."
        for ((i=0; i<$num_us_channels; i++)); do

            # --- UPDATED SED COMMANDS ---
            # This regex strips all non-numeric characters except . and -
            local freq_val=$(echo "${us_freqs[i]}" | sed 's/[^0-9.-]//g')
            local power_val=$(echo "${us_powers[i]}" | sed 's/[^0-9.-]//g')

            if [[ "${us_mods[i]}" == "OFDMA" ]]; then
                # This is an OFDMA channel
                local new_obj
                new_obj=$(jq -n \
                    --arg portid "${us_ids[i]}" \
                    --arg state "${us_states[i]}" \
                    --arg subcarr0freq "$freq_val" \
                    --arg power "$power_val" \
                    '{portid: $portid, state: $state, subcarr0freq: $subcarr0freq, power: $power}')
                txofdm_json_array=$(echo "$txofdm_json_array" | jq --argjson obj "$new_obj" '. + [$obj]')
            else
                # This is a regular ATDMA/TDMA channel
                local new_obj
                new_obj=$(jq -n \
                    --arg portid "${us_ids[i]}" \
                    --arg frequency "$freq_val" \
                    --arg power "$power_val" \
                    '{portid: $portid, frequency: $frequency, power: $power}')
                tx_json_array=$(echo "$tx_json_array" | jq --argjson obj "$new_obj" '. + [$obj]')
            fi
        done

        # --- 6. Event Log (Still Missing) ---
        log "Event log data not found on this page. Setting to empty."
        local eventlog_data="[]"

        # --- 7. Combine and Save JSON ---
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

###################
### MAIN SCRIPT ###
###################

  # Print script start message
    checktime=$(date +%Y-%m-%d_%H-%M-%S)
    log "Modem diagnostic script started at $checktime"

### Determine modem model and define appropriate functions ###

  # Determine modem model

        # Set a default type
        modemtype="Unknown"
        log "Attempting to detect modem model at $modemaddress..."

        # Pull login page with curl
        RESPONSE=$(curl -s $modemaddress/login.html)

        # Check for unique strings on login page
        if echo "$RESPONSE" | grep -q 'This document has moved to a new'; then
          modemtype="CODA56"
        elif echo "$RESPONSE" | grep -q '<title>DM1000</title>'; then
          modemtype="DM1000"
        elif echo "$RESPONSE" | grep -q '<title>403 Forbidden</title>'; then
          # A 403 on login.html could be a Rogers Xfinity modem.
          # Per request, we'll now check the root page for the Rogers title.
          log "Got 403 on login.html. Checking http://$modemaddress for '<title>Rogers</title>'..."
          ROOT_RESPONSE=$(curl -s "http://$modemaddress")

          if echo "$ROOT_RESPONSE" | grep -q '<title>Rogers</title>'; then
              modemtype="Xfinity"
          else
              log "Got 403, but root page did not contain Rogers title. Model remains Unknown."
          fi
        else
          log "login.html response did not match any known model signatures."
        fi

        # Print results of model check and end script run if unknown
        if [[ "$modemtype" == "Unknown" ]]; then
          log "Modem model not detected, exiting"
          exit 0
        else
          log "Modem model detected: $modemtype"
        fi

  # Define functions based on model

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

  for func in login clearfec getmac getdata; do
    eval "
    function ${func}() {
      \${modem_${func}[\$modemtype]}
    }
    "
  done

### Log in to modem and get diagnostic data ###

  # Log in to modem
  log "Logging in to modem"
  login
  # At this point, $modemtype might have been changed (e.g., to "Xfinity-XB8")

  # 2. Add new keys to the arrays to handle the more specific model types
  #    This maps "Xfinity-XB8" to use the same functions as "Xfinity"
  if [[ "$modemtype" == "Xfinity-XB8" || "$modemtype" == "Xfinity-XB7" ]]; then
      log "Mapping specific Xfinity model functions..."
      modem_getmac[$modemtype]="${modem_getmac[Xfinity]}"
      modem_getdata[$modemtype]="${modem_getdata[Xfinity]}"
      modem_clearfec[$modemtype]="${modem_clearfec[Xfinity]}"
  fi

  # 3. Now that $modemtype is finalized, define the REST of the functions
  for func in clearfec getmac getdata; do
    eval "
    function ${func}() {
      \${modem_${func}[\$modemtype]}
    }
    "
  done

  # Get modem MAC
  log "Getting modem MAC address"
  getmac

  # Create folder to store results of checks
  log "Creating folder to store check results"
  checkdir="$(dirname "$0")/ModemCheck-$modemtype-$modemmac"
  mkdir -p "$checkdir"

  # Set the full path for the timestamped JSON file
  checkfile="$checkdir/$checktime.json"

  # Download modem sysinfo, power levels, and event logs
  getdata

  #Clear FEC counters
  log "Clearing FEC counters"
  clearfec

  #Run iPerf3 tests to check speeds
  log "Running iperf3 upload test..."
  iperf3test_ul=$(iperf3 -c $iperf3server -p $iperf3port -t 1 -P 4 2>&1 | grep '\[SUM\].*sender' | awk '{print $6, $7}')

  if [ -n "$iperf3test_ul" ]; then
      log "Upload test result: $iperf3test_ul"
  else
      log "Upload test failed to return a valid result."
      iperf3test_ul="n/a"
  fi

  sleep 1

  log "Running iperf3 download test..."
  iperf3test_dl=$(iperf3 -c $iperf3server -p $iperf3port -t 1 -P 4 -R 2>&1 | grep '\[SUM\].*sender' | awk '{print $6, $7}')

  if [ -n "$iperf3test_dl" ]; then
      log "Download test result: $iperf3test_dl"
  else
      log "Download test failed to return a valid result."
      iperf3test_dl="n/a"
  fi

  # Add iperf3 results to the JSON file
  log "Adding iperf3 results to $checkfile"
  jq --arg ul "$iperf3test_ul" --arg dl "$iperf3test_dl" \
     '. + {iperf3test_ul: $ul, iperf3test_dl: $dl}' "$checkfile" > "$checkfile.tmp" && mv "$checkfile.tmp" "$checkfile"

  log "All done! See you next time."
