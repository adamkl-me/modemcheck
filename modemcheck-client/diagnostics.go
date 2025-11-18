package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"net/http"
	"os/exec"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"time"

	"modemcheck-client/scraper"

	// Third-party libraries for network diagnostics
	// See THIRD-PARTY-LICENSES.md for full license information
	"github.com/go-ping/ping"                   // MIT License - Copyright (c) 2016 Cameron Sparr and contributors
	"github.com/showwin/speedtest-go/speedtest" // MIT License - Copyright (c) 2015 ITO Shogo
)

// ShouldRunSpeedTest determines if a speed test should run based on interval and previous results.
func (m *ModemCheck) ShouldRunSpeedTest(state *SpeedTestState) bool {
	if !m.config.SpeedTestEnabled {
		return false
	}

	// If last test failed, always run on next attempt
	if !state.LastTestSuccess {
		m.Log(fmt.Sprintf("Last speed test failed, retrying now (run %d)", state.RunCount))
		return true
	}

	// Check if enough runs have passed since last test
	runsSinceLastTest := state.RunCount - state.LastSpeedTest
	if runsSinceLastTest >= m.config.SpeedTestInterval {
		m.Log(fmt.Sprintf("Speed test interval reached (%d runs), executing test (run %d)",
			m.config.SpeedTestInterval, state.RunCount))
		return true
	}

	m.Log(fmt.Sprintf("Skipping speed test (run %d of %d until next test)",
		runsSinceLastTest, m.config.SpeedTestInterval))
	return false
}

// RunSpeedTests runs speed tests against public servers using speedtest-go and records
// download/upload speeds, latency, and jitter metrics.
func (m *ModemCheck) RunSpeedTests(data *scraper.ModemData, state *SpeedTestState) bool {
	data.SpeedTestEnabled = m.config.SpeedTestEnabled

	if !m.config.SpeedTestEnabled {
		m.Log("Speed tests are disabled")
		data.SpeedTestUpload = -1
		data.SpeedTestDownload = -1
		return true // Return true since "disabled" is not a failure
	}

	// Check if we should run the speed test
	if !m.ShouldRunSpeedTest(state) {
		m.Log("Speed test skipped based on interval configuration")
		data.SpeedTestUpload = -2  // -2 indicates "skipped by interval"
		data.SpeedTestDownload = -2
		return true // Return true since skipping is not a failure
	}

	m.Log("Running speed test using public servers...")
	state.LastSpeedTest = state.RunCount

	// Fetch server list
	serverList, err := speedtest.FetchServers()
	if err != nil {
		m.Log(fmt.Sprintf("Failed to fetch server list: %v", err))
		data.SpeedTestUpload = -1
		data.SpeedTestDownload = -1
		return false
	}

	// Find nearby servers
	targets, err := serverList.FindServer([]int{})
	if err != nil {
		m.Log(fmt.Sprintf("Failed to find servers: %v", err))
		data.SpeedTestUpload = -1
		data.SpeedTestDownload = -1
		return false
	}

	if len(targets) == 0 {
		m.Log("No speed test servers found")
		data.SpeedTestUpload = -1
		data.SpeedTestDownload = -1
		return false
	}

	// Use the first (closest) server
	server := targets[0]
	m.Log(fmt.Sprintf("Testing with server: %s (%s, %s)", server.Name, server.Sponsor, server.Country))

	// Store server information
	data.SpeedTestServerName = server.Sponsor
	data.SpeedTestServerID = server.ID

	// Run ping/latency test first to get unloaded metrics
	err = server.PingTest(nil)
	if err == nil {
		// Extract unloaded latency metrics (convert from nanoseconds to milliseconds)
		data.SpeedTestLatency = math.Round(float64(server.Latency)/1000000.0*10) / 10 // Round to 1 decimal
		data.SpeedTestMaxLatency = math.Round(float64(server.MaxLatency)/1000000.0*10) / 10
		data.SpeedTestJitter = math.Round(float64(server.Jitter)/1000000.0*10) / 10
	}

	// Run download test
	m.Log("Running download test...")
	err = server.DownloadTest()
	if err != nil {
		m.Log(fmt.Sprintf("Download test failed: %v", err))
		data.SpeedTestDownload = -1
	} else {
		// Convert from Bps to Mbps and round to 2 decimal places
		downloadMbps := (server.DLSpeed.Mbps())
		data.SpeedTestDownload = math.Round(downloadMbps*100) / 100
		m.Log(fmt.Sprintf("Download speed: %.2f Mbps", data.SpeedTestDownload))
	}

	// Run upload test
	m.Log("Running upload test...")
	err = server.UploadTest()
	if err != nil {
		m.Log(fmt.Sprintf("Upload test failed: %v", err))
		data.SpeedTestUpload = -1
	} else {
		// Convert from Bps to Mbps and round to 2 decimal places
		uploadMbps := (server.ULSpeed.Mbps())
		data.SpeedTestUpload = math.Round(uploadMbps*100) / 100
		m.Log(fmt.Sprintf("Upload speed: %.2f Mbps", data.SpeedTestUpload))
	}

	m.Log(fmt.Sprintf("Speed test complete - DL: %.2f Mbps, UL: %.2f Mbps",
		data.SpeedTestDownload, data.SpeedTestUpload))

	// Check if test was successful (both upload and download succeeded)
	success := data.SpeedTestDownload != -1 && data.SpeedTestUpload != -1
	return success
}

