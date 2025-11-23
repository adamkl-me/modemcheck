package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// TestLoadConfigFile tests configuration loading and validation
func TestLoadConfigFile(t *testing.T) {
	tmpDir := t.TempDir()

	t.Run("valid config with defaults", func(t *testing.T) {
		configPath := filepath.Join(tmpDir, "valid_config.json")
		configData := `{
			"ModemAddress": "192.168.100.1",
			"IgnitePassword": "testpass",
			"SpeedTestEnabled": true,
			"AutoUpdateEnabled": true,
			"LocalCleanupEnabled": true
		}`

		if err := os.WriteFile(configPath, []byte(configData), 0644); err != nil {
			t.Fatalf("Failed to write config file: %v", err)
		}

		var config Configuration
		if err := LoadConfigFile(configPath, &config); err != nil {
			t.Fatalf("LoadConfigFile() failed: %v", err)
		}

		// Verify defaults are set
		if config.SpeedTestInterval != 1 {
			t.Errorf("SpeedTestInterval default = %d, want 1", config.SpeedTestInterval)
		}
		if config.PingCount != DefaultPingCount {
			t.Errorf("PingCount default = %d, want %d", config.PingCount, DefaultPingCount)
		}
		if config.LocalRetentionDays != 90 {
			t.Errorf("LocalRetentionDays default = %d, want 90", config.LocalRetentionDays)
		}
		if config.UpdateChannel != "stable" {
			t.Errorf("UpdateChannel default = %q, want 'stable'", config.UpdateChannel)
		}
	})

	t.Run("invalid SpeedTestInterval", func(t *testing.T) {
		configPath := filepath.Join(tmpDir, "invalid_interval.json")
		configData := `{
			"ModemAddress": "192.168.100.1",
			"SpeedTestInterval": -1
		}`

		if err := os.WriteFile(configPath, []byte(configData), 0644); err != nil {
			t.Fatalf("Failed to write config file: %v", err)
		}

		var config Configuration
		err := LoadConfigFile(configPath, &config)
		if err == nil {
			t.Error("LoadConfigFile() should fail with SpeedTestInterval = -1")
		}
		if err != nil && !contains(err.Error(), "SpeedTestInterval") {
			t.Errorf("Error should mention SpeedTestInterval, got: %v", err)
		}
	})

	t.Run("invalid PingCount - too low", func(t *testing.T) {
		configPath := filepath.Join(tmpDir, "invalid_ping_low.json")
		configData := `{
			"ModemAddress": "192.168.100.1",
			"PingCount": -1
		}`

		if err := os.WriteFile(configPath, []byte(configData), 0644); err != nil {
			t.Fatalf("Failed to write config file: %v", err)
		}

		var config Configuration
		err := LoadConfigFile(configPath, &config)
		if err == nil {
			t.Error("LoadConfigFile() should fail with PingCount = -1")
		}
	})

	t.Run("invalid PingCount - too high", func(t *testing.T) {
		configPath := filepath.Join(tmpDir, "invalid_ping_high.json")
		configData := `{
			"ModemAddress": "192.168.100.1",
			"PingCount": 101
		}`

		if err := os.WriteFile(configPath, []byte(configData), 0644); err != nil {
			t.Fatalf("Failed to write config file: %v", err)
		}

		var config Configuration
		err := LoadConfigFile(configPath, &config)
		if err == nil {
			t.Error("LoadConfigFile() should fail with PingCount = 101")
		}
	})

	t.Run("invalid LocalRetentionDays", func(t *testing.T) {
		configPath := filepath.Join(tmpDir, "invalid_retention.json")
		configData := `{
			"ModemAddress": "192.168.100.1",
			"LocalRetentionDays": -1
		}`

		if err := os.WriteFile(configPath, []byte(configData), 0644); err != nil {
			t.Fatalf("Failed to write config file: %v", err)
		}

		var config Configuration
		err := LoadConfigFile(configPath, &config)
		if err == nil {
			t.Error("LoadConfigFile() should fail with LocalRetentionDays < 1")
		}
	})

	t.Run("invalid UpdateChannel", func(t *testing.T) {
		configPath := filepath.Join(tmpDir, "invalid_channel.json")
		configData := `{
			"ModemAddress": "192.168.100.1",
			"UpdateChannel": "invalid-channel"
		}`

		if err := os.WriteFile(configPath, []byte(configData), 0644); err != nil {
			t.Fatalf("Failed to write config file: %v", err)
		}

		var config Configuration
		err := LoadConfigFile(configPath, &config)
		if err == nil {
			t.Error("LoadConfigFile() should fail with invalid UpdateChannel")
		}
		if err != nil && !contains(err.Error(), "UpdateChannel") {
			t.Errorf("Error should mention UpdateChannel, got: %v", err)
		}
	})

	t.Run("valid UpdateChannel - beta", func(t *testing.T) {
		configPath := filepath.Join(tmpDir, "beta_channel.json")
		configData := `{
			"ModemAddress": "192.168.100.1",
			"UpdateChannel": "beta"
		}`

		if err := os.WriteFile(configPath, []byte(configData), 0644); err != nil {
			t.Fatalf("Failed to write config file: %v", err)
		}

		var config Configuration
		if err := LoadConfigFile(configPath, &config); err != nil {
			t.Fatalf("LoadConfigFile() failed with valid beta channel: %v", err)
		}

		if config.UpdateChannel != "beta" {
			t.Errorf("UpdateChannel = %q, want 'beta'", config.UpdateChannel)
		}
	})

	t.Run("cloud enabled without CloudHost", func(t *testing.T) {
		configPath := filepath.Join(tmpDir, "missing_host.json")
		configData := `{
			"ModemAddress": "192.168.100.1",
			"EnableCloud": true,
			"CloudAPIKey": "test-key"
		}`

		if err := os.WriteFile(configPath, []byte(configData), 0644); err != nil {
			t.Fatalf("Failed to write config file: %v", err)
		}

		var config Configuration
		err := LoadConfigFile(configPath, &config)
		if err == nil {
			t.Error("LoadConfigFile() should fail when EnableCloud=true without CloudHost")
		}
		if err != nil && !contains(err.Error(), "CloudHost") {
			t.Errorf("Error should mention CloudHost, got: %v", err)
		}
	})

	t.Run("cloud enabled without CloudAPIKey", func(t *testing.T) {
		configPath := filepath.Join(tmpDir, "missing_apikey.json")
		configData := `{
			"ModemAddress": "192.168.100.1",
			"EnableCloud": true,
			"CloudHost": "api.example.com"
		}`

		if err := os.WriteFile(configPath, []byte(configData), 0644); err != nil {
			t.Fatalf("Failed to write config file: %v", err)
		}

		var config Configuration
		err := LoadConfigFile(configPath, &config)
		if err == nil {
			t.Error("LoadConfigFile() should fail when EnableCloud=true without CloudAPIKey")
		}
		if err != nil && !contains(err.Error(), "CloudAPIKey") {
			t.Errorf("Error should mention CloudAPIKey, got: %v", err)
		}
	})

	t.Run("valid cloud config", func(t *testing.T) {
		configPath := filepath.Join(tmpDir, "valid_cloud.json")
		configData := `{
			"ModemAddress": "192.168.100.1",
			"EnableCloud": true,
			"CloudHost": "api.example.com",
			"CloudPort": "8080",
			"CloudAPIKey": "test-api-key-123",
			"CloudPath": "/api/upload"
		}`

		if err := os.WriteFile(configPath, []byte(configData), 0644); err != nil {
			t.Fatalf("Failed to write config file: %v", err)
		}

		var config Configuration
		if err := LoadConfigFile(configPath, &config); err != nil {
			t.Fatalf("LoadConfigFile() failed with valid cloud config: %v", err)
		}

		if config.CloudHost != "api.example.com" {
			t.Errorf("CloudHost = %q, want 'api.example.com'", config.CloudHost)
		}
		if config.CloudPort != "8080" {
			t.Errorf("CloudPort = %q, want '8080'", config.CloudPort)
		}
	})

	t.Run("missing config file", func(t *testing.T) {
		var config Configuration
		err := LoadConfigFile("/nonexistent/config.json", &config)
		if err == nil {
			t.Error("LoadConfigFile() should fail with non-existent file")
		}
	})

	t.Run("invalid JSON", func(t *testing.T) {
		configPath := filepath.Join(tmpDir, "invalid.json")
		if err := os.WriteFile(configPath, []byte("{invalid json}"), 0644); err != nil {
			t.Fatalf("Failed to write config file: %v", err)
		}

		var config Configuration
		err := LoadConfigFile(configPath, &config)
		if err == nil {
			t.Error("LoadConfigFile() should fail with invalid JSON")
		}
	})
}

