package main

import (
	"context"
	"fmt"
	"math"
	"os/exec"
	"regexp"
	"runtime"
	"strconv"
	"time"

	"modemcheck-client/scraper"

	"github.com/go-ping/ping"
	"github.com/showwin/speedtest-go/speedtest"
)

// RunSpeedTests runs speed tests against public servers using speedtest-go
func (m *ModemCheck) RunSpeedTests(data *scraper.ModemData) {
	data.SpeedTestEnabled = m.config.SpeedTestEnabled

	if !m.config.SpeedTestEnabled {
		m.Log("Speed tests are disabled")
		data.SpeedTestUpload = -1
		data.SpeedTestDownload = -1
		return
	}

	m.Log("Running speed test using public servers...")

	// Fetch server list
	serverList, err := speedtest.FetchServers()
	if err != nil {
		m.Log(fmt.Sprintf("Failed to fetch server list: %v", err))
		data.SpeedTestUpload = -1
		data.SpeedTestDownload = -1
		return
	}

	// Find nearby servers
	targets, err := serverList.FindServer([]int{})
	if err != nil {
		m.Log(fmt.Sprintf("Failed to find servers: %v", err))
		data.SpeedTestUpload = -1
		data.SpeedTestDownload = -1
		return
	}

	if len(targets) == 0 {
		m.Log("No speed test servers found")
		data.SpeedTestUpload = -1
		data.SpeedTestDownload = -1
		return
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
}

// RunPingTests runs ping tests to Google and Cloudflare concurrently
func (m *ModemCheck) RunPingTests(data *scraper.ModemData) {
	m.Log("Running ping tests to google.ca and one.one.one.one...")

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
		avg, loss, jitter, maxLatency := m.runPing("google.ca", DefaultPingCount)
		results <- pingResult{"google.ca", avg, loss, jitter, maxLatency}
	}()

	go func() {
		avg, loss, jitter, maxLatency := m.runPing("one.one.one.one", DefaultPingCount)
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

func (m *ModemCheck) runPing(host string, count int) (avg string, loss string, jitter string, maxLatency string) {
	// Try go-ping library first
	avg, loss, jitter, maxLatency = m.runGoPing(host, count)
	if avg != "" {
		return avg, loss, jitter, maxLatency
	}

	// If go-ping failed, fall back to system ping command
	return m.runSystemPing(host, count)
}

// runGoPing uses the go-ping library for ping tests
func (m *ModemCheck) runGoPing(host string, count int) (avg string, loss string, jitter string, maxLatency string) {
	// Create a new pinger
	pinger, err := ping.NewPinger(host)
	if err != nil {
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
			pinger, err = ping.NewPinger(host)
			if err != nil {
				return "", "", "", ""
			}
			pinger.Count = count
			pinger.Timeout = PingTimeout
			pinger.SetPrivileged(false)

			err = pinger.Run()
			if err != nil {
				return "", "", "", ""
			}
		} else {
			// Try privileged mode as a fallback on Linux
			pinger, err = ping.NewPinger(host)
			if err != nil {
				return "", "", "", ""
			}
			pinger.Count = count
			pinger.Timeout = PingTimeout
			pinger.SetPrivileged(true)

			err = pinger.Run()
			if err != nil {
				// Both modes failed, return empty to trigger system ping fallback
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

// runSystemPing uses the system ping command as a fallback
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
