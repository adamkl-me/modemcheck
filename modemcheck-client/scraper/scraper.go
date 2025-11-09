package scraper

import (
	"fmt"
	"net/http"
	"os"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// SysInfo represents system information from the modem
type SysInfo struct {
	SysTime   int64  `json:"systime"` // Unix epoch timestamp
	Firmware  string `json:"firmware"`
	Uptime    int64  `json:"uptime"` // Uptime in seconds
	ModemType string `json:"modemtype"`
	ModemMAC  string `json:"modemmac"`
	CheckTime int64  `json:"checktime"` // Unix epoch timestamp of when check was performed
}

// RXChannel represents downstream channel data
type RXChannel struct {
	PortID      string `json:"portid"`
	Frequency   string `json:"frequency"`
	Power       string `json:"power"`
	SNR         string `json:"snr"`
	Octets      string `json:"octets"`
	Correcteds  string `json:"correcteds"`
	Uncorrectds string `json:"uncorrectds"`
}

// RXOFDMChannel represents downstream OFDM channel data
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

// TXChannel represents upstream channel data
type TXChannel struct {
	PortID    string `json:"portid"`
	Frequency string `json:"frequency"`
	Power     string `json:"power"`
}

// TXOFDMAChannel represents upstream OFDMA channel data
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

// EventLog represents modem event log entries
type EventLog struct {
	Time  int64  `json:"time"` // Unix epoch timestamp
	ID    string `json:"id"`
	Event string `json:"event"`
}

// ModemData represents all data collected from a modem
type ModemData struct {
	SysInfo            SysInfo          `json:"sysinfo"`
	RX                 []RXChannel      `json:"rx"`
	RXOFDM             []RXOFDMChannel  `json:"rxofdm"`
	TX                 []TXChannel      `json:"tx"`
	TXOFDM             []TXOFDMAChannel `json:"txofdm"`
	EventLog           []EventLog       `json:"eventlog"`
	SpeedTestUpload    float64          `json:"iperf3test_ul,omitempty"`    // Upload speed in Mbps (kept as iperf3test_ul for viewer compatibility)
	SpeedTestDownload  float64          `json:"iperf3test_dl,omitempty"`    // Download speed in Mbps (kept as iperf3test_dl for viewer compatibility)
	PingGoogleAvg      string           `json:"ping_google_avg,omitempty"`
	PingGoogleLoss     string           `json:"ping_google_loss,omitempty"`
	PingCloudflareAvg  string           `json:"ping_cloudflare_avg,omitempty"`
	PingCloudflareLoss string           `json:"ping_cloudflare_loss,omitempty"`
}

// ModemScraper defines the interface that all modem scrapers must implement
type ModemScraper interface {
	// Login authenticates with the modem
	Login() error

	// GetMAC retrieves the modem's MAC address
	GetMAC() (string, error)

	// GetData collects all diagnostic data from the modem
	GetData(checkTime int64) (*ModemData, error)

	// ClearFEC clears the FEC (Forward Error Correction) counters
	ClearFEC() error

	// GetModemType returns the modem type string
	GetModemType() string
}

// Logger defines the interface for logging
type Logger interface {
	Log(message string)
}

// parseModemTime converts various timestamp formats to Unix epoch
func parseModemTime(format, timeStr string) int64 {
	timeStr = strings.TrimSpace(timeStr)
	if timeStr == "" {
		return 0
	}

	var t time.Time
	var err error

	switch format {
	case "coda56-system":
		// Format: "Mon Nov 03, 2025, 18:45:28"
		t, err = time.Parse("Mon Jan 02, 2006, 15:04:05", timeStr)
	case "coda56-event":
		// Format: "11/03/25 18:41:57"
		t, err = time.Parse("01/02/06 15:04:05", timeStr)
	case "xb8-system":
		// Format: "2025-11-05 13:21:21"
		t, err = time.Parse("2006-01-02 15:04:05", timeStr)
	case "dm1000-system":
		// Format: Various HTML extracted formats, try multiple
		formats := []string{
			"Mon 2006-01-02 15:04:05", // Thu 2025-11-06 06:07:42
			"2006-01-02_15:04:05",     // 2025-11-04_17:09:46
			"2006-01-02 15:04:05",
			"Mon Jan 02 15:04:05 2006",
			"01/02/2006 15:04:05",
		}
		for _, layout := range formats {
			t, err = time.Parse(layout, timeStr)
			if err == nil {
				break
			}
		}
	}

	if err != nil {
		fmt.Fprintf(os.Stderr, "Warning: Failed to parse time '%s' with format '%s': %v\n", timeStr, format, err)
		return 0
	}

	return t.Unix()
}

// parseUptimeToSeconds converts various uptime formats to total seconds
func parseUptimeToSeconds(uptimeStr string) int64 {
	uptimeStr = strings.TrimSpace(uptimeStr)
	if uptimeStr == "" {
		return 0
	}

	var totalSeconds int64

	// CODA56 format: "00h:04m:41s"
	codaRe := regexp.MustCompile(`(\d+)h:(\d+)m:(\d+)s`)
	if matches := codaRe.FindStringSubmatch(uptimeStr); matches != nil {
		hours, _ := strconv.ParseInt(matches[1], 10, 64)
		minutes, _ := strconv.ParseInt(matches[2], 10, 64)
		seconds, _ := strconv.ParseInt(matches[3], 10, 64)
		return hours*3600 + minutes*60 + seconds
	}

	// XB8 format: "6 days 13h: 18m: 59s"
	xb8Re := regexp.MustCompile(`(?:(\d+)\s*days?\s*)?(?:(\d+)h:\s*)?(?:(\d+)m:\s*)?(?:(\d+)s)?`)
	if matches := xb8Re.FindStringSubmatch(uptimeStr); matches != nil {
		days := int64(0)
		hours := int64(0)
		minutes := int64(0)
		seconds := int64(0)

		if matches[1] != "" {
			days, _ = strconv.ParseInt(matches[1], 10, 64)
		}
		if matches[2] != "" {
			hours, _ = strconv.ParseInt(matches[2], 10, 64)
		}
		if matches[3] != "" {
			minutes, _ = strconv.ParseInt(matches[3], 10, 64)
		}
		if matches[4] != "" {
			seconds, _ = strconv.ParseInt(matches[4], 10, 64)
		}

		totalSeconds = days*86400 + hours*3600 + minutes*60 + seconds
		if totalSeconds > 0 {
			return totalSeconds
		}
	}

	// DM1000 format: "2 d: 19 h: 2 m"
	dm1000Re := regexp.MustCompile(`(?:(\d+)\s*d:\s*)?(?:(\d+)\s*h:\s*)?(?:(\d+)\s*m)?`)
	if matches := dm1000Re.FindStringSubmatch(uptimeStr); matches != nil {
		days := int64(0)
		hours := int64(0)
		minutes := int64(0)

		if matches[1] != "" {
			days, _ = strconv.ParseInt(matches[1], 10, 64)
		}
		if matches[2] != "" {
			hours, _ = strconv.ParseInt(matches[2], 10, 64)
		}
		if matches[3] != "" {
			minutes, _ = strconv.ParseInt(matches[3], 10, 64)
		}

		totalSeconds = days*86400 + hours*3600 + minutes*60
		if totalSeconds > 0 {
			return totalSeconds
		}
	}

	fmt.Fprintf(os.Stderr, "Warning: Failed to parse uptime '%s'\n", uptimeStr)
	return 0
}

// getString extracts a string value from a map
func getString(m map[string]interface{}, key string) string {
	if val, ok := m[key]; ok {
		return fmt.Sprintf("%v", val)
	}
	return ""
}

// DetectModem attempts to detect the modem type at a given address
func DetectModem(address string, client *http.Client) string {
	// Try CODA detection first
	if modemType := DetectCODA(address, client); modemType != "" {
		return modemType
	}

	// Try DM1000
	if DetectDM1000(address, client) {
		return "DM1000"
	}

	// Try Xfinity
	if DetectXfinity(address, client) {
		return "Xfinity"
	}

	return "Unknown"
}
