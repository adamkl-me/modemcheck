package main

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// TestGetStateFilePath verifies state file path generation
func TestGetStateFilePath(t *testing.T) {
	path, err := getStateFilePath()
	if err != nil {
		t.Fatalf("getStateFilePath() error = %v", err)
	}

	// Should end with .config_state.json
	if filepath.Base(path) != ".config_state.json" {
		t.Errorf("getStateFilePath() = %v, want file named .config_state.json", path)
	}

	// Should be in the same directory as executable
	execPath, _ := os.Executable()
	execDir := filepath.Dir(execPath)
	if filepath.Dir(path) != execDir {
		t.Errorf("getStateFilePath() dir = %v, want %v", filepath.Dir(path), execDir)
	}
}

// TestLoadConfigState_MissingFile verifies default state when file doesn't exist
func TestLoadConfigState_MissingFile(t *testing.T) {
	// Ensure state file doesn't exist
	stateFile, err := getStateFilePath()
	if err != nil {
		t.Fatalf("getStateFilePath() error = %v", err)
	}

	// Remove any existing state file for this test
	os.Remove(stateFile)
	os.Remove(stateFile + ".lock")
	defer func() {
		os.Remove(stateFile)
		os.Remove(stateFile + ".lock")
	}()

	state, err := LoadConfigState()
	if err != nil {
		t.Fatalf("LoadConfigState() error = %v", err)
	}

	// Verify default state (new structure: Version is int, Status/SyncStatus are strings)
	if state.Version != 0 {
		t.Errorf("Version = %d, want 0", state.Version)
	}
	if state.Status != "" {
		t.Errorf("Status = %q, want empty string", state.Status)
	}
	if state.SyncStatus != "" {
		t.Errorf("SyncStatus = %q, want empty string", state.SyncStatus)
	}
	if state.ServerConfigHash != "" {
		t.Errorf("ServerConfigHash = %q, want empty string", state.ServerConfigHash)
	}
	if !state.LastSync.IsZero() {
		t.Errorf("LastSync = %v, want zero time", state.LastSync)
	}
}

// TestLoadConfigState_ValidFile verifies loading from a valid state file
func TestLoadConfigState_ValidFile(t *testing.T) {
	stateFile, err := getStateFilePath()
	if err != nil {
		t.Fatalf("getStateFilePath() error = %v", err)
	}

	// Create a valid state file with new structure
	expectedTime := time.Now().UTC().Truncate(time.Second)
	state := ConfigState{
		Version:          1,
		Status:           "managed",
		SyncStatus:       "active",
		ServerConfigHash: "abc123hash",
		LastSync:         expectedTime,
	}

	data, _ := json.MarshalIndent(state, "", "  ")
	if err := os.WriteFile(stateFile, data, 0600); err != nil {
		t.Fatalf("Failed to write test state file: %v", err)
	}
	defer func() {
		os.Remove(stateFile)
		os.Remove(stateFile + ".lock")
	}()

	// Load and verify
	loaded, err := LoadConfigState()
	if err != nil {
		t.Fatalf("LoadConfigState() error = %v", err)
	}

	if loaded.Version != 1 {
		t.Errorf("Version = %d, want %d", loaded.Version, 1)
	}
	if loaded.Status != "managed" {
		t.Errorf("Status = %q, want %q", loaded.Status, "managed")
	}
	if loaded.SyncStatus != "active" {
		t.Errorf("SyncStatus = %q, want %q", loaded.SyncStatus, "active")
	}
	if loaded.ServerConfigHash != "abc123hash" {
		t.Errorf("ServerConfigHash = %q, want %q", loaded.ServerConfigHash, "abc123hash")
	}
	if !loaded.LastSync.Equal(expectedTime) {
		t.Errorf("LastSync = %v, want %v", loaded.LastSync, expectedTime)
	}
}

// TestLoadConfigState_CorruptedFile verifies auto-recovery for invalid JSON
func TestLoadConfigState_CorruptedFile(t *testing.T) {
	stateFile, err := getStateFilePath()
	if err != nil {
		t.Fatalf("getStateFilePath() error = %v", err)
	}

	// Write invalid JSON
	if err := os.WriteFile(stateFile, []byte("not valid json {{{"), 0600); err != nil {
		t.Fatalf("Failed to write test file: %v", err)
	}
	defer func() {
		os.Remove(stateFile)
		os.Remove(stateFile + ".lock")
	}()

	// Corrupted files are now auto-recovered with default state (no error)
	state, err := LoadConfigState()
	if err != nil {
		t.Errorf("LoadConfigState() error = %v, expected auto-recovery", err)
	}
	// Should return default state after auto-recovery
	if state.Version != 0 {
		t.Errorf("Version = %d, want 0 (default after recovery)", state.Version)
	}
	if state.Status != "" {
		t.Errorf("Status = %q, want empty (default after recovery)", state.Status)
	}
}

