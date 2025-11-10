package scraper

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strings"
)

// DM1000Scraper handles Sercomm DM1000 cable modems.
type DM1000Scraper struct{
	client       *http.Client
	modemAddress string
	modemType    string
	logger       Logger
}

// NewDM1000Scraper creates a new DM1000 scraper instance.
func NewDM1000Scraper(client *http.Client, modemAddress string, logger Logger) *DM1000Scraper {
	return &DM1000Scraper{
		client:       client,
		modemAddress: modemAddress,
		modemType:    "DM1000",
		logger:       logger,
	}
}

// Login authenticates with the modem
func (s *DM1000Scraper) Login() error {
	s.logger.Log("Attempting login to Sercomm DM1000 modem...")
	user := "technician"
	pass := "sercommdocsis"
	passB64 := base64.StdEncoding.EncodeToString([]byte(pass))

	data := fmt.Sprintf("login_user=%s&pws=%s&submit=Apply&is_parent_window=1&todo=login&this_file=login.html&next_file=&language=en&message=&passwd=%s&cur_passwd=",
		user, passB64, passB64)

	_, err := s.client.Post(fmt.Sprintf("http://%s/setup.cgi", s.modemAddress),
		"application/x-www-form-urlencoded", strings.NewReader(data))
	if err != nil {
		s.logger.Log(fmt.Sprintf("Login POST request failed: %v", err))
		return err
	}

	// Verify login
	s.logger.Log("Verifying login...")
	resp, err := s.client.Get(fmt.Sprintf("http://%s/setup.cgi?todo=Cm_Status", s.modemAddress))
	if err != nil {
		s.logger.Log(fmt.Sprintf("Verification GET request failed: %v", err))
		return err
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	if len(body) > 0 {
		s.logger.Log("Sercomm DM1000 modem login successful")
		return nil
	}

	return fmt.Errorf("login failed")
}

// GetMAC retrieves the modem's MAC address
func (s *DM1000Scraper) GetMAC() (string, error) {
	s.logger.Log("Fetching MAC address from interface parameters...")
	resp, err := s.client.Get(fmt.Sprintf("http://%s/setup.cgi?todo=Interface_param", s.modemAddress))
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	re := regexp.MustCompile(`"name":"wan0".*?"mac":"([^"]+)"`)
	matches := re.FindStringSubmatch(string(body))

	if len(matches) > 1 {
		mac := strings.ToUpper(strings.ReplaceAll(matches[1], ":", ""))
		if matched, _ := regexp.MatchString(`^[0-9A-F]{12}$`, mac); matched {
			s.logger.Log(fmt.Sprintf("Successfully retrieved modem WAN MAC address: %s", mac))
			return mac, nil
		}
	}

	return "", fmt.Errorf("unable to get valid modem MAC")
}

// GetData collects all diagnostic data from the modem including system info,
// downstream/upstream channels (both SC-QAM and OFDM), and event logs.
func (s *DM1000Scraper) GetData(checkTime int64) (*ModemData, error) {
	s.logger.Log("Fetching system information...")
	data := &ModemData{}

	// Get status page for uptime and system time
	resp, _ := s.client.Get(fmt.Sprintf("http://%s/status.html", s.modemAddress))
	statusBody, _ := io.ReadAll(resp.Body)
	resp.Body.Close()

	// Extract system time
	timeRe := regexp.MustCompile(`<td  align="left" id ="time_date">([^<]+)`)
	if matches := timeRe.FindStringSubmatch(string(statusBody)); len(matches) > 1 {
		data.SysInfo.SysTime = parseModemTime("dm1000-system", strings.TrimSpace(matches[1]))
	}

	// Extract uptime - matches pattern: dw(str_status16) followed by <td> with uptime value
	uptimeRe := regexp.MustCompile(`(?s)str_status16.*?<td.*?align="left">([^<]+)</td>`)
	if matches := uptimeRe.FindStringSubmatch(string(statusBody)); len(matches) > 1 {
		data.SysInfo.Uptime = parseUptimeToSeconds(strings.TrimSpace(matches[1]))
	}

	// Get firmware version
	resp, _ = s.client.Get(fmt.Sprintf("http://%s/setup.cgi?todo=Version_Info", s.modemAddress))
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

	modemMAC, _ := s.GetMAC()
	data.SysInfo.ModemType = s.modemType
	data.SysInfo.ModemMAC = modemMAC
	data.SysInfo.CheckTime = checkTime

	// Get RX data
	s.logger.Log("Fetching downstream channel data...")
	resp, _ = s.client.Get(fmt.Sprintf("http://%s/setup.cgi?todo=RF_DS_param", s.modemAddress))
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
	resp, _ = s.client.Get(fmt.Sprintf("http://%s/setup.cgi?todo=RF_DS_31_param", s.modemAddress))
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
	s.logger.Log("Fetching upstream channel data...")
	resp, _ = s.client.Get(fmt.Sprintf("http://%s/setup.cgi?todo=RF_US_param", s.modemAddress))
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
	resp, _ = s.client.Get(fmt.Sprintf("http://%s/setup.cgi?todo=RF_US_31_param", s.modemAddress))
	var txofdmData map[string]interface{}
	json.NewDecoder(resp.Body).Decode(&txofdmData)
	resp.Body.Close()

	if nodes, ok := txofdmData["nodes"].([]interface{}); ok && len(nodes) > 0 {
		if nodeMap, ok := nodes[0].(map[string]interface{}); ok {
			// DM1000 has index1 and index2 for two OFDMA channels
			if index1, ok := nodeMap["index1"].(string); ok && index1 != "" {
				data.TXOFDM = append(data.TXOFDM, s.extractDM1000OFDMA(nodes, "index1"))
			}
			if index2, ok := nodeMap["index2"].(string); ok && index2 != "" {
				data.TXOFDM = append(data.TXOFDM, s.extractDM1000OFDMA(nodes, "index2"))
			}
		}
	}

	// Get event log
	s.logger.Log("Fetching event log...")
	resp, _ = s.client.Get(fmt.Sprintf("http://%s/setup.cgi?todo=Event_Log", s.modemAddress))
	var eventData map[string]interface{}
	json.NewDecoder(resp.Body).Decode(&eventData)
	resp.Body.Close()

	if nodes, ok := eventData["nodes"].([]interface{}); ok {
		for _, node := range nodes {
			if event, ok := node.(map[string]interface{}); ok {
				data.EventLog = append(data.EventLog, EventLog{
					Time:  parseModemTime("dm1000-system", getString(event, "d")),
					ID:    getString(event, "id"),
					Event: getString(event, "text"),
				})
			}
		}
	}

	return data, nil
}

// extractDM1000OFDMA extracts OFDMA channel data from DM1000 JSON structure.
// The nodes array contains field values indexed by position, with indexKey specifying
// which OFDMA channel (index1 or index2) to extract.
func (s *DM1000Scraper) extractDM1000OFDMA(nodes []interface{}, indexKey string) TXOFDMAChannel {
	channel := TXOFDMAChannel{}
	// Field map defines the position-to-field mapping from the DM1000 API response
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

// ClearFEC clears the FEC (Forward Error Correction) counters.
func (s *DM1000Scraper) ClearFEC() error {
	data := "todo=reset_FEC_Counters&this_file=status.html&next_file=status.html"
	_, err := s.client.Post(fmt.Sprintf("http://%s/setup.cgi", s.modemAddress),
		"application/x-www-form-urlencoded", strings.NewReader(data))
	return err
}

// GetModemType returns the modem type string (DM1000).
func (s *DM1000Scraper) GetModemType() string {
	return s.modemType
}

// DetectDM1000 attempts to detect DM1000 modem by checking for the DM1000-specific title tag.
func DetectDM1000(address string, client *http.Client) bool {
	resp, err := client.Get(fmt.Sprintf("http://%s/login.html", address))
	if err != nil {
		return false
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	return strings.Contains(string(body), "<title>DM1000</title>")
}