// TestSpeedTestState tests speed test state persistence
func TestSpeedTestState(t *testing.T) {
	tmpDir := t.TempDir()

	t.Run("load non-existent state", func(t *testing.T) {
		state, err := LoadSpeedTestState(tmpDir)
		if err != nil {
			t.Fatalf("LoadSpeedTestState() failed: %v", err)
		}

		// Should return default state
		if state.RunCount != 0 {
			t.Errorf("RunCount = %d, want 0", state.RunCount)
		}
		if state.LastSpeedTest != 0 {
			t.Errorf("LastSpeedTest = %d, want 0", state.LastSpeedTest)
		}
		if !state.LastTestSuccess {
			t.Error("LastTestSuccess = false, want true (default)")
		}
	})

	t.Run("save and load state", func(t *testing.T) {
		state, err := LoadSpeedTestState(tmpDir)
		if err != nil {
			t.Fatalf("LoadSpeedTestState() failed: %v", err)
		}

		// Modify state
		state.RunCount = 10
		state.LastSpeedTest = 5
		state.LastTestSuccess = false

		// Save state
		if err := state.Save(); err != nil {
			t.Fatalf("Save() failed: %v", err)
		}

		// Load state again
		loadedState, err := LoadSpeedTestState(tmpDir)
		if err != nil {
			t.Fatalf("LoadSpeedTestState() failed on second load: %v", err)
		}

		// Verify loaded state matches
		if loadedState.RunCount != 10 {
			t.Errorf("RunCount = %d, want 10", loadedState.RunCount)
		}
		if loadedState.LastSpeedTest != 5 {
			t.Errorf("LastSpeedTest = %d, want 5", loadedState.LastSpeedTest)
		}
		if loadedState.LastTestSuccess {
			t.Error("LastTestSuccess = true, want false")
		}
	})

	t.Run("save skips unchanged state", func(t *testing.T) {
		state, err := LoadSpeedTestState(tmpDir)
		if err != nil {
			t.Fatalf("LoadSpeedTestState() failed: %v", err)
		}

		state.RunCount = 20
		state.LastSpeedTest = 10
		state.LastTestSuccess = true

		// First save
		if err := state.Save(); err != nil {
			t.Fatalf("First Save() failed: %v", err)
		}

		// Get file modification time
		stateFile := filepath.Join(tmpDir, "speedtest_state.json")
		info1, err := os.Stat(stateFile)
		if err != nil {
			t.Fatalf("Failed to stat state file: %v", err)
		}
		mtime1 := info1.ModTime()

		// Wait a bit to ensure different mtime if file is written
		time.Sleep(10 * time.Millisecond)

		// Save again without changes
		if err := state.Save(); err != nil {
			t.Fatalf("Second Save() failed: %v", err)
		}

		// Get file modification time again
		info2, err := os.Stat(stateFile)
		if err != nil {
			t.Fatalf("Failed to stat state file after second save: %v", err)
		}
		mtime2 := info2.ModTime()

		// Modification time should be the same (file not written)
		if !mtime1.Equal(mtime2) {
			t.Error("Save() should skip write when state is unchanged")
		}
	})

	t.Run("save writes when state changes", func(t *testing.T) {
		state, err := LoadSpeedTestState(tmpDir)
		if err != nil {
			t.Fatalf("LoadSpeedTestState() failed: %v", err)
		}

		state.RunCount = 30
		state.Save() // First save

		stateFile := filepath.Join(tmpDir, "speedtest_state.json")
		info1, err := os.Stat(stateFile)
		if err != nil {
			t.Fatalf("Failed to stat state file: %v", err)
		}
		mtime1 := info1.ModTime()

		time.Sleep(10 * time.Millisecond)

		// Change state and save
		state.RunCount = 31
		state.Save()

		info2, err := os.Stat(stateFile)
		if err != nil {
			t.Fatalf("Failed to stat state file: %v", err)
		}
		mtime2 := info2.ModTime()

		// Modification time should be different (file was written)
		if mtime1.Equal(mtime2) {
			t.Error("Save() should write when state changes")
		}
	})
}

