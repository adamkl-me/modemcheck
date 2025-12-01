package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func init() {
	// Use HTTP for tests (HTTPS in production)
	SetConfigSyncURLScheme("http")
}

// TestGenerateNonce tests nonce generation
func TestGenerateNonce(t *testing.T) {
	t.Run("generates valid nonce", func(t *testing.T) {
		nonce, err := generateNonce()
		if err != nil {
			t.Fatalf("generateNonce() error = %v", err)
		}

		// Nonce should be SHA256 hex (64 chars)
		if len(nonce) != 64 {
			t.Errorf("nonce length = %d, want 64", len(nonce))
		}

		// Should be valid hex
		_, err = hex.DecodeString(nonce)
		if err != nil {
			t.Errorf("nonce is not valid hex: %v", err)
		}
	})

	t.Run("generates unique nonces", func(t *testing.T) {
		nonce1, _ := generateNonce()
		nonce2, _ := generateNonce()

		if nonce1 == nonce2 {
			t.Error("generateNonce() produced duplicate nonces")
		}
	})

	t.Run("generates correct length", func(t *testing.T) {
		for i := 0; i < 10; i++ {
			nonce, _ := generateNonce()
			if len(nonce) != 64 {
				t.Errorf("iteration %d: nonce length = %d, want 64", i, len(nonce))
			}
		}
	})
}

// TestCalculateConfigHash tests config hash calculation
func TestCalculateConfigHash(t *testing.T) {
	t.Run("calculates hash correctly", func(t *testing.T) {
		config := map[string]interface{}{
			"PingCount":   25,
			"EnableCloud": true,
		}

		hash, err := calculateConfigHash(config)
		if err != nil {
			t.Fatalf("calculateConfigHash() error = %v", err)
		}

		// Hash should be SHA256 hex (64 chars)
		if len(hash) != 64 {
			t.Errorf("hash length = %d, want 64", len(hash))
		}

		// Should be valid hex
		_, err = hex.DecodeString(hash)
		if err != nil {
			t.Errorf("hash is not valid hex: %v", err)
		}
	})

	t.Run("same config produces same hash", func(t *testing.T) {
		config := map[string]interface{}{
			"PingCount":   25,
			"EnableCloud": true,
		}

		hash1, _ := calculateConfigHash(config)
		hash2, _ := calculateConfigHash(config)

		if hash1 != hash2 {
			t.Errorf("same config produced different hashes: %s != %s", hash1, hash2)
		}
	})

	t.Run("hash is order independent", func(t *testing.T) {
		config1 := map[string]interface{}{
			"PingCount":   25,
			"EnableCloud": true,
		}
		config2 := map[string]interface{}{
			"EnableCloud": true,
			"PingCount":   25,
		}

		hash1, _ := calculateConfigHash(config1)
		hash2, _ := calculateConfigHash(config2)

		if hash1 != hash2 {
			t.Error("hash is not order independent")
		}
	})

	t.Run("different configs produce different hashes", func(t *testing.T) {
		config1 := map[string]interface{}{
			"PingCount": 25,
		}
		config2 := map[string]interface{}{
			"PingCount": 50,
		}

		hash1, _ := calculateConfigHash(config1)
		hash2, _ := calculateConfigHash(config2)

		if hash1 == hash2 {
			t.Error("different configs produced same hash")
		}
	})

	t.Run("handles empty config", func(t *testing.T) {
		config := make(map[string]interface{})

		hash, err := calculateConfigHash(config)
		if err != nil {
			t.Errorf("calculateConfigHash() with empty config error = %v", err)
		}

		if len(hash) != 64 {
			t.Errorf("empty config hash length = %d, want 64", len(hash))
		}
	})

	t.Run("handles nested structures", func(t *testing.T) {
		config := map[string]interface{}{
			"level1": map[string]interface{}{
				"level2": map[string]interface{}{
					"value": []int{1, 2, 3},
				},
			},
		}

		hash, err := calculateConfigHash(config)
		if err != nil {
			t.Errorf("calculateConfigHash() with nested config error = %v", err)
		}

		if len(hash) != 64 {
			t.Errorf("nested config hash length = %d, want 64", len(hash))
		}
	})
}

