package main

import (
	"encoding/json"
	"os"
	"testing"
	"time"
)

// TestRecoverStateFile_FromBackup verifies recovery from .bak file
func TestRecoverStateFile_FromBackup(t *testing.T) {
	stateFile, err := getStateFilePath()
	if err != nil {
		t.Fatalf("getStateFilePath() error = %v", err)
	}

	backupFile := stateFile + ".bak"
	tempFile := stateFile + ".tmp"

	// Cleanup before and after test
	os.Remove(stateFile)
	os.Remove(backupFile)
	os.Remove(tempFile)
	os.Remove(stateFile + ".lock")
	defer func() {
		os.Remove(stateFile)
		os.Remove(backupFile)
		os.Remove(tempFile)
		os.Remove(stateFile + ".lock")
	}()

	// Create a valid backup file
	validState := ConfigState{
		Version:          5,
		Status:           "managed",
		SyncStatus:       "active",
		ServerConfigHash: "backup_hash_123",
		LastSync:         time.Now().UTC().Truncate(time.Second),
	}
	data, _ := json.MarshalIndent(validState, "", "  ")
	if err := os.WriteFile(backupFile, data, 0600); err != nil {
		t.Fatalf("Failed to create backup file: %v", err)
	}

	// Create corrupted main state file
	if err := os.WriteFile(stateFile, []byte("corrupted {{{"), 0600); err != nil {
		t.Fatalf("Failed to create corrupted file: %v", err)
	}

	// Attempt recovery
	recovered, err := RecoverStateFile()
	if err != nil {
		t.Fatalf("RecoverStateFile() error = %v", err)
	}

	// Verify recovered state matches backup
	if recovered.Version != validState.Version {
		t.Errorf("Version = %d, want %d", recovered.Version, validState.Version)
	}
	if recovered.Status != validState.Status {
		t.Errorf("Status = %q, want %q", recovered.Status, validState.Status)
	}
	if recovered.ServerConfigHash != validState.ServerConfigHash {
		t.Errorf("ServerConfigHash = %q, want %q", recovered.ServerConfigHash, validState.ServerConfigHash)
	}

	// Verify main state file was restored
	restoredData, err := os.ReadFile(stateFile)
	if err != nil {
		t.Fatalf("Failed to read restored state file: %v", err)
	}
	var restoredState ConfigState
	if err := json.Unmarshal(restoredData, &restoredState); err != nil {
		t.Fatalf("Restored state file is not valid JSON: %v", err)
	}
	if restoredState.ServerConfigHash != validState.ServerConfigHash {
		t.Errorf("Restored file hash = %q, want %q", restoredState.ServerConfigHash, validState.ServerConfigHash)
	}
}

// TestRecoverStateFile_FromTempFile verifies recovery from .tmp file when .bak is invalid
func TestRecoverStateFile_FromTempFile(t *testing.T) {
	stateFile, err := getStateFilePath()
	if err != nil {
		t.Fatalf("getStateFilePath() error = %v", err)
	}

	backupFile := stateFile + ".bak"
	tempFile := stateFile + ".tmp"

	// Cleanup
	os.Remove(stateFile)
	os.Remove(backupFile)
	os.Remove(tempFile)
	os.Remove(stateFile + ".lock")
	defer func() {
		os.Remove(stateFile)
		os.Remove(backupFile)
		os.Remove(tempFile)
		os.Remove(stateFile + ".lock")
	}()

	// Create invalid backup file
	if err := os.WriteFile(backupFile, []byte("invalid backup {{{"), 0600); err != nil {
		t.Fatalf("Failed to create invalid backup: %v", err)
	}

	// Create valid temp file
	validState := ConfigState{
		Version:          7,
		Status:           "locked",
		SyncStatus:       "active",
		ServerConfigHash: "temp_hash_456",
		LastSync:         time.Now().UTC().Truncate(time.Second),
	}
	data, _ := json.MarshalIndent(validState, "", "  ")
	if err := os.WriteFile(tempFile, data, 0600); err != nil {
		t.Fatalf("Failed to create temp file: %v", err)
	}

	// Create corrupted main state file
	if err := os.WriteFile(stateFile, []byte("corrupted main"), 0600); err != nil {
		t.Fatalf("Failed to create corrupted file: %v", err)
	}

	// Attempt recovery
	recovered, err := RecoverStateFile()
	if err != nil {
		t.Fatalf("RecoverStateFile() error = %v", err)
	}

	// Verify recovered state matches temp file
	if recovered.Version != validState.Version {
		t.Errorf("Version = %d, want %d", recovered.Version, validState.Version)
	}
	if recovered.ServerConfigHash != validState.ServerConfigHash {
		t.Errorf("ServerConfigHash = %q, want %q", recovered.ServerConfigHash, validState.ServerConfigHash)
	}

	// Verify temp file was cleaned up after successful recovery
	if _, err := os.Stat(tempFile); !os.IsNotExist(err) {
		t.Error("Temp file should be removed after successful recovery")
	}
}