// RunPingTests runs ping tests to Google and Cloudflare concurrently and records
// average latency, packet loss, jitter, and maximum latency for each target.
func (m *ModemCheck) RunPingTests(data *scraper.ModemData) {
	m.Log(fmt.Sprintf("Running ping tests (%d pings each) to google.ca and one.one.one.one...", m.config.PingCount))

	// Use channels to collect results from concurrent goroutines
	type pingResult struct {
		host       string
		avg        string
		loss       string
		jitter     string
		maxLatency string
	}
	results := make(chan pingResult, 2)

	// Start both pings concurrently
	go func() {
		defer func() {
			if r := recover(); r != nil {
				m.Log(fmt.Sprintf("Panic in google.ca ping test: %v", r))
				results <- pingResult{"google.ca", "", "", "", ""}
			}
		}()
		avg, loss, jitter, maxLatency := m.runPing("google.ca", m.config.PingCount)
		results <- pingResult{"google.ca", avg, loss, jitter, maxLatency}
	}()

	go func() {
		defer func() {
			if r := recover(); r != nil {
				m.Log(fmt.Sprintf("Panic in one.one.one.one ping test: %v", r))
				results <- pingResult{"one.one.one.one", "", "", "", ""}
			}
		}()
		avg, loss, jitter, maxLatency := m.runPing("one.one.one.one", m.config.PingCount)
		results <- pingResult{"one.one.one.one", avg, loss, jitter, maxLatency}
	}()

	// Collect results from both pings
	for i := 0; i < 2; i++ {
		result := <-results
		if result.avg != "" {
			m.Log(fmt.Sprintf("%s: avg %s ms, %s packet loss", result.host, result.avg, result.loss))
			if result.host == "google.ca" {
				data.PingGoogleAvg = result.avg
				data.PingGoogleLoss = result.loss
				data.PingGoogleJitter = result.jitter
				data.PingGoogleMaxLatency = result.maxLatency
			} else {
				data.PingCloudflareAvg = result.avg
				data.PingCloudflareLoss = result.loss
				data.PingCloudflareJitter = result.jitter
				data.PingCloudflareMaxLatency = result.maxLatency
			}
		} else {
			m.Log(fmt.Sprintf("Ping to %s failed", result.host))
			if result.host == "google.ca" {
				data.PingGoogleAvg = "Failed"
				data.PingGoogleLoss = "N/A"
				data.PingGoogleJitter = "N/A"
				data.PingGoogleMaxLatency = "N/A"
			} else {
				data.PingCloudflareAvg = "Failed"
				data.PingCloudflareLoss = "N/A"
				data.PingCloudflareJitter = "N/A"
				data.PingCloudflareMaxLatency = "N/A"
			}
		}
	}
}

// runPing executes a ping test to the specified host using either the go-ping library
// or falling back to the system ping command if the library fails.
func (m *ModemCheck) runPing(host string, count int) (avg string, loss string, jitter string, maxLatency string) {
	// Try go-ping library first
	avg, loss, jitter, maxLatency = m.runGoPing(host, count)
	if avg != "" {
		return avg, loss, jitter, maxLatency
	}

	// If go-ping failed, fall back to system ping command
	return m.runSystemPing(host, count)
}