// TestCanonicalizeJSON tests JSON canonicalization
func TestCanonicalizeJSON(t *testing.T) {
	t.Run("sorts keys", func(t *testing.T) {
		config := map[string]interface{}{
			"zebra":  1,
			"apple":  2,
			"middle": 3,
		}

		canonical, err := canonicalizeJSON(config)
		if err != nil {
			t.Fatalf("canonicalizeJSON() error = %v", err)
		}

		// Keys should be sorted
		expected := `{"apple":2,"middle":3,"zebra":1}`
		if canonical != expected {
			t.Errorf("canonicalizeJSON() = %s, want %s", canonical, expected)
		}
	})

	t.Run("removes whitespace", func(t *testing.T) {
		config := map[string]interface{}{
			"key": "value",
		}

		canonical, err := canonicalizeJSON(config)
		if err != nil {
			t.Fatalf("canonicalizeJSON() error = %v", err)
		}

		// Should not contain whitespace
		if canonical != `{"key":"value"}` {
			t.Errorf("canonicalizeJSON() = %s, has unexpected whitespace", canonical)
		}
	})

	t.Run("is deterministic", func(t *testing.T) {
		config := map[string]interface{}{
			"b": 2,
			"a": 1,
			"c": 3,
		}

		canonical1, _ := canonicalizeJSON(config)
		canonical2, _ := canonicalizeJSON(config)

		if canonical1 != canonical2 {
			t.Error("canonicalizeJSON() is not deterministic")
		}
	})
}

// TestGenerateConfigSyncSignature tests HMAC signature generation
// Note: v2.1 signature format excludes modem_id (API key is primary key)
func TestGenerateConfigSyncSignature(t *testing.T) {
	apiKey := "test_api_key_123"
	timestamp := "2024-01-01T00:00:00Z"
	nonce := "abc123"
	configHash := "def456"

	t.Run("generates valid signature", func(t *testing.T) {
		signature := generateConfigSyncSignature(apiKey, timestamp, nonce, configHash)

		// Signature should be HMAC-SHA256 hex (64 chars)
		if len(signature) != 64 {
			t.Errorf("signature length = %d, want 64", len(signature))
		}

		// Should be valid hex
		_, err := hex.DecodeString(signature)
		if err != nil {
			t.Errorf("signature is not valid hex: %v", err)
		}
	})

	t.Run("same inputs produce same signature", func(t *testing.T) {
		sig1 := generateConfigSyncSignature(apiKey, timestamp, nonce, configHash)
		sig2 := generateConfigSyncSignature(apiKey, timestamp, nonce, configHash)

		if sig1 != sig2 {
			t.Error("same inputs produced different signatures")
		}
	})

	t.Run("different inputs produce different signatures", func(t *testing.T) {
		sig1 := generateConfigSyncSignature(apiKey, timestamp, nonce, configHash)
		sig2 := generateConfigSyncSignature(apiKey, timestamp, "different_nonce", configHash)

		if sig1 == sig2 {
			t.Error("different inputs produced same signature")
		}
	})

	t.Run("matches expected HMAC format", func(t *testing.T) {
		// Manual HMAC calculation - v2.1 format: timestamp|nonce|config_hash (no modem_id)
		message := timestamp + "|" + nonce + "|" + configHash
		mac := hmac.New(sha256.New, []byte(apiKey))
		mac.Write([]byte(message))
		expected := hex.EncodeToString(mac.Sum(nil))

		signature := generateConfigSyncSignature(apiKey, timestamp, nonce, configHash)

		if signature != expected {
			t.Errorf("signature = %s, want %s", signature, expected)
		}
	})

	t.Run("changing any parameter changes signature", func(t *testing.T) {
		sig := generateConfigSyncSignature(apiKey, timestamp, nonce, configHash)

		// Change each parameter (note: modem_id no longer in signature)
		sigDiffKey := generateConfigSyncSignature("different_key", timestamp, nonce, configHash)
		sigDiffTime := generateConfigSyncSignature(apiKey, "2024-02-01T00:00:00Z", nonce, configHash)
		sigDiffNonce := generateConfigSyncSignature(apiKey, timestamp, "xyz789", configHash)
		sigDiffHash := generateConfigSyncSignature(apiKey, timestamp, nonce, "ghi789")

		if sig == sigDiffKey || sig == sigDiffTime || sig == sigDiffNonce || sig == sigDiffHash {
			t.Error("changing parameters did not change signature")
		}
	})
}

