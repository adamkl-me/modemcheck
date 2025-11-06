package main

import (
	"context"
	"crypto/tls"
	"encoding/base64"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/http/cookiejar"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"time"
)

// Constants for configuration and limits
const (
	// Queue configuration
	maxQueueSize    = 100
	queueMaxAgeDays = 14

	// Log configuration
	logMaxAgeDays = 30

	// HTTP timeouts
	defaultHTTPTimeout = 10 * time.Second
	iperf3Timeout      = 5 * time.Second
	pingTimeout        = 30 * time.Second

	// Test configuration
	defaultPingCount = 25

	// File size limits
	maxFileUploadSize = 10 * 1024 * 1024 // 10MB
)

// Configuration holds all user-configurable settings
type Configuration struct {
	ModemAddress        string
	IgnitePassword      string
	Iperf3Enabled       bool
	Iperf3Server        string
	Iperf3Port          string
	Iperf3Streams       int
	Iperf3UploadLimit   int
	Iperf3DownloadLimit int
	Silent              bool
	NoLogs              bool
	// Cloud mode settings
	EnableCloud bool // Enable cloud upload (always saves locally)
	CloudHost   string
	CloudPort   string
	CloudAPIKey string // API key for authentication
	CloudPath   string
}

// UploadQueueEntry represents a failed upload that needs to be retried
type UploadQueueEntry struct {
	FilePath     string    `json:"file_path"`
	ModemID      string    `json:"modem_id"`
	Timestamp    string    `json:"timestamp"`
	Attempts     int       `json:"attempts"`
	LastAttempt  time.Time `json:"last_attempt"`
	LastError    string    `json:"last_error"`
	FirstFailure time.Time `json:"first_failure"`
}

// UploadQueue manages failed uploads
type UploadQueue struct {
	FailedUploads []UploadQueueEntry `json:"failed_uploads"`
}

// ModemCheck represents the main application state
type ModemCheck struct {
	config       Configuration
	client       *http.Client
	modemType    string
	modemAddress string
	modemMAC     string
	checkTime    string
	checkDir     string
	checkFile    string
	logFile      *os.File
}

// SysInfo represents system information from the modem
type SysInfo struct {
	SysTime   string `json:"systime"`
	Firmware  string `json:"firmware"`
	Uptime    string `json:"uptime"`
	ModemType string `json:"modemtype"`
	ModemMAC  string `json:"modemmac"`
	CheckTime string `json:"checktime"`
}

// ChannelData represents various channel data structures
type RXChannel struct {
	PortID      string `json:"portid"`
	Frequency   string `json:"frequency"`
	Power       string `json:"power"`
	SNR         string `json:"snr"`
	Octets      string `json:"octets"`
	Correcteds  string `json:"correcteds"`
	Uncorrectds string `json:"uncorrectds"`
}

type RXOFDMChannel struct {
	PortID       string `json:"portid"`
	Subcarr0Freq string `json:"subcarr0freq"`
	PLCLock      string `json:"plclock"`
	NCPLock      string `json:"ncplock"`
	MDC1Lock     string `json:"mdc1lock"`
	PLCPower     string `json:"plcpower"`
	PLCSNR       string `json:"plcsnr"`
	Octets       string `json:"octets"`
	Correcteds   string `json:"correcteds"`
	Uncorrectds  string `json:"uncorrectds"`
}

type TXChannel struct {
	PortID    string `json:"portid"`
	Frequency string `json:"frequency"`
	Power     string `json:"power"`
}

type TXOFDMAChannel struct {
	PortID         string `json:"portid"`
	State          string `json:"state"`
	Subcarr0Freq   string `json:"subcarr0freq"`
	Power          string `json:"power"`
	ActiveSCs      string `json:"activescs,omitempty"`
	ExcludedSCs    string `json:"excludedscs,omitempty"`
	NotUsedSCs     string `json:"notusedscs,omitempty"`
	Minislots      string `json:"minislots,omitempty"`
	InterfaceSpeed string `json:"interfacespeed,omitempty"`
}

type EventLog struct {
	Time  string `json:"time"`
	ID    string `json:"id"`
	Event string `json:"event"`
}

type ModemData struct {
	SysInfo             SysInfo          `json:"sysinfo"`
	RX                  []RXChannel      `json:"rx"`
	RXOFDM              []RXOFDMChannel  `json:"rxofdm"`
	TX                  []TXChannel      `json:"tx"`
	TXOFDM              []TXOFDMAChannel `json:"txofdm"`
	EventLog            []EventLog       `json:"eventlog"`
	Iperf3TestUL        string           `json:"iperf3test_ul,omitempty"`
	Iperf3TestDL        string           `json:"iperf3test_dl,omitempty"`
	Iperf3UploadLimit   string           `json:"iperf3uploadlimit,omitempty"`
	Iperf3DownloadLimit string           `json:"iperf3downloadlimit,omitempty"`
	PingGoogleAvg       string           `json:"ping_google_avg,omitempty"`
	PingGoogleLoss      string           `json:"ping_google_loss,omitempty"`
	PingCloudflareAvg   string           `json:"ping_cloudflare_avg,omitempty"`
	PingCloudflareLoss  string           `json:"ping_cloudflare_loss,omitempty"`
}

// NewModemCheck creates a new ModemCheck instance
func NewModemCheck(config Configuration) *ModemCheck {
	// Create HTTP client with custom transport (ignore SSL errors)
	jar, _ := cookiejar.New(nil)
	transport := &http.Transport{
		TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
	}
	client := &http.Client{
		Transport: transport,
		Jar:       jar,
		Timeout:   defaultHTTPTimeout,
	}

	return &ModemCheck{
		config:    config,
		client:    client,
		checkTime: time.Now().Format("2006-01-02_15-04-05"),
	}
}

// Log writes to both stdout and log file
func (m *ModemCheck) Log(message string) {
	timestamp := time.Now().Format("Mon Jan 2 03:04:05 PM MST 2006")
	logMessage := fmt.Sprintf("%s: %s\n", timestamp, message)

	// Print to stdout unless silent mode is enabled
	if !m.config.Silent {
		fmt.Print(logMessage)
	}

	// Write to log file unless NoLogs is enabled
	if m.logFile != nil && !m.config.NoLogs {
		m.logFile.WriteString(logMessage)
	}
}

