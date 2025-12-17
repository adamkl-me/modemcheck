package scraper

import (
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
)

// Pre-compiled regex patterns for performance
var (
	xfinityMACValidationRe = regexp.MustCompile(`^[0-9A-F]{12}$`)
	xfinityMACPatternRe    = regexp.MustCompile(`([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}`)
	xfinityFirmwareRe      = regexp.MustCompile(`<span class="value" id="software_image">([^<]+)`)
	xfinityDownstreamRe    = regexp.MustCompile(`(?s)<div class="netWidth">Downstream</div>.*?</table>`)
	xfinityCodewordsRe     = regexp.MustCompile(`(?s)CM Error Codewords.*?</table>`)
	xfinityUpstreamRe      = regexp.MustCompile(`(?s)<div class="netWidth">Upstream</div>.*?</table>`)
	xfinityCellRe          = regexp.MustCompile(`<div class="netWidth">([^<]+)</div>`)
	xfinityNumericRe       = regexp.MustCompile(`[^0-9.-]`)

	// Pre-compiled MAC extraction patterns (tried in order)
	xfinityMACExtractionPatterns = []*regexp.Regexp{
		regexp.MustCompile(`<span class="readonlyLabel">CM MAC:</span>.*?class="value">([^<]+)`),
		regexp.MustCompile(`<span class="readonlyLabel">CM MAC:</span>.*?<span class="value">([^<]+)`),
		regexp.MustCompile(`CM MAC:.*?class="value">([^<]+)`),
		regexp.MustCompile(`CM MAC:.*?<span[^>]*>([0-9A-Fa-f:]+)</span>`),
		regexp.MustCompile(`CM MAC:[^>]*>([0-9A-Fa-f:]+)<`),
	}
)

// XfinityScraper handles Rogers Xfinity/XB7/XB8 cable modems.
type XfinityScraper struct {
	client       *http.Client
	modemAddress string
	modemType    string
	password     string
	logger       Logger
}

// NewXfinityScraper creates a new Xfinity scraper instance.
func NewXfinityScraper(client *http.Client, modemAddress string, password string, logger Logger) *XfinityScraper {
	return &XfinityScraper{
		client:       client,
		modemAddress: modemAddress,
		modemType:    "Xfinity",
		password:     password,
		logger:       logger,
	}
}

// readResponseBody reads the HTTP response body with a size limit to prevent memory exhaustion
// Limit is set to 2MB which is more than sufficient for modem HTML pages
func readResponseBody(body io.Reader) ([]byte, error) {
	const maxResponseSize = 2 * 1024 * 1024 // 2MB limit
	limitedReader := io.LimitReader(body, maxResponseSize)
	data, err := io.ReadAll(limitedReader)
	if err != nil {
		return nil, fmt.Errorf("failed to read response body: %w", err)
	}
	return data, nil
}

// Login authenticates with the modem and detects the specific model (XB7 or XB8).
func (s *XfinityScraper) Login() error {
	s.logger.Log("Attempting login to Rogers Xfinity Modem...")

	username := "admin"
	postData := url.Values{
		"username": {username},
		"password": {s.password},
		"locale":   {"false"},
	}.Encode()

	req, _ := http.NewRequest("POST", fmt.Sprintf("http://%s/check.jst", s.modemAddress),
		strings.NewReader(postData))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("User-Agent", "Mozilla/5.0")
	req.Header.Set("Referer", fmt.Sprintf("http://%s/", s.modemAddress))

	resp, err := s.client.Do(req)
	if err != nil {
		s.logger.Log(fmt.Sprintf("Login POST request failed: %v", err))
		return err
	}
	defer resp.Body.Close()

	// Verify login
	s.logger.Log("Verifying login and detecting model...")
	resp, err = s.client.Get(fmt.Sprintf("http://%s/network_setup.jst", s.modemAddress))
	if err != nil {
		s.logger.Log(fmt.Sprintf("Verification GET request failed: %v", err))
		return err
	}
	defer resp.Body.Close()

	body, err := readResponseBody(resp.Body)
	if err != nil {
		s.logger.Log(fmt.Sprintf("Failed to read verification response: %v", err))
		return fmt.Errorf("failed to read login verification response: %w", err)
	}
	bodyStr := string(body)

	if !strings.Contains(bodyStr, "CM MAC:") {
		return fmt.Errorf("rogers Xfinity modem login failed. Check credentials")
	}

	s.logger.Log("Rogers Xfinity modem login successful.")

	// Detect XB7 vs XB8
	if strings.Contains(bodyStr, "XB8") {
		s.modemType = "XB8"
		s.logger.Log(fmt.Sprintf("Detected specific model: %s", s.modemType))
	} else if strings.Contains(bodyStr, "XB7") {
		s.modemType = "XB7"
		s.logger.Log(fmt.Sprintf("Detected specific model: %s", s.modemType))
	}

	return nil
}