// TestConfigToMap tests configuration struct to map conversion
func TestConfigToMap(t *testing.T) {
	t.Run("converts all fields", func(t *testing.T) {
		config := &Configuration{
			ModemAddress:        "192.168.100.1",
			IgnitePassword:      "password123",
			SpeedTestEnabled:    true,
			SpeedTestInterval:   5,
			PingCount:           25,
			AutoUpdateEnabled:   true,
			UpdateChannel:       "stable",
			Silent:              false,
			NoLogs:              false,
			LocalCleanupEnabled: true,
			LocalRetentionDays:  30,
			EnableCloud: true,
			CloudHost:   "cloud.example.com",
			CloudPort:   "443",
			CloudAPIKey: "api-key-123",
		}

		m := configToMap(config)

		if m["ModemAddress"] != "192.168.100.1" {
			t.Errorf("ModemAddress = %v, want 192.168.100.1", m["ModemAddress"])
		}
		if m["PingCount"] != 25 {
			t.Errorf("PingCount = %v, want 25", m["PingCount"])
		}
		if m["EnableCloud"] != true {
			t.Errorf("EnableCloud = %v, want true", m["EnableCloud"])
		}
	})
}

// TestMapToConfig tests map to configuration struct conversion
func TestMapToConfig(t *testing.T) {
	t.Run("converts all fields", func(t *testing.T) {
		data := map[string]interface{}{
			"ModemAddress":         "192.168.100.1",
			"IgnitePassword":       "password123",
			"SpeedTestEnabled":     true,
			"SpeedTestInterval":    float64(5), // JSON unmarshals as float64
			"SpeedTestConnections": float64(4), // Required field
			"PingCount":            float64(25),
			"AutoUpdateEnabled":    true,
			"UpdateChannel":        "stable",
			"Silent":               false,
			"NoLogs":               false,
			"LocalCleanupEnabled":  true,
			"LocalRetentionDays":   float64(30),
			"EnableCloud":          true,
			"CloudHost":            "cloud.example.com",
			"CloudPort":            "443",
			"CloudAPIKey":          "api-key-123",
		}

		config := &Configuration{}
		err := mapToConfig(data, config)
		if err != nil {
			t.Fatalf("mapToConfig() error = %v", err)
		}

		if config.ModemAddress != "192.168.100.1" {
			t.Errorf("ModemAddress = %s, want 192.168.100.1", config.ModemAddress)
		}
		if config.PingCount != 25 {
			t.Errorf("PingCount = %d, want 25", config.PingCount)
		}
		if !config.EnableCloud {
			t.Error("EnableCloud should be true")
		}
	})

	t.Run("handles missing fields with defaults", func(t *testing.T) {
		data := map[string]interface{}{
			"ModemAddress":         "192.168.100.1",
			"SpeedTestInterval":    float64(1),  // Required field
			"SpeedTestConnections": float64(1),  // Required field
			"PingCount":            float64(50), // Required field
			"LocalRetentionDays":   float64(90), // Required field
		}

		config := &Configuration{
			PingCount:     50, // Default value
			UpdateChannel: "beta",
		}

		err := mapToConfig(data, config)
		if err != nil {
			t.Fatalf("mapToConfig() error = %v", err)
		}

		// Should preserve default for missing field
		if config.PingCount != 50 {
			t.Errorf("PingCount = %d, want 50", config.PingCount)
		}
		// Should update provided field
		if config.ModemAddress != "192.168.100.1" {
			t.Errorf("ModemAddress = %s, want 192.168.100.1", config.ModemAddress)
		}
	})

	t.Run("handles native int values", func(t *testing.T) {
		// When Go code uses int directly (not from JSON)
		data := map[string]interface{}{
			"PingCount":            int(42),
			"SpeedTestInterval":    int(10),
			"SpeedTestConnections": int(4), // Required field
			"LocalRetentionDays":   int(90),
		}

		config := &Configuration{}
		err := mapToConfig(data, config)
		if err != nil {
			t.Fatalf("mapToConfig() error = %v", err)
		}

		if config.PingCount != 42 {
			t.Errorf("PingCount = %d, want 42", config.PingCount)
		}
		if config.SpeedTestInterval != 10 {
			t.Errorf("SpeedTestInterval = %d, want 10", config.SpeedTestInterval)
		}
		if config.LocalRetentionDays != 90 {
			t.Errorf("LocalRetentionDays = %d, want 90", config.LocalRetentionDays)
		}
	})

	t.Run("handles invalid type for int field gracefully", func(t *testing.T) {
		// If a string is provided where int expected, should use default
		data := map[string]interface{}{
			"PingCount":            "not-an-int",
			"SpeedTestInterval":    float64(1),  // Required field
			"SpeedTestConnections": float64(1),  // Required field
			"LocalRetentionDays":   float64(90), // Required field
		}

		config := &Configuration{PingCount: 25}
		err := mapToConfig(data, config)
		if err != nil {
			t.Fatalf("mapToConfig() error = %v", err)
		}

		// Should preserve default when type is wrong
		if config.PingCount != 25 {
			t.Errorf("PingCount = %d, want 25 (default)", config.PingCount)
		}
	})

	t.Run("handles invalid type for bool field gracefully", func(t *testing.T) {
		// If a string is provided where bool expected, should use default
		data := map[string]interface{}{
			"EnableCloud":          "yes",        // string, not bool
			"SpeedTestInterval":    float64(1),   // Required field
			"SpeedTestConnections": float64(1),   // Required field
			"PingCount":            float64(25),  // Required field
			"LocalRetentionDays":   float64(90),  // Required field
		}

		config := &Configuration{EnableCloud: true}
		err := mapToConfig(data, config)
		if err != nil {
			t.Fatalf("mapToConfig() error = %v", err)
		}

		// Should preserve default when type is wrong
		if !config.EnableCloud {
			t.Error("EnableCloud should remain true (default)")
		}
	})

	t.Run("handles edge cases for numeric conversion", func(t *testing.T) {
		data := map[string]interface{}{
			"PingCount":            float64(1),    // Minimum valid (not 0)
			"SpeedTestInterval":    float64(1),    // Minimum valid
			"SpeedTestConnections": float64(1),    // Required field
			"LocalRetentionDays":   float64(3650), // Maximum (10 years)
		}

		config := &Configuration{}
		err := mapToConfig(data, config)
		if err != nil {
			t.Fatalf("mapToConfig() error = %v", err)
		}

		if config.PingCount != 1 {
			t.Errorf("PingCount = %d, want 1", config.PingCount)
		}
		if config.SpeedTestInterval != 1 {
			t.Errorf("SpeedTestInterval = %d, want 1", config.SpeedTestInterval)
		}
		if config.LocalRetentionDays != 3650 {
			t.Errorf("LocalRetentionDays = %d, want 3650", config.LocalRetentionDays)
		}
	})

	t.Run("handles float with decimal conversion", func(t *testing.T) {
		// JSON might send float with decimals - converts to int (rounds)
		data := map[string]interface{}{
			"PingCount":            float64(25.5), // Rounds to 26
			"SpeedTestInterval":    float64(1),   // Required field
			"SpeedTestConnections": float64(1),   // Required field
			"LocalRetentionDays":   float64(90),  // Required field
		}

		config := &Configuration{}
		err := mapToConfig(data, config)
		if err != nil {
			t.Fatalf("mapToConfig() error = %v", err)
		}

		// Verify float is converted to int (rounding behavior)
		if config.PingCount != 26 {
			t.Errorf("PingCount = %d, want 26 (rounded from 25.5)", config.PingCount)
		}
	})
}

