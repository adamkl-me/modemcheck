#!/bin/bash

####################################
####💻⚙️ Modem-Check v2.0 ⚙️💻####
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
            '{sysinfo: $sysinfo, rx: $rx, rxofdm: $rxofdm, tx: $tx, txofdm: $txofdm, eventlog: $eventlog}' > "$checkdir/checkresult.json"

      log "Modem data collected and saved to $checkdir/checkresult.json"
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
                "power": .nodes[7].index1
            },
            {
                "portid": .nodes[0].index2,
                "state": .nodes[2].index2,
                "subcarr0freq": .nodes[18].index2,
                "power": .nodes[7].index2
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
            '{sysinfo: $sysinfo, rx: $rx, rxofdm: $rxofdm, tx: $tx, txofdm: $txofdm, eventlog: $eventlog}' > "$checkdir/checkresult.json"

        log "Modem data collected and saved to $checkdir/checkresult.json"
    }

###################
### MAIN SCRIPT ###
###################

  # Print script start message
    checktime=$(date +%Y-%m-%d_%H-%M-%S)
    log "Modem diagnostic script started at $checktime"

### Determine modem model and define appropriate functions ###

  # Determine modem model

      # Pull login page with curl
      RESPONSE=$(curl -s $modemaddress/login.html)

      # Check for unique strings on login page
      if echo "$RESPONSE" | grep -q 'This document has moved to a new'; then
        modemtype="CODA56"
      elif echo "$RESPONSE" | grep -q '<title>DM1000</title>'; then
        modemtype="DM1000"
      else
        modemtype="Unknown"
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
  )

  declare -A modem_clearfec=(
    [CODA56]="CODA56_clearfec"
    [DM1000]="DM1000_clearfec"
  )

  declare -A modem_getmac=(
    [CODA56]="CODA56_getmac"
    [DM1000]="DM1000_getmac"
  )

  declare -A modem_getdata=(
    [CODA56]="CODA56_getdata"
    [DM1000]="DM1000_getdata"
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

  # Get modem MAC
  log "Getting modem MAC address"
  getmac

  # Create folder to store results of checks, and set it as the working directory
  log "Creating folder to store check results"
  checkdir="$(dirname "$0")/ModemCheck-$modemtype-$modemmac/$checktime"
  mkdir -p "$checkdir"

  # Download modem sysinfo, power levels, and event logs
  getdata

  #Clear FEC counters
  log "Clearing FEC counters"
  clearfec

  log "All done! See you next time."