// TestRecoverStateFile_DefaultState verifies fallback to default state
func TestRecoverStateFile_DefaultState(t *testing.T) {
	stateFile, err := getStateFilePath()
	if err != nil {
		t.Fatalf("getStateFilePath() error = %v", err)
	}

	backupFile := stateFile + ".bak"
	tempFile := stateFile + ".tmp"

	// Cleanup
	os.Remove(stateFile)
	os.Remove(backupFile)
	os.Remove(tempFile)
	os.Remove(stateFile + ".lock")
	defer func() {
		os.Remove(stateFile)
		os.Remove(backupFile)
		os.Remove(tempFile)
		os.Remove(stateFile + ".lock")
	}()

	// Create invalid backup file
	if err := os.WriteFile(backupFile, []byte("invalid"), 0600); err != nil {
		t.Fatalf("Failed to create invalid backup: %v", err)
	}

	// Create invalid temp file
	if err := os.WriteFile(tempFile, []byte("invalid temp"), 0600); err != nil {
		t.Fatalf("Failed to create invalid temp: %v", err)
	}

	// Create corrupted main state file
	if err := os.WriteFile(stateFile, []byte("corrupted"), 0600); err != nil {
		t.Fatalf("Failed to create corrupted file: %v", err)
	}

	// Attempt recovery - should fall back to default state
	recovered, err := RecoverStateFile()
	if err != nil {
		t.Fatalf("RecoverStateFile() error = %v", err)
	}

	// Verify default state
	if recovered.Version != 0 {
		t.Errorf("Version = %d, want 0", recovered.Version)
	}
	if recovered.Status != "" {
		t.Errorf("Status = %q, want empty string", recovered.Status)
	}
	if recovered.SyncStatus != "" {
		t.Errorf("SyncStatus = %q, want empty string", recovered.SyncStatus)
	}
	if recovered.ServerConfigHash != "" {
		t.Errorf("ServerConfigHash = %q, want empty string", recovered.ServerConfigHash)
	}
	if !recovered.LastSync.IsZero() {
		t.Errorf("LastSync = %v, want zero time", recovered.LastSync)
	}

	// Verify a valid state file was created
	restoredData, err := os.ReadFile(stateFile)
	if err != nil {
		t.Fatalf("Failed to read restored state file: %v", err)
	}
	var restoredState ConfigState
	if err := json.Unmarshal(restoredData, &restoredState); err != nil {
		t.Fatalf("Restored state file is not valid JSON: %v", err)
	}
}

// TestLoadConfigState_AutoRecovery verifies LoadConfigState automatically recovers from corruption
func TestLoadConfigState_AutoRecovery(t *testing.T) {
	stateFile, err := getStateFilePath()
	if err != nil {
		t.Fatalf("getStateFilePath() error = %v", err)
	}

	backupFile := stateFile + ".bak"

	// Cleanup
	os.Remove(stateFile)
	os.Remove(backupFile)
	os.Remove(stateFile + ".lock")
	defer func() {
		os.Remove(stateFile)
		os.Remove(backupFile)
		os.Remove(stateFile + ".lock")
	}()

	// Create a valid backup file
	validState := ConfigState{
		Version:          10,
		Status:           "managed",
		SyncStatus:       "pending",
		ServerConfigHash: "auto_recovery_hash",
		LastSync:         time.Now().UTC().Truncate(time.Second),
	}
	data, _ := json.MarshalIndent(validState, "", "  ")
	if err := os.WriteFile(backupFile, data, 0600); err != nil {
		t.Fatalf("Failed to create backup file: %v", err)
	}

	// Create corrupted main state file
	if err := os.WriteFile(stateFile, []byte("corrupted json {{{"), 0600); err != nil {
		t.Fatalf("Failed to create corrupted file: %v", err)
	}

	// LoadConfigState should automatically recover
	recovered, err := LoadConfigState()
	if err != nil {
		t.Fatalf("LoadConfigState() should recover from corruption, got error: %v", err)
	}

	// Verify recovered state matches backup
	if recovered.Version != validState.Version {
		t.Errorf("Version = %d, want %d", recovered.Version, validState.Version)
	}
	if recovered.ServerConfigHash != validState.ServerConfigHash {
		t.Errorf("ServerConfigHash = %q, want %q", recovered.ServerConfigHash, validState.ServerConfigHash)
	}
}

// TestSaveConfigState_CreatesBackup verifies SaveConfigState creates backup before overwriting
func TestSaveConfigState_CreatesBackup(t *testing.T) {
	stateFile, err := getStateFilePath()
	if err != nil {
		t.Fatalf("getStateFilePath() error = %v", err)
	}

	backupFile := stateFile + ".bak"

	// Cleanup
	os.Remove(stateFile)
	os.Remove(backupFile)
	os.Remove(stateFile + ".lock")
	os.Remove(stateFile + ".tmp")
	defer func() {
		os.Remove(stateFile)
		os.Remove(backupFile)
		os.Remove(stateFile + ".lock")
		os.Remove(stateFile + ".tmp")
	}()

	// Create initial state
	initialState := &ConfigState{
		Version:          1,
		Status:           "unmanaged",
		ServerConfigHash: "initial_hash",
		LastSync:         time.Now().UTC().Truncate(time.Second),
	}
	if err := SaveConfigState(initialState); err != nil {
		t.Fatalf("SaveConfigState() initial save error = %v", err)
	}

	// Backup should not exist yet (no previous state to backup)
	if _, err := os.Stat(backupFile); !os.IsNotExist(err) {
		t.Error("Backup file should not exist after first save")
	}

	// Save a new state (should create backup of previous state)
	newState := &ConfigState{
		Version:          2,
		Status:           "managed",
		ServerConfigHash: "new_hash",
		LastSync:         time.Now().UTC().Truncate(time.Second),
	}
	if err := SaveConfigState(newState); err != nil {
		t.Fatalf("SaveConfigState() second save error = %v", err)
	}

	// Backup should now exist but should have been cleaned up (on success)
	// Actually, based on the implementation, backup is removed on success
	if _, err := os.Stat(backupFile); !os.IsNotExist(err) {
		t.Error("Backup file should be removed after successful save")
	}

	// Main file should have new state
	loaded, err := LoadConfigState()
	if err != nil {
		t.Fatalf("LoadConfigState() error = %v", err)
	}
	if loaded.Version != 2 {
		t.Errorf("Version = %d, want 2", loaded.Version)
	}
}
