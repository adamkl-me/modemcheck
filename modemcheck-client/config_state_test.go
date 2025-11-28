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

	// Verify default state
	if state.Version != "" {
		t.Errorf("Version = %q, want empty string", state.Version)
	}
	if state.Status != "" {
		t.Errorf("Status = %q, want empty string", state.Status)
	}
	if state.ActiveTrack != "" {
		t.Errorf("ActiveTrack = %q, want empty string", state.ActiveTrack)
	}
	if state.ClientVersion != 0 {
		t.Errorf("ClientVersion = %d, want 0", state.ClientVersion)
	}
	if state.ServerVersion != 0 {
		t.Errorf("ServerVersion = %d, want 0", state.ServerVersion)
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

	// Create a valid state file
	expectedTime := time.Now().UTC().Truncate(time.Second)
	state := ConfigState{
		Version:          "v1_client",
		Status:           "one_time_active",
		ActiveTrack:      "client",
		ClientVersion:    1,
		ServerVersion:    0,
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

	if loaded.Version != "v1_client" {
		t.Errorf("Version = %q, want %q", loaded.Version, "v1_client")
	}
	if loaded.Status != "one_time_active" {
		t.Errorf("Status = %q, want %q", loaded.Status, "one_time_active")
	}
	if loaded.ActiveTrack != "client" {
		t.Errorf("ActiveTrack = %q, want %q", loaded.ActiveTrack, "client")
	}
	if loaded.ClientVersion != 1 {
		t.Errorf("ClientVersion = %d, want %d", loaded.ClientVersion, 1)
	}
	if loaded.ServerVersion != 0 {
		t.Errorf("ServerVersion = %d, want %d", loaded.ServerVersion, 0)
	}
	if loaded.ServerConfigHash != "abc123hash" {
		t.Errorf("ServerConfigHash = %q, want %q", loaded.ServerConfigHash, "abc123hash")
	}
	if !loaded.LastSync.Equal(expectedTime) {
		t.Errorf("LastSync = %v, want %v", loaded.LastSync, expectedTime)
	}
}

// TestLoadConfigState_CorruptedFile verifies error handling for invalid JSON
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

	_, err = LoadConfigState()
	if err == nil {
		t.Error("LoadConfigState() expected error for corrupted file, got nil")
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
		Version:          "v2_server",
		Status:           "enforced_active",
		ActiveTrack:      "server",
		ClientVersion:    1,
		ServerVersion:    2,
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
		t.Errorf("Loaded Version = %q, want %q", loaded.Version, state.Version)
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

	state := &ConfigState{Version: "test"}
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
		s.Version = "v1_client"
		s.Status = "one_time_active"
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
	if state.Version != "v1_client" {
		t.Errorf("Version = %q, want %q", state.Version, "v1_client")
	}
	if state.Status != "one_time_active" {
		t.Errorf("Status = %q, want %q", state.Status, "one_time_active")
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

// TestIsConfigEnforced_EnforcedStates verifies enforced status detection
func TestIsConfigEnforced_EnforcedStates(t *testing.T) {
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
		{"enforced_ready", "enforced_ready", true},
		{"enforced_active", "enforced_active", true},
		{"one_time_active", "one_time_active", false},
		{"one_time_ready", "one_time_ready", false},
		{"empty status", "", false},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			state := &ConfigState{Status: tc.status}
			if err := SaveConfigState(state); err != nil {
				t.Fatalf("SaveConfigState() error = %v", err)
			}

			enforced, err := IsConfigEnforced()
			if err != nil {
				t.Fatalf("IsConfigEnforced() error = %v", err)
			}
			if enforced != tc.expected {
				t.Errorf("IsConfigEnforced() = %v, want %v", enforced, tc.expected)
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

	state := &ConfigState{Status: "enforced_active"}
	if err := SaveConfigState(state); err != nil {
		t.Fatalf("SaveConfigState() error = %v", err)
	}

	locked, err := IsConfigLocked()
	if err != nil {
		t.Fatalf("IsConfigLocked() error = %v", err)
	}
	if !locked {
		t.Error("IsConfigLocked() = false, want true for enforced_active status")
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
		Version:  "v3_server",
		LastSync: expectedTime,
	}
	if err := SaveConfigState(state); err != nil {
		t.Fatalf("SaveConfigState() error = %v", err)
	}

	syncTime, version, err := GetLastSyncInfo()
	if err != nil {
		t.Fatalf("GetLastSyncInfo() error = %v", err)
	}
	if version != "v3_server" {
		t.Errorf("version = %q, want %q", version, "v3_server")
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

// TestShouldSync_EnforcedRateLimiting verifies rate limiting for enforced configs
func TestShouldSync_EnforcedRateLimiting(t *testing.T) {
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
				Version:  "v1_server",
				Status:   "enforced_active",
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

// TestShouldSync_OneTimeReady verifies faster sync for pending configs
func TestShouldSync_OneTimeReady(t *testing.T) {
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
				Version:  "v1_client",
				Status:   "one_time_ready",
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
				Version:  "v1_client",
				Status:   "one_time_active",
				LastSync: tc.lastSync,
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
		if err := os.WriteFile(f, []byte(`{"version":"v1"}`), 0600); err != nil {
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
	if err := os.WriteFile(stateFile, []byte(`{"version":"v1"}`), 0600); err != nil {
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
	if err := os.WriteFile(legacyFile, []byte(`{"version":"v1"}`), 0600); err != nil {
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
		Version:          "v5_server",
		Status:           "enforced_active",
		ActiveTrack:      "server",
		ClientVersion:    3,
		ServerVersion:    5,
		ServerConfigHash: "sha256hash123",
		LastSync:         time.Now().UTC().Truncate(time.Second),
		Mode:             "locked", // legacy field
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
		t.Errorf("Version = %q, want %q", loaded.Version, original.Version)
	}
	if loaded.Status != original.Status {
		t.Errorf("Status = %q, want %q", loaded.Status, original.Status)
	}
	if loaded.ActiveTrack != original.ActiveTrack {
		t.Errorf("ActiveTrack = %q, want %q", loaded.ActiveTrack, original.ActiveTrack)
	}
	if loaded.ClientVersion != original.ClientVersion {
		t.Errorf("ClientVersion = %d, want %d", loaded.ClientVersion, original.ClientVersion)
	}
	if loaded.ServerVersion != original.ServerVersion {
		t.Errorf("ServerVersion = %d, want %d", loaded.ServerVersion, original.ServerVersion)
	}
	if loaded.ServerConfigHash != original.ServerConfigHash {
		t.Errorf("ServerConfigHash = %q, want %q", loaded.ServerConfigHash, original.ServerConfigHash)
	}
	if !loaded.LastSync.Equal(original.LastSync) {
		t.Errorf("LastSync = %v, want %v", loaded.LastSync, original.LastSync)
	}
	if loaded.Mode != original.Mode {
		t.Errorf("Mode = %q, want %q", loaded.Mode, original.Mode)
	}
}