// TestSaveConfigState_Success verifies state saving
func TestSaveConfigState_Success(t *testing.T) {
	stateFile, err := getStateFilePath()
	if err != nil {
		t.Fatalf("getStateFilePath() error = %v", err)
	}

	defer func() {
		os.Remove(stateFile)
		os.Remove(stateFile + ".lock")
		os.Remove(stateFile + ".tmp")
	}()

	state := &ConfigState{
		Version:          2,
		Status:           "locked",
		SyncStatus:       "active",
		ServerConfigHash: "hashvalue",
		LastSync:         time.Now().UTC(),
	}

	if err := SaveConfigState(state); err != nil {
		t.Fatalf("SaveConfigState() error = %v", err)
	}

	// Verify file was created
	if _, err := os.Stat(stateFile); os.IsNotExist(err) {
		t.Error("State file was not created")
	}

	// Verify file permissions (Unix only)
	info, err := os.Stat(stateFile)
	if err != nil {
		t.Fatalf("os.Stat() error = %v", err)
	}
	// Should be readable/writable by owner only
	if info.Mode().Perm() != 0600 {
		t.Errorf("File permissions = %o, want 0600", info.Mode().Perm())
	}

	// Verify content can be loaded back
	loaded, err := LoadConfigState()
	if err != nil {
		t.Fatalf("LoadConfigState() after save error = %v", err)
	}
	if loaded.Version != state.Version {
		t.Errorf("Loaded Version = %d, want %d", loaded.Version, state.Version)
	}
	if loaded.Status != state.Status {
		t.Errorf("Loaded Status = %q, want %q", loaded.Status, state.Status)
	}
}

// TestSaveConfigState_AtomicWrite verifies no temp file remains after save
func TestSaveConfigState_AtomicWrite(t *testing.T) {
	stateFile, err := getStateFilePath()
	if err != nil {
		t.Fatalf("getStateFilePath() error = %v", err)
	}

	defer func() {
		os.Remove(stateFile)
		os.Remove(stateFile + ".lock")
		os.Remove(stateFile + ".tmp")
	}()

	state := &ConfigState{Version: 1}
	if err := SaveConfigState(state); err != nil {
		t.Fatalf("SaveConfigState() error = %v", err)
	}

	// Temp file should not exist after successful save
	tempFile := stateFile + ".tmp"
	if _, err := os.Stat(tempFile); !os.IsNotExist(err) {
		t.Errorf("Temp file %s should not exist after save", tempFile)
	}
}

// TestUpdateConfigState_Success verifies state update with callback
func TestUpdateConfigState_Success(t *testing.T) {
	stateFile, err := getStateFilePath()
	if err != nil {
		t.Fatalf("getStateFilePath() error = %v", err)
	}

	// Start with a clean state
	os.Remove(stateFile)
	os.Remove(stateFile + ".lock")
	defer func() {
		os.Remove(stateFile)
		os.Remove(stateFile + ".lock")
	}()

	// Update state
	err = UpdateConfigState(func(s *ConfigState) error {
		s.Version = 1
		s.Status = "managed"
		s.SyncStatus = "active"
		s.LastSync = time.Now().UTC()
		return nil
	})
	if err != nil {
		t.Fatalf("UpdateConfigState() error = %v", err)
	}

	// Verify update
	state, err := LoadConfigState()
	if err != nil {
		t.Fatalf("LoadConfigState() error = %v", err)
	}
	if state.Version != 1 {
		t.Errorf("Version = %d, want %d", state.Version, 1)
	}
	if state.Status != "managed" {
		t.Errorf("Status = %q, want %q", state.Status, "managed")
	}
}

// TestUpdateConfigState_CallbackError verifies error propagation from callback
func TestUpdateConfigState_CallbackError(t *testing.T) {
	stateFile, err := getStateFilePath()
	if err != nil {
		t.Fatalf("getStateFilePath() error = %v", err)
	}

	os.Remove(stateFile)
	os.Remove(stateFile + ".lock")
	defer func() {
		os.Remove(stateFile)
		os.Remove(stateFile + ".lock")
	}()

	expectedErr := errors.New("callback error")
	err = UpdateConfigState(func(s *ConfigState) error {
		return expectedErr
	})

	if err == nil {
		t.Error("UpdateConfigState() expected error, got nil")
	}
}

