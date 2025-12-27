//go:build windows

package main

import "modemcheck-client/scraper"

// runTraceroute executes a traceroute to the specified host using the system tracert command.
// On Windows, we use the native tracert command directly since the Go traceroute library
// (pixelbender/go-traceroute) uses Unix-specific syscalls that don't compile on Windows.
func (m *ModemCheck) runTraceroute(host string) *scraper.TracerouteResult {
	return m.runSystemTraceroute(host)
}