// runGoPing uses the go-ping library for ping tests. It automatically handles privileged
// vs unprivileged mode based on the operating system and available permissions.
func (m *ModemCheck) runGoPing(host string, count int) (avg string, loss string, jitter string, maxLatency string) {
	// Create a new pinger
	pinger, err := ping.NewPinger(host)
	if err != nil {
		m.Log(fmt.Sprintf("Failed to create pinger for %s: %v", host, err))
		return "", "", "", ""
	}

	// Configure the pinger
	pinger.Count = count
	pinger.Timeout = PingTimeout

	// On Linux, use unprivileged mode by default (doesn't require root)
	// On Windows, use privileged mode (works without admin)
	usePrivileged := runtime.GOOS == "windows"
	pinger.SetPrivileged(usePrivileged)

	// Run the ping
	err = pinger.Run()
	if err != nil {
		// If it failed and we tried privileged mode, fall back to unprivileged
		if usePrivileged {
			m.Log(fmt.Sprintf("Privileged ping failed for %s: %v, trying unprivileged mode", host, err))
			pinger, err = ping.NewPinger(host)
			if err != nil {
				m.Log(fmt.Sprintf("Failed to create unprivileged pinger for %s: %v", host, err))
				return "", "", "", ""
			}
			pinger.Count = count
			pinger.Timeout = PingTimeout
			pinger.SetPrivileged(false)

			err = pinger.Run()
			if err != nil {
				m.Log(fmt.Sprintf("Unprivileged ping also failed for %s: %v", host, err))
				return "", "", "", ""
			}
		} else {
			// Try privileged mode as a fallback on Linux
			m.Log(fmt.Sprintf("Unprivileged ping failed for %s: %v, trying privileged mode", host, err))
			pinger, err = ping.NewPinger(host)
			if err != nil {
				m.Log(fmt.Sprintf("Failed to create privileged pinger for %s: %v", host, err))
				return "", "", "", ""
			}
			pinger.Count = count
			pinger.Timeout = PingTimeout
			pinger.SetPrivileged(true)

			err = pinger.Run()
			if err != nil {
				// Both modes failed, return empty to trigger system ping fallback
				m.Log(fmt.Sprintf("Both privileged and unprivileged ping failed for %s: %v, will fallback to system ping", host, err))
				return "", "", "", ""
			}
		}
	}

	// Get statistics
	stats := pinger.Statistics()

	// Calculate packet loss percentage
	var lossPercent float64
	if stats.PacketsSent > 0 {
		lossPercent = float64(stats.PacketLoss)
	}
	loss = fmt.Sprintf("%.1f%%", lossPercent)

	// Get average RTT in milliseconds (rounded to 1 decimal)
	if stats.AvgRtt > 0 {
		avgMs := float64(stats.AvgRtt) / float64(time.Millisecond)
		avg = fmt.Sprintf("%.1f", avgMs)
	}

	// Get jitter (StdDev RTT) in milliseconds (rounded to 1 decimal)
	if stats.StdDevRtt > 0 {
		jitterMs := float64(stats.StdDevRtt) / float64(time.Millisecond)
		jitter = fmt.Sprintf("%.1f", jitterMs)
	}

	// Get max RTT in milliseconds (rounded to 1 decimal)
	if stats.MaxRtt > 0 {
		maxMs := float64(stats.MaxRtt) / float64(time.Millisecond)
		maxLatency = fmt.Sprintf("%.1f", maxMs)
	}

	return avg, loss, jitter, maxLatency
}

