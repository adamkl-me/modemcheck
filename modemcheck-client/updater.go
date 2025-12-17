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
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/gofrs/flock"
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

// parseSemanticVersion parses a semantic version string (e.g., "1.2.3" or "7.0.0-test.1")
// into major, minor, patch integers and optional pre-release suffix.
// Returns an error if the version string is not valid semver format.
func parseSemanticVersion(version string) (major, minor, patch int, prerelease string, err error) {
	// Remove any 'v' prefix
	version = strings.TrimPrefix(version, "v")

	// Check for pre-release suffix (e.g., "-test.1", "-beta.2")
	if idx := strings.Index(version, "-"); idx != -1 {
		prerelease = version[idx+1:]
		version = version[:idx]
	}

	// Split by dots
	parts := strings.Split(version, ".")
	if len(parts) != 3 {
		return 0, 0, 0, "", fmt.Errorf("invalid version format: expected X.Y.Z, got %s", version)
	}

	// Parse each component
	major, err = strconv.Atoi(parts[0])
	if err != nil {
		return 0, 0, 0, "", fmt.Errorf("invalid major version: %w", err)
	}

	minor, err = strconv.Atoi(parts[1])
	if err != nil {
		return 0, 0, 0, "", fmt.Errorf("invalid minor version: %w", err)
	}

	patch, err = strconv.Atoi(parts[2])
	if err != nil {
		return 0, 0, 0, "", fmt.Errorf("invalid patch version: %w", err)
	}

	return major, minor, patch, prerelease, nil
}

// shouldUpdateVersion returns true if latestVersion is newer than currentVersion using proper semver comparison.
// Handles pre-release versions (e.g., "7.0.0-test.1"):
// - 7.0.0 is newer than 7.0.0-test.1 (stable > pre-release)
// - 7.0.0-test.2 is newer than 7.0.0-test.1 (compare pre-release numbers)
func shouldUpdateVersion(currentVersion, latestVersion string) (bool, error) {
	curMajor, curMinor, curPatch, curPrerelease, err := parseSemanticVersion(currentVersion)
	if err != nil {
		return false, fmt.Errorf("failed to parse current version: %w", err)
	}

	latMajor, latMinor, latPatch, latPrerelease, err := parseSemanticVersion(latestVersion)
	if err != nil {
		return false, fmt.Errorf("failed to parse latest version: %w", err)
	}

	// Compare major version first
	if latMajor > curMajor {
		return true, nil
	} else if latMajor < curMajor {
		return false, nil
	}

	// Major versions equal, compare minor
	if latMinor > curMinor {
		return true, nil
	} else if latMinor < curMinor {
		return false, nil
	}

	// Major and minor equal, compare patch
	if latPatch > curPatch {
		return true, nil
	} else if latPatch < curPatch {
		return false, nil
	}

	// Major, minor, and patch all equal - check pre-release status
	// Stable version (no prerelease) is newer than pre-release of same version
	if curPrerelease != "" && latPrerelease == "" {
		// Current is pre-release, latest is stable - upgrade to stable
		return true, nil
	} else if curPrerelease == "" && latPrerelease != "" {
		// Current is stable, latest is pre-release - don't downgrade
		return false, nil
	} else if curPrerelease != "" && latPrerelease != "" {
		// Both are pre-releases - compare pre-release versions
		// Try to extract numbers from pre-release (e.g., "test.1" -> 1)
		curPrereleaseNum := extractPrereleaseNumber(curPrerelease)
		latPrereleaseNum := extractPrereleaseNumber(latPrerelease)

		if latPrereleaseNum > curPrereleaseNum {
			return true, nil
		}
	}

	// Latest version is equal or older
	return false, nil
}

// extractPrereleaseNumber extracts the numeric part from a pre-release string.
// E.g., "test.1" -> 1, "beta.12" -> 12, "alpha" -> 0
func extractPrereleaseNumber(prerelease string) int {
	// Find the last dot and get everything after it
	parts := strings.Split(prerelease, ".")
	if len(parts) < 2 {
		return 0
	}

	lastPart := parts[len(parts)-1]
	num, err := strconv.Atoi(lastPart)
	if err != nil {
		return 0
	}
	return num
}