// TestIsConfigLocked_LockedStatus verifies locked status detection
func TestIsConfigLocked_LockedStatus(t *testing.T) {
	stateFile, err := getStateFilePath()
	if err != nil {
		t.Fatalf("getStateFilePath() error = %v", err)
	}

	defer func() {
		os.Remove(stateFile)
		os.Remove(stateFile + ".lock")
	}()

	tests := []struct {
		name     string
		status   string
		expected bool
	}{
		{"locked status", "locked", true},
		{"managed status", "managed", false},
		{"unmanaged status", "unmanaged", false},
		{"empty status", "", false},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			state := &ConfigState{Status: tc.status}
			if err := SaveConfigState(state); err != nil {
				t.Fatalf("SaveConfigState() error = %v", err)
			}

			locked, err := IsConfigLocked()
			if err != nil {
				t.Fatalf("IsConfigLocked() error = %v", err)
			}
			if locked != tc.expected {
				t.Errorf("IsConfigLocked() = %v, want %v", locked, tc.expected)
			}
		})
	}
}

// TestIsConfigLocked_Alias verifies backward compatibility alias
func TestIsConfigLocked_Alias(t *testing.T) {
	stateFile, err := getStateFilePath()
	if err != nil {
		t.Fatalf("getStateFilePath() error = %v", err)
	}

	defer func() {
		os.Remove(stateFile)
		os.Remove(stateFile + ".lock")
	}()

	state := &ConfigState{Status: "locked"}
	if err := SaveConfigState(state); err != nil {
		t.Fatalf("SaveConfigState() error = %v", err)
	}

	locked, err := IsConfigLocked()
	if err != nil {
		t.Fatalf("IsConfigLocked() error = %v", err)
	}
	if !locked {
		t.Error("IsConfigLocked() = false, want true for locked status")
	}
}

// TestIsConfigManaged_ManagedStatus verifies managed status detection
func TestIsConfigManaged_ManagedStatus(t *testing.T) {
	stateFile, err := getStateFilePath()
	if err != nil {
		t.Fatalf("getStateFilePath() error = %v", err)
	}

	defer func() {
		os.Remove(stateFile)
		os.Remove(stateFile + ".lock")
	}()

	tests := []struct {
		name     string
		status   string
		expected bool
	}{
		{"managed status", "managed", true},
		{"locked status", "locked", false},
		{"unmanaged status", "unmanaged", false},
		{"empty status", "", false},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			state := &ConfigState{Status: tc.status}
			if err := SaveConfigState(state); err != nil {
				t.Fatalf("SaveConfigState() error = %v", err)
			}

			managed, err := IsConfigManaged()
			if err != nil {
				t.Fatalf("IsConfigManaged() error = %v", err)
			}
			if managed != tc.expected {
				t.Errorf("IsConfigManaged() = %v, want %v", managed, tc.expected)
			}
		})
	}
}

// TestGetLastSyncInfo verifies sync info retrieval
func TestGetLastSyncInfo(t *testing.T) {
	stateFile, err := getStateFilePath()
	if err != nil {
		t.Fatalf("getStateFilePath() error = %v", err)
	}

	defer func() {
		os.Remove(stateFile)
		os.Remove(stateFile + ".lock")
	}()

	expectedTime := time.Now().UTC().Truncate(time.Second)
	state := &ConfigState{
		Version:  3,
		LastSync: expectedTime,
	}
	if err := SaveConfigState(state); err != nil {
		t.Fatalf("SaveConfigState() error = %v", err)
	}

	syncTime, version, err := GetLastSyncInfo()
	if err != nil {
		t.Fatalf("GetLastSyncInfo() error = %v", err)
	}
	if version != 3 {
		t.Errorf("version = %d, want %d", version, 3)
	}
	if !syncTime.Equal(expectedTime) {
		t.Errorf("syncTime = %v, want %v", syncTime, expectedTime)
	}
}

// TestShouldSync_NeverSynced verifies sync is needed when never synced
func TestShouldSync_NeverSynced(t *testing.T) {
	stateFile, err := getStateFilePath()
	if err != nil {
		t.Fatalf("getStateFilePath() error = %v", err)
	}

	os.Remove(stateFile)
	os.Remove(stateFile + ".lock")
	defer func() {
		os.Remove(stateFile)
		os.Remove(stateFile + ".lock")
	}()

	shouldSync, err := ShouldSync(24 * time.Hour)
	if err != nil {
		t.Fatalf("ShouldSync() error = %v", err)
	}
	if !shouldSync {
		t.Error("ShouldSync() = false, want true when never synced")
	}
}

