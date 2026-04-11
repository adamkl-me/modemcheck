package main

import (
	"bytes"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"net/http"
	"sort"
	"strings"
	"time"
)

// Version 3.0: Simplified config sync with single endpoint and 3-state model
// - Removed preflight endpoint (merged into sync)
// - Removed dual-track versioning (now single-track: v1, v2, v3...)
// - States: unmanaged, managed, locked
// - SyncStatus: n/a, pending, active

// Shared HTTP client for config sync operations to avoid repeated TLS handshakes
var configSyncHTTPClient = &http.Client{
	Timeout: 30 * time.Second,
	Transport: &http.Transport{
		DisableKeepAlives:   false,
		MaxIdleConns:        10,
		MaxIdleConnsPerHost: 5,
		IdleConnTimeout:     90 * time.Second,
	},
}

// SetConfigSyncHTTPClient allows tests to inject a custom HTTP client
// This should only be used in tests
func SetConfigSyncHTTPClient(client *http.Client) {
	configSyncHTTPClient = client
}

// configSyncURLScheme allows tests to use HTTP instead of HTTPS
var configSyncURLScheme = "https"

// SetConfigSyncURLScheme allows tests to use HTTP instead of HTTPS
// This should only be used in tests
func SetConfigSyncURLScheme(scheme string) {
	configSyncURLScheme = scheme
}

// ConfigSyncRequest represents the request payload for config sync
type ConfigSyncRequest struct {
	APIKey     string                 `json:"api_key"` // #nosec G117 -- client's own auth credential intentionally transmitted over HTTPS
	ModemID    string                 `json:"modem_id,omitempty"` // Optional - for tracking metadata only
	Config     map[string]interface{} `json:"config"`
	Version    int                    `json:"version"`     // Simple int version (0 for first sync)
	ConfigHash string                 `json:"config_hash"` // SHA256 of canonical JSON
	Timestamp  string                 `json:"timestamp"`   // ISO 8601
	Nonce      string                 `json:"nonce"`       // SHA256 hex
	Signature  string                 `json:"signature"`   // HMAC-SHA256 of "{timestamp}|{nonce}|{config_hash}"
}

// ConfigSyncResponse represents the server response with simplified versioning
type ConfigSyncResponse struct {
	Success         bool                   `json:"success"`
	Config          map[string]interface{} `json:"config"`
	Version         int                    `json:"version"`      // Simple int version
	Status          string                 `json:"status"`       // unmanaged, managed, locked
	SyncStatus      string                 `json:"sync_status"`  // n/a, pending, active
	ConfigHash      string                 `json:"config_hash"`
	ServerTimestamp string                 `json:"server_timestamp"`
	ConfigChanged   bool                   `json:"config_changed"`
	Error           *ErrorResponse         `json:"error,omitempty"`
}

// ErrorResponse represents API error structure
type ErrorResponse struct {
	Code      string                 `json:"code"`
	Message   string                 `json:"message"`
	ErrorID   string                 `json:"error_id"`
	Timestamp string                 `json:"timestamp"`
	Details   map[string]interface{} `json:"details,omitempty"`
}

// generateNonce creates a cryptographically secure random nonce
func generateNonce() (string, error) {
	// Generate 32 random bytes
	nonce := make([]byte, 32)
	if _, err := rand.Read(nonce); err != nil {
		return "", fmt.Errorf("failed to generate nonce: %w", err)
	}

	// Return as SHA256 hex string (64 characters)
	hash := sha256.Sum256(nonce)
	return hex.EncodeToString(hash[:]), nil
}

// calculateConfigHash computes SHA256 hash of configuration
// Uses canonical JSON (sorted keys, no whitespace) for consistency
func calculateConfigHash(config map[string]interface{}) (string, error) {
	// Convert to canonical JSON (sorted keys, no whitespace)
	canonicalJSON, err := canonicalizeJSON(config)
	if err != nil {
		return "", fmt.Errorf("failed to canonicalize config: %w", err)
	}

	// Calculate SHA256
	hash := sha256.Sum256([]byte(canonicalJSON))
	return hex.EncodeToString(hash[:]), nil
}