// InitLogFile initializes the log file
func (m *ModemCheck) InitLogFile() error {
	// Skip log file creation if NoLogs is enabled
	if m.config.NoLogs {
		return nil
	}

	logPath := filepath.Join(filepath.Dir(os.Args[0]), "modem-check_logs.txt")
	file, err := os.OpenFile(logPath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	m.logFile = file
	return nil
}

// DetectModem attempts to detect the modem type at a given address
func (m *ModemCheck) DetectModem(address string) string {
	// First, try CODA-specific endpoint (CODA45/CODA56 have no login page)
	codaResp, err := m.client.Get(fmt.Sprintf("http://%s/data/getSysInfo.asp", address))
	if err == nil {
		defer codaResp.Body.Close()
		codaBody, _ := io.ReadAll(codaResp.Body)
		codaStr := string(codaBody)
		// Check if it's valid JSON with CODA-specific fields
		if strings.Contains(codaStr, "rfMac") && strings.Contains(codaStr, "systemUptime") {
			// Distinguish between CODA45 (2 ports) and CODA56 (1 port)
			linkResp, err := m.client.Get(fmt.Sprintf("http://%s/data/getLinkStatus.asp", address))
			if err == nil {
				defer linkResp.Body.Close()
				linkBody, _ := io.ReadAll(linkResp.Body)

				// Parse JSON array to count ethernet ports
				var linkStatus []map[string]interface{}
				if json.Unmarshal(linkBody, &linkStatus) == nil {
					if len(linkStatus) > 1 {
						return "CODA45"
					}
				}
			}
			return "CODA56"
		}
	}

	// Try login.html for other modem types
	resp, err := m.client.Get(fmt.Sprintf("http://%s/login.html", address))
	if err != nil {
		return "Unknown"
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	bodyStr := string(body)

	// Check for redirect message (CODA alternative detection)
	if strings.Contains(bodyStr, "This document has moved to a new") {
		// Check link status to determine model
		linkResp, err := m.client.Get(fmt.Sprintf("http://%s/data/getLinkStatus.asp", address))
		if err == nil {
			defer linkResp.Body.Close()
			linkBody, _ := io.ReadAll(linkResp.Body)
			var linkStatus []map[string]interface{}
			if json.Unmarshal(linkBody, &linkStatus) == nil {
				if len(linkStatus) > 1 {
					return "CODA45"
				}
			}
		}
		return "CODA56"
	} else if strings.Contains(bodyStr, "<title>DM1000</title>") {
		return "DM1000"
	} else if strings.Contains(bodyStr, "<title>403 Forbidden</title>") {
		// Check root page for Rogers/Xfinity
		rootResp, err := m.client.Get(fmt.Sprintf("http://%s", address))
		if err == nil {
			defer rootResp.Body.Close()
			rootBody, _ := io.ReadAll(rootResp.Body)
			if strings.Contains(string(rootBody), "<title>Rogers</title>") {
				return "Xfinity"
			}
		}
	}

	return "Unknown"
}

// AutoDetectModem scans common addresses for modems
func (m *ModemCheck) AutoDetectModem() error {
	m.Log("Autodetect enabled. Scanning common modem addresses...")

	commonAddresses := []string{"192.168.100.1", "192.168.0.1", "10.0.0.1", "172.20.0.1"}

	for _, address := range commonAddresses {
		m.Log(fmt.Sprintf("Checking %s...", address))
		detected := m.DetectModem(address)

		if detected != "Unknown" {
			m.modemAddress = address
			m.modemType = detected
			m.Log(fmt.Sprintf("Modem detected at %s: %s", m.modemAddress, m.modemType))
			return nil
		}
	}

	return fmt.Errorf("no supported modem found at any common address. Tried: %v", commonAddresses)
}

// CODA Functions (CODA45/CODA56)
func (m *ModemCheck) CODALogin() error {
	m.Log("Login not required for Hitron CODA modem")
	return nil
}

func (m *ModemCheck) CODAClearFEC() error {
	data := `model=%7B%22portId%22%3A%221%22%2C%22frequency%22%3A%22591000000%22%2C%22modulation%22%3A%222%22%2C%22signalStrength%22%3A%225.700%22%2C%22snr%22%3A%2237.356%22%2C%22dsoctets%22%3A%221113110%22%2C%22correcteds%22%3A%220%22%2C%22uncorrect%22%3A%220%22%2C%22channelId%22%3A%224%22%2C%22resetval%22%3A%221%22%7D`
	_, err := m.client.Post(fmt.Sprintf("http://%s/goform/ResetFECCnt", m.modemAddress), "application/x-www-form-urlencoded", strings.NewReader(data))
	return err
}

func (m *ModemCheck) CODAGetMAC() error {
	resp, err := m.client.Get(fmt.Sprintf("http://%s/data/getSysInfo.asp?", m.modemAddress))
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	var sysInfo []map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&sysInfo); err != nil {
		return err
	}

	if len(sysInfo) > 0 {
		if rfMac, ok := sysInfo[0]["rfMac"].(string); ok {
			m.modemMAC = strings.ReplaceAll(rfMac, ":", "")
			if matched, _ := regexp.MatchString(`^[0-9A-Fa-f]{12}$`, m.modemMAC); matched {
				m.Log(fmt.Sprintf("Successfully retrieved modem WAN MAC address: %s", m.modemMAC))
				return nil
			}
		}
	}

	return fmt.Errorf("unable to get valid modem MAC")
}

func (m *ModemCheck) CODAGetData() (*ModemData, error) {
	data := &ModemData{}

	// Get system info
	resp, err := m.client.Get(fmt.Sprintf("http://%s/data/getSysInfo.asp", m.modemAddress))
	if err != nil {
		return nil, err
	}
	var sysInfoArray []map[string]interface{}
	json.NewDecoder(resp.Body).Decode(&sysInfoArray)
	resp.Body.Close()

	if len(sysInfoArray) > 0 {
		data.SysInfo = SysInfo{
			SysTime:   getString(sysInfoArray[0], "systemTime"),
			Firmware:  getString(sysInfoArray[0], "swVersion"),
			Uptime:    getString(sysInfoArray[0], "systemUptime"),
			ModemType: m.modemType,
			ModemMAC:  m.modemMAC,
			CheckTime: m.checkTime,
		}
	}

	// Get RX data
	resp, _ = m.client.Get(fmt.Sprintf("http://%s/data/dsinfo.asp", m.modemAddress))
	var rxRaw []map[string]interface{}
	json.NewDecoder(resp.Body).Decode(&rxRaw)
	resp.Body.Close()

	for _, ch := range rxRaw {
		data.RX = append(data.RX, RXChannel{
			PortID:      getString(ch, "portId"),
			Frequency:   getString(ch, "frequency"),
			Power:       getString(ch, "signalStrength"),
			SNR:         getString(ch, "snr"),
			Octets:      getString(ch, "dsoctets"),
			Correcteds:  getString(ch, "correcteds"),
			Uncorrectds: getString(ch, "uncorrect"),
		})
	}

	// Get RX OFDM data
	resp, _ = m.client.Get(fmt.Sprintf("http://%s/data/dsofdminfo.asp", m.modemAddress))
	var rxofdmRaw []map[string]interface{}
	json.NewDecoder(resp.Body).Decode(&rxofdmRaw)
	resp.Body.Close()

	for _, ch := range rxofdmRaw {
		data.RXOFDM = append(data.RXOFDM, RXOFDMChannel{
			PortID:       getString(ch, "receive"),
			Subcarr0Freq: getString(ch, "Subcarr0freqFreq"),
			PLCLock:      getString(ch, "plclock"),
			NCPLock:      getString(ch, "ncplock"),
			MDC1Lock:     getString(ch, "mdc1lock"),
			PLCPower:     getString(ch, "plcpower"),
			PLCSNR:       getString(ch, "SNR"),
			Octets:       getString(ch, "dsoctets"),
			Correcteds:   getString(ch, "correcteds"),
			Uncorrectds:  getString(ch, "uncorrect"),
		})
	}

	// Get TX data
	resp, _ = m.client.Get(fmt.Sprintf("http://%s/data/usinfo.asp", m.modemAddress))
	var txRaw []map[string]interface{}
	json.NewDecoder(resp.Body).Decode(&txRaw)
	resp.Body.Close()

	for _, ch := range txRaw {
		data.TX = append(data.TX, TXChannel{
			PortID:    getString(ch, "portId"),
			Frequency: getString(ch, "frequency"),
			Power:     getString(ch, "signalStrength"),
		})
	}

	// Get TX OFDM data
	resp, _ = m.client.Get(fmt.Sprintf("http://%s/data/usofdminfo.asp", m.modemAddress))
	var txofdmRaw []map[string]interface{}
	json.NewDecoder(resp.Body).Decode(&txofdmRaw)
	resp.Body.Close()

	for _, ch := range txofdmRaw {
		data.TXOFDM = append(data.TXOFDM, TXOFDMAChannel{
			PortID:       getString(ch, "uschindex"),
			State:        getString(ch, "state"),
			Subcarr0Freq: getString(ch, "frequency"),
			Power:        getString(ch, "repPower1_6"),
		})
	}

	// Get event log
	resp, _ = m.client.Get(fmt.Sprintf("http://%s/data/status_log.asp", m.modemAddress))
	var eventLogRaw []map[string]interface{}
	json.NewDecoder(resp.Body).Decode(&eventLogRaw)
	resp.Body.Close()

	for _, event := range eventLogRaw {
		data.EventLog = append(data.EventLog, EventLog{
			Time:  getString(event, "time"),
			ID:    getString(event, "type"),
			Event: getString(event, "event"),
		})
	}

	return data, nil
}

// DM1000 Functions
func (m *ModemCheck) DM1000Login() error {
	user := "technician"
	pass := "sercommdocsis"
	passB64 := base64.StdEncoding.EncodeToString([]byte(pass))

	data := fmt.Sprintf("login_user=%s&pws=%s&submit=Apply&is_parent_window=1&todo=login&this_file=login.html&next_file=&language=en&message=&passwd=%s&cur_passwd=",
		user, passB64, passB64)

	_, err := m.client.Post(fmt.Sprintf("http://%s/setup.cgi", m.modemAddress),
		"application/x-www-form-urlencoded", strings.NewReader(data))
	if err != nil {
		return err
	}

	// Verify login
	resp, err := m.client.Get(fmt.Sprintf("http://%s/setup.cgi?todo=Cm_Status", m.modemAddress))
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	if len(body) > 0 {
		m.Log("Login successful")
		return nil
	}

	return fmt.Errorf("login failed")
}

func (m *ModemCheck) DM1000ClearFEC() error {
	data := "todo=reset_FEC_Counters&this_file=status.html&next_file=status.html"
	_, err := m.client.Post(fmt.Sprintf("http://%s/setup.cgi", m.modemAddress),
		"application/x-www-form-urlencoded", strings.NewReader(data))
	return err
}

func (m *ModemCheck) DM1000GetMAC() error {
	resp, err := m.client.Get(fmt.Sprintf("http://%s/setup.cgi?todo=Interface_param", m.modemAddress))
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	re := regexp.MustCompile(`"name":"wan0".*?"mac":"([^"]+)"`)
	matches := re.FindStringSubmatch(string(body))

	if len(matches) > 1 {
		m.modemMAC = strings.ToUpper(strings.ReplaceAll(matches[1], ":", ""))
		if matched, _ := regexp.MatchString(`^[0-9A-F]{12}$`, m.modemMAC); matched {
			m.Log(fmt.Sprintf("Successfully retrieved modem WAN MAC address: %s", m.modemMAC))
			return nil
		}
	}

	return fmt.Errorf("unable to get valid modem MAC")
}

func (m *ModemCheck) DM1000GetData() (*ModemData, error) {
	data := &ModemData{}

	// Get status page for uptime and system time
	resp, _ := m.client.Get(fmt.Sprintf("http://%s/status.html", m.modemAddress))
	statusBody, _ := io.ReadAll(resp.Body)
	resp.Body.Close()

	// Extract system time
	timeRe := regexp.MustCompile(`<td  align="left" id ="time_date">([^<]+)`)
	if matches := timeRe.FindStringSubmatch(string(statusBody)); len(matches) > 1 {
		data.SysInfo.SysTime = strings.TrimSpace(matches[1])
	}

	// Extract uptime - matches pattern: dw(str_status16) followed by <td> with uptime value
	// Example: <th>...str_status16...</th><td align="left">2 d: 19 h: 2 m</td>
	uptimeRe := regexp.MustCompile(`(?s)str_status16.*?<td.*?align="left">([^<]+)</td>`)
	if matches := uptimeRe.FindStringSubmatch(string(statusBody)); len(matches) > 1 {
		data.SysInfo.Uptime = strings.TrimSpace(matches[1])
	}

	// Get firmware version
	resp, _ = m.client.Get(fmt.Sprintf("http://%s/setup.cgi?todo=Version_Info", m.modemAddress))
	var versionInfo map[string]interface{}
	json.NewDecoder(resp.Body).Decode(&versionInfo)
	resp.Body.Close()

	if nodes, ok := versionInfo["nodes"].([]interface{}); ok {
		for _, node := range nodes {
			if nodeMap, ok := node.(map[string]interface{}); ok {
				if fwinfo, ok := nodeMap["fwinfo"].(string); ok {
					data.SysInfo.Firmware = fwinfo
					break
				}
			}
		}
	}

	data.SysInfo.ModemType = m.modemType
	data.SysInfo.ModemMAC = m.modemMAC
	data.SysInfo.CheckTime = m.checkTime

	// Get RX data
	resp, _ = m.client.Get(fmt.Sprintf("http://%s/setup.cgi?todo=RF_DS_param", m.modemAddress))
	var rxData map[string]interface{}
	json.NewDecoder(resp.Body).Decode(&rxData)
	resp.Body.Close()

	if nodes, ok := rxData["nodes"].([]interface{}); ok {
		for _, node := range nodes {
			if ch, ok := node.(map[string]interface{}); ok {
				data.RX = append(data.RX, RXChannel{
					PortID:      getString(ch, "numD"),
					Frequency:   getString(ch, "FreqD"),
					Power:       getString(ch, "PowerD"),
					SNR:         getString(ch, "SNRD"),
					Octets:      getString(ch, "octetsD"),
					Correcteds:  getString(ch, "correctedsD"),
					Uncorrectds: getString(ch, "uncorrectedsD"),
				})
			}
		}
	}

	// Get RX OFDM data
	resp, _ = m.client.Get(fmt.Sprintf("http://%s/setup.cgi?todo=RF_DS_31_param", m.modemAddress))
	var rxofdmData map[string]interface{}
	json.NewDecoder(resp.Body).Decode(&rxofdmData)
	resp.Body.Close()

	if nodes, ok := rxofdmData["nodes"].([]interface{}); ok {
		for _, node := range nodes {
			if ch, ok := node.(map[string]interface{}); ok {
				data.RXOFDM = append(data.RXOFDM, RXOFDMChannel{
					PortID:       getString(ch, "num"),
					Subcarr0Freq: getString(ch, "OFDMFreq"),
					PLCLock:      getString(ch, "PLC"),
					NCPLock:      getString(ch, "NCP"),
					MDC1Lock:     getString(ch, "MDC1"),
					PLCPower:     getString(ch, "PLC_power"),
					PLCSNR:       getString(ch, "AV_PLC"),
					Octets:       "n/a",
					Correcteds:   "n/a",
					Uncorrectds:  "n/a",
				})
			}
		}
	}

	// Get TX data
	resp, _ = m.client.Get(fmt.Sprintf("http://%s/setup.cgi?todo=RF_US_param", m.modemAddress))
	var txData map[string]interface{}
	json.NewDecoder(resp.Body).Decode(&txData)
	resp.Body.Close()

	if nodes, ok := txData["nodes"].([]interface{}); ok {
		for _, node := range nodes {
			if ch, ok := node.(map[string]interface{}); ok {
				data.TX = append(data.TX, TXChannel{
					PortID:    getString(ch, "num"),
					Frequency: getString(ch, "Freq"),
					Power:     getString(ch, "rep_power"),
				})
			}
		}
	}

	// Get TX OFDMA data
	resp, _ = m.client.Get(fmt.Sprintf("http://%s/setup.cgi?todo=RF_US_31_param", m.modemAddress))
	var txofdmData map[string]interface{}
	json.NewDecoder(resp.Body).Decode(&txofdmData)
	resp.Body.Close()

	if nodes, ok := txofdmData["nodes"].([]interface{}); ok && len(nodes) > 0 {
		if nodeMap, ok := nodes[0].(map[string]interface{}); ok {
			// DM1000 has index1 and index2 for two OFDMA channels
			if index1, ok := nodeMap["index1"].(string); ok && index1 != "" {
				data.TXOFDM = append(data.TXOFDM, m.extractDM1000OFDMA(nodes, "index1"))
			}
			if index2, ok := nodeMap["index2"].(string); ok && index2 != "" {
				data.TXOFDM = append(data.TXOFDM, m.extractDM1000OFDMA(nodes, "index2"))
			}
		}
	}

	// Get event log
	resp, _ = m.client.Get(fmt.Sprintf("http://%s/setup.cgi?todo=Event_Log", m.modemAddress))
	var eventData map[string]interface{}
	json.NewDecoder(resp.Body).Decode(&eventData)
	resp.Body.Close()

	if nodes, ok := eventData["nodes"].([]interface{}); ok {
		for _, node := range nodes {
			if event, ok := node.(map[string]interface{}); ok {
				data.EventLog = append(data.EventLog, EventLog{
					Time:  getString(event, "d"),
					ID:    getString(event, "id"),
					Event: getString(event, "text"),
				})
			}
		}
	}

	return data, nil
}

func (m *ModemCheck) extractDM1000OFDMA(nodes []interface{}, indexKey string) TXOFDMAChannel {
	channel := TXOFDMAChannel{}
	fieldMap := map[int]string{
		0:  "portid",
		2:  "state",
		7:  "power",
		18: "subcarr0freq",
		21: "activescs",
		22: "excludedscs",
		23: "notusedscs",
		24: "minislots",
		25: "interfacespeed",
	}

	for idx, node := range nodes {
		if nodeMap, ok := node.(map[string]interface{}); ok {
			if value, ok := nodeMap[indexKey].(string); ok {
				switch fieldMap[idx] {
				case "portid":
					channel.PortID = value
				case "state":
					channel.State = value
				case "power":
					channel.Power = value
				case "subcarr0freq":
					channel.Subcarr0Freq = value
				case "activescs":
					channel.ActiveSCs = value
				case "excludedscs":
					channel.ExcludedSCs = value
				case "notusedscs":
					channel.NotUsedSCs = value
				case "minislots":
					channel.Minislots = value
				case "interfacespeed":
					channel.InterfaceSpeed = value
				}
			}
		}
	}
	return channel
}

// Xfinity Functions
func (m *ModemCheck) XfinityLogin() error {
	m.Log("Attempting login to Rogers Xfinity Modem...")

	username := "admin"
	postData := fmt.Sprintf("username=%s&password=%s&locale=false", username, m.config.IgnitePassword)

	req, _ := http.NewRequest("POST", fmt.Sprintf("http://%s/check.jst", m.modemAddress),
		strings.NewReader(postData))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("User-Agent", "Mozilla/5.0")
	req.Header.Set("Referer", fmt.Sprintf("http://%s/", m.modemAddress))

	resp, err := m.client.Do(req)
	if err != nil {
		m.Log(fmt.Sprintf("Login POST request failed: %v", err))
		return err
	}
	resp.Body.Close()

	// Verify login
	m.Log("Verifying login and detecting model...")
	resp, err = m.client.Get(fmt.Sprintf("http://%s/network_setup.jst", m.modemAddress))
	if err != nil {
		m.Log(fmt.Sprintf("Verification GET request failed: %v", err))
		return err
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	bodyStr := string(body)

	if !strings.Contains(bodyStr, "CM MAC:") {
		return fmt.Errorf("Rogers Xfinity modem login failed. Check credentials")
	}

	m.Log("Rogers Xfinity modem login successful.")

	// Detect XB7 vs XB8
	if strings.Contains(bodyStr, "XB8") {
		m.modemType = "XB8"
		m.Log(fmt.Sprintf("Detected specific model: %s", m.modemType))
	} else if strings.Contains(bodyStr, "XB7") {
		m.modemType = "XB7"
		m.Log(fmt.Sprintf("Detected specific model: %s", m.modemType))
	}

	return nil
}

func (m *ModemCheck) XfinityClearFEC() error {
	m.Log("FEC clear function not yet implemented for Rogers Xfinity modem.")
	return nil
}

func (m *ModemCheck) XfinityGetMAC() error {
	m.Log("Fetching MAC address from network_setup.jst...")
	resp, err := m.client.Get(fmt.Sprintf("http://%s/network_setup.jst", m.modemAddress))
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	bodyStr := string(body)

	if !strings.Contains(bodyStr, "CM MAC:") {
		return fmt.Errorf("authentication failed or page structure unexpected")
	}

	// Try multiple regex patterns to extract MAC address
	patterns := []string{
		`<span class="readonlyLabel">CM MAC:</span>.*?class="value">([^<]+)`,
		`<span class="readonlyLabel">CM MAC:</span>.*?<span class="value">([^<]+)`,
		`CM MAC:.*?class="value">([^<]+)`,
		`CM MAC:.*?<span[^>]*>([0-9A-Fa-f:]+)</span>`,
		`CM MAC:[^>]*>([0-9A-Fa-f:]+)<`,
	}

	for _, pattern := range patterns {
		re := regexp.MustCompile(pattern)
		matches := re.FindStringSubmatch(bodyStr)

		if len(matches) > 1 {
			mac := strings.ReplaceAll(strings.TrimSpace(matches[1]), ":", "")
			mac = strings.ReplaceAll(mac, " ", "")
			mac = strings.ToUpper(mac)

			if matched, _ := regexp.MatchString(`^[0-9A-F]{12}$`, mac); matched {
				m.modemMAC = mac
				m.Log(fmt.Sprintf("Successfully retrieved modem CM MAC address: %s", m.modemMAC))
				return nil
			}
		}
	}

	// If we still haven't found it, try a more general approach
	// Look for any MAC address pattern in the vicinity of "CM MAC:"
	macPattern := regexp.MustCompile(`([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}`)

	// Find the position of "CM MAC:" in the body
	cmMacIndex := strings.Index(bodyStr, "CM MAC:")
	if cmMacIndex != -1 {
		// Look in the next 500 characters after "CM MAC:"
		searchWindow := bodyStr[cmMacIndex:min(cmMacIndex+500, len(bodyStr))]
		if macMatch := macPattern.FindString(searchWindow); macMatch != "" {
			mac := strings.ReplaceAll(macMatch, ":", "")
			mac = strings.ReplaceAll(mac, "-", "")
			mac = strings.ToUpper(mac)

			if len(mac) == 12 {
				m.modemMAC = mac
				m.Log(fmt.Sprintf("Successfully retrieved modem CM MAC address: %s", m.modemMAC))
				return nil
			}
		}
	}

	return fmt.Errorf("unable to parse valid modem CM MAC")
}

func (m *ModemCheck) XfinityGetData() (*ModemData, error) {
	m.Log("Fetching data from network_setup.jst...")
	resp, err := m.client.Get(fmt.Sprintf("http://%s/network_setup.jst", m.modemAddress))
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	pageContent, _ := io.ReadAll(resp.Body)
	pageStr := string(pageContent)

	if !strings.Contains(pageStr, "CM MAC:") {
		m.Log("Failed to fetch data page. Re-logging in...")
		m.XfinityLogin()
		resp, _ = m.client.Get(fmt.Sprintf("http://%s/network_setup.jst", m.modemAddress))
		pageContent, _ = io.ReadAll(resp.Body)
		pageStr = string(pageContent)
		resp.Body.Close()
	}

	data := &ModemData{}

	// Get system info
	data.SysInfo.SysTime = m.extractValue(pageStr, "Local time:")
	data.SysInfo.Uptime = m.extractValue(pageStr, "System Uptime:")
	data.SysInfo.ModemType = m.modemType
	data.SysInfo.ModemMAC = m.modemMAC
	data.SysInfo.CheckTime = m.checkTime

	// Get firmware from software.jst
	resp, _ = m.client.Get(fmt.Sprintf("http://%s/software.jst", m.modemAddress))
	softwareBody, _ := io.ReadAll(resp.Body)
	resp.Body.Close()

	fwRe := regexp.MustCompile(`<span class="value" id="software_image">([^<]+)`)
	if matches := fwRe.FindStringSubmatch(string(softwareBody)); len(matches) > 1 {
		data.SysInfo.Firmware = strings.TrimSpace(matches[1])
	}

	// Parse downstream channels
	data.RX, data.RXOFDM = m.parseXfinityDownstream(pageStr)

	// Parse upstream channels
	data.TX, data.TXOFDM = m.parseXfinityUpstream(pageStr)

	// Event log not available on Xfinity
	data.EventLog = []EventLog{}

	return data, nil
}

func (m *ModemCheck) extractValue(page, label string) string {
	// Try pattern 1: <span class="readonlyLabel">Label:</span><span class="value">Value</span>
	re := regexp.MustCompile(regexp.QuoteMeta(label) + `[^<]*</span>\s*<span class="value">\s*([^<]+)`)
	if matches := re.FindStringSubmatch(page); len(matches) > 1 {
		return strings.TrimSpace(matches[1])
	}

	// Try pattern 2: Label: <span ...>Value</span>
	re = regexp.MustCompile(regexp.QuoteMeta(label) + `.*?<[^>]+>([^<]+)`)
	if matches := re.FindStringSubmatch(page); len(matches) > 1 {
		return strings.TrimSpace(matches[1])
	}
	return ""
}

func (m *ModemCheck) parseXfinityDownstream(page string) ([]RXChannel, []RXOFDMChannel) {
	rxChannels := []RXChannel{}
	rxofdmChannels := []RXOFDMChannel{}

	// Extract downstream table (use (?s) for multiline matching)
	dsTableRe := regexp.MustCompile(`(?s)<div class="netWidth">Downstream</div>.*?</table>`)
	dsTable := dsTableRe.FindString(page)

	// Extract codeword table
	cwTableRe := regexp.MustCompile(`(?s)CM Error Codewords.*?</table>`)
	cwTable := cwTableRe.FindString(page)

	// Parse channel IDs, frequencies, SNR, power, modulation
	channelIDs := m.extractTableRow(dsTable, "Channel ID")
	frequencies := m.extractTableRow(dsTable, "Frequency")
	snrs := m.extractTableRow(dsTable, "SNR")
	powers := m.extractTableRow(dsTable, "Power Level")
	modulations := m.extractTableRow(dsTable, "Modulation")

	// Parse codeword data
	cwIDs := m.extractTableRow(cwTable, "Channel ID")
	unerrored := m.extractTableRow(cwTable, "Unerrored Codewords")
	correctable := m.extractTableRow(cwTable, "Correctable Codewords")
	uncorrectable := m.extractTableRow(cwTable, "Uncorrectable Codewords")

	// Create codeword map
	cwMap := make(map[string]map[string]string)
	for i, id := range cwIDs {
		cwMap[id] = map[string]string{
			"unerrored":     getAtIndex(unerrored, i),
			"correctable":   getAtIndex(correctable, i),
			"uncorrectable": getAtIndex(uncorrectable, i),
		}
	}

	// Build channel structs
	for i, id := range channelIDs {
		mod := getAtIndex(modulations, i)
		freq := cleanNumeric(getAtIndex(frequencies, i))
		snr := cleanNumeric(getAtIndex(snrs, i))
		power := cleanNumeric(getAtIndex(powers, i))

		cw := cwMap[id]
		octets := cw["unerrored"]
		correcteds := cw["correctable"]
		uncorrectds := cw["uncorrectable"]

		if mod == "OFDM" {
			rxofdmChannels = append(rxofdmChannels, RXOFDMChannel{
				PortID:       id,
				Subcarr0Freq: freq,
				PLCLock:      "n/a",
				NCPLock:      "n/a",
				MDC1Lock:     "n/a",
				PLCPower:     power,
				PLCSNR:       snr,
				Octets:       octets,
				Correcteds:   correcteds,
				Uncorrectds:  uncorrectds,
			})
		} else {
			rxChannels = append(rxChannels, RXChannel{
				PortID:      id,
				Frequency:   freq,
				Power:       power,
				SNR:         snr,
				Octets:      octets,
				Correcteds:  correcteds,
				Uncorrectds: uncorrectds,
			})
		}
	}

	return rxChannels, rxofdmChannels
}

func (m *ModemCheck) parseXfinityUpstream(page string) ([]TXChannel, []TXOFDMAChannel) {
	txChannels := []TXChannel{}
	txofdmaChannels := []TXOFDMAChannel{}

	// Extract upstream table (use (?s) for multiline matching)
	usTableRe := regexp.MustCompile(`(?s)<div class="netWidth">Upstream</div>.*?</table>`)
	usTable := usTableRe.FindString(page)

	channelIDs := m.extractTableRow(usTable, "Channel ID")
	lockStatus := m.extractTableRow(usTable, "Lock Status")
	frequencies := m.extractTableRow(usTable, "Frequency")
	powers := m.extractTableRow(usTable, "Power Level")
	modulations := m.extractTableRow(usTable, "Modulation")

	for i, id := range channelIDs {
		mod := getAtIndex(modulations, i)
		freq := cleanNumeric(getAtIndex(frequencies, i))
		power := cleanNumeric(getAtIndex(powers, i))
		state := getAtIndex(lockStatus, i)

		if mod == "OFDMA" {
			txofdmaChannels = append(txofdmaChannels, TXOFDMAChannel{
				PortID:       id,
				State:        state,
				Subcarr0Freq: freq,
				Power:        power,
			})
		} else {
			txChannels = append(txChannels, TXChannel{
				PortID:    id,
				Frequency: freq,
				Power:     power,
			})
		}
	}

	return txChannels, txofdmaChannels
}

func (m *ModemCheck) extractTableRow(table, rowLabel string) []string {
	results := []string{}

	// Match the row more flexibly - handle both <th> and <td> tags
	re := regexp.MustCompile(`(?s)<t[hd][^>]*>\s*` + regexp.QuoteMeta(rowLabel) + `\s*</t[hd]>(.*?)</tr>`)
	rowMatch := re.FindStringSubmatch(table)

	if len(rowMatch) < 2 {
		return results
	}

	// Extract cell values from <div class="netWidth">
	cellRe := regexp.MustCompile(`<div class="netWidth">([^<]+)</div>`)
	cells := cellRe.FindAllStringSubmatch(rowMatch[1], -1)

	for _, cell := range cells {
		if len(cell) > 1 {
			results = append(results, strings.TrimSpace(cell[1]))
		}
	}

	return results
}

// Speed test functions
func (m *ModemCheck) RunSpeedTests(data *ModemData) {
	if !m.config.Iperf3Enabled {
		m.Log("iPerf3 tests are disabled")
		data.Iperf3TestUL = "Disabled"
		data.Iperf3TestDL = "Disabled"
		return
	}

	perStreamUL := m.config.Iperf3UploadLimit / m.config.Iperf3Streams
	perStreamDL := m.config.Iperf3DownloadLimit / m.config.Iperf3Streams

	// Upload test
	m.Log(fmt.Sprintf("Running iperf3 upload test with %d streams capped at %d Mbps total...",
		m.config.Iperf3Streams, m.config.Iperf3UploadLimit))

	uploadResult := m.runIperf3("-c", m.config.Iperf3Server, "-p", m.config.Iperf3Port,
		"-t", "1", "-P", strconv.Itoa(m.config.Iperf3Streams), "-b", fmt.Sprintf("%dM", perStreamUL))

	if uploadResult != "" {
		m.Log(fmt.Sprintf("Upload test result: %s", uploadResult))
		data.Iperf3TestUL = uploadResult
	} else {
		m.Log("Upload test failed to return a valid result")
		data.Iperf3TestUL = "Failed"
	}

	time.Sleep(1 * time.Second)

	// Download test
	m.Log(fmt.Sprintf("Running iperf3 download test with %d streams capped at %d Mbps total...",
		m.config.Iperf3Streams, m.config.Iperf3DownloadLimit))

	downloadResult := m.runIperf3("-c", m.config.Iperf3Server, "-p", m.config.Iperf3Port,
		"-t", "1", "-P", strconv.Itoa(m.config.Iperf3Streams), "-R", "-b", fmt.Sprintf("%dM", perStreamDL))

	if downloadResult != "" {
		m.Log(fmt.Sprintf("Download test result: %s", downloadResult))
		data.Iperf3TestDL = downloadResult
	} else {
		m.Log("Download test failed to return a valid result")
		data.Iperf3TestDL = "Failed"
	}

	data.Iperf3UploadLimit = strconv.Itoa(m.config.Iperf3UploadLimit)
	data.Iperf3DownloadLimit = strconv.Itoa(m.config.Iperf3DownloadLimit)
}

func (m *ModemCheck) runIperf3(args ...string) string {
	ctx, cancel := context.WithTimeout(context.Background(), iperf3Timeout)
	defer cancel()

	cmd := exec.CommandContext(ctx, "iperf3", args...)
	output, err := cmd.CombinedOutput()

	if err != nil {
		return ""
	}

	// Parse output for [SUM] sender line
	lines := strings.Split(string(output), "\n")
	for _, line := range lines {
		if strings.Contains(line, "[SUM]") && strings.Contains(line, "sender") {
			fields := strings.Fields(line)
			if len(fields) >= 7 {
				return fields[5] + " " + fields[6]
			}
		}
	}

	return ""
}

// RunPingTests runs ping tests to Google and Cloudflare concurrently
func (m *ModemCheck) RunPingTests(data *ModemData) {
	m.Log("Running ping tests to google.ca and one.one.one.one...")

	// Use channels to collect results from concurrent goroutines
	type pingResult struct {
		host string
		avg  string
		loss string
	}
	results := make(chan pingResult, 2)

	// Start both pings concurrently
	go func() {
		avg, loss := m.runPing("google.ca", defaultPingCount)
		results <- pingResult{"google.ca", avg, loss}
	}()

	go func() {
		avg, loss := m.runPing("one.one.one.one", defaultPingCount)
		results <- pingResult{"one.one.one.one", avg, loss}
	}()

	// Collect results from both pings
	for i := 0; i < 2; i++ {
		result := <-results
		if result.avg != "" {
			m.Log(fmt.Sprintf("%s: avg %s ms, %s packet loss", result.host, result.avg, result.loss))
			if result.host == "google.ca" {
				data.PingGoogleAvg = result.avg
				data.PingGoogleLoss = result.loss
			} else {
				data.PingCloudflareAvg = result.avg
				data.PingCloudflareLoss = result.loss
			}
		} else {
			m.Log(fmt.Sprintf("Ping to %s failed", result.host))
			if result.host == "google.ca" {
				data.PingGoogleAvg = "Failed"
				data.PingGoogleLoss = "N/A"
			} else {
				data.PingCloudflareAvg = "Failed"
				data.PingCloudflareLoss = "N/A"
			}
		}
	}
}

func (m *ModemCheck) runPing(host string, count int) (avg string, loss string) {
	ctx, cancel := context.WithTimeout(context.Background(), pingTimeout)
	defer cancel()

	// Windows uses -n for count, Linux/macOS use -c
	countFlag := "-c"
	if runtime.GOOS == "windows" {
		countFlag = "-n"
	}

	cmd := exec.CommandContext(ctx, "ping", countFlag, strconv.Itoa(count), host)
	output, err := cmd.CombinedOutput()

	if err != nil {
		return "", ""
	}

	outputStr := string(output)

	// Parse packet loss
	// Linux/macOS: "25 packets transmitted, 25 received, 0% packet loss"
	// Windows: "Packets: Sent = 25, Received = 25, Lost = 0 (0% loss)"
	lossRe := regexp.MustCompile(`(\d+)% (?:packet )?loss`)
	if matches := lossRe.FindStringSubmatch(outputStr); len(matches) > 1 {
		loss = matches[1] + "%"
	}

	// Parse average ping time
	// Linux: "rtt min/avg/max/mdev = 12.345/23.456/34.567/5.678 ms"
	// macOS: "round-trip min/avg/max/stddev = 12.345/23.456/34.567/5.678 ms"
	// Windows: "Minimum = 12ms, Maximum = 34ms, Average = 23ms"
	if runtime.GOOS == "windows" {
		avgRe := regexp.MustCompile(`Average = (\d+)ms`)
		if matches := avgRe.FindStringSubmatch(outputStr); len(matches) > 1 {
			avg = matches[1]
		}
	} else {
		avgRe := regexp.MustCompile(`(?:rtt|round-trip) min/avg/max/(?:mdev|stddev) = [\d.]+/([\d.]+)/`)
		if matches := avgRe.FindStringSubmatch(outputStr); len(matches) > 1 {
			avg = matches[1]
		}
	}

	return avg, loss
}

// Helper functions
func getString(m map[string]interface{}, key string) string {
	if val, ok := m[key]; ok {
		return fmt.Sprintf("%v", val)
	}
	return ""
}

func getAtIndex(slice []string, index int) string {
	if index < len(slice) {
		return slice[index]
	}
	return ""
}

func cleanNumeric(s string) string {
	re := regexp.MustCompile(`[^0-9.-]`)
	return re.ReplaceAllString(s, "")
}

// uploadToCloudWithModemID uploads a file to the cloud server with a specific modem ID
func (m *ModemCheck) uploadToCloudWithModemID(localFile string, modemID string) error {
	m.Log(fmt.Sprintf("Uploading to cloud server: %s:%s", m.config.CloudHost, m.config.CloudPort))

	// Validate API key
	if m.config.CloudAPIKey == "" {
		return fmt.Errorf("no API key provided (CloudAPIKey is required)")
	}

	// Open local file
	file, err := os.Open(localFile)
	if err != nil {
		return fmt.Errorf("failed to open local file: %v", err)
	}
	defer file.Close()

	// Read file contents
	fileContents, err := io.ReadAll(file)
	if err != nil {
		return fmt.Errorf("failed to read local file: %v", err)
	}

	// Prepare remote directory and filename
	remoteDirName := modemID
	remoteFileName := filepath.Base(localFile)

	// Smart protocol detection: use HTTP for localhost/local IPs, HTTPS for external domains
	protocol := "https"
	host := strings.ToLower(m.config.CloudHost)
	if strings.Contains(host, "localhost") || strings.Contains(host, "127.0.0.1") ||
		strings.HasPrefix(host, "192.168.") || strings.HasPrefix(host, "10.") ||
		strings.HasPrefix(host, "172.16.") {
		protocol = "http"
	}

	// Build upload URL
	uploadURL := fmt.Sprintf("%s://%s:%s/cgi-bin/upload.py", protocol, m.config.CloudHost, m.config.CloudPort)

	// Create HTTP request with multipart form data
	body := &strings.Builder{}
	body.WriteString(fmt.Sprintf("--boundary123\r\n"))
	body.WriteString(fmt.Sprintf("Content-Disposition: form-data; name=\"api_key\"\r\n\r\n"))
	body.WriteString(fmt.Sprintf("%s\r\n", m.config.CloudAPIKey))
	body.WriteString(fmt.Sprintf("--boundary123\r\n"))
	body.WriteString(fmt.Sprintf("Content-Disposition: form-data; name=\"modem_id\"\r\n\r\n"))
	body.WriteString(fmt.Sprintf("%s\r\n", remoteDirName))
	body.WriteString(fmt.Sprintf("--boundary123\r\n"))
	body.WriteString(fmt.Sprintf("Content-Disposition: form-data; name=\"filename\"\r\n\r\n"))
	body.WriteString(fmt.Sprintf("%s\r\n", remoteFileName))
	body.WriteString(fmt.Sprintf("--boundary123\r\n"))
	body.WriteString(fmt.Sprintf("Content-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n", remoteFileName))
	body.WriteString(fmt.Sprintf("Content-Type: application/json\r\n\r\n"))
	body.Write(fileContents)
	body.WriteString(fmt.Sprintf("\r\n--boundary123--\r\n"))

	// Create HTTP client with timeout
	client := &http.Client{
		Timeout: 30 * time.Second,
	}

	// Create POST request
	req, err := http.NewRequest("POST", uploadURL, strings.NewReader(body.String()))
	if err != nil {
		return fmt.Errorf("failed to create HTTP request: %v", err)
	}
	req.Header.Set("Content-Type", "multipart/form-data; boundary=boundary123")

	// Send request
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("failed to upload file: %v", err)
	}
	defer resp.Body.Close()

	// Check response
	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("upload failed with status %d: %s", resp.StatusCode, string(respBody))
	}

	m.Log(fmt.Sprintf("Successfully uploaded %s to %s/%s", remoteFileName, m.config.CloudPath, remoteDirName))
	return nil
}