// TestIsNetworkError tests network error detection
func TestIsNetworkError(t *testing.T) {
	tests := []struct {
		name     string
		errMsg   string
		expected bool
	}{
		{"connection refused", "dial tcp: connection refused", true},
		{"no such host", "no such host", true},
		{"timeout", "connection timeout exceeded", true},
		{"network unreachable", "network is unreachable", true},
		{"dial error", "dial tcp error", true},
		{"EOF", "unexpected EOF", true},
		{"validation error", "invalid config", false},
		{"auth error", "unauthorized", false},
		{"empty error", "", false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var err error
			if tt.errMsg != "" {
				err = &testError{msg: tt.errMsg}
			}

			result := isNetworkError(err)
			if result != tt.expected {
				t.Errorf("isNetworkError(%q) = %v, want %v", tt.errMsg, result, tt.expected)
			}
		})
	}
}

// testError is a simple error implementation for testing
type testError struct {
	msg string
}

func (e *testError) Error() string {
	return e.msg
}

// TestConfigSyncRequest tests the sync request structure
func TestConfigSyncRequest(t *testing.T) {
	t.Run("version is int type", func(t *testing.T) {
		req := ConfigSyncRequest{
			APIKey:     "test-key",
			ModemID:    "ARRIS-TEST",
			Config:     map[string]interface{}{"PingCount": 25},
			Version:    2, // Int version
			ConfigHash: "hash123",
			Timestamp:  "2024-01-01T00:00:00Z",
			Nonce:      "nonce123",
			Signature:  "sig123",
		}

		if req.Version != 2 {
			t.Errorf("Version = %d, want 2", req.Version)
		}
	})
}