// GetMAC retrieves the modem's CM MAC address using multiple regex patterns to ensure compatibility.
func (s *XfinityScraper) GetMAC() (string, error) {
	s.logger.Log("Fetching MAC address from network_setup.jst...")
	resp, err := s.client.Get(fmt.Sprintf("http://%s/network_setup.jst", s.modemAddress))
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	body, err := readResponseBody(resp.Body)
	if err != nil {
		s.logger.Log(fmt.Sprintf("Failed to read MAC address page: %v", err))
		return "", fmt.Errorf("failed to read MAC address page: %w", err)
	}
	bodyStr := string(body)

	if !strings.Contains(bodyStr, "CM MAC:") {
		return "", fmt.Errorf("authentication failed or page structure unexpected")
	}

	// Try multiple pre-compiled regex patterns to extract MAC address
	for _, re := range xfinityMACExtractionPatterns {
		matches := re.FindStringSubmatch(bodyStr)

		if len(matches) > 1 {
			mac := strings.ReplaceAll(strings.TrimSpace(matches[1]), ":", "")
			mac = strings.ReplaceAll(mac, " ", "")
			mac = strings.ToUpper(mac)

			if xfinityMACValidationRe.MatchString(mac) {
				s.logger.Log(fmt.Sprintf("Successfully retrieved modem CM MAC address: %s", mac))
				return mac, nil
			}
		}
	}

	// If we still haven't found it, try a more general approach
	// Find the position of "CM MAC:" in the body
	cmMacIndex := strings.Index(bodyStr, "CM MAC:")
	if cmMacIndex != -1 {
		// Look in the next 500 characters after "CM MAC:"
		endIndex := cmMacIndex + 500
		if endIndex > len(bodyStr) {
			endIndex = len(bodyStr)
		}
		searchWindow := bodyStr[cmMacIndex:endIndex]
		if macMatch := xfinityMACPatternRe.FindString(searchWindow); macMatch != "" {
			mac := strings.ReplaceAll(macMatch, ":", "")
			mac = strings.ReplaceAll(mac, "-", "")
			mac = strings.ToUpper(mac)

			if len(mac) == 12 {
				s.logger.Log(fmt.Sprintf("Successfully retrieved modem CM MAC address: %s", mac))
				return mac, nil
			}
		}
	}

	return "", fmt.Errorf("unable to parse valid modem CM MAC")
}

// GetData collects all diagnostic data from the modem including system info and
// downstream/upstream channels. Event logs are not available on Xfinity modems.
func (s *XfinityScraper) GetData(checkTime int64) (*ModemData, error) {
	s.logger.Log("Fetching data from network_setup.jst...")
	resp, err := s.client.Get(fmt.Sprintf("http://%s/network_setup.jst", s.modemAddress))
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	pageContent, err := readResponseBody(resp.Body)
	if err != nil {
		s.logger.Log(fmt.Sprintf("Failed to read response body: %v", err))
		return nil, fmt.Errorf("failed to read network setup page: %w", err)
	}
	pageStr := string(pageContent)

	if !strings.Contains(pageStr, "CM MAC:") {
		s.logger.Log("Failed to fetch data page. Re-logging in...")
		s.Login()
		retryResp, err := s.client.Get(fmt.Sprintf("http://%s/network_setup.jst", s.modemAddress))
		if err != nil {
			return nil, fmt.Errorf("failed to fetch network setup after re-login: %w", err)
		}
		defer retryResp.Body.Close()
		pageContent, err = readResponseBody(retryResp.Body)
		if err != nil {
			s.logger.Log(fmt.Sprintf("Failed to read retry response body: %v", err))
			return nil, fmt.Errorf("failed to read network setup retry page: %w", err)
		}
		pageStr = string(pageContent)
	}

	data := &ModemData{}

	// Get system info
	modemMAC, err := s.GetMAC()
	if err != nil {
		s.logger.Log(fmt.Sprintf("Warning: Failed to retrieve MAC address: %v", err))
	}
	data.SysInfo.SysTime = parseModemTime("xb8-system", s.extractValue(pageStr, "Local time:"))
	data.SysInfo.Uptime = parseUptimeToSeconds(s.extractValue(pageStr, "System Uptime:"))
	data.SysInfo.ModemType = s.modemType
	data.SysInfo.ModemMAC = modemMAC
	data.SysInfo.CheckTime = checkTime

	// Get firmware from software.jst
	swResp, err := s.client.Get(fmt.Sprintf("http://%s/software.jst", s.modemAddress))
	if err != nil {
		s.logger.Log(fmt.Sprintf("Failed to fetch software version: %v", err))
	} else {
		defer swResp.Body.Close()
		softwareBody, err := readResponseBody(swResp.Body)
		if err != nil {
			s.logger.Log(fmt.Sprintf("Failed to read software version response: %v", err))
		} else {
			if matches := xfinityFirmwareRe.FindStringSubmatch(string(softwareBody)); len(matches) > 1 {
				data.SysInfo.Firmware = strings.TrimSpace(matches[1])
			}
		}
	}

	// Parse downstream channels
	data.RX, data.RXOFDM = s.parseXfinityDownstream(pageStr)

	// Parse upstream channels
	data.TX, data.TXOFDM = s.parseXfinityUpstream(pageStr)

	// Event log not available on Xfinity
	data.EventLog = []EventLog{}

	return data, nil
}