// UploadToCloud uploads the JSON file to the cloud server using current modem info
func (m *ModemCheck) UploadToCloud(localFile string) error {
	if !m.config.EnableCloud {
		return nil // Silently skip if cloud is disabled
	}

	// Use current modem type and MAC to build modem ID
	modemID := fmt.Sprintf("%s-%s", m.modemType, m.modemMAC)
	return m.uploadToCloudWithModemID(localFile, modemID)
}

// Queue management
const queueFilePath = "ModemCheck-Results/.upload_queue.json"

// loadUploadQueue loads the upload queue from disk
func loadUploadQueue() (*UploadQueue, error) {
	queue := &UploadQueue{FailedUploads: []UploadQueueEntry{}}

	data, err := os.ReadFile(queueFilePath)
	if err != nil {
		if os.IsNotExist(err) {
			return queue, nil // Return empty queue if file doesn't exist
		}
		return nil, err
	}

	if err := json.Unmarshal(data, queue); err != nil {
		return nil, err
	}

	return queue, nil
}

// saveUploadQueue saves the upload queue to disk
func saveUploadQueue(queue *UploadQueue) error {
	// Ensure directory exists
	dir := filepath.Dir(queueFilePath)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return err
	}

	data, err := json.MarshalIndent(queue, "", "  ")
	if err != nil {
		return err
	}

	return os.WriteFile(queueFilePath, data, 0644)
}