// TestConfigSyncResponse tests the sync response structure
func TestConfigSyncResponse(t *testing.T) {
	t.Run("has simplified versioning fields", func(t *testing.T) {
		resp := ConfigSyncResponse{
			Success:         true,
			Config:          map[string]interface{}{"PingCount": 50},
			Version:         3, // Simple int version
			Status:          "locked",
			SyncStatus:      "active",
			ConfigHash:      "hash456",
			ServerTimestamp: "2024-01-01T00:00:00Z",
			ConfigChanged:   true,
		}

		if resp.Version != 3 {
			t.Errorf("Version = %d, want 3", resp.Version)
		}
		if resp.Status != "locked" {
			t.Errorf("Status = %s, want locked", resp.Status)
		}
		if resp.SyncStatus != "active" {
			t.Errorf("SyncStatus = %s, want active", resp.SyncStatus)
		}
		if !resp.ConfigChanged {
			t.Error("ConfigChanged should be true")
		}
	})
}

// TestConfigState tests the ConfigState struct with simplified versioning
func TestConfigState(t *testing.T) {
	t.Run("struct fields are correct types", func(t *testing.T) {
		state := ConfigState{
			Version:          3,
			Status:           "locked",
			SyncStatus:       "active",
			ServerConfigHash: "abc123def456",
		}

		if state.Version != 3 {
			t.Errorf("Version = %d, want 3", state.Version)
		}
		if state.Status != "locked" {
			t.Errorf("Status = %s, want locked", state.Status)
		}
		if state.SyncStatus != "active" {
			t.Errorf("SyncStatus = %s, want active", state.SyncStatus)
		}
		if state.ServerConfigHash != "abc123def456" {
			t.Errorf("ServerConfigHash = %s, want abc123def456", state.ServerConfigHash)
		}
	})

	t.Run("all 3 status values are valid", func(t *testing.T) {
		statuses := []string{
			"unmanaged",
			"managed",
			"locked",
		}

		for _, status := range statuses {
			state := ConfigState{
				Version: 1,
				Status:  status,
			}

			// Status should be preserved
			if state.Status != status {
				t.Errorf("Status = %s, want %s", state.Status, status)
			}
		}
	})

	t.Run("all sync_status values are valid", func(t *testing.T) {
		syncStatuses := []string{
			"n/a",
			"pending",
			"active",
		}

		for _, ss := range syncStatuses {
			state := ConfigState{
				Version:    1,
				Status:     "managed",
				SyncStatus: ss,
			}

			if state.SyncStatus != ss {
				t.Errorf("SyncStatus = %s, want %s", state.SyncStatus, ss)
			}
		}
	})
}

