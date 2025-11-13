package main

import (
	"context"
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

	"github.com/jedisct1/go-minisign"
)

// Update-related constants.
const (
	GitHubAPILatestURL    = "https://api.github.com/repos/adamkl-me/modemcheck/releases/latest"
	GitHubAPIReleasesURL  = "https://api.github.com/repos/adamkl-me/modemcheck/releases"
	UpdateTimeout         = 30 * time.Second
	UpdateUserAgent       = "ModemCheck-AutoUpdater"
	UpdateLockFile        = ".update_lock"
	UpdateCooldown        = 5 * time.Minute

	// MinisignPublicKey is the public key used to verify update signatures
	// This key must match the private key used to sign release binaries
	MinisignPublicKey = "RWQGilCovDisAC2fs6E3Og2ETthVyaxIlAW/En1rsPQmR5aA2TVO9n90"
)

// GitHubRelease represents a GitHub release API response.
type GitHubRelease struct {
	TagName    string `json:"tag_name"`
	Prerelease bool   `json:"prerelease"`
	Draft      bool   `json:"draft"`
	Assets     []struct {
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

// verifySignature verifies the Minisign signature of a file.
// Returns nil if the signature is valid, or an error if verification fails.
func verifySignature(filePath, signaturePath string) error {
	// Read the public key
	publicKey, err := minisign.NewPublicKey(MinisignPublicKey)
	if err != nil {
		return fmt.Errorf("failed to parse public key: %w", err)
	}

	// Read the signature file
	sigData, err := os.ReadFile(signaturePath)
	if err != nil {
		return fmt.Errorf("failed to read signature file: %w", err)
	}

	signature, err := minisign.DecodeSignature(string(sigData))
	if err != nil {
		return fmt.Errorf("failed to parse signature: %w", err)
	}

	// Read and verify the file
	fileData, err := os.ReadFile(filePath)
	if err != nil {
		return fmt.Errorf("failed to read file for verification: %w", err)
	}

	valid, err := publicKey.Verify(fileData, signature)
	if err != nil {
		return fmt.Errorf("signature verification error: %w", err)
	}

	if !valid {
		return fmt.Errorf("signature verification failed: invalid signature")
	}

	return nil
}

// verifyBinaryExecutable verifies that a binary can execute by running it with --version flag.
// This helps catch corrupted downloads or incompatible binaries before installation.
func verifyBinaryExecutable(binaryPath string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	cmd := exec.CommandContext(ctx, binaryPath, "--version")
	output, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("binary failed to execute: %w (output: %s)", err, string(output))
	}

	// Check that output contains something reasonable (not empty)
	if len(output) == 0 {
		return fmt.Errorf("binary produced no output for --version")
	}

	return nil
}

// RollbackUpdate restores the backup binary if it exists.
// This is called when a new update fails to work properly.
func (m *ModemCheck) RollbackUpdate() error {
	currentExe, err := os.Executable()
	if err != nil {
		return fmt.Errorf("failed to get executable path: %w", err)
	}

	currentExe, err = filepath.EvalSymlinks(currentExe)
	if err != nil {
		return fmt.Errorf("failed to resolve symlinks: %w", err)
	}

	backupFile := currentExe + ".old"

	// Check if backup exists
	if _, err := os.Stat(backupFile); os.IsNotExist(err) {
		return fmt.Errorf("no backup file found at: %s", backupFile)
	}

	m.Log("Rolling back to previous version...")

	// Remove the current (broken) binary
	if err := os.Remove(currentExe); err != nil {
		return fmt.Errorf("failed to remove current binary: %w", err)
	}

	// Restore the backup
	if err := os.Rename(backupFile, currentExe); err != nil {
		return fmt.Errorf("failed to restore backup: %w", err)
	}

	// Clear the update lock so updates can be attempted again
	clearUpdateLock()

	m.Log("Successfully rolled back to previous version")
	return nil
}

// CheckForUpdates checks GitHub releases for a newer version and returns update availability,
// the latest version string, and download URL for the current platform's binary.
// It supports both stable releases and pre-releases based on the UpdateChannel config setting.
func (m *ModemCheck) CheckForUpdates() (updateAvailable bool, latestVersion string, downloadURL string) {
	if !m.config.AutoUpdateEnabled {
		return false, "", ""
	}

	// Determine which API endpoint to use based on update channel
	apiURL := GitHubAPILatestURL
	includePrerelease := false

	if m.config.UpdateChannel == "beta" || m.config.UpdateChannel == "test" {
		apiURL = GitHubAPIReleasesURL
		includePrerelease = true
		m.Log(fmt.Sprintf("Checking for updates (channel: %s, including pre-releases)...", m.config.UpdateChannel))
	} else {
		m.Log("Checking for updates...")
	}

	client := &http.Client{Timeout: UpdateTimeout}
	req, err := http.NewRequest("GET", apiURL, nil)
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

	// Parse response based on endpoint
	var releases []GitHubRelease
	if includePrerelease {
		// Using /releases endpoint - returns array
		if err := json.NewDecoder(resp.Body).Decode(&releases); err != nil {
			m.Log(fmt.Sprintf("Failed to parse releases info: %v", err))
			return false, "", ""
		}

		// Filter to only include pre-releases, exclude drafts
		var filteredReleases []GitHubRelease
		for _, rel := range releases {
			if !rel.Draft && rel.Prerelease {
				filteredReleases = append(filteredReleases, rel)
			}
		}

		if len(filteredReleases) == 0 {
			m.Log("No pre-release versions available")
			return false, "", ""
		}

		// Use the first (most recent) pre-release
		releases = filteredReleases[:1]
	} else {
		// Using /releases/latest endpoint - returns single object
		var release GitHubRelease
		if err := json.NewDecoder(resp.Body).Decode(&release); err != nil {
			m.Log(fmt.Sprintf("Failed to parse release info: %v", err))
			return false, "", ""
		}
		releases = []GitHubRelease{release}
	}

	release := releases[0]

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

	// Find the appropriate binary for this platform using runtime detection
	platformName := getPlatformBinaryName()
	for _, asset := range release.Assets {
		if strings.Contains(asset.Name, platformName) {
			releaseType := "stable"
			if release.Prerelease {
				releaseType = "pre-release"
			}
			m.Log(fmt.Sprintf("Update available: v%s -> v%s (%s)", currentVersion, latestVersion, releaseType))
			return true, latestVersion, asset.BrowserDownloadURL
		}
	}

	m.Log(fmt.Sprintf("Update available (v%s) but no binary found for platform: %s", latestVersion, platformName))
	return false, "", ""
}

// DownloadAndApplyUpdate downloads the update binary, validates it with cryptographic
// signature verification, verifies it can execute, creates a backup of the current binary,
// and atomically replaces it with the new version. This function addresses two critical
// security vulnerabilities: lack of code signing and TOCTOU race conditions.
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

	// Define file paths
	tmpFile := currentExe + ".tmp"
	sigFile := tmpFile + ".minisig"
	backupFile := currentExe + ".old"

	// Cleanup function to remove temporary files on error
	cleanup := func() {
		os.Remove(tmpFile)
		os.Remove(sigFile)
	}

	// STEP 1: Download binary to temporary file
	// This prevents TOCTOU by downloading first before touching the current binary
	if err := downloadFile(tmpFile, downloadURL); err != nil {
		cleanup()
		return fmt.Errorf("failed to download update: %w", err)
	}
	m.Log("Binary downloaded successfully")

	// STEP 2: Download signature file
	// Signature files should be named the same as the binary with .minisig extension
	signatureURL := downloadURL + ".minisig"
	if err := downloadFile(sigFile, signatureURL); err != nil {
		cleanup()
		return fmt.Errorf("failed to download signature file: %w", err)
	}
	m.Log("Signature file downloaded successfully")

	// STEP 3: Verify signature (CRITICAL SECURITY CHECK)
	// This prevents execution of malicious or tampered binaries
	m.Log("Verifying cryptographic signature...")
	if err := verifySignature(tmpFile, sigFile); err != nil {
		cleanup()
		return fmt.Errorf("signature verification failed: %w", err)
	}
	m.Log("✓ Signature verification passed")

	// STEP 4: Make the new binary executable (Unix systems)
	if runtime.GOOS != "windows" {
		if err := os.Chmod(tmpFile, 0755); err != nil {
			cleanup()
			return fmt.Errorf("failed to make binary executable: %w", err)
		}
	}

	// STEP 5: Verify binary can execute (pre-execution check)
	// This catches corrupted downloads or incompatible binaries before installation
	m.Log("Verifying binary can execute...")
	if err := verifyBinaryExecutable(tmpFile); err != nil {
		cleanup()
		return fmt.Errorf("binary verification failed: %w", err)
	}
	m.Log("✓ Binary execution test passed")

	// STEP 6: Create backup of current binary
	// Remove old backup if exists
	os.Remove(backupFile)

	if err := os.Rename(currentExe, backupFile); err != nil {
		cleanup()
		return fmt.Errorf("failed to backup current binary: %w", err)
	}
	m.Log("Current binary backed up")

	// STEP 7: Atomically move new binary into place
	// This is the critical section - if this fails, rollback is attempted
	if err := os.Rename(tmpFile, currentExe); err != nil {
		// ROLLBACK: Attempt to restore backup
		m.Log("Failed to install update, attempting rollback...")
		if rollbackErr := os.Rename(backupFile, currentExe); rollbackErr != nil {
			// Critical failure: both install and rollback failed
			// System may be in broken state - log error and manual intervention needed
			return fmt.Errorf("CRITICAL: failed to install update AND rollback failed: install error: %w, rollback error: %v", err, rollbackErr)
		}
		cleanup()
		return fmt.Errorf("failed to install update (rollback successful): %w", err)
	}

	// Cleanup signature file (no longer needed)
	os.Remove(sigFile)

	m.Log(fmt.Sprintf("✓ Successfully updated to v%s", newVersion))
	m.Log("Backup saved as: " + backupFile)

	// Create update lock to track this update attempt
	// This will be checked on next startup to verify the update succeeded
	createUpdateLock(newVersion)

	m.Log("Restarting with new version...")

	// Note: We intentionally keep the .old backup file instead of deleting it
	// This allows for manual rollback if the new version has issues
	// The backup will be cleaned up on the next successful update

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
// It uses Go's runtime constants directly to avoid brittle string parsing and mapping.
// The naming convention matches the output of the Makefile's cross-compilation targets.
func getPlatformBinaryName() string {
	// Use runtime constants directly - no manual mapping needed
	// This is more robust and leverages Go's build system
	osName := runtime.GOOS
	archName := runtime.GOARCH

	// Normalize architecture name to match release naming convention
	// Only map the ones that differ from Go's standard naming
	switch archName {
	case "amd64":
		archName = "x64"
	case "386":
		archName = "x86"
	// arm, arm64, mips, mipsle, etc. are used as-is
	}

	// Build platform string based on OS
	// Use compile-time constant checks where possible for better optimization
	var platformName string

	switch osName {
	case "windows":
		// Windows binaries have .exe extension
		platformName = fmt.Sprintf("%s-%s.exe", osName, archName)
	case "darwin", "linux", "freebsd", "openbsd", "netbsd":
		// Unix-like systems: no extension
		platformName = fmt.Sprintf("%s-%s", osName, archName)
	default:
		// Fallback for any other OS
		platformName = fmt.Sprintf("%s-%s", osName, archName)
	}

	return platformName
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