// addToUploadQueue adds a failed upload to the queue
func addToUploadQueue(queue *UploadQueue, entry UploadQueueEntry) {
	// Check if entry already exists
	for i, existing := range queue.FailedUploads {
		if existing.FilePath == entry.FilePath {
			// Update existing entry
			queue.FailedUploads[i].Attempts++
			queue.FailedUploads[i].LastAttempt = time.Now()
			queue.FailedUploads[i].LastError = entry.LastError
			return
		}
	}

	// Add new entry
	entry.Attempts = 1
	entry.FirstFailure = time.Now()
	entry.LastAttempt = time.Now()
	queue.FailedUploads = append(queue.FailedUploads, entry)

	// Enforce max queue size (remove oldest entries)
	if len(queue.FailedUploads) > maxQueueSize {
		queue.FailedUploads = queue.FailedUploads[len(queue.FailedUploads)-maxQueueSize:]
	}
}

// removeFromUploadQueue removes an entry from the queue
func removeFromUploadQueue(queue *UploadQueue, filePath string) {
	for i, entry := range queue.FailedUploads {
		if entry.FilePath == filePath {
			queue.FailedUploads = append(queue.FailedUploads[:i], queue.FailedUploads[i+1:]...)
			return
		}
	}
}

// cleanupUploadQueue removes old and missing files from queue
func cleanupUploadQueue(queue *UploadQueue) {
	cutoffDate := time.Now().AddDate(0, 0, -queueMaxAgeDays)
	cleaned := []UploadQueueEntry{}

	for _, entry := range queue.FailedUploads {
		// Remove entries older than cutoff date
		if entry.FirstFailure.Before(cutoffDate) {
			continue
		}

		// Remove entries where file no longer exists
		if _, err := os.Stat(entry.FilePath); os.IsNotExist(err) {
			continue
		}

		cleaned = append(cleaned, entry)
	}

	queue.FailedUploads = cleaned
}

