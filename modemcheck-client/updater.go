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

// Update-related constants.
const (
	GitHubAPIURL    = "https://api.github.com/repos/adamkl-me/modemcheck/releases/latest"
	UpdateTimeout   = 30 * time.Second
	UpdateUserAgent = "ModemCheck-AutoUpdater"
	UpdateLockFile  = ".update_lock"
	UpdateCooldown  = 5 * time.Minute
)

// GitHubRelease represents a GitHub release API response.
type GitHubRelease struct {
	TagName string `json:"tag_name"`
	Assets  []struct {
		Name               string `json:"name"`
		BrowserDownloadURL string `json:"browser_download_url"`
	} `json:"assets"`
}

// UpdateLock represents the update lock file structure.
type UpdateLock struct {
	Version   string    `json:"version"`
	Timestamp time.Time `json:"timestamp"`
}

// checkUpdateLock checks if an update was recently attempted and failed.
// Returns true if the update should be blocked (cooldown period not expired).
func checkUpdateLock(targetVersion string) bool {
	exePath, err := os.Executable()
	if err != nil {
		return false
	}
	exeDir := filepath.Dir(exePath)
	lockPath := filepath.Join(exeDir, UpdateLockFile)

	data, err := os.ReadFile(lockPath)
	if err != nil {
		// No lock file, allow update
		return false
	}

	var lock UpdateLock
	if err := json.Unmarshal(data, &lock); err != nil {
		// Invalid lock file, allow update
		return false
	}

	// Check if the lock is for the same version
	if lock.Version != targetVersion {
		// Different version, allow update
		return false
	}

	// Check if cooldown period has expired
	if time.Since(lock.Timestamp) > UpdateCooldown {
		// Cooldown expired, allow update
		return false
	}

	// Update blocked due to recent failed attempt
	return true
}

// createUpdateLock creates a lock file to prevent repeated update attempts.
func createUpdateLock(version string) {
	exePath, err := os.Executable()
	if err != nil {
		return
	}
	exeDir := filepath.Dir(exePath)
	lockPath := filepath.Join(exeDir, UpdateLockFile)

	lock := UpdateLock{
		Version:   version,
		Timestamp: time.Now(),
	}

	data, err := json.MarshalIndent(lock, "", "  ")
	if err != nil {
		return
	}

	os.WriteFile(lockPath, data, 0644)
}

// clearUpdateLock removes the update lock file.
func clearUpdateLock() {
	exePath, err := os.Executable()
	if err != nil {
		return
	}
	exeDir := filepath.Dir(exePath)
	lockPath := filepath.Join(exeDir, UpdateLockFile)
	os.Remove(lockPath)
}

// CheckForUpdates checks GitHub releases for a newer version and returns update availability,
// the latest version string, and download URL for the current platform's binary.
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

	// Simple string comparison for version checking (works for basic semver)
	// Note: This uses lexicographic comparison which may not work for all version formats
	if latestVersion <= currentVersion {
		m.Log(fmt.Sprintf("Already running latest version: v%s", currentVersion))
		return false, "", ""
	}

	// Check if an update to this version was recently attempted and failed
	if checkUpdateLock(latestVersion) {
		m.Log(fmt.Sprintf("Update to v%s was recently attempted and may have failed. Waiting for cooldown period.", latestVersion))
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

// DownloadAndApplyUpdate downloads the update binary, validates it, creates a backup
// of the current binary, and atomically replaces it with the new version.
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

	// Create update lock to track this update attempt
	// This will be checked on next startup to verify the update succeeded
	createUpdateLock(newVersion)

	m.Log("Restarting with new version...")

	// Clean up backup after successful update
	// We do this in a separate goroutine after a delay to ensure the new process starts
	go func() {
		time.Sleep(5 * time.Second)
		os.Remove(backupFile)
	}()

	return nil
}

// downloadFile downloads a file from the given URL and saves it to the specified filepath.
// It uses an HTTP client with a 5-minute timeout and validates the response status code.
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

// getPlatformBinaryName returns the platform-specific binary name pattern used in GitHub releases.
// It maps Go's GOOS/GOARCH values to the naming convention used for release binaries.
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

// RestartProcess restarts the current process with the same arguments.
// On Windows, it spawns a new process and exits. On Unix systems, it uses execve to replace the current process.
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
