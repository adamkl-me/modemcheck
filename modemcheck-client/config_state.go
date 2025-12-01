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
//
// Version 3.0: Simplified state model
// - Status: unmanaged, managed, locked (3 states, not 6)
// - SyncStatus: n/a, pending, active
// - Version: simple int (1, 2, 3...) not string ("v1_client")
type ConfigState struct {
	Version          int       `json:"version"`            // Simple int version (1, 2, 3...)
	Status           string    `json:"status"`             // unmanaged, managed, locked
	SyncStatus       string    `json:"sync_status"`        // n/a, pending, active
	ServerConfigHash string    `json:"server_config_hash"` // SHA256 hash from last sync
	LastSync         time.Time `json:"last_sync"`          // Last successful sync timestamp
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
			Version:          0,
			Status:           "",
			SyncStatus:       "",
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

	// Track if we've manually unlocked (to avoid double-unlock in defer)
	unlocked := false
	defer func() {
		if !unlocked {
			lock.Unlock()
		}
	}()

	// Read state file
	data, err := os.ReadFile(stateFile)
	if err != nil {
		return nil, fmt.Errorf("failed to read state file: %w", err)
	}

	// Parse JSON
	var state ConfigState
	if err := json.Unmarshal(data, &state); err != nil {
		// State file is corrupted - attempt recovery
		fmt.Fprintf(os.Stderr, "Warning: state file corrupted, attempting recovery: %v\n", err)

		// Release read lock before recovery (RecoverStateFile needs write lock)
		// Mark as unlocked so defer doesn't double-unlock
		unlocked = true
		lock.Unlock()

		recoveredState, recoverErr := RecoverStateFile()
		if recoverErr != nil {
			return nil, fmt.Errorf("failed to parse state file and recovery failed: parse error: %w, recovery error: %v", err, recoverErr)
		}

		return recoveredState, nil
	}

	return &state, nil
}

// SaveConfigState atomically saves the configuration sync state
// Uses temp file + atomic rename to prevent corruption on crash
// Also creates a backup (.bak) for recovery if main file is corrupted
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

	// Create backup of existing state file before overwriting
	backupFile := stateFile + ".bak"
	if _, err := os.Stat(stateFile); err == nil {
		// State file exists, create backup
		if err := os.Rename(stateFile, backupFile); err != nil {
			// Continue even if backup fails (non-critical)
			fmt.Fprintf(os.Stderr, "Warning: failed to create state file backup: %v\n", err)
		}
	}

	// Atomic write: write to temp file, then rename
	tempFile := stateFile + ".tmp"

	// Write to temp file with restrictive permissions (only owner can read/write)
	if err := os.WriteFile(tempFile, data, 0600); err != nil {
		// Restore from backup if write failed
		if _, bakErr := os.Stat(backupFile); bakErr == nil {
			os.Rename(backupFile, stateFile)
		}
		return fmt.Errorf("failed to write temp state file: %w", err)
	}

	// Atomic rename (overwrites existing file)
	if err := os.Rename(tempFile, stateFile); err != nil {
		// Clean up temp file on error
		os.Remove(tempFile)
		// Restore from backup
		if _, bakErr := os.Stat(backupFile); bakErr == nil {
			os.Rename(backupFile, stateFile)
		}
		return fmt.Errorf("failed to rename temp state file: %w", err)
	}

	// Success - can remove old backup now
	os.Remove(backupFile)

	return nil
}