// retryFailedUploads attempts to upload all files in the queue
func (m *ModemCheck) retryFailedUploads(queue *UploadQueue) {
	if len(queue.FailedUploads) == 0 {
		return
	}

	m.Log(fmt.Sprintf("Found %d file(s) in upload queue, attempting retry...", len(queue.FailedUploads)))

	successCount := 0
	failCount := 0
	missingCount := 0

	// Create a copy to iterate over since we'll be modifying the original
	entries := make([]UploadQueueEntry, len(queue.FailedUploads))
	copy(entries, queue.FailedUploads)

	for _, entry := range entries {
		// Check if file still exists
		if _, err := os.Stat(entry.FilePath); os.IsNotExist(err) {
			m.Log(fmt.Sprintf("  ✗ File no longer exists: %s", entry.FilePath))
			removeFromUploadQueue(queue, entry.FilePath)
			missingCount++
			continue
		}

		// Attempt upload using the modemID from the queue entry
		err := m.uploadToCloudWithModemID(entry.FilePath, entry.ModemID)
		if err == nil {
			m.Log(fmt.Sprintf("  ✓ Successfully uploaded: %s (was attempt #%d)", filepath.Base(entry.FilePath), entry.Attempts+1))
			removeFromUploadQueue(queue, entry.FilePath)
			successCount++
		} else {
			m.Log(fmt.Sprintf("  ✗ Upload failed: %s - %v", filepath.Base(entry.FilePath), err))
			// Update the entry with new attempt info
			for i := range queue.FailedUploads {
				if queue.FailedUploads[i].FilePath == entry.FilePath {
					queue.FailedUploads[i].Attempts++
					queue.FailedUploads[i].LastAttempt = time.Now()
					queue.FailedUploads[i].LastError = err.Error()
					break
				}
			}
			failCount++
		}
	}

	// Save the queue to persist any removals or updates
	if err := saveUploadQueue(queue); err != nil {
		m.Log(fmt.Sprintf("Warning: Failed to save upload queue: %v", err))
	}

	if successCount > 0 || missingCount > 0 {
		m.Log(fmt.Sprintf("Retry summary: %d succeeded, %d failed, %d missing", successCount, failCount, missingCount))
	}
}