// canonicalizeJSON converts a map to canonical JSON string
// Canonical form: sorted keys, no whitespace
func canonicalizeJSON(data map[string]interface{}) (string, error) {
	// Sort keys
	keys := make([]string, 0, len(data))
	for k := range data {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	// Build JSON manually with sorted keys
	var buf bytes.Buffer
	buf.WriteString("{")

	for i, key := range keys {
		if i > 0 {
			buf.WriteString(",")
		}

		// Write key
		keyJSON, err := json.Marshal(key)
		if err != nil {
			return "", err
		}
		buf.Write(keyJSON)
		buf.WriteString(":")

		// Write value
		valueJSON, err := json.Marshal(data[key])
		if err != nil {
			return "", err
		}
		buf.Write(valueJSON)
	}

	buf.WriteString("}")
	return buf.String(), nil
}

// generateConfigSyncSignature creates HMAC-SHA256 signature for config sync
// Message format: timestamp|nonce|config_hash
func generateConfigSyncSignature(apiKey, timestamp, nonce, configHash string) string {
	message := fmt.Sprintf("%s|%s|%s", timestamp, nonce, configHash)

	mac := hmac.New(sha256.New, []byte(apiKey))
	mac.Write([]byte(message))
	signature := hex.EncodeToString(mac.Sum(nil))

	return signature
}

// configToMap converts Configuration struct to map for JSON serialization
// Version 3.0: Removed CloudPath, EnforceHTTPS, InsecureTLS
func configToMap(config *Configuration) map[string]interface{} {
	return map[string]interface{}{
		"ModemAddress":         config.ModemAddress,
		"IgnitePassword":       config.IgnitePassword,
		"SpeedTestEnabled":     config.SpeedTestEnabled,
		"SpeedTestInterval":    config.SpeedTestInterval,
		"SpeedTestConnections": config.SpeedTestConnections,
		"PingCount":            config.PingCount,
		"AutoUpdateEnabled":    config.AutoUpdateEnabled,
		"UpdateChannel":        config.UpdateChannel,
		"Silent":               config.Silent,
		"NoLogs":               config.NoLogs,
		"LocalCleanupEnabled":  config.LocalCleanupEnabled,
		"LocalRetentionDays":   config.LocalRetentionDays,
		"EnableCloud":          config.EnableCloud,
		"CloudHost":            config.CloudHost,
		"CloudPort":            config.CloudPort,
		"CloudAPIKey":          config.CloudAPIKey,
	}
}

// validateConfigRanges validates config field ranges after sync
// Returns error if any field has an invalid range
func validateConfigRanges(config *Configuration) error {
	// Validate SpeedTestInterval (must be >= 1)
	if config.SpeedTestInterval < 1 {
		return fmt.Errorf("SpeedTestInterval must be at least 1 (got: %d)", config.SpeedTestInterval)
	}

	// Validate SpeedTestConnections (must be 1-16)
	if config.SpeedTestConnections < 1 || config.SpeedTestConnections > 16 {
		return fmt.Errorf("SpeedTestConnections must be between 1 and 16 (got: %d)", config.SpeedTestConnections)
	}

	// Validate PingCount (must be 1-100)
	if config.PingCount < 1 || config.PingCount > 100 {
		return fmt.Errorf("PingCount must be between 1 and 100 (got: %d)", config.PingCount)
	}

	// Validate LocalRetentionDays (must be >= 1)
	if config.LocalRetentionDays < 1 {
		return fmt.Errorf("LocalRetentionDays must be at least 1 (got: %d)", config.LocalRetentionDays)
	}

	// Validate UpdateChannel (must be stable, beta, or test)
	validChannels := map[string]bool{"stable": true, "beta": true, "test": true, "": true}
	if !validChannels[config.UpdateChannel] {
		return fmt.Errorf("UpdateChannel must be 'stable', 'beta', or 'test' (got: %s)", config.UpdateChannel)
	}

	return nil
}

// mapToConfig converts map back to Configuration struct
// Version 3.0: Removed CloudPath, EnforceHTTPS, InsecureTLS
func mapToConfig(data map[string]interface{}, config *Configuration) error {
	// Helper to safely get values with type checking
	getString := func(key string, defaultVal string) string {
		if v, ok := data[key]; ok {
			if s, ok := v.(string); ok {
				return s
			}
		}
		return defaultVal
	}

	getBool := func(key string, defaultVal bool) bool {
		if v, ok := data[key]; ok {
			if b, ok := v.(bool); ok {
				return b
			}
		}
		return defaultVal
	}

	getInt := func(key string, defaultVal int) int {
		if v, ok := data[key]; ok {
			// Handle both int and float64 (JSON unmarshals numbers as float64)
			switch val := v.(type) {
			case int:
				return val
			case float64:
				// Use math.Round to properly round instead of truncating
				return int(math.Round(val))
			}
		}
		return defaultVal
	}

	// Map all fields (v3.0 - 16 fields, no CloudPath/EnforceHTTPS/InsecureTLS)
	config.ModemAddress = getString("ModemAddress", config.ModemAddress)
	config.IgnitePassword = getString("IgnitePassword", config.IgnitePassword)
	config.SpeedTestEnabled = getBool("SpeedTestEnabled", config.SpeedTestEnabled)
	config.SpeedTestInterval = getInt("SpeedTestInterval", config.SpeedTestInterval)
	config.SpeedTestConnections = getInt("SpeedTestConnections", config.SpeedTestConnections)
	config.PingCount = getInt("PingCount", config.PingCount)
	config.AutoUpdateEnabled = getBool("AutoUpdateEnabled", config.AutoUpdateEnabled)
	config.UpdateChannel = getString("UpdateChannel", config.UpdateChannel)
	config.Silent = getBool("Silent", config.Silent)
	config.NoLogs = getBool("NoLogs", config.NoLogs)
	config.LocalCleanupEnabled = getBool("LocalCleanupEnabled", config.LocalCleanupEnabled)
	config.LocalRetentionDays = getInt("LocalRetentionDays", config.LocalRetentionDays)
	config.EnableCloud = getBool("EnableCloud", config.EnableCloud)
	config.CloudHost = getString("CloudHost", config.CloudHost)
	config.CloudPort = getString("CloudPort", config.CloudPort)
	// Note: CloudAPIKey is intentionally NOT synced from server.
	// The API key is a client-side authentication credential and must not be
	// overwritable by the server to prevent credential hijacking attacks.

	// Validate ranges after mapping server values
	if err := validateConfigRanges(config); err != nil {
		return fmt.Errorf("invalid server config: %w", err)
	}

	return nil
}

// SyncConfig syncs client configuration with the server
// modemID is optional - used for tracking metadata only, not as part of lookup key
// Returns true if config was changed (client should save), false otherwise
//
// Version 3.0: Simplified state model
// - Status: unmanaged, managed, locked
// - SyncStatus: n/a, pending, active
// - Single-track versioning (1, 2, 3...)
func SyncConfig(config *Configuration, modemID string, state *ConfigState) (bool, error) {
	// Check if cloud is enabled
	if !config.EnableCloud {
		return false, fmt.Errorf("cloud sync disabled")
	}

	// Build sync URL (HTTPS by default, configurable for testing)
	syncURL := fmt.Sprintf("%s://%s:%s/api/config/sync", configSyncURLScheme, config.CloudHost, config.CloudPort)

	// Convert config to map
	configMap := configToMap(config)

	// Calculate config hash
	configHash, err := calculateConfigHash(configMap)
	if err != nil {
		return false, fmt.Errorf("failed to calculate config hash: %w", err)
	}

	// Generate nonce
	nonce, err := generateNonce()
	if err != nil {
		return false, fmt.Errorf("failed to generate nonce: %w", err)
	}

	// Get current timestamp
	timestamp := time.Now().UTC().Format(time.RFC3339)

	// Generate signature
	signature := generateConfigSyncSignature(config.CloudAPIKey, timestamp, nonce, configHash)

	// Build request (modem_id is optional tracking metadata)
	syncRequest := ConfigSyncRequest{
		APIKey:     config.CloudAPIKey,
		ModemID:    modemID, // Optional - for tracking only
		Config:     configMap,
		Version:    state.Version, // Simple int version
		ConfigHash: configHash,
		Timestamp:  timestamp,
		Nonce:      nonce,
		Signature:  signature,
	}

	// Marshal request — api_key is intentionally included; it's the client's own auth credential sent over HTTPS
	requestBody, err := json.Marshal(syncRequest) // #nosec G117 -- api_key is the client's own credential, not a hardcoded secret; transmitted over HTTPS
	if err != nil {
		return false, fmt.Errorf("failed to marshal sync request: %w", err)
	}

	// Create HTTP request
	req, err := http.NewRequest("POST", syncURL, bytes.NewBuffer(requestBody))
	if err != nil {
		return false, fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")

	// Send request using shared HTTP client
	resp, err := configSyncHTTPClient.Do(req) // #nosec G704 -- URL is user-configured cloud server endpoint, SSRF is by design
	if err != nil {
		return false, fmt.Errorf("failed to send sync request: %w", err)
	}
	defer resp.Body.Close()

	// Read response
	responseBody, err := io.ReadAll(io.LimitReader(resp.Body, MaxResponseSize))
	if err != nil {
		return false, fmt.Errorf("failed to read response: %w", err)
	}

	// Check status code
	if resp.StatusCode != http.StatusOK {
		var errorResp map[string]interface{}
		if err := json.Unmarshal(responseBody, &errorResp); err == nil {
			if errObj, ok := errorResp["error"].(map[string]interface{}); ok {
				if msg, ok := errObj["message"].(string); ok {
					return false, fmt.Errorf("sync failed: %s (HTTP %d)", msg, resp.StatusCode)
				}
			}
		}
		return false, fmt.Errorf("sync failed with HTTP %d: %s", resp.StatusCode, string(responseBody))
	}

	// Parse response
	var syncResponse ConfigSyncResponse
	if err := json.Unmarshal(responseBody, &syncResponse); err != nil {
		return false, fmt.Errorf("failed to parse sync response: %w", err)
	}

	// Validate server timestamp to prevent replay attacks
	if syncResponse.ServerTimestamp != "" {
		serverTime, err := time.Parse(time.RFC3339, syncResponse.ServerTimestamp)
		if err != nil {
			return false, fmt.Errorf("invalid server timestamp format: %w", err)
		}
		timeDiff := time.Since(serverTime)
		// Allow 5-minute clock skew in either direction
		if timeDiff < -5*time.Minute || timeDiff > 5*time.Minute {
			return false, fmt.Errorf("server timestamp outside acceptable range (clock skew: %v)", timeDiff)
		}
	}

	if !syncResponse.Success {
		if syncResponse.Error != nil {
			return false, fmt.Errorf("sync failed: %s", syncResponse.Error.Message)
		}
		return false, fmt.Errorf("sync failed: unknown error")
	}

	// Check if config changed
	configChanged := syncResponse.ConfigChanged

	// Update state with simplified versioning (v3.0)
	state.Version = syncResponse.Version
	state.Status = syncResponse.Status
	state.SyncStatus = syncResponse.SyncStatus
	state.ServerConfigHash = syncResponse.ConfigHash
	state.LastSync = time.Now()

	// Apply server config if:
	// 1. Status is "locked" - server always controls config
	// 2. Status is "managed" AND config changed - server pushed new config
	isLocked := syncResponse.Status == "locked"
	isManaged := syncResponse.Status == "managed"
	shouldApplyConfig := isLocked || (isManaged && configChanged)

	if shouldApplyConfig {
		// Apply server config to our config struct
		if err := mapToConfig(syncResponse.Config, config); err != nil {
			return false, fmt.Errorf("failed to apply server config: %w", err)
		}

		// Update state hash to match what we just applied
		state.ServerConfigHash = syncResponse.ConfigHash

		return true, nil // Config was changed
	}

	return false, nil // Config was not changed
}

// SyncWithRetry attempts to sync config with automatic retries
// Version 3.0: Simplified - removed failover server support
func SyncWithRetry(config *Configuration, modemID string, state *ConfigState, maxRetries int) (bool, error) {
	var lastErr error

	for attempt := 0; attempt < maxRetries; attempt++ {
		if attempt > 0 {
			// Exponential backoff: 1s, 2s, 4s (capped at 8s for safety)
			shift := attempt - 1
			if shift < 0 {
				shift = 0
			}
			if shift > 3 {
				shift = 3 // Cap at 8 seconds max
			}
			backoff := time.Duration(1<<shift) * time.Second
			time.Sleep(backoff)
		}

		configChanged, err := SyncConfig(config, modemID, state)
		if err == nil {
			return configChanged, nil
		}

		lastErr = err

		// Check if it's a non-retryable error
		if strings.Contains(err.Error(), "locked") {
			// Config is locked by server - not retryable
			return false, lastErr
		}
		if strings.Contains(err.Error(), "nonce") {
			// Nonce replay - not retryable (would need new nonce)
			return false, lastErr
		}

		// If this is a network error, retry
		if !isNetworkError(err) {
			// Non-network error, don't retry
			return false, lastErr
		}
	}

	return false, fmt.Errorf("sync failed after %d retries: %w", maxRetries, lastErr)
}

// isNetworkError checks if an error is a network-related error
func isNetworkError(err error) bool {
	if err == nil {
		return false
	}
	errStr := err.Error()
	return strings.Contains(errStr, "connection refused") ||
		strings.Contains(errStr, "no such host") ||
		strings.Contains(errStr, "timeout") ||
		strings.Contains(errStr, "network") ||
		strings.Contains(errStr, "dial") ||
		strings.Contains(errStr, "EOF")
}