// TestShouldSync_LockedRateLimiting verifies rate limiting for locked configs
func TestShouldSync_LockedRateLimiting(t *testing.T) {
	stateFile, err := getStateFilePath()
	if err != nil {
		t.Fatalf("getStateFilePath() error = %v", err)
	}

	defer func() {
		os.Remove(stateFile)
		os.Remove(stateFile + ".lock")
	}()

	tests := []struct {
		name        string
		lastSync    time.Time
		expected    bool
		description string
	}{
		{
			name:        "recent sync",
			lastSync:    time.Now().Add(-30 * time.Minute),
			expected:    false,
			description: "should not sync if last sync was < 1 hour ago",
		},
		{
			name:        "old sync",
			lastSync:    time.Now().Add(-2 * time.Hour),
			expected:    true,
			description: "should sync if last sync was >= 1 hour ago",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			state := &ConfigState{
				Version:  1,
				Status:   "locked",
				LastSync: tc.lastSync,
			}
			if err := SaveConfigState(state); err != nil {
				t.Fatalf("SaveConfigState() error = %v", err)
			}

			shouldSync, err := ShouldSync(24 * time.Hour)
			if err != nil {
				t.Fatalf("ShouldSync() error = %v", err)
			}
			if shouldSync != tc.expected {
				t.Errorf("ShouldSync() = %v, want %v (%s)", shouldSync, tc.expected, tc.description)
			}
		})
	}
}

// TestShouldSync_PendingFasterSync verifies faster sync for pending configs
func TestShouldSync_PendingFasterSync(t *testing.T) {
	stateFile, err := getStateFilePath()
	if err != nil {
		t.Fatalf("getStateFilePath() error = %v", err)
	}

	defer func() {
		os.Remove(stateFile)
		os.Remove(stateFile + ".lock")
	}()

	tests := []struct {
		name     string
		lastSync time.Time
		expected bool
	}{
		{"recent (5min)", time.Now().Add(-5 * time.Minute), false},
		{"old (20min)", time.Now().Add(-20 * time.Minute), true},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			state := &ConfigState{
				Version:    1,
				Status:     "managed",
				SyncStatus: "pending",
				LastSync:   tc.lastSync,
			}
			if err := SaveConfigState(state); err != nil {
				t.Fatalf("SaveConfigState() error = %v", err)
			}

			shouldSync, err := ShouldSync(24 * time.Hour)
			if err != nil {
				t.Fatalf("ShouldSync() error = %v", err)
			}
			if shouldSync != tc.expected {
				t.Errorf("ShouldSync() = %v, want %v", shouldSync, tc.expected)
			}
		})
	}
}

// TestShouldSync_IntervalBased verifies interval-based sync for normal states
func TestShouldSync_IntervalBased(t *testing.T) {
	stateFile, err := getStateFilePath()
	if err != nil {
		t.Fatalf("getStateFilePath() error = %v", err)
	}

	defer func() {
		os.Remove(stateFile)
		os.Remove(stateFile + ".lock")
	}()

	syncInterval := 6 * time.Hour

	tests := []struct {
		name     string
		lastSync time.Time
		expected bool
	}{
		{"within interval", time.Now().Add(-3 * time.Hour), false},
		{"at interval", time.Now().Add(-6 * time.Hour), true},
		{"past interval", time.Now().Add(-10 * time.Hour), true},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			state := &ConfigState{
				Version:    1,
				Status:     "managed",
				SyncStatus: "active",
				LastSync:   tc.lastSync,
			}
			if err := SaveConfigState(state); err != nil {
				t.Fatalf("SaveConfigState() error = %v", err)
			}

			shouldSync, err := ShouldSync(syncInterval)
			if err != nil {
				t.Fatalf("ShouldSync() error = %v", err)
			}
			if shouldSync != tc.expected {
				t.Errorf("ShouldSync() = %v, want %v", shouldSync, tc.expected)
			}
		})
	}
}