// cleanupLogFile purges log entries older than 30 days
func (m *ModemCheck) cleanupLogFile() error {
	logFileName := "modem-check_logs.txt"

	// Check if log file exists
	if _, err := os.Stat(logFileName); os.IsNotExist(err) {
		return nil // No log file to clean up
	}

	// Read the log file
	data, err := os.ReadFile(logFileName)
	if err != nil {
		return err
	}

	lines := strings.Split(string(data), "\n")
	cutoffDate := time.Now().AddDate(0, 0, -logMaxAgeDays)
	var keptLines []string

	for _, line := range lines {
		// Skip empty lines
		if len(strings.TrimSpace(line)) == 0 {
			continue
		}

		// Try to parse timestamp from log line format: [YYYY-MM-DD HH:MM:SS]
		if len(line) > 21 && line[0] == '[' {
			timestampStr := line[1:20] // Extract YYYY-MM-DD HH:MM:SS
			if logTime, err := time.Parse("2006-01-02 15:04:05", timestampStr); err == nil {
				if logTime.Before(cutoffDate) {
					continue // Skip old entries
				}
			}
		}

		keptLines = append(keptLines, line)
	}

	// Write back the cleaned log
	if len(keptLines) < len(lines) {
		cleanedData := strings.Join(keptLines, "\n")
		if err := os.WriteFile(logFileName, []byte(cleanedData), 0644); err != nil {
			return err
		}
	}

	return nil
}

