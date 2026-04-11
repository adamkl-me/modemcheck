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
	// Note: github.com/pixelbender/go-traceroute is imported in diagnostics_unix.go only
	// (uses Unix-specific syscalls that don't compile on Windows)
)

// Shared HTTP client for IP detection services to avoid repeated TLS handshakes
var ipDetectionHTTPClient = &http.Client{
	Timeout: 10 * time.Second,
	Transport: &http.Transport{
		MaxIdleConns:        10,
		MaxIdleConnsPerHost: 5,
		IdleConnTimeout:     30 * time.Second,
	},
}

// Pre-compiled regexes for ping output parsing (compiled once at package init)
var (
	pingLossRe      = regexp.MustCompile(`([\d.]+)% (?:packet )?loss`)
	pingAvgReWin    = regexp.MustCompile(`Average = (\d+)ms`)
	pingMaxReWin    = regexp.MustCompile(`Maximum = (\d+)ms`)
	pingStatsReUnix = regexp.MustCompile(`(?:rtt|round-trip) min/avg/max/(?:mdev|stddev) = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)`)
)

// Pre-compiled regexes for traceroute output parsing
var (
	// Unix traceroute format: " 1  192.168.1.1 (192.168.1.1)  1.234 ms  1.345 ms  1.456 ms"
	// or " 1  router.local (192.168.1.1)  1.234 ms  1.345 ms  1.456 ms"
	tracerouteUnixRe = regexp.MustCompile(`^\s*(\d+)\s+(\S+)\s+\(([^)]+)\)\s+([\d.]+)\s*ms\s+([\d.]+)\s*ms\s+([\d.]+)\s*ms`)
	// Unix traceroute timeout format: " 2  * * *"
	tracerouteUnixTimeoutRe = regexp.MustCompile(`^\s*(\d+)\s+\*\s+\*\s+\*`)
	// Windows tracert format: "  1     1 ms     1 ms     1 ms  192.168.1.1"
	// or "  1    <1 ms    <1 ms    <1 ms  192.168.1.1"
	tracerouteWinRe = regexp.MustCompile(`^\s*(\d+)\s+(<?\d+)\s*ms\s+(<?\d+)\s*ms\s+(<?\d+)\s*ms\s+(\S+)`)
	// Windows tracert timeout format: "  2     *        *        *     Request timed out."
	tracerouteWinTimeoutRe = regexp.MustCompile(`^\s*(\d+)\s+\*\s+\*\s+\*`)
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

	m.Log(fmt.Sprintf("Running speed test using public servers (%d parallel connections)...", m.config.SpeedTestConnections))
	state.LastSpeedTest = state.RunCount

	// Create speedtest client with configured number of parallel connections
	client := speedtest.New(speedtest.WithUserConfig(&speedtest.UserConfig{
		MaxConnections: m.config.SpeedTestConnections,
	}))

	// Fetch server list using the configured client
	serverList, err := client.FetchServers()
	if err != nil {
		m.Log(fmt.Sprintf("Failed to fetch server list: %v", err))
		data.SpeedTestUpload = -1
		data.SpeedTestDownload = -1
		return false
	}

	// Use all available servers (already sorted by distance and pre-pinged by FetchServers)
	servers := serverList
	if len(servers) == 0 {
		m.Log("No speed test servers found")
		data.SpeedTestUpload = -1
		data.SpeedTestDownload = -1
		return false
	}

	// Select server with lowest latency for reporting (servers already have latency from FetchServers ping)
	var server *speedtest.Server
	var bestLatency time.Duration = time.Hour
	for _, s := range servers {
		if s.Latency > 0 && s.Latency < bestLatency {
			bestLatency = s.Latency
			server = s
		}
	}
	if server == nil {
		server = servers[0] // Fallback to first (closest by distance) if no valid latency
	}

	// Log mode and server info
	if m.config.SpeedTestConnections > 1 && len(servers) > 1 {
		m.Log(fmt.Sprintf("Multi-server mode: %d servers available, best: %s (%.1fms)",
			len(servers), server.Name, float64(server.Latency)/float64(time.Millisecond)))
	} else {
		m.Log(fmt.Sprintf("Single-server mode: %s (%.1fms)",
			server.Name, float64(server.Latency)/float64(time.Millisecond)))
	}

	m.Log(fmt.Sprintf("Testing with server: %s (%s, %s)", server.Name, server.Sponsor, server.Country))

	// Store server information
	data.SpeedTestServerName = server.Sponsor
	data.SpeedTestServerID = server.ID

	// Run ping/latency test first to get unloaded metrics
	err = server.PingTest(nil)
	if err == nil {
		// Extract unloaded latency metrics (convert from nanoseconds to milliseconds)
		data.SpeedTestLatency = math.Round(float64(server.Latency)/NanosecondsPerMillisecond*10) / 10 // Round to 1 decimal
		data.SpeedTestMaxLatency = math.Round(float64(server.MaxLatency)/NanosecondsPerMillisecond*10) / 10
		data.SpeedTestJitter = math.Round(float64(server.Jitter)/NanosecondsPerMillisecond*10) / 10
	}

	// Run download test
	m.Log("Running download test...")
	if m.config.SpeedTestConnections > 1 && len(servers) > 1 {
		err = server.MultiDownloadTestContext(context.Background(), servers)
	} else {
		err = server.DownloadTest()
	}
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
	if m.config.SpeedTestConnections > 1 && len(servers) > 1 {
		err = server.MultiUploadTestContext(context.Background(), servers)
	} else {
		err = server.UploadTest()
	}
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

// RunPingTests runs ping tests to Google and Cloudflare concurrently, along with
// a traceroute to 8.8.8.8. Records average latency, packet loss, jitter,
// and maximum latency for each ping target.
func (m *ModemCheck) RunPingTests(data *scraper.ModemData) {
	m.Log(fmt.Sprintf("Running ping tests (%d pings each) and traceroute to 8.8.8.8...", m.config.PingCount))

	// Use channels to collect results from concurrent goroutines
	type pingResult struct {
		host       string
		avg        string
		loss       string
		jitter     string
		maxLatency string
	}
	results := make(chan pingResult, 2)
	tracerouteResult := make(chan *scraper.TracerouteResult, 1)

	// Start both pings concurrently
	go func() {
		defer func() {
			if r := recover(); r != nil {
				m.Log(fmt.Sprintf("Panic in 8.8.8.8 ping test: %v", r))
				results <- pingResult{"8.8.8.8", "", "", "", ""}
			}
		}()
		avg, loss, jitter, maxLatency := m.runPing("8.8.8.8", m.config.PingCount)
		results <- pingResult{"8.8.8.8", avg, loss, jitter, maxLatency}
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

	// Start traceroute concurrently
	go func() {
		defer func() {
			if r := recover(); r != nil {
				m.Log(fmt.Sprintf("Panic in traceroute test: %v", r))
				tracerouteResult <- nil
			}
		}()
		tracerouteResult <- m.runTraceroute("8.8.8.8")
	}()

	// Collect results from both pings
	for i := 0; i < 2; i++ {
		result := <-results
		if result.avg != "" {
			m.Log(fmt.Sprintf("%s: avg %s ms, %s packet loss", result.host, result.avg, result.loss))
			if result.host == "8.8.8.8" {
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
			if result.host == "8.8.8.8" {
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

	// Collect traceroute result
	data.TracerouteGoogle = <-tracerouteResult
	if data.TracerouteGoogle != nil {
		m.Log(fmt.Sprintf("Traceroute to %s: %d hops, status: %s",
			data.TracerouteGoogle.Target,
			data.TracerouteGoogle.HopCount,
			data.TracerouteGoogle.Status))
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
	pinger.Interval = PingInterval

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
			pinger.Interval = PingInterval
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
			pinger.Interval = PingInterval
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
	// Validate host parameter to prevent command injection and invalid inputs
	// DNS hostname max length is 253 characters per RFC 1035
	if len(host) == 0 || len(host) > MaxHostnameLength {
		m.Log(fmt.Sprintf("Invalid host length for ping: %d characters (must be 1-%d)", len(host), MaxHostnameLength))
		return "", "", "", ""
	}

	// SECURITY: Validate hostname characters to prevent command injection
	// Check for obviously invalid characters that could indicate injection attempts
	// Valid hostnames and IPs should only contain alphanumeric, dots, hyphens, and colons (IPv6)
	// This prevents malicious inputs like: "google.com; rm -rf /" or "8.8.8.8 && curl evil.com"
	for _, char := range host {
		if !((char >= 'a' && char <= 'z') || (char >= 'A' && char <= 'Z') ||
			(char >= '0' && char <= '9') || char == '.' || char == '-' || char == ':') {
			m.Log(fmt.Sprintf("Invalid characters in hostname for ping: %s", host))
			return "", "", "", ""
		}
	}

	// Validate per-label length (RFC 1035: max 63 chars per label)
	// Skip for IPv6 addresses (contain colons)
	if !strings.Contains(host, ":") {
		labels := strings.Split(host, ".")
		for _, label := range labels {
			if len(label) > 63 {
				m.Log(fmt.Sprintf("Invalid hostname label length: %d (max 63)", len(label)))
				return "", "", "", ""
			}
			if len(label) == 0 {
				m.Log("Invalid hostname: empty label")
				return "", "", "", ""
			}
		}
	}

	ctx, cancel := context.WithTimeout(context.Background(), PingTimeout)
	defer cancel()

	// Windows uses -n for count, Linux/macOS use -c
	countFlag := "-c"
	if runtime.GOOS == "windows" {
		countFlag = "-n"
	}

	// SECURITY: exec.CommandContext prevents shell injection by not invoking a shell
	// The hostname is passed as a separate argument, not concatenated into a command string
	// #nosec G204 -- host is validated via isValidHostname(), ping is a fixed command
	cmd := exec.CommandContext(ctx, "ping", countFlag, strconv.Itoa(count), host)
	output, err := cmd.CombinedOutput()

	if err != nil {
		m.Log(fmt.Sprintf("System ping command failed for %s: %v, output: %s", host, err, string(output)))
		return "", "", "", ""
	}

	outputStr := string(output)

	// Parse packet loss (rounded to 1 decimal) using pre-compiled regex
	// Note: ParseFloat errors are intentionally ignored here because the regex
	// guarantees the captured group contains only numeric characters. Parse
	// failure would indicate a regex bug (should be caught in development).
	if matches := pingLossRe.FindStringSubmatch(outputStr); len(matches) > 1 {
		lossVal, _ := strconv.ParseFloat(matches[1], 64)
		loss = fmt.Sprintf("%.1f%%", lossVal)
	}

	// Parse average ping time and other stats using pre-compiled regexes
	if runtime.GOOS == "windows" {
		// Windows format: Minimum = 12ms, Maximum = 34ms, Average = 23ms
		if matches := pingAvgReWin.FindStringSubmatch(outputStr); len(matches) > 1 {
			avgVal, _ := strconv.ParseFloat(matches[1], 64)
			avg = fmt.Sprintf("%.1f", avgVal)
		}

		if matches := pingMaxReWin.FindStringSubmatch(outputStr); len(matches) > 1 {
			maxVal, _ := strconv.ParseFloat(matches[1], 64)
			maxLatency = fmt.Sprintf("%.1f", maxVal)
		}
		// Windows ping doesn't provide jitter, leave empty
	} else {
		// Unix-like systems (Linux, macOS, FreeBSD)
		// Format: rtt min/avg/max/mdev = 12.345/23.456/34.567/5.678 ms
		if matches := pingStatsReUnix.FindStringSubmatch(outputStr); len(matches) > 4 {
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

// runTraceroute is implemented in platform-specific files:
// - diagnostics_unix.go: Uses go-traceroute library with fallback to system command
// - diagnostics_windows.go: Uses system tracert command directly

// runSystemTraceroute executes a traceroute using the system command.
// Uses system traceroute (Linux/macOS) or tracert (Windows) command.
// This is the fallback when the Go traceroute library fails.
func (m *ModemCheck) runSystemTraceroute(host string) *scraper.TracerouteResult {
	startTime := time.Now()

	// Validate host parameter (reuse same validation as ping)
	if len(host) == 0 || len(host) > MaxHostnameLength {
		m.Log(fmt.Sprintf("Invalid host length for traceroute: %d characters", len(host)))
		return &scraper.TracerouteResult{
			Target: host,
			Status: "failed",
			Error:  "invalid host length",
		}
	}

	// SECURITY: Validate hostname characters to prevent command injection
	for _, char := range host {
		if !((char >= 'a' && char <= 'z') || (char >= 'A' && char <= 'Z') ||
			(char >= '0' && char <= '9') || char == '.' || char == '-' || char == ':') {
			m.Log(fmt.Sprintf("Invalid characters in hostname for traceroute: %s", host))
			return &scraper.TracerouteResult{
				Target: host,
				Status: "failed",
				Error:  "invalid hostname characters",
			}
		}
	}

	ctx, cancel := context.WithTimeout(context.Background(), TracerouteTimeout)
	defer cancel()

	var cmd *exec.Cmd
	if runtime.GOOS == "windows" {
		// Windows: tracert with DNS resolution to show both hostname and IP
		cmd = exec.CommandContext(ctx, "tracert", "-h", "30", host) // #nosec G204 -- host validated above (alphanumeric + .:-); binary hardcoded
	} else {
		// Linux/macOS: traceroute with DNS resolution to show hostname (IP) format
		cmd = exec.CommandContext(ctx, "traceroute", "-m", "30", host) // #nosec G204 -- host validated above (alphanumeric + .:-); binary hardcoded
	}

	output, err := cmd.CombinedOutput()
	duration := time.Since(startTime)

	result := &scraper.TracerouteResult{
		Target:    host,
		RawOutput: string(output),
		Duration:  fmt.Sprintf("%.1fs", duration.Seconds()),
	}

	if err != nil {
		// Check if it was a timeout
		if ctx.Err() == context.DeadlineExceeded {
			m.Log(fmt.Sprintf("Traceroute to %s timed out after %v", host, TracerouteTimeout))
			result.Status = "timeout"
			result.Error = "traceroute timed out"
		} else {
			m.Log(fmt.Sprintf("Traceroute to %s failed: %v", host, err))
			result.Status = "failed"
			result.Error = err.Error()
		}
		// Still try to parse any partial output we got
		result.Hops = m.parseTracerouteOutput(string(output))
		result.HopCount = len(result.Hops)
		return result
	}

	// Parse the output
	result.Hops = m.parseTracerouteOutput(string(output))
	result.HopCount = len(result.Hops)
	result.Status = "success"

	return result
}

// parseTracerouteOutput parses traceroute/tracert output into structured hop data.
func (m *ModemCheck) parseTracerouteOutput(output string) []scraper.TracerouteHop {
	var hops []scraper.TracerouteHop
	lines := strings.Split(output, "\n")
	isWindows := runtime.GOOS == "windows"

	for _, line := range lines {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}

		var hop scraper.TracerouteHop

		if isWindows {
			// Try to match Windows tracert output
			if matches := tracerouteWinRe.FindStringSubmatch(line); matches != nil {
				hopNum, _ := strconv.Atoi(matches[1])
				hop.Hop = hopNum
				hop.RTT1 = strings.TrimPrefix(matches[2], "<") + " ms"
				hop.RTT2 = strings.TrimPrefix(matches[3], "<") + " ms"
				hop.RTT3 = strings.TrimPrefix(matches[4], "<") + " ms"
				hop.IP = matches[5]
				hop.Host = matches[5] // Windows tracert shows hostname or IP (same value)
				hops = append(hops, hop)
			} else if matches := tracerouteWinTimeoutRe.FindStringSubmatch(line); matches != nil {
				hopNum, _ := strconv.Atoi(matches[1])
				hop.Hop = hopNum
				hop.Timeout = true
				hops = append(hops, hop)
			}
		} else {
			// Try to match Unix traceroute output
			if matches := tracerouteUnixRe.FindStringSubmatch(line); matches != nil {
				hopNum, _ := strconv.Atoi(matches[1])
				hop.Hop = hopNum
				hop.Host = matches[2]
				hop.IP = matches[3]
				hop.RTT1 = matches[4] + " ms"
				hop.RTT2 = matches[5] + " ms"
				hop.RTT3 = matches[6] + " ms"
				hops = append(hops, hop)
			} else if matches := tracerouteUnixTimeoutRe.FindStringSubmatch(line); matches != nil {
				hopNum, _ := strconv.Atoi(matches[1])
				hop.Hop = hopNum
				hop.Timeout = true
				hops = append(hops, hop)
			}
		}
	}

	return hops
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
	// Validate that cache has all required fields (ASN and ISPName are mandatory)
	if cache != nil && cache.PublicIP == currentIP && cache.ASN != "" && cache.ISPName != "" {
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

	// Try both IP services in parallel and use the first one that succeeds
	// This avoids 10+ second delays when one service is slow or down
	type ipResult struct {
		publicIP  string
		asn       string
		ispName   string
		ipCity    string
		ipCountry string
		service   string
	}
	resultChan := make(chan ipResult, 2)

	// Launch both services concurrently
	go func() {
		tempData := &scraper.ModemData{}
		if m.tryIPAPI(tempData) {
			resultChan <- ipResult{
				publicIP: tempData.PublicIP, asn: tempData.ASN, ispName: tempData.ISPName,
				ipCity: tempData.IPCity, ipCountry: tempData.IPCountry, service: "ip-api.com",
			}
		} else {
			resultChan <- ipResult{} // Empty result indicates failure
		}
	}()

	go func() {
		tempData := &scraper.ModemData{}
		if m.tryIPAPICo(tempData) {
			resultChan <- ipResult{
				publicIP: tempData.PublicIP, asn: tempData.ASN, ispName: tempData.ISPName,
				ipCity: tempData.IPCity, ipCountry: tempData.IPCountry, service: "ipapi.co",
			}
		} else {
			resultChan <- ipResult{} // Empty result indicates failure
		}
	}()

	// Wait for first successful result or both failures.
	// Buffer size (2) matches goroutine count, so sends are always non-blocking.
	var successResult *ipResult
	for i := 0; i < 2; i++ {
		result := <-resultChan
		if result.publicIP != "" && successResult == nil {
			successResult = &result
		}
	}

	if successResult != nil {
		data.PublicIP = successResult.publicIP
		data.ASN = successResult.asn
		data.ISPName = successResult.ispName
		data.IPCity = successResult.ipCity
		data.IPCountry = successResult.ipCountry
		m.Log(fmt.Sprintf("Public IP: %s (ASN: %s, ISP: %s) [via %s]",
			data.PublicIP, data.ASN, data.ISPName, successResult.service))
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

// fetchJSONFromService is a helper function to fetch JSON data from an HTTP service
// It handles HTTP request, status checking, and JSON decoding with proper error logging
func (m *ModemCheck) fetchJSONFromService(url string, serviceName string, target interface{}) error {
	resp, err := ipDetectionHTTPClient.Get(url)
	if err != nil {
		m.Log(fmt.Sprintf("%s error: %v", serviceName, err))
		return fmt.Errorf("%s request failed: %w", serviceName, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		m.Log(fmt.Sprintf("%s returned status %d", serviceName, resp.StatusCode))
		return fmt.Errorf("%s returned status %d", serviceName, resp.StatusCode)
	}

	if err := json.NewDecoder(resp.Body).Decode(target); err != nil {
		m.Log(fmt.Sprintf("%s parse error: %v", serviceName, err))
		return fmt.Errorf("%s parse error: %w", serviceName, err)
	}

	return nil
}

// tryIPAPICo attempts to get IP info from ipapi.co (primary service)
func (m *ModemCheck) tryIPAPICo(data *scraper.ModemData) bool {
	var ipInfo struct {
		IP      string `json:"ip"`
		ASN     string `json:"asn"`
		Org     string `json:"org"`
		City    string `json:"city"`
		Country string `json:"country"`
	}

	if err := m.fetchJSONFromService("https://ipapi.co/json/", "ipapi.co", &ipInfo); err != nil {
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
	var ipInfo struct {
		Query   string `json:"query"` // ip-api.com uses "query" for IP
		AS      string `json:"as"`    // Format: "AS15169 Google LLC"
		ISP     string `json:"isp"`
		City    string `json:"city"`
		Country string `json:"country"`
		Status  string `json:"status"`
	}

	if err := m.fetchJSONFromService("http://ip-api.com/json/", "ip-api.com", &ipInfo); err != nil {
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
	// Try ipify with JSON format first
	var jsonIP struct {
		IP string `json:"ip"`
	}
	if err := m.fetchJSONFromService("https://api.ipify.org?format=json", "ipify.org", &jsonIP); err == nil && jsonIP.IP != "" {
		data.PublicIP = jsonIP.IP
		return true
	}

	// Try ifconfig.me as plain text fallback
	// Must set a User-Agent: ifconfig.me returns 403 to Go's default automated client UA
	req, err := http.NewRequest("GET", "https://ifconfig.me/ip", nil)
	if err != nil {
		m.Log(fmt.Sprintf("ifconfig.me request error: %v", err))
		return false
	}
	req.Header.Set("User-Agent", "modemcheck/"+Version)
	resp, err := ipDetectionHTTPClient.Do(req)
	if err != nil {
		m.Log(fmt.Sprintf("ifconfig.me error: %v", err))
		return false
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		m.Log(fmt.Sprintf("ifconfig.me returned status %d", resp.StatusCode))
		return false
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		m.Log(fmt.Sprintf("ifconfig.me read error: %v", err))
		return false
	}

	// Parse as plain text
	ip := strings.TrimSpace(string(body))
	if ip != "" && len(ip) <= MaxIPLength { // Validate IP length (IPv6 max is 45 chars)
		data.PublicIP = ip
		return true
	}

	return false
}