// runSystemPing uses the system ping command as a fallback when go-ping fails.
// It parses the output to extract statistics and handles platform-specific output formats.
func (m *ModemCheck) runSystemPing(host string, count int) (avg string, loss string, jitter string, maxLatency string) {
	ctx, cancel := context.WithTimeout(context.Background(), PingTimeout)
	defer cancel()

	// Windows uses -n for count, Linux/macOS use -c
	countFlag := "-c"
	if runtime.GOOS == "windows" {
		countFlag = "-n"
	}

	cmd := exec.CommandContext(ctx, "ping", countFlag, strconv.Itoa(count), host)
	output, err := cmd.CombinedOutput()

	if err != nil {
		m.Log(fmt.Sprintf("System ping command failed for %s: %v, output: %s", host, err, string(output)))
		return "", "", "", ""
	}

	outputStr := string(output)

	// Parse packet loss (rounded to 1 decimal)
	lossRe := regexp.MustCompile(`([\d.]+)% (?:packet )?loss`)
	if matches := lossRe.FindStringSubmatch(outputStr); len(matches) > 1 {
		lossVal, _ := strconv.ParseFloat(matches[1], 64)
		loss = fmt.Sprintf("%.1f%%", lossVal)
	}

	// Parse average ping time and other stats
	if runtime.GOOS == "windows" {
		// Windows format: Minimum = 12ms, Maximum = 34ms, Average = 23ms
		avgRe := regexp.MustCompile(`Average = (\d+)ms`)
		if matches := avgRe.FindStringSubmatch(outputStr); len(matches) > 1 {
			avgVal, _ := strconv.ParseFloat(matches[1], 64)
			avg = fmt.Sprintf("%.1f", avgVal)
		}

		maxRe := regexp.MustCompile(`Maximum = (\d+)ms`)
		if matches := maxRe.FindStringSubmatch(outputStr); len(matches) > 1 {
			maxVal, _ := strconv.ParseFloat(matches[1], 64)
			maxLatency = fmt.Sprintf("%.1f", maxVal)
		}
		// Windows ping doesn't provide jitter, leave empty
	} else {
		// Unix-like systems (Linux, macOS, FreeBSD)
		// Format: rtt min/avg/max/mdev = 12.345/23.456/34.567/5.678 ms
		statsRe := regexp.MustCompile(`(?:rtt|round-trip) min/avg/max/(?:mdev|stddev) = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)`)
		if matches := statsRe.FindStringSubmatch(outputStr); len(matches) > 4 {
			avgVal, _ := strconv.ParseFloat(matches[2], 64)
			avg = fmt.Sprintf("%.1f", avgVal)

			maxVal, _ := strconv.ParseFloat(matches[3], 64)
			maxLatency = fmt.Sprintf("%.1f", maxVal)

			jitterVal, _ := strconv.ParseFloat(matches[4], 64)
			jitter = fmt.Sprintf("%.1f", jitterVal)
		}
	}

	return avg, loss, jitter, maxLatency
}

// GetPublicIPInfo detects the client's public IP address, ASN, and ISP information.
// Uses caching to reduce API calls and multiple fallback services for reliability.
func (m *ModemCheck) GetPublicIPInfo(data *scraper.ModemData) {
	m.Log("Detecting public IP and network information...")

	// First, try to load cached IP info
	cache, err := LoadIPInfoCache()
	if err != nil {
		m.Log(fmt.Sprintf("Warning: Failed to load IP cache: %v", err))
	}

	// Quick check to get current IP only (minimal API call)
	currentIP := ""
	if m.trySimpleIP(data) {
		currentIP = data.PublicIP
	}

	// If we have cached info and the IP hasn't changed, use the cache
	if cache != nil && cache.PublicIP == currentIP && cache.ASN != "" {
		m.Log(fmt.Sprintf("Using cached ASN info for IP: %s", currentIP))
		data.PublicIP = cache.PublicIP
		data.ASN = cache.ASN
		data.ISPName = cache.ISPName
		data.IPCity = cache.IPCity
		data.IPCountry = cache.IPCountry
		m.Log(fmt.Sprintf("Public IP: %s (ASN: %s, ISP: %s) [cached]",
			data.PublicIP, data.ASN, data.ISPName))
		return
	}

	// IP has changed or no cache, fetch full info
	if currentIP != "" {
		m.Log(fmt.Sprintf("IP changed or cache expired, fetching fresh ASN info..."))
	} else {
		m.Log("Fetching IP and ASN information...")
	}

	// Try primary service (ip-api.com - free, no rate limits for reasonable usage)
	if m.tryIPAPI(data) {
		m.Log(fmt.Sprintf("Public IP: %s (ASN: %s, ISP: %s)",
			data.PublicIP, data.ASN, data.ISPName))
		// Save to cache for future use
		if err := SaveIPInfoCache(data.PublicIP, data.ASN, data.ISPName, data.IPCity, data.IPCountry); err != nil {
			m.Log(fmt.Sprintf("Warning: Failed to save IP cache: %v", err))
		}
		return
	}

	m.Log("Primary IP service failed, trying fallback (ipapi.co)...")

	// Try fallback service (ipapi.co)
	if m.tryIPAPICo(data) {
		m.Log(fmt.Sprintf("Public IP: %s (ASN: %s, ISP: %s)",
			data.PublicIP, data.ASN, data.ISPName))
		// Save to cache for future use
		if err := SaveIPInfoCache(data.PublicIP, data.ASN, data.ISPName, data.IPCity, data.IPCountry); err != nil {
			m.Log(fmt.Sprintf("Warning: Failed to save IP cache: %v", err))
		}
		return
	}

	// If we already have the IP from the simple check, use that
	if currentIP != "" {
		m.Log(fmt.Sprintf("Public IP: %s (ASN/ISP info unavailable)", currentIP))
		data.PublicIP = currentIP
		data.ASN = "N/A"
		data.ISPName = "N/A"
		return
	}

	m.Log("Warning: Failed to detect public IP from all sources")
}