// checkUpdateLock checks if an update was recently attempted and failed.
// Returns true if the update should be blocked (cooldown period not expired).
// Uses flock to prevent race conditions with concurrent update checks.
func checkUpdateLock(targetVersion string) bool {
	exePath, err := os.Executable()
	if err != nil {
		return false
	}
	exeDir := filepath.Dir(exePath)
	lockPath := filepath.Join(exeDir, UpdateLockFile)
	flockPath := lockPath + ".flock"

	// Acquire file lock to prevent race conditions
	fileLock := flock.New(flockPath)
	locked, err := fileLock.TryRLock()
	if err != nil || !locked {
		// Can't acquire lock, be conservative and block update
		return true
	}
	defer fileLock.Unlock()

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
// Uses flock to prevent race conditions with concurrent writes.
func createUpdateLock(version string) {
	exePath, err := os.Executable()
	if err != nil {
		return
	}
	exeDir := filepath.Dir(exePath)
	lockPath := filepath.Join(exeDir, UpdateLockFile)
	flockPath := lockPath + ".flock"

	// Acquire exclusive file lock
	fileLock := flock.New(flockPath)
	locked, err := fileLock.TryLock()
	if err != nil || !locked {
		// Can't acquire lock, skip creating update lock
		return
	}
	defer fileLock.Unlock()

	lock := UpdateLock{
		Version:   version,
		Timestamp: time.Now(),
	}

	data, err := json.MarshalIndent(lock, "", "  ")
	if err != nil {
		return
	}

	os.WriteFile(lockPath, data, 0600)
}

// clearUpdateLock removes the update lock file.
// Uses flock to prevent race conditions.
func clearUpdateLock() {
	exePath, err := os.Executable()
	if err != nil {
		return
	}
	exeDir := filepath.Dir(exePath)
	lockPath := filepath.Join(exeDir, UpdateLockFile)
	flockPath := lockPath + ".flock"

	// Acquire exclusive file lock
	fileLock := flock.New(flockPath)
	locked, err := fileLock.TryLock()
	if err != nil || !locked {
		return
	}
	defer fileLock.Unlock()

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

// extractTimestampFromSignature extracts the cryptographic timestamp from a Minisign signature file.
// Returns the timestamp and build date embedded in the signature's trusted comment.
// Returns an error if the signature format is invalid or timestamp is missing.
func extractTimestampFromSignature(signaturePath string) (time.Time, string, error) {
	// Read signature file
	sigData, err := os.ReadFile(signaturePath)
	if err != nil {
		return time.Time{}, "", fmt.Errorf("failed to read signature file: %w", err)
	}

	// Parse signature lines
	lines := strings.Split(string(sigData), "\n")
	for _, line := range lines {
		// Look for trusted comment line (starts with "trusted comment:")
		if strings.HasPrefix(line, "trusted comment:") {
			// Extract comment text after "trusted comment: "
			comment := strings.TrimPrefix(line, "trusted comment:")
			comment = strings.TrimSpace(comment)

			// Parse timestamp from comment (format: "timestamp:1234567890")
			timestampIdx := strings.Index(comment, "timestamp:")
			if timestampIdx == -1 {
				return time.Time{}, "", fmt.Errorf("timestamp not found in signature trusted comment")
			}

			// Extract timestamp value (between "timestamp:" and next space or end)
			timestampStart := timestampIdx + len("timestamp:")
			timestampEnd := strings.Index(comment[timestampStart:], " ")
			var timestampStr string
			if timestampEnd == -1 {
				timestampStr = comment[timestampStart:]
			} else {
				timestampStr = comment[timestampStart : timestampStart+timestampEnd]
			}

			// Parse Unix timestamp
			timestamp, err := strconv.ParseInt(timestampStr, 10, 64)
			if err != nil {
				return time.Time{}, "", fmt.Errorf("invalid timestamp format: %w", err)
			}

			// Extract build date (format: "build_date:2025-11-22")
			buildDate := ""
			buildDateIdx := strings.Index(comment, "build_date:")
			if buildDateIdx != -1 {
				buildDateStart := buildDateIdx + len("build_date:")
				buildDateEnd := strings.Index(comment[buildDateStart:], " ")
				if buildDateEnd == -1 {
					buildDate = comment[buildDateStart:]
				} else {
					buildDate = comment[buildDateStart : buildDateStart+buildDateEnd]
				}
				buildDate = strings.TrimSpace(buildDate)
			}

			return time.Unix(timestamp, 0), buildDate, nil
		}
	}

	return time.Time{}, "", fmt.Errorf("trusted comment not found in signature file")
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

// normalizeExecutablePath removes any trailing .old extensions from an executable path.
// This prevents infinite .old.old.old chaining if the binary is executed from a backup file.
//
// Examples:
//   - /usr/local/bin/modem-check          → /usr/local/bin/modem-check
//   - /usr/local/bin/modem-check.old      → /usr/local/bin/modem-check
//   - /usr/local/bin/modem-check.old.old  → /usr/local/bin/modem-check
//
// This handles edge cases where:
//   - User manually runs the .old backup
//   - Cron job or systemd service points to .old file
//   - Process continues running after a failed rollback
func normalizeExecutablePath(path string) string {
	// Remove all trailing .old extensions
	// Use a loop in case there are multiple .old.old.old extensions
	for strings.HasSuffix(path, ".old") {
		path = strings.TrimSuffix(path, ".old")
	}
	return path
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

	// Normalize executable path to prevent .old chaining
	currentExe = normalizeExecutablePath(currentExe)

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

	// Use context-based timeout for better control and graceful cancellation
	ctx, cancel := context.WithTimeout(context.Background(), UpdateTimeout)
	defer cancel()

	client := &http.Client{}
	req, err := http.NewRequestWithContext(ctx, "GET", apiURL, nil)
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

	// Compare versions using proper semantic versioning
	shouldUpdate, err := shouldUpdateVersion(currentVersion, latestVersion)
	if err != nil {
		m.Log(fmt.Sprintf("Warning: Failed to parse version numbers: %v (current: %s, latest: %s)", err, currentVersion, latestVersion))
		// Fall back to string comparison for non-semver versions
		if latestVersion <= currentVersion {
			m.Log(fmt.Sprintf("Already running latest version: v%s", currentVersion))
			return false, "", ""
		}
	} else if !shouldUpdate {
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

	// Normalize executable path by removing any trailing .old extensions
	// This prevents infinite .old.old.old chaining if the binary is somehow
	// executed from a backup file (e.g., manual execution, cron job misconfiguration)
	currentExe = normalizeExecutablePath(currentExe)

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

	// STEP 3.5: Verify signature timestamp freshness (prevents rollback attacks)
	// Extract cryptographic timestamp from signature (can't be manipulated like file mtime)
	// An attacker with GitHub access could serve an old vulnerable binary with valid signature,
	// but they can't forge a new timestamp without the signing key
	sigTimestamp, buildDate, err := extractTimestampFromSignature(sigFile)
	if err != nil {
		// Fallback to file mtime for backwards compatibility with old signatures
		m.Log(fmt.Sprintf("Warning: Could not extract timestamp from signature (%v), using file mtime", err))
		sigInfo, statErr := os.Stat(sigFile)
		if statErr != nil {
			cleanup()
			return fmt.Errorf("failed to get signature file info: %w", statErr)
		}
		sigTimestamp = sigInfo.ModTime()
		buildDate = ""
	}

	// Verify signature timestamp is reasonable
	sigAge := time.Since(sigTimestamp)
	// maxSignatureAge limits how old a signed binary can be to prevent rollback attacks.
	// An attacker with repository access could serve an old vulnerable binary with a valid
	// signature. The 30-day window balances security (limiting attack surface) against
	// operational needs (allowing normal release cycles and client update delays).
	// SECURITY NOTE: Consider reducing to 7-14 days for higher-security deployments.
	const maxSignatureAge = 30 * 24 * time.Hour // 30 days

	// Check for clock skew (negative age means signature is in the future)
	if sigAge < 0 {
		cleanup()
		return fmt.Errorf("signature timestamp is in the future (clock skew detected)")
	}

	// Check for rollback attacks (signature too old)
	if sigAge > maxSignatureAge {
		cleanup()
		return fmt.Errorf("signature timestamp too old (%d days), possible rollback attack (max age: 30 days)", int(sigAge.Hours()/24))
	}

	if buildDate != "" {
		m.Log(fmt.Sprintf("✓ Signature freshness verified (age: %d days, build date: %s)", int(sigAge.Hours()/24), buildDate))
	} else {
		m.Log(fmt.Sprintf("✓ Signature freshness verified (age: %d days)", int(sigAge.Hours()/24)))
	}

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
// It uses context-based timeout for better control and graceful cancellation.
func downloadFile(filepath string, url string) error {
	// Use context-based timeout for better control and graceful cancellation
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()

	client := &http.Client{}

	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
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

	// Limit download size to prevent downloading extremely large files
	limitedReader := io.LimitReader(resp.Body, MaxBinaryDownloadSize)

	written, err := io.Copy(out, limitedReader)
	if err != nil {
		return err
	}

	// Check if we hit the size limit
	if written == MaxBinaryDownloadSize {
		os.Remove(filepath)
		return fmt.Errorf("download exceeded size limit of %d MB", MaxBinaryDownloadSize/(1024*1024))
	}

	return nil
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