// TestLastSuccessfulModem tests modem state persistence
func TestLastSuccessfulModem(t *testing.T) {
	// Save current working directory
	originalWd, err := os.Getwd()
	if err != nil {
		t.Fatalf("Failed to get working directory: %v", err)
	}
	defer os.Chdir(originalWd)

	// Create temporary directory and change to it
	// This allows os.Executable() to work in a controlled location
	tmpDir := t.TempDir()

	// Copy current test executable to tmp directory for testing
	// (This is needed because os.Executable() returns the test binary path)
	exePath, _ := os.Executable()
	tmpExe := filepath.Join(tmpDir, "test-binary")
	data, _ := os.ReadFile(exePath)
	os.WriteFile(tmpExe, data, 0755)

	t.Run("save and load modem state", func(t *testing.T) {
		// Save modem state
		err := SaveLastSuccessfulModem("XB8", "AA:BB:CC:DD:EE:FF", "192.168.100.1")
		if err != nil {
			t.Fatalf("SaveLastSuccessfulModem() failed: %v", err)
		}

		// Load modem state
		state, err := LoadLastSuccessfulModem()
		if err != nil {
			t.Fatalf("LoadLastSuccessfulModem() failed: %v", err)
		}

		// Verify loaded state
		if state.ModemType != "XB8" {
			t.Errorf("ModemType = %q, want 'XB8'", state.ModemType)
		}
		if state.ModemMAC != "AA:BB:CC:DD:EE:FF" {
			t.Errorf("ModemMAC = %q, want 'AA:BB:CC:DD:EE:FF'", state.ModemMAC)
		}
		if state.ModemAddress != "192.168.100.1" {
			t.Errorf("ModemAddress = %q, want '192.168.100.1'", state.ModemAddress)
		}
		if state.LastSuccessTime == 0 {
			t.Error("LastSuccessTime should be set")
		}
	})

	t.Run("load non-existent state", func(t *testing.T) {
		// Remove state file
		exePath, _ := os.Executable()
		exeDir := filepath.Dir(exePath)
		stateFile := filepath.Join(exeDir, "last_successful_modem.json")
		os.Remove(stateFile)

		// Load should return empty state without error
		state, err := LoadLastSuccessfulModem()
		if err != nil {
			t.Fatalf("LoadLastSuccessfulModem() should not error on missing file: %v", err)
		}

		// Should have empty values
		if state.ModemType != "" || state.ModemMAC != "" {
			t.Error("Loaded state should be empty when file doesn't exist")
		}
	})
}