// RecoverStateFile attempts to recover a corrupted state file
// Recovery strategy (in order of preference):
//  1. Try to restore from backup file (.bak)
//  2. Try to restore from temp file (.tmp) if it exists and is valid
//  3. Reinitialize with default state (safe fallback)
//
// This function is called automatically by LoadConfigState() if JSON parsing fails
func RecoverStateFile() (*ConfigState, error) {
	stateFile, err := getStateFilePath()
	if err != nil {
		return nil, err
	}

	// Acquire write lock for recovery operations
	lock := flock.New(stateFile + ".lock")
	locked, err := lock.TryLock()
	if err != nil {
		return nil, fmt.Errorf("failed to acquire write lock for recovery: %w", err)
	}
	if !locked {
		return nil, fmt.Errorf("state file is locked by another process")
	}
	defer lock.Unlock()

	backupFile := stateFile + ".bak"
	tempFile := stateFile + ".tmp"

	// Strategy 1: Try backup file
	if data, err := os.ReadFile(backupFile); err == nil {
		var state ConfigState
		if err := json.Unmarshal(data, &state); err == nil {
			// Backup is valid - restore it as main state file
			fmt.Fprintf(os.Stderr, "Successfully recovered state from backup file\n")
			if err := os.WriteFile(stateFile, data, 0600); err != nil {
				return nil, fmt.Errorf("failed to restore backup: %w", err)
			}
			return &state, nil
		}
	}

	// Strategy 2: Try temp file (might be more recent than corrupted main file)
	if data, err := os.ReadFile(tempFile); err == nil {
		var state ConfigState
		if err := json.Unmarshal(data, &state); err == nil {
			// Temp file is valid - use it as main state file
			fmt.Fprintf(os.Stderr, "Successfully recovered state from temp file\n")
			if err := os.WriteFile(stateFile, data, 0600); err != nil {
				return nil, fmt.Errorf("failed to restore from temp file: %w", err)
			}
			// Clean up temp file after successful recovery
			os.Remove(tempFile)
			return &state, nil
		}
	}

	// Strategy 3: Reinitialize with default state
	fmt.Fprintf(os.Stderr, "No valid backup found, reinitializing with default state\n")
	defaultState := &ConfigState{
		Version:          0,
		Status:           "",
		SyncStatus:       "",
		ServerConfigHash: "",
		LastSync:         time.Time{},
	}

	// Write default state directly (already holding lock)
	data, err := json.MarshalIndent(defaultState, "", "  ")
	if err != nil {
		return nil, fmt.Errorf("failed to marshal default state: %w", err)
	}
	if err := os.WriteFile(stateFile, data, 0600); err != nil {
		return nil, fmt.Errorf("failed to write default state: %w", err)
	}

	return defaultState, nil
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

// IsConfigLocked checks if config is in locked status
// Locked configs cannot be modified locally - server always wins
func IsConfigLocked() (bool, error) {
	state, err := LoadConfigState()
	if err != nil {
		return false, err
	}

	return state.Status == "locked", nil
}

// IsConfigManaged checks if config is in managed status
// Managed configs accept client changes but server can push updates
func IsConfigManaged() (bool, error) {
	state, err := LoadConfigState()
	if err != nil {
		return false, err
	}

	return state.Status == "managed", nil
}

// GetLastSyncInfo returns the last sync timestamp and version
func GetLastSyncInfo() (time.Time, int, error) {
	state, err := LoadConfigState()
	if err != nil {
		return time.Time{}, 0, err
	}

	return state.LastSync, state.Version, nil
}

// ShouldSync determines if a config sync should be attempted
// Returns true if:
// - Never synced before (Version is 0)
// - More than syncInterval has elapsed since last sync
// - Config is locked (always sync to catch server updates)
// - Config has pending sync status (server config waiting)
func ShouldSync(syncInterval time.Duration) (bool, error) {
	state, err := LoadConfigState()
	if err != nil {
		return false, err
	}

	// Never synced before
	if state.Version == 0 {
		return true, nil
	}

	// Always sync if locked (server might have updates)
	if state.Status == "locked" {
		// But rate limit to once per hour minimum to avoid excessive requests
		if time.Since(state.LastSync) < 1*time.Hour {
			return false, nil
		}
		return true, nil
	}

	// Sync more frequently if pending (waiting for server config)
	if state.SyncStatus == "pending" {
		// Check every 15 minutes for pending server configs
		if time.Since(state.LastSync) < 15*time.Minute {
			return false, nil
		}
		return true, nil
	}

	// In other states, sync based on interval
	return time.Since(state.LastSync) >= syncInterval, nil
}