// Main execution
func (m *ModemCheck) Run() error {
	// Initialize log file
	if err := m.InitLogFile(); err != nil {
		return err
	}
	if m.logFile != nil {
		defer m.logFile.Close()
	}

	m.Log(fmt.Sprintf("Modem check script (v4.1.2) started at %s", m.checkTime))

	// Clean up old log entries (30 days)
	if !m.config.NoLogs {
		if err := m.cleanupLogFile(); err != nil {
			m.Log(fmt.Sprintf("Warning: Failed to cleanup log file: %v", err))
		}
	}

	// Load upload queue
	queue, err := loadUploadQueue()
	if err != nil {
		m.Log(fmt.Sprintf("Warning: Failed to load upload queue: %v", err))
		queue = &UploadQueue{FailedUploads: []UploadQueueEntry{}}
	}

	// Clean up old queue entries
	cleanupUploadQueue(queue)

	// Retry failed uploads first (before modem detection for faster feedback)
	if m.config.EnableCloud {
		m.retryFailedUploads(queue)
	}

	// Detect modem
	if m.config.ModemAddress == "autodetect" {
		if err := m.AutoDetectModem(); err != nil {
			m.Log(err.Error())
			return err
		}
	} else {
		m.modemAddress = m.config.ModemAddress
		m.Log(fmt.Sprintf("Using configured modem address: %s", m.modemAddress))
		m.Log("Attempting to detect modem model...")
		m.modemType = m.DetectModem(m.modemAddress)
		if m.modemType == "Unknown" {
			return fmt.Errorf("modem model not detected at %s", m.modemAddress)
		}
		m.Log(fmt.Sprintf("Modem model detected: %s", m.modemType))
	}

	// Login
	m.Log("Logging in to modem")
	var err2 error
	switch m.modemType {
	case "CODA45", "CODA56":
		err2 = m.CODALogin()
	case "DM1000":
		err2 = m.DM1000Login()
	case "Xfinity", "Xfinity-XB7", "Xfinity-XB8", "XB7", "XB8":
		err2 = m.XfinityLogin()
	}
	if err2 != nil {
		return err2
	}

	// Get MAC
	m.Log("Getting modem MAC address")
	switch m.modemType {
	case "CODA45", "CODA56":
		err2 = m.CODAGetMAC()
	case "DM1000":
		err2 = m.DM1000GetMAC()
	case "Xfinity", "Xfinity-XB7", "Xfinity-XB8", "XB7", "XB8":
		err2 = m.XfinityGetMAC()
	}
	if err2 != nil {
		return err2
	}

	// Create output directory
	m.Log("Creating folder to store check results")

	// Always store locally in ModemCheck-Results subdirectory
	baseDir := filepath.Join(filepath.Dir(os.Args[0]), "ModemCheck-Results")
	m.checkDir = filepath.Join(baseDir, fmt.Sprintf("%s-%s", m.modemType, m.modemMAC))
	os.MkdirAll(m.checkDir, 0755)
	m.checkFile = filepath.Join(m.checkDir, m.checkTime+".json") // Collect data
	m.Log("Collecting modem diagnostic data")
	var data *ModemData
	switch m.modemType {
	case "CODA45", "CODA56":
		data, err = m.CODAGetData()
	case "DM1000":
		data, err = m.DM1000GetData()
	case "Xfinity", "Xfinity-XB7", "Xfinity-XB8", "XB7", "XB8":
		data, err = m.XfinityGetData()
	}
	if err != nil {
		return err
	}

	// Save data
	jsonData, _ := json.MarshalIndent(data, "", "  ")
	if err := os.WriteFile(m.checkFile, jsonData, 0644); err != nil {
		return err
	}
	m.Log(fmt.Sprintf("Modem data collected and saved to %s", m.checkFile))

	// Clear FEC
	m.Log("Clearing FEC counters")
	switch m.modemType {
	case "CODA45", "CODA56":
		m.CODAClearFEC()
	case "DM1000":
		m.DM1000ClearFEC()
	case "Xfinity", "Xfinity-XB7", "Xfinity-XB8", "XB7", "XB8":
		m.XfinityClearFEC()
	}

	// Ping tests (run before speed tests)
	m.RunPingTests(data)

	// Speed tests (run after ping tests)
	m.RunSpeedTests(data)

	// Save updated data with ping and speed test results
	m.Log(fmt.Sprintf("Adding test results to %s", m.checkFile))
	jsonData, _ = json.MarshalIndent(data, "", "  ")
	os.WriteFile(m.checkFile, jsonData, 0644)

	// Upload to cloud if enabled
	if m.config.EnableCloud {
		if err := m.UploadToCloud(m.checkFile); err != nil {
			m.Log(fmt.Sprintf("Cloud upload failed: %v", err))

			// Add to upload queue for retry
			modemID := fmt.Sprintf("%s-%s", m.modemType, m.modemMAC)
			entry := UploadQueueEntry{
				FilePath:  m.checkFile,
				ModemID:   modemID,
				Timestamp: m.checkTime,
				LastError: err.Error(),
			}
			addToUploadQueue(queue, entry)

			// Save updated queue
			if err := saveUploadQueue(queue); err != nil {
				m.Log(fmt.Sprintf("Warning: Failed to save upload queue: %v", err))
			} else {
				m.Log("Added to upload queue for retry on next run")
			}
		} else {
			m.Log("Cloud upload successful!")
		}
	}

	// Save queue even if cloud is disabled (to persist any cleanup/retries)
	if err := saveUploadQueue(queue); err != nil {
		m.Log(fmt.Sprintf("Warning: Failed to save upload queue: %v", err))
	}

	m.Log("All done! See you next time.")
	return nil
}