// TestIPInfoCache tests IP info cache persistence and expiration
func TestIPInfoCache(t *testing.T) {
	t.Run("save and load cache", func(t *testing.T) {
		// Save cache
		err := SaveIPInfoCache("1.2.3.4", "AS1234", "Test ISP", "TestCity", "US")
		if err != nil {
			t.Fatalf("SaveIPInfoCache() failed: %v", err)
		}

		// Load cache
		cache, err := LoadIPInfoCache()
		if err != nil {
			t.Fatalf("LoadIPInfoCache() failed: %v", err)
		}

		// Verify loaded cache
		if cache == nil {
			t.Fatal("LoadIPInfoCache() returned nil for valid cache")
		}
		if cache.PublicIP != "1.2.3.4" {
			t.Errorf("PublicIP = %q, want '1.2.3.4'", cache.PublicIP)
		}
		if cache.ASN != "AS1234" {
			t.Errorf("ASN = %q, want 'AS1234'", cache.ASN)
		}
		if cache.ISPName != "Test ISP" {
			t.Errorf("ISPName = %q, want 'Test ISP'", cache.ISPName)
		}
	})

	t.Run("load non-existent cache", func(t *testing.T) {
		// Remove cache file
		exePath, _ := os.Executable()
		exeDir := filepath.Dir(exePath)
		cacheFile := filepath.Join(exeDir, ".ip_info_cache.json")
		os.Remove(cacheFile)

		// Load should return nil without error
		cache, err := LoadIPInfoCache()
		if err != nil {
			t.Fatalf("LoadIPInfoCache() should not error on missing file: %v", err)
		}
		if cache != nil {
			t.Error("LoadIPInfoCache() should return nil for missing file")
		}
	})

	t.Run("expired cache returns nil", func(t *testing.T) {
		// Create cache file with old timestamp
		exePath, _ := os.Executable()
		exeDir := filepath.Dir(exePath)
		cacheFile := filepath.Join(exeDir, ".ip_info_cache.json")

		oldCache := IPInfoCache{
			PublicIP:  "1.2.3.4",
			ASN:       "AS1234",
			ISPName:   "Test ISP",
			IPCity:    "TestCity",
			IPCountry: "US",
			Timestamp: time.Now().Add(-25 * time.Hour), // 25 hours ago (expired)
		}

		data, _ := json.MarshalIndent(oldCache, "", "  ")
		os.WriteFile(cacheFile, data, 0644)

		// Load should return nil for expired cache
		cache, err := LoadIPInfoCache()
		if err != nil {
			t.Fatalf("LoadIPInfoCache() failed: %v", err)
		}
		if cache != nil {
			t.Error("LoadIPInfoCache() should return nil for expired cache (>24 hours)")
		}
	})

	t.Run("fresh cache is loaded", func(t *testing.T) {
		// Create cache file with recent timestamp
		exePath, _ := os.Executable()
		exeDir := filepath.Dir(exePath)
		cacheFile := filepath.Join(exeDir, ".ip_info_cache.json")

		freshCache := IPInfoCache{
			PublicIP:  "5.6.7.8",
			ASN:       "AS5678",
			ISPName:   "Fresh ISP",
			IPCity:    "FreshCity",
			IPCountry: "CA",
			Timestamp: time.Now().Add(-1 * time.Hour), // 1 hour ago (fresh)
		}

		data, _ := json.MarshalIndent(freshCache, "", "  ")
		os.WriteFile(cacheFile, data, 0644)

		// Load should return the cache
		cache, err := LoadIPInfoCache()
		if err != nil {
			t.Fatalf("LoadIPInfoCache() failed: %v", err)
		}
		if cache == nil {
			t.Fatal("LoadIPInfoCache() should return cache for fresh data")
		}
		if cache.PublicIP != "5.6.7.8" {
			t.Errorf("PublicIP = %q, want '5.6.7.8'", cache.PublicIP)
		}
	})
}
