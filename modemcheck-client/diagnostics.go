package main

import (
	"fmt"
	"math"
	"time"

	"github.com/go-ping/ping"
	"github.com/showwin/speedtest-go/speedtest"
	"modemcheck-client/scraper"
)

// RunSpeedTests runs speed tests against public servers using speedtest-go
func (m *ModemCheck) RunSpeedTests(data *scraper.ModemData) {
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
		host string
		avg  string
		loss string
	}
	results := make(chan pingResult, 2)

	// Start both pings concurrently
	go func() {
		avg, loss := m.runPing("google.ca", DefaultPingCount)
		results <- pingResult{"google.ca", avg, loss}
	}()

	go func() {
		avg, loss := m.runPing("one.one.one.one", DefaultPingCount)
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
	// Create a new pinger
	pinger, err := ping.NewPinger(host)
	if err != nil {
		return "", ""
	}

	// Configure the pinger
	pinger.Count = count
	pinger.Timeout = PingTimeout

	// Try privileged mode first (ICMP), then fall back to unprivileged (UDP)
	pinger.SetPrivileged(true)

	// Run the ping
	err = pinger.Run()
	if err != nil {
		// Privileged mode failed, try unprivileged mode
		pinger, err = ping.NewPinger(host)
		if err != nil {
			return "", ""
		}
		pinger.Count = count
		pinger.Timeout = PingTimeout
		pinger.SetPrivileged(false)

		err = pinger.Run()
		if err != nil {
			return "", ""
		}
	}

	// Get statistics
	stats := pinger.Statistics()

	// Calculate packet loss percentage
	var lossPercent float64
	if stats.PacketsSent > 0 {
		lossPercent = float64(stats.PacketLoss)
	}
	loss = fmt.Sprintf("%.0f%%", lossPercent)

	// Get average RTT in milliseconds
	if stats.AvgRtt > 0 {
		avgMs := float64(stats.AvgRtt) / float64(time.Millisecond)
		avg = fmt.Sprintf("%.3f", avgMs)
	}

	return avg, loss
}
