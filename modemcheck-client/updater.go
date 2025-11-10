package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"time"
)

const (
	GitHubAPIURL    = "https://api.github.com/repos/adamkl-me/modemcheck/releases/latest"
	UpdateTimeout   = 30 * time.Second
	UpdateUserAgent = "ModemCheck-AutoUpdater"
)

// GitHubRelease represents a GitHub release response
type GitHubRelease struct {
	TagName string `json:"tag_name"`
	Assets  []struct {
		Name               string `json:"name"`
		BrowserDownloadURL string `json:"browser_download_url"`
	} `json:"assets"`
}

// CheckForUpdates checks GitHub releases for a newer version
func (m *ModemCheck) CheckForUpdates() (updateAvailable bool, latestVersion string, downloadURL string) {
	if !m.config.AutoUpdateEnabled {
		return false, "", ""
	}

	m.Log("Checking for updates...")

	client := &http.Client{Timeout: UpdateTimeout}
	req, err := http.NewRequest("GET", GitHubAPIURL, nil)
	if err != nil {
		m.Log(fmt.Sprintf("Update check failed: %v", err))
		return false, "", ""
	}

	req.Header.Set("User-Agent", UpdateUserAgent)
	req.Header.Set("Accept", "application/vnd.github.v3+json")

	resp, err := client.Do(req)
	if err != nil {
		m.Log(fmt.Sprintf("Update check failed: %v", err))
		return false, "", ""
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		m.Log(fmt.Sprintf("Update check failed with status: %d", resp.StatusCode))
		return false, "", ""
	}

	var release GitHubRelease
	if err := json.NewDecoder(resp.Body).Decode(&release); err != nil {
		m.Log(fmt.Sprintf("Failed to parse release info: %v", err))
		return false, "", ""
	}

	// Remove 'v' prefix if present for comparison
	latestVersion = strings.TrimPrefix(release.TagName, "v")
	currentVersion := strings.TrimPrefix(Version, "v")

	// Simple version comparison (works for semver)
	if latestVersion <= currentVersion {
		m.Log(fmt.Sprintf("Already running latest version: v%s", currentVersion))
		return false, "", ""
	}

	// Find the appropriate binary for this platform
	platformName := getPlatformBinaryName()
	for _, asset := range release.Assets {
		if strings.Contains(asset.Name, platformName) {
			m.Log(fmt.Sprintf("Update available: v%s -> v%s", currentVersion, latestVersion))
			return true, latestVersion, asset.BrowserDownloadURL
		}
	}

	m.Log(fmt.Sprintf("Update available (v%s) but no binary found for platform: %s", latestVersion, platformName))
	return false, "", ""
}

// DownloadAndApplyUpdate downloads and applies the update
func (m *ModemCheck) DownloadAndApplyUpdate(downloadURL, newVersion string) error {
	m.Log(fmt.Sprintf("Downloading update from: %s", downloadURL))

	// Get current executable path
	currentExe, err := os.Executable()
	if err != nil {
		return fmt.Errorf("failed to get executable path: %w", err)
	}

	// Resolve symlinks
	currentExe, err = filepath.EvalSymlinks(currentExe)
	if err != nil {
		return fmt.Errorf("failed to resolve symlinks: %w", err)
	}

	// Download to temporary file
	tmpFile := currentExe + ".tmp"
	if err := downloadFile(tmpFile, downloadURL); err != nil {
		return fmt.Errorf("failed to download update: %w", err)
	}

	// Make the new binary executable (Unix systems)
	if runtime.GOOS != "windows" {
		if err := os.Chmod(tmpFile, 0755); err != nil {
			os.Remove(tmpFile)
			return fmt.Errorf("failed to make binary executable: %w", err)
		}
	}

	// Backup current binary
	backupFile := currentExe + ".old"
	os.Remove(backupFile) // Remove old backup if exists

	if err := os.Rename(currentExe, backupFile); err != nil {
		os.Remove(tmpFile)
		return fmt.Errorf("failed to backup current binary: %w", err)
	}

	// Move new binary into place
	if err := os.Rename(tmpFile, currentExe); err != nil {
		// Try to restore backup
		os.Rename(backupFile, currentExe)
		return fmt.Errorf("failed to install update: %w", err)
	}

	m.Log(fmt.Sprintf("Successfully updated to v%s", newVersion))
	m.Log("Backup saved as: " + backupFile)
	m.Log("Restarting with new version...")

	// Clean up backup after successful update
	// We do this in a separate goroutine after a delay to ensure the new process starts
	go func() {
		time.Sleep(5 * time.Second)
		os.Remove(backupFile)
	}()

	return nil
}

// downloadFile downloads a file from url to filepath
func downloadFile(filepath string, url string) error {
	client := &http.Client{Timeout: 5 * time.Minute}

	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return err
	}
	req.Header.Set("User-Agent", UpdateUserAgent)

	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("download failed with status: %d", resp.StatusCode)
	}

	out, err := os.Create(filepath)
	if err != nil {
		return err
	}
	defer out.Close()

	_, err = io.Copy(out, resp.Body)
	return err
}

// getPlatformBinaryName returns the platform-specific binary name pattern
func getPlatformBinaryName() string {
	goos := runtime.GOOS
	goarch := runtime.GOARCH

	// Map Go architecture names to binary naming convention
	archMap := map[string]string{
		"amd64": "x64",
		"arm":   "arm",
		"arm64": "arm64",
	}

	arch := archMap[goarch]
	if arch == "" {
		arch = goarch
	}

	// Handle OS-specific naming
	switch goos {
	case "darwin":
		return fmt.Sprintf("darwin-%s", arch)
	case "windows":
		return fmt.Sprintf("windows-%s.exe", arch)
	case "linux":
		return fmt.Sprintf("linux-%s", arch)
	case "freebsd":
		return fmt.Sprintf("freebsd-%s", arch)
	default:
		return fmt.Sprintf("%s-%s", goos, arch)
	}
}

// RestartProcess restarts the current process with the same arguments
func RestartProcess() error {
	executable, err := os.Executable()
	if err != nil {
		return fmt.Errorf("failed to get executable path: %w", err)
	}

	// Get current process arguments
	args := os.Args[1:]

	// On Windows, we need to use a different approach
	if runtime.GOOS == "windows" {
		// Spawn new process and exit current
		cmd := exec.Command(executable, args...)
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		cmd.Stdin = os.Stdin

		if err := cmd.Start(); err != nil {
			return fmt.Errorf("failed to start new process: %w", err)
		}

		os.Exit(0)
	}

	// On Unix systems, use execve to replace current process
	return syscall.Exec(executable, append([]string{executable}, args...), os.Environ())
}