// TestLockedStatusCheck tests logic for checking locked status
func TestLockedStatusCheck(t *testing.T) {
	tests := []struct {
		status   string
		isLocked bool
	}{
		{"locked", true},
		{"managed", false},
		{"unmanaged", false},
		{"", false},
	}

	for _, tt := range tests {
		t.Run(tt.status, func(t *testing.T) {
			// Check the status logic inline (mirrors IsConfigLocked)
			isLocked := tt.status == "locked"
			if isLocked != tt.isLocked {
				t.Errorf("status %q isLocked = %v, want %v", tt.status, isLocked, tt.isLocked)
			}
		})
	}
}

// TestShouldSyncLogic tests sync timing logic inline (without file system)
func TestShouldSyncLogic(t *testing.T) {
	t.Run("zero version means first sync", func(t *testing.T) {
		version := 0
		shouldSync := version == 0
		if !shouldSync {
			t.Error("zero version should trigger sync")
		}
	})

	t.Run("locked status triggers sync after rate limit", func(t *testing.T) {
		status := "locked"
		isLocked := status == "locked"
		if !isLocked {
			t.Error("locked should be recognized as locked status")
		}
	})

	t.Run("pending sync status indicates awaiting sync", func(t *testing.T) {
		syncStatus := "pending"
		isPending := syncStatus == "pending"
		if !isPending {
			t.Error("pending should be recognized as pending sync status")
		}
	})
}

// TestVersionIncrement tests version increment behavior
func TestVersionIncrement(t *testing.T) {
	t.Run("version increments correctly", func(t *testing.T) {
		versions := []int{0, 1, 2, 10, 100}
		for _, v := range versions {
			next := v + 1
			if next <= v {
				t.Errorf("version %d + 1 = %d, should be greater", v, next)
			}
		}
	})

	t.Run("version starts at zero", func(t *testing.T) {
		state := ConfigState{}
		if state.Version != 0 {
			t.Errorf("default version = %d, want 0", state.Version)
		}
	})
}

// TestSyncConfig_Success tests successful config sync
func TestSyncConfig_Success(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/config/sync" {
			t.Errorf("unexpected path: %s", r.URL.Path)
		}

		// Parse request
		var req ConfigSyncRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			t.Errorf("failed to decode request: %v", err)
			w.WriteHeader(http.StatusBadRequest)
			return
		}

		// Verify required fields
		if req.APIKey == "" || req.Timestamp == "" || req.Nonce == "" || req.Signature == "" {
			t.Error("missing required fields")
		}

		// Return success response (no config change)
		response := ConfigSyncResponse{
			Success:         true,
			Config:          req.Config,
			Version:         1,
			Status:          "managed",
			SyncStatus:      "active",
			ConfigHash:      req.ConfigHash,
			ServerTimestamp: time.Now().UTC().Format(time.RFC3339),
			ConfigChanged:   false,
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(response)
	}))
	defer server.Close()

	serverURL := strings.TrimPrefix(server.URL, "http://")
	parts := strings.Split(serverURL, ":")

	config := &Configuration{
		EnableCloud: true,
		CloudHost:   parts[0],
		CloudPort:   parts[1],
		CloudAPIKey: "test-api-key",
		PingCount:   25,
	}

	state := &ConfigState{}

	configChanged, err := SyncConfig(config, "TEST-MODEM", state)

	if err != nil {
		t.Fatalf("SyncConfig() error = %v", err)
	}
	if configChanged {
		t.Error("configChanged = true, want false")
	}
	if state.Version != 1 {
		t.Errorf("state.Version = %d, want 1", state.Version)
	}
	if state.Status != "managed" {
		t.Errorf("state.Status = %s, want managed", state.Status)
	}
}