func main() {
	// Command-line flags
	modemAddress := flag.String("address", "autodetect", "Modem IP address or 'autodetect'")
	xfinityPassword := flag.String("xfinitypassword", "password", "Password for Rogers Xfinity modems")
	iperf3Enabled := flag.Bool("iperf3", false, "Enable iPerf3 speed tests")
	iperf3Server := flag.String("iperf3-server", "speedtest.mtl2.ca.leaseweb.net", "iPerf3 server address")
	iperf3Port := flag.String("iperf3-port", "5201", "iPerf3 server port or port range (e.g., 5201 or 5201-5210)")
	iperf3Streams := flag.Int("iperf3-streams", 4, "Number of parallel iPerf3 streams")
	iperf3UploadLimit := flag.Int("iperf3-upload-limit", 150, "Upload bandwidth limit (Mbps)")
	iperf3DownloadLimit := flag.Int("iperf3-download-limit", 1500, "Download bandwidth limit (Mbps)")
	silent := flag.Bool("silent", false, "Suppress output to terminal")
	noLogs := flag.Bool("nologs", false, "Disable log file creation")
	enableCloud := flag.Bool("enablecloud", false, "Enable cloud upload (always saves locally)")
	configFile := flag.String("config", "", "Path to configuration file (optional)")

	flag.Parse()

	config := Configuration{
		ModemAddress:        *modemAddress,
		IgnitePassword:      *xfinityPassword,
		Iperf3Enabled:       *iperf3Enabled,
		Iperf3Server:        *iperf3Server,
		Iperf3Port:          *iperf3Port,
		Iperf3Streams:       *iperf3Streams,
		Iperf3UploadLimit:   *iperf3UploadLimit,
		Iperf3DownloadLimit: *iperf3DownloadLimit,
		Silent:              *silent,
		NoLogs:              *noLogs,
		// Cloud settings default to disabled, loaded from config file if provided
		EnableCloud: *enableCloud,
		CloudHost:   "",
		CloudPort:   "",
		CloudAPIKey: "",
		CloudPath:   "",
	}

	// Load config file if specified
	if *configFile != "" {
		if err := loadConfigFile(*configFile, &config); err != nil {
			log.Fatalf("Error loading config file: %v", err)
		}
	}

	// Create and run modem check
	modemCheck := NewModemCheck(config)
	if err := modemCheck.Run(); err != nil {
		log.Fatalf("Error: %v", err)
	}
}

func loadConfigFile(path string, config *Configuration) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("failed to read config file: %w", err)
	}

	if err := json.Unmarshal(data, config); err != nil {
		return fmt.Errorf("failed to parse config file: %w", err)
	}

	// Validate critical configuration
	if config.EnableCloud {
		if config.CloudHost == "" {
			return fmt.Errorf("CloudHost is required when EnableCloud is true")
		}
		if config.CloudAPIKey == "" {
			return fmt.Errorf("CloudAPIKey is required when EnableCloud is true")
		}
	}

	// Validate port ranges
	if config.Iperf3Streams < 1 {
		config.Iperf3Streams = 4 // Default
	}
	if config.Iperf3UploadLimit < 0 {
		config.Iperf3UploadLimit = 0
	}
	if config.Iperf3DownloadLimit < 0 {
		config.Iperf3DownloadLimit = 0
	}

	return nil
}

// min returns the minimum of two integers
func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
