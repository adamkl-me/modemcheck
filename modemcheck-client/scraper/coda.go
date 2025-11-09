package scraper

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strings"
)

// CODAScraper handles Hitron CODA45/CODA56 modems
type CODAScraper struct {
	client       *http.Client
	modemAddress string
	modemType    string
	logger       Logger
}

// NewCODAScraper creates a new CODA scraper
func NewCODAScraper(client *http.Client, modemAddress string, modemType string, logger Logger) *CODAScraper {
	return &CODAScraper{
		client:       client,
		modemAddress: modemAddress,
		modemType:    modemType,
		logger:       logger,
	}
}

// Login authenticates with the modem (not required for CODA)
func (s *CODAScraper) Login() error {
	s.logger.Log("Login not required for Hitron CODA modem")
	return nil
}

// GetMAC retrieves the modem's MAC address
func (s *CODAScraper) GetMAC() (string, error) {
	resp, err := s.client.Get(fmt.Sprintf("http://%s/data/getSysInfo.asp?", s.modemAddress))
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	var sysInfo []map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&sysInfo); err != nil {
		return "", err
	}

	if len(sysInfo) > 0 {
		if rfMac, ok := sysInfo[0]["rfMac"].(string); ok {
			mac := strings.ReplaceAll(rfMac, ":", "")
			if matched, _ := regexp.MatchString(`^[0-9A-Fa-f]{12}$`, mac); matched {
				s.logger.Log(fmt.Sprintf("Successfully retrieved modem WAN MAC address: %s", mac))
				return mac, nil
			}
		}
	}

	return "", fmt.Errorf("unable to get valid modem MAC")
}

// GetData collects all diagnostic data from the modem
func (s *CODAScraper) GetData(checkTime int64) (*ModemData, error) {
	data := &ModemData{}

	// Get system info
	resp, err := s.client.Get(fmt.Sprintf("http://%s/data/getSysInfo.asp", s.modemAddress))
	if err != nil {
		return nil, err
	}
	var sysInfoArray []map[string]interface{}
	json.NewDecoder(resp.Body).Decode(&sysInfoArray)
	resp.Body.Close()

	if len(sysInfoArray) > 0 {
		modemMAC, _ := s.GetMAC()
		data.SysInfo = SysInfo{
			SysTime:   parseModemTime("coda56-system", getString(sysInfoArray[0], "systemTime")),
			Firmware:  getString(sysInfoArray[0], "swVersion"),
			Uptime:    parseUptimeToSeconds(getString(sysInfoArray[0], "systemUptime")),
			ModemType: s.modemType,
			ModemMAC:  modemMAC,
			CheckTime: checkTime,
		}
	}

	// Get RX data
	resp, _ = s.client.Get(fmt.Sprintf("http://%s/data/dsinfo.asp", s.modemAddress))
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
	resp, _ = s.client.Get(fmt.Sprintf("http://%s/data/dsofdminfo.asp", s.modemAddress))
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
	resp, _ = s.client.Get(fmt.Sprintf("http://%s/data/usinfo.asp", s.modemAddress))
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
	resp, _ = s.client.Get(fmt.Sprintf("http://%s/data/usofdminfo.asp", s.modemAddress))
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
	resp, _ = s.client.Get(fmt.Sprintf("http://%s/data/status_log.asp", s.modemAddress))
	var eventLogRaw []map[string]interface{}
	json.NewDecoder(resp.Body).Decode(&eventLogRaw)
	resp.Body.Close()

	for _, event := range eventLogRaw {
		data.EventLog = append(data.EventLog, EventLog{
			Time:  parseModemTime("coda56-event", getString(event, "time")),
			ID:    getString(event, "type"),
			Event: getString(event, "event"),
		})
	}

	return data, nil
}

// ClearFEC clears the FEC counters
func (s *CODAScraper) ClearFEC() error {
	data := `model=%7B%22portId%22%3A%221%22%2C%22frequency%22%3A%22591000000%22%2C%22modulation%22%3A%222%22%2C%22signalStrength%22%3A%225.700%22%2C%22snr%22%3A%2237.356%22%2C%22dsoctets%22%3A%221113110%22%2C%22correcteds%22%3A%220%22%2C%22uncorrect%22%3A%220%22%2C%22channelId%22%3A%224%22%2C%22resetval%22%3A%221%22%7D`
	_, err := s.client.Post(fmt.Sprintf("http://%s/goform/ResetFECCnt", s.modemAddress), "application/x-www-form-urlencoded", strings.NewReader(data))
	return err
}

// GetModemType returns the modem type string
func (s *CODAScraper) GetModemType() string {
	return s.modemType
}

// DetectCODA attempts to detect CODA modem type
func DetectCODA(address string, client *http.Client) string {
	// Try CODA-specific endpoint (CODA45/CODA56 have no login page)
	codaResp, err := client.Get(fmt.Sprintf("http://%s/data/getSysInfo.asp", address))
	if err == nil {
		defer codaResp.Body.Close()
		codaBody, _ := io.ReadAll(codaResp.Body)
		codaStr := string(codaBody)
		// Check if it's valid JSON with CODA-specific fields
		if strings.Contains(codaStr, "rfMac") && strings.Contains(codaStr, "systemUptime") {
			// Distinguish between CODA45 (2 ports) and CODA56 (1 port)
			linkResp, err := client.Get(fmt.Sprintf("http://%s/data/getLinkStatus.asp", address))
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

	return ""
}