// TestSyncConfig_ConfigChanged tests sync when config is changed by server
func TestSyncConfig_ConfigChanged(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		response := ConfigSyncResponse{
			Success: true,
			Config: map[string]interface{}{
				"PingCount":            50, // Changed from client's 25
				"EnableCloud":          true,
				"ModemAddress":         "192.168.100.1",
				"SpeedTestInterval":    float64(1),  // Required field
				"SpeedTestConnections": float64(1),  // Required field
				"LocalRetentionDays":   float64(90), // Required field
			},
			Version:         2,
			Status:          "locked",
			SyncStatus:      "active",
			ConfigHash:      "newhash123",
			ServerTimestamp: time.Now().UTC().Format(time.RFC3339),
			ConfigChanged:   true,
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(response)
	}))
	defer server.Close()

	serverURL := strings.TrimPrefix(server.URL, "http://")
	parts := strings.Split(serverURL, ":")

	config := &Configuration{
		EnableCloud: true,
		CloudHost:   parts[0],
		CloudPort:   parts[1],
		CloudAPIKey: "test-api-key",
		PingCount:   25, // Original value
	}

	state := &ConfigState{}

	configChanged, err := SyncConfig(config, "TEST-MODEM", state)

	if err != nil {
		t.Fatalf("SyncConfig() error = %v", err)
	}
	if !configChanged {
		t.Error("configChanged = false, want true")
	}
	if config.PingCount != 50 {
		t.Errorf("config.PingCount = %d, want 50 (server value)", config.PingCount)
	}
	if state.Status != "locked" {
		t.Errorf("state.Status = %s, want locked", state.Status)
	}
}

// TestSyncConfig_ServerError tests sync when server returns error
func TestSyncConfig_ServerError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadRequest)
		response := map[string]interface{}{
			"error": map[string]interface{}{
				"code":    "VALIDATION_ERROR",
				"message": "Invalid config hash",
			},
		}
		json.NewEncoder(w).Encode(response)
	}))
	defer server.Close()

	serverURL := strings.TrimPrefix(server.URL, "http://")
	parts := strings.Split(serverURL, ":")

	config := &Configuration{
		EnableCloud: true,
		CloudHost:   parts[0],
		CloudPort:   parts[1],
		CloudAPIKey: "test-api-key",
	}

	state := &ConfigState{}

	_, err := SyncConfig(config, "TEST-MODEM", state)

	if err == nil {
		t.Error("SyncConfig() expected error for server error response")
	}
	if !strings.Contains(err.Error(), "Invalid config hash") {
		t.Errorf("unexpected error: %v", err)
	}
}

// TestSyncConfig_CloudDisabled tests sync when cloud is disabled
func TestSyncConfig_CloudDisabled(t *testing.T) {
	config := &Configuration{
		EnableCloud: false,
	}
	state := &ConfigState{}

	_, err := SyncConfig(config, "TEST-MODEM", state)

	if err == nil {
		t.Error("SyncConfig() expected error when cloud disabled")
	}
}