// TestCleanupOldStateFiles verifies cleanup of legacy per-modem state files
func TestCleanupOldStateFiles(t *testing.T) {
	// Get executable directory
	execPath, err := os.Executable()
	if err != nil {
		t.Fatalf("os.Executable() error = %v", err)
	}
	dir := filepath.Dir(execPath)

	// Create some legacy per-modem state files
	legacyFiles := []string{
		filepath.Join(dir, ".config_state_MODEM1-AA11BB22CC33.json"),
		filepath.Join(dir, ".config_state_MODEM2-DD44EE55FF66.json"),
	}

	for _, f := range legacyFiles {
		if err := os.WriteFile(f, []byte(`{"version":1}`), 0600); err != nil {
			t.Fatalf("Failed to create test file %s: %v", f, err)
		}
	}

	defer func() {
		for _, f := range legacyFiles {
			os.Remove(f)
			os.Remove(f + ".lock")
		}
	}()

	// Run cleanup
	if err := CleanupOldStateFiles(); err != nil {
		t.Fatalf("CleanupOldStateFiles() error = %v", err)
	}

	// Verify files were removed
	for _, f := range legacyFiles {
		if _, err := os.Stat(f); !os.IsNotExist(err) {
			t.Errorf("Legacy file %s should have been removed", f)
		}
	}
}

// TestCleanupOldStateFiles_PreservesMainStateFile verifies the main state file is not deleted
func TestCleanupOldStateFiles_PreservesMainStateFile(t *testing.T) {
	stateFile, err := getStateFilePath()
	if err != nil {
		t.Fatalf("getStateFilePath() error = %v", err)
	}

	// Create main state file
	if err := os.WriteFile(stateFile, []byte(`{"version":1}`), 0600); err != nil {
		t.Fatalf("Failed to create test file: %v", err)
	}

	defer func() {
		os.Remove(stateFile)
		os.Remove(stateFile + ".lock")
	}()

	// Run cleanup
	if err := CleanupOldStateFiles(); err != nil {
		t.Fatalf("CleanupOldStateFiles() error = %v", err)
	}

	// Verify main state file still exists
	if _, err := os.Stat(stateFile); os.IsNotExist(err) {
		t.Error("Main state file should NOT have been removed")
	}
}

// TestCleanupOldStateFiles_Idempotent verifies cleanup can be called multiple times safely
func TestCleanupOldStateFiles_Idempotent(t *testing.T) {
	// Get executable directory
	execPath, err := os.Executable()
	if err != nil {
		t.Fatalf("os.Executable() error = %v", err)
	}
	dir := filepath.Dir(execPath)

	// Create a legacy state file
	legacyFile := filepath.Join(dir, ".config_state_TEST-IDEMPOTENT.json")
	if err := os.WriteFile(legacyFile, []byte(`{"version":1}`), 0600); err != nil {
		t.Fatalf("Failed to create test file: %v", err)
	}
	defer os.Remove(legacyFile)
	defer os.Remove(legacyFile + ".lock")

	// First cleanup - should remove the file
	if err := CleanupOldStateFiles(); err != nil {
		t.Fatalf("CleanupOldStateFiles() first call error = %v", err)
	}

	// Verify file was removed
	if _, err := os.Stat(legacyFile); !os.IsNotExist(err) {
		t.Error("Legacy file should have been removed after first call")
	}

	// Second cleanup - should succeed with nothing to do (idempotent)
	if err := CleanupOldStateFiles(); err != nil {
		t.Fatalf("CleanupOldStateFiles() second call (idempotent) error = %v", err)
	}

	// Third cleanup - still should succeed
	if err := CleanupOldStateFiles(); err != nil {
		t.Fatalf("CleanupOldStateFiles() third call (idempotent) error = %v", err)
	}
}

// TestConfigState_JSONRoundTrip verifies JSON serialization/deserialization
func TestConfigState_JSONRoundTrip(t *testing.T) {
	original := ConfigState{
		Version:          5,
		Status:           "locked",
		SyncStatus:       "active",
		ServerConfigHash: "sha256hash123",
		LastSync:         time.Now().UTC().Truncate(time.Second),
	}

	data, err := json.Marshal(original)
	if err != nil {
		t.Fatalf("json.Marshal() error = %v", err)
	}

	var loaded ConfigState
	if err := json.Unmarshal(data, &loaded); err != nil {
		t.Fatalf("json.Unmarshal() error = %v", err)
	}

	if loaded.Version != original.Version {
		t.Errorf("Version = %d, want %d", loaded.Version, original.Version)
	}
	if loaded.Status != original.Status {
		t.Errorf("Status = %q, want %q", loaded.Status, original.Status)
	}
	if loaded.SyncStatus != original.SyncStatus {
		t.Errorf("SyncStatus = %q, want %q", loaded.SyncStatus, original.SyncStatus)
	}
	if loaded.ServerConfigHash != original.ServerConfigHash {
		t.Errorf("ServerConfigHash = %q, want %q", loaded.ServerConfigHash, original.ServerConfigHash)
	}
	if !loaded.LastSync.Equal(original.LastSync) {
		t.Errorf("LastSync = %v, want %v", loaded.LastSync, original.LastSync)
	}
}