// extractValue extracts a value from an HTML page given a label using multiple regex patterns
// to handle different HTML structure variations.
func (s *XfinityScraper) extractValue(page, label string) string {
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

// parseXfinityDownstream parses downstream channel data from HTML tables,
// separating SC-QAM and OFDM channels based on modulation type.
func (s *XfinityScraper) parseXfinityDownstream(page string) ([]RXChannel, []RXOFDMChannel) {
	rxChannels := []RXChannel{}
	rxofdmChannels := []RXOFDMChannel{}

	// Extract downstream table (use (?s) for multiline matching)
	dsTable := xfinityDownstreamRe.FindString(page)

	// Extract codeword table
	cwTable := xfinityCodewordsRe.FindString(page)

	// Parse channel IDs, frequencies, SNR, power, modulation
	channelIDs := s.extractTableRow(dsTable, "Channel ID")
	frequencies := s.extractTableRow(dsTable, "Frequency")
	snrs := s.extractTableRow(dsTable, "SNR")
	powers := s.extractTableRow(dsTable, "Power Level")
	modulations := s.extractTableRow(dsTable, "Modulation")

	// Parse codeword data
	cwIDs := s.extractTableRow(cwTable, "Channel ID")
	unerrored := s.extractTableRow(cwTable, "Unerrored Codewords")
	correctable := s.extractTableRow(cwTable, "Correctable Codewords")
	uncorrectable := s.extractTableRow(cwTable, "Uncorrectable Codewords")

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

// parseXfinityUpstream parses upstream channel data from HTML tables,
// separating SC-QAM and OFDMA channels based on modulation type.
func (s *XfinityScraper) parseXfinityUpstream(page string) ([]TXChannel, []TXOFDMAChannel) {
	txChannels := []TXChannel{}
	txofdmaChannels := []TXOFDMAChannel{}

	// Extract upstream table (use (?s) for multiline matching)
	usTable := xfinityUpstreamRe.FindString(page)

	channelIDs := s.extractTableRow(usTable, "Channel ID")
	lockStatus := s.extractTableRow(usTable, "Lock Status")
	frequencies := s.extractTableRow(usTable, "Frequency")
	powers := s.extractTableRow(usTable, "Power Level")
	modulations := s.extractTableRow(usTable, "Modulation")

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

// extractTableRow extracts a row of data from an HTML table by finding the row with
// the specified label and parsing all cell values.
func (s *XfinityScraper) extractTableRow(table, rowLabel string) []string {
	results := []string{}

	// Match the row more flexibly - handle both <th> and <td> tags
	re := regexp.MustCompile(`(?s)<t[hd][^>]*>\s*` + regexp.QuoteMeta(rowLabel) + `\s*</t[hd]>(.*?)</tr>`)
	rowMatch := re.FindStringSubmatch(table)

	if len(rowMatch) < 2 {
		return results
	}

	// Extract cell values from <div class="netWidth">
	cells := xfinityCellRe.FindAllStringSubmatch(rowMatch[1], -1)

	for _, cell := range cells {
		if len(cell) > 1 {
			results = append(results, strings.TrimSpace(cell[1]))
		}
	}

	return results
}

// ClearFEC clears the FEC counters. This is not yet implemented for Xfinity modems.
func (s *XfinityScraper) ClearFEC() error {
	s.logger.Log("FEC clear function not yet implemented for Rogers Xfinity modem.")
	return nil
}

// GetModemType returns the modem type string (Xfinity, XB7, or XB8).
func (s *XfinityScraper) GetModemType() string {
	return s.modemType
}

// DetectXfinity attempts to detect Xfinity modem by checking for Rogers-specific pages.
func DetectXfinity(address string, client *http.Client) bool {
	resp, err := client.Get(fmt.Sprintf("http://%s/login.html", address))
	if err != nil {
		return false
	}
	defer resp.Body.Close()

	body, err := readResponseBody(resp.Body)
	if err != nil {
		return false
	}
	bodyStr := string(body)

	if strings.Contains(bodyStr, "<title>403 Forbidden</title>") {
		// Check root page for Rogers/Xfinity
		rootResp, err := client.Get(fmt.Sprintf("http://%s", address))
		if err == nil {
			defer rootResp.Body.Close()
			rootBody, err := readResponseBody(rootResp.Body)
			if err == nil && strings.Contains(string(rootBody), "<title>Rogers</title>") {
				return true
			}
		}
	}

	return false
}

// getAtIndex safely retrieves a string from a slice at the given index,
// returning an empty string if the index is out of bounds.
func getAtIndex(slice []string, index int) string {
	if index < len(slice) {
		return slice[index]
	}
	return ""
}

// cleanNumeric removes all non-numeric characters except decimal points and minus signs.
func cleanNumeric(s string) string {
	return xfinityNumericRe.ReplaceAllString(s, "")
}