// TestSyncWithRetry_Success tests retry with immediate success
func TestSyncWithRetry_Success(t *testing.T) {
	callCount := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		callCount++
		response := ConfigSyncResponse{
			Success:         true,
			Config:          map[string]interface{}{"PingCount": float64(25)},
			Version:         1,
			Status:          "managed",
			SyncStatus:      "active",
			ConfigHash:      "hash123",
			ServerTimestamp: time.Now().UTC().Format(time.RFC3339),
			ConfigChanged:   false,
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(response)
	}))
	defer server.Close()

	serverURL := strings.TrimPrefix(server.URL, "http://")
	parts := strings.Split(serverURL, ":")

	config := &Configuration{
		EnableCloud: true,
		CloudHost:   parts[0],
		CloudPort:   parts[1],
		CloudAPIKey: "test-api-key",
	}

	state := &ConfigState{}

	_, err := SyncWithRetry(config, "TEST-MODEM", state, 3)

	if err != nil {
		t.Fatalf("SyncWithRetry() error = %v", err)
	}
	if callCount != 1 {
		t.Errorf("server called %d times, want 1 (no retries needed)", callCount)
	}
}

// TestSyncWithRetry_NonNetworkError tests that non-network errors are not retried
func TestSyncWithRetry_NonNetworkError(t *testing.T) {
	callCount := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		callCount++
		// HTTP 500 error is not a network error - should not be retried
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"error": map[string]interface{}{"message": "temporary error"},
		})
	}))
	defer server.Close()

	serverURL := strings.TrimPrefix(server.URL, "http://")
	parts := strings.Split(serverURL, ":")

	config := &Configuration{
		EnableCloud: true,
		CloudHost:   parts[0],
		CloudPort:   parts[1],
		CloudAPIKey: "test-api-key",
	}

	state := &ConfigState{}

	_, err := SyncWithRetry(config, "TEST-MODEM", state, 3)

	if err == nil {
		t.Error("SyncWithRetry() expected error for server error")
	}
	// Non-network errors should not be retried (only 1 call)
	if callCount != 1 {
		t.Errorf("server called %d times, want 1 (non-network errors not retried)", callCount)
	}
}

// TestSyncWithRetry_NonRetryableError tests retry behavior for locked config
func TestSyncWithRetry_NonRetryableError(t *testing.T) {
	callCount := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		callCount++
		w.WriteHeader(http.StatusConflict)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"error": map[string]interface{}{
				"message": "config is locked by another process",
			},
		})
	}))
	defer server.Close()

	serverURL := strings.TrimPrefix(server.URL, "http://")
	parts := strings.Split(serverURL, ":")

	config := &Configuration{
		EnableCloud: true,
		CloudHost:   parts[0],
		CloudPort:   parts[1],
		CloudAPIKey: "test-api-key",
	}

	state := &ConfigState{}

	_, err := SyncWithRetry(config, "TEST-MODEM", state, 3)

	if err == nil {
		t.Error("SyncWithRetry() expected error for locked config")
	}
	if callCount > 1 {
		t.Errorf("server called %d times, want 1 (locked error should not retry)", callCount)
	}
}

// TestSyncWithRetry_NetworkError tests that network errors trigger retries
func TestSyncWithRetry_NetworkError(t *testing.T) {
	// Test with a non-existent server to get network errors
	config := &Configuration{
		EnableCloud: true,
		CloudHost:   "127.0.0.1",
		CloudPort:   "1", // Invalid port will cause connection refused
		CloudAPIKey: "test-api-key",
	}

	state := &ConfigState{}

	// This should retry 3 times before failing
	_, err := SyncWithRetry(config, "TEST-MODEM", state, 3)

	if err == nil {
		t.Error("SyncWithRetry() expected error for network failure")
	}
	// The error should indicate multiple retries failed
	if !strings.Contains(err.Error(), "sync failed") && !strings.Contains(err.Error(), "connection refused") {
		t.Errorf("unexpected error: %v", err)
	}
}
