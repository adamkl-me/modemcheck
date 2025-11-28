package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/gofrs/flock"
)

// ConfigState tracks client configuration sync state
// Stored in .config_state.json alongside config file (single file per API key)
// Version 2.1: API key-only binding (modem_id removed from primary key)
type ConfigState struct {
	Version          string    `json:"version"`            // Current version display (e.g., "v1_client")
	Status           string    `json:"status"`             // 6 status states (replaces Mode)
	ActiveTrack      string    `json:"active_track"`       // "client" or "server"
	ClientVersion    int       `json:"client_version"`     // Latest v#_client number
	ServerVersion    int       `json:"server_version"`     // Latest v#_server number
	ServerConfigHash string    `json:"server_config_hash"` // SHA256 hash from last sync
	LastSync         time.Time `json:"last_sync"`          // Last successful sync timestamp

	// Backward compatibility: Mode is deprecated, use Status
	Mode string `json:"mode,omitempty"` // DEPRECATED: kept for migration
}

// getStateFilePath returns the path to the state file
// Since configs are bound to API key only (not modem), we use a single state file
func getStateFilePath() (string, error) {
	// Get executable directory (same location as config file)
	execPath, err := os.Executable()
	if err != nil {
		return "", fmt.Errorf("failed to get executable path: %w", err)
	}

	dir := filepath.Dir(execPath)
	return filepath.Join(dir, ".config_state.json"), nil
}

// LoadConfigState loads the configuration sync state
// Returns default state (never synced) if file doesn't exist
func LoadConfigState() (*ConfigState, error) {
	stateFile, err := getStateFilePath()
	if err != nil {
		return nil, err
	}

	// Check if state file exists
	if _, err := os.Stat(stateFile); os.IsNotExist(err) {
		// No state file - return default state (first sync)
		return &ConfigState{
			Version:          "",
			Status:           "",
			ActiveTrack:      "",
			ClientVersion:    0,
			ServerVersion:    0,
			ServerConfigHash: "",
			LastSync:         time.Time{},
		}, nil
	}

	// Acquire read lock
	lock := flock.New(stateFile + ".lock")

	locked, err := lock.TryRLock()
	if err != nil {
		return nil, fmt.Errorf("failed to acquire read lock: %w", err)
	}
	if !locked {
		return nil, fmt.Errorf("state file is locked by another process")
	}
	defer lock.Unlock()

	// Read state file
	data, err := os.ReadFile(stateFile)
	if err != nil {
		return nil, fmt.Errorf("failed to read state file: %w", err)
	}

	// Parse JSON
	var state ConfigState
	if err := json.Unmarshal(data, &state); err != nil {
		return nil, fmt.Errorf("failed to parse state file: %w", err)
	}

	return &state, nil
}

// SaveConfigState atomically saves the configuration sync state
// Uses temp file + atomic rename to prevent corruption on crash
func SaveConfigState(state *ConfigState) error {
	stateFile, err := getStateFilePath()
	if err != nil {
		return err
	}

	// Acquire write lock
	lock := flock.New(stateFile + ".lock")

	locked, err := lock.TryLock()
	if err != nil {
		return fmt.Errorf("failed to acquire write lock: %w", err)
	}
	if !locked {
		return fmt.Errorf("state file is locked by another process")
	}
	defer lock.Unlock()

	// Marshal to JSON with indentation for readability
	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal state: %w", err)
	}

	// Atomic write: write to temp file, then rename
	tempFile := stateFile + ".tmp"

	// Write to temp file with restrictive permissions (only owner can read/write)
	if err := os.WriteFile(tempFile, data, 0600); err != nil {
		return fmt.Errorf("failed to write temp state file: %w", err)
	}

	// Atomic rename (overwrites existing file)
	if err := os.Rename(tempFile, stateFile); err != nil {
		// Clean up temp file on error
		os.Remove(tempFile)
		return fmt.Errorf("failed to rename temp state file: %w", err)
	}

	return nil
}

// UpdateConfigState updates specific fields in the state file atomically
// The updateFn receives the current state and can modify it
func UpdateConfigState(updateFn func(*ConfigState) error) error {
	// Load current state
	state, err := LoadConfigState()
	if err != nil {
		return fmt.Errorf("failed to load state: %w", err)
	}

	// Apply update function
	if err := updateFn(state); err != nil {
		return fmt.Errorf("update function failed: %w", err)
	}

	// Save updated state
	if err := SaveConfigState(state); err != nil {
		return fmt.Errorf("failed to save state: %w", err)
	}

	return nil
}

// CleanupOldStateFiles removes legacy per-modem state files from v2.0 and earlier
// These files had the format .config_state_{modem_id}.json
// Since v2.1, we use a single .config_state.json file
func CleanupOldStateFiles() error {
	// Get executable directory
	execPath, err := os.Executable()
	if err != nil {
		return fmt.Errorf("failed to get executable path: %w", err)
	}

	dir := filepath.Dir(execPath)

	// Find all legacy per-modem state files (but not the new single state file)
	pattern := filepath.Join(dir, ".config_state_*.json")
	matches, err := filepath.Glob(pattern)
	if err != nil {
		return fmt.Errorf("failed to glob state files: %w", err)
	}

	for _, stateFile := range matches {
		// Try to acquire write lock before deleting
		lockFile := stateFile + ".lock"
		lock := flock.New(lockFile)
		locked, err := lock.TryLock()
		if err != nil || !locked {
			continue // Skip locked files
		}

		// Delete state file while holding lock
		os.Remove(stateFile)

		// Release lock before deleting lock file (proper order for idempotency)
		lock.Unlock()

		// Delete lock file after releasing (safe to delete now)
		os.Remove(lockFile)
	}

	return nil
}

// IsConfigEnforced checks if config is in an enforced status
// Enforced configs should not be modified locally
func IsConfigEnforced() (bool, error) {
	state, err := LoadConfigState()
	if err != nil {
		return false, err
	}

	// Check for enforced status states
	return state.Status == "enforced_ready" || state.Status == "enforced_active", nil
}

// IsConfigLocked is an alias for IsConfigEnforced (backward compatibility)
// DEPRECATED: Use IsConfigEnforced instead
func IsConfigLocked() (bool, error) {
	return IsConfigEnforced()
}

// GetLastSyncInfo returns the last sync timestamp and version
func GetLastSyncInfo() (time.Time, string, error) {
	state, err := LoadConfigState()
	if err != nil {
		return time.Time{}, "", err
	}

	return state.LastSync, state.Version, nil
}

// ShouldSync determines if a config sync should be attempted
// Returns true if:
// - Never synced before (Version is empty)
// - More than syncInterval has elapsed since last sync
// - Config is in enforced status (always sync to catch server updates)
// - Config is in a "ready" state (pending server config to receive)
func ShouldSync(syncInterval time.Duration) (bool, error) {
	state, err := LoadConfigState()
	if err != nil {
		return false, err
	}

	// Never synced before
	if state.Version == "" {
		return true, nil
	}

	// Always sync if in enforced status (server might have updates)
	if state.Status == "enforced_ready" || state.Status == "enforced_active" {
		// But rate limit to once per hour minimum to avoid excessive requests
		if time.Since(state.LastSync) < 1*time.Hour {
			return false, nil
		}
		return true, nil
	}

	// Sync more frequently if in ready state (waiting for server config)
	if state.Status == "one_time_ready" {
		// Check every 15 minutes for pending server configs
		if time.Since(state.LastSync) < 15*time.Minute {
			return false, nil
		}
		return true, nil
	}

	// In other states, sync based on interval
	return time.Since(state.LastSync) >= syncInterval, nil
}