// extractASN extracts just the ASN number from a string like "AS812 Rogers Communications Canada Inc."
// Returns just "AS812" or the original string if no space found.
func extractASN(asnString string) string {
	// Find the first space and take everything before it
	if idx := strings.Index(asnString, " "); idx != -1 {
		return asnString[:idx]
	}
	return asnString
}

// tryIPAPICo attempts to get IP info from ipapi.co (primary service)
func (m *ModemCheck) tryIPAPICo(data *scraper.ModemData) bool {
	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Get("https://ipapi.co/json/")
	if err != nil {
		m.Log(fmt.Sprintf("ipapi.co error: %v", err))
		return false
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		m.Log(fmt.Sprintf("ipapi.co returned status %d", resp.StatusCode))
		return false
	}

	var ipInfo struct {
		IP      string `json:"ip"`
		ASN     string `json:"asn"`
		Org     string `json:"org"`
		City    string `json:"city"`
		Country string `json:"country"`
	}

	if err := json.NewDecoder(resp.Body).Decode(&ipInfo); err != nil {
		m.Log(fmt.Sprintf("ipapi.co parse error: %v", err))
		return false
	}

	// Validate we got actual data
	if ipInfo.IP == "" {
		m.Log("ipapi.co returned empty IP")
		return false
	}

	data.PublicIP = ipInfo.IP
	data.ASN = extractASN(ipInfo.ASN)  // Extract just "AS812" from "AS812 Rogers..."
	data.ISPName = ipInfo.Org
	data.IPCity = ipInfo.City
	data.IPCountry = ipInfo.Country

	return true
}

// tryIPAPI attempts to get IP info from ip-api.com (fallback service)
func (m *ModemCheck) tryIPAPI(data *scraper.ModemData) bool {
	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Get("http://ip-api.com/json/")
	if err != nil {
		m.Log(fmt.Sprintf("ip-api.com error: %v", err))
		return false
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		m.Log(fmt.Sprintf("ip-api.com returned status %d", resp.StatusCode))
		return false
	}

	var ipInfo struct {
		Query   string `json:"query"` // ip-api.com uses "query" for IP
		AS      string `json:"as"`    // Format: "AS15169 Google LLC"
		ISP     string `json:"isp"`
		City    string `json:"city"`
		Country string `json:"country"`
		Status  string `json:"status"`
	}

	if err := json.NewDecoder(resp.Body).Decode(&ipInfo); err != nil {
		m.Log(fmt.Sprintf("ip-api.com parse error: %v", err))
		return false
	}

	// Check for API failure
	if ipInfo.Status == "fail" || ipInfo.Query == "" {
		m.Log("ip-api.com returned failure status")
		return false
	}

	data.PublicIP = ipInfo.Query
	data.ASN = extractASN(ipInfo.AS)  // Extract just "AS812" from "AS812 Rogers..."
	data.ISPName = ipInfo.ISP
	data.IPCity = ipInfo.City
	data.IPCountry = ipInfo.Country

	return true
}

// trySimpleIP attempts to get just the IP address from a simple service (last resort)
func (m *ModemCheck) trySimpleIP(data *scraper.ModemData) bool {
	// Try multiple simple IP services
	services := []string{
		"https://api.ipify.org?format=json",
		"https://ifconfig.me/ip",
	}

	client := &http.Client{Timeout: 5 * time.Second}

	for _, service := range services {
		resp, err := client.Get(service)
		if err != nil {
			continue
		}
		defer resp.Body.Close()

		if resp.StatusCode != 200 {
			continue
		}

		body, err := io.ReadAll(resp.Body)
		if err != nil {
			continue
		}

		// Try parsing as JSON first (ipify)
		var jsonIP struct {
			IP string `json:"ip"`
		}
		if err := json.Unmarshal(body, &jsonIP); err == nil && jsonIP.IP != "" {
			data.PublicIP = jsonIP.IP
			return true
		}

		// Try as plain text (ifconfig.me)
		ip := strings.TrimSpace(string(body))
		if ip != "" && len(ip) < 50 { // Basic validation
			data.PublicIP = ip
			return true
		}
	}

	return false
}
