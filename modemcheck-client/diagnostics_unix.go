//go:build !windows

package main

import (
	"context"
	"fmt"
	"net"
	"strings"
	"time"

	"modemcheck-client/scraper"

	// Third-party library for network diagnostics (Unix only)
	// See THIRD-PARTY-LICENSES.md for full license information
	"github.com/pixelbender/go-traceroute/traceroute" // MIT License - Copyright (c) 2016 Dmitry Avtonomov
)

// runTraceroute executes a traceroute to the specified host using the Go library first,
// falling back to the system command if the library fails.
func (m *ModemCheck) runTraceroute(host string) *scraper.TracerouteResult {
	// Try Go traceroute library first (requires raw socket permissions)
	result := m.runGoTraceroute(host)
	if result != nil && result.Status == "success" {
		return result
	}

	// Fall back to system command
	if result != nil && result.Error != "" {
		m.Log(fmt.Sprintf("Go traceroute failed: %s, falling back to system command...", result.Error))
	} else {
		m.Log("Go traceroute failed, falling back to system command...")
	}
	return m.runSystemTraceroute(host)
}

// runGoTraceroute uses the pixelbender/go-traceroute library for traceroute.
// Uses pure ICMP like system traceroute, producing consistent hop-by-hop results.
// Requires raw socket permissions (root on Linux/macOS).
func (m *ModemCheck) runGoTraceroute(host string) *scraper.TracerouteResult {
	startTime := time.Now()

	// Validate host parameter
	if len(host) == 0 || len(host) > MaxHostnameLength {
		return &scraper.TracerouteResult{
			Target: host,
			Status: "failed",
			Error:  "invalid host length",
		}
	}

	// SECURITY: Validate hostname characters to prevent injection
	for _, char := range host {
		if !((char >= 'a' && char <= 'z') || (char >= 'A' && char <= 'Z') ||
			(char >= '0' && char <= '9') || char == '.' || char == '-' || char == ':') {
			return &scraper.TracerouteResult{
				Target: host,
				Status: "failed",
				Error:  "invalid hostname characters",
			}
		}
	}

	// Resolve hostname to IP address with timeout to prevent hanging
	ip := net.ParseIP(host)
	if ip == nil {
		dnsCtx, dnsCancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer dnsCancel()
		ips, err := net.DefaultResolver.LookupIPAddr(dnsCtx, host)
		if err != nil || len(ips) == 0 {
			return &scraper.TracerouteResult{
				Target: host,
				Status: "failed",
				Error:  fmt.Sprintf("DNS lookup failed: %v", err),
			}
		}
		ip = ips[0].IP
	}

	// Run traceroute using pure ICMP (like system traceroute)
	traceHops, err := traceroute.Trace(ip)
	duration := time.Since(startTime)

	if err != nil {
		return &scraper.TracerouteResult{
			Target:   host,
			Status:   "failed",
			Error:    fmt.Sprintf("traceroute library error: %v", err),
			Duration: fmt.Sprintf("%.1fs", duration.Seconds()),
		}
	}

	// The library returns a sparse list - only hops that responded.
	// We need to fill in gaps with timeout entries for a complete picture.

	// First, build a map of distance -> hop data and find max distance
	hopMap := make(map[int]*traceroute.Hop)
	maxDistance := 0
	for _, hop := range traceHops {
		hopMap[hop.Distance] = hop
		if hop.Distance > maxDistance {
			maxDistance = hop.Distance
		}
	}

	// Build complete hop list from 1 to maxDistance, filling in timeouts
	hops := make([]scraper.TracerouteHop, maxDistance)
	for i := 1; i <= maxDistance; i++ {
		h := &hops[i-1]
		h.Hop = i

		if hop, exists := hopMap[i]; exists && len(hop.Nodes) > 0 {
			node := hop.Nodes[0]
			h.IP = node.IP.String()
			h.Host = h.IP // Default to IP, will be updated by concurrent DNS lookup
			// RTT from first probe (convert to milliseconds)
			if len(node.RTT) > 0 {
				rttMs := float64(node.RTT[0].Microseconds()) / 1000.0
				h.RTT1 = fmt.Sprintf("%.2f ms", rttMs)
			}
		} else {
			// No response at this hop - mark as timeout
			h.Timeout = true
		}
	}

	// Perform reverse DNS lookups concurrently to avoid 30+ second delays
	// Use a wait group to track all goroutines
	type dnsResult struct {
		index    int
		hostname string
	}
	dnsResults := make(chan dnsResult, maxDistance)
	dnsCtx, dnsCancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer dnsCancel()

	dnsCount := 0
	for i := range hops {
		if hops[i].IP != "" && !hops[i].Timeout {
			dnsCount++
			go func(idx int, ipAddr string) {
				names, err := net.DefaultResolver.LookupAddr(dnsCtx, ipAddr)
				if err == nil && len(names) > 0 {
					// Remove trailing dot from DNS name if present
					dnsResults <- dnsResult{idx, strings.TrimSuffix(names[0], ".")}
				} else {
					dnsResults <- dnsResult{idx, ""}
				}
			}(i, hops[i].IP)
		}
	}

	// Collect DNS results (non-blocking with timeout already handled by context)
	for j := 0; j < dnsCount; j++ {
		result := <-dnsResults
		if result.hostname != "" {
			hops[result.index].Host = result.hostname
		}
	}

	return &scraper.TracerouteResult{
		Target:   host,
		Status:   "success",
		Duration: fmt.Sprintf("%.1fs", duration.Seconds()),
		Hops:     hops,
		HopCount: len(hops),
	}
}
