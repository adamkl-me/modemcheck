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
	"net/http"
	"sort"
	"strings"
	"time"
)

// Shared HTTP client for config sync operations to avoid repeated TLS handshakes
// and improve performance. This client is reused across PreflightCheck and SyncConfig calls.
var configSyncHTTPClient = &http.Client{
	Timeout: 30 * time.Second,
	Transport: &http.Transport{
		DisableKeepAlives:   false,
		MaxIdleConns:        10,
		MaxIdleConnsPerHost: 5,
		IdleConnTimeout:     90 * time.Second,
	},
}

// PreflightRequest represents the request payload for pre-flight API key validation
type PreflightRequest struct {
	APIKey    string `json:"api_key"`
	Timestamp string `json:"timestamp"` // ISO 8601
	Nonce     string `json:"nonce"`     // SHA256 hex
	Signature string `json:"signature"` // HMAC-SHA256 of "{timestamp}|{nonce}"
}

// PreflightResponse represents the server response for pre-flight check
type PreflightResponse struct {
	Success           bool                   `json:"success"`
	APIKeyValid       bool                   `json:"api_key_valid"`
	HasExistingConfig bool                   `json:"has_existing_config"`
	Status            string                 `json:"status,omitempty"` // Config status if exists (6 states)
	Config            map[string]interface{} `json:"config,omitempty"` // Enforced config to apply (if any)
	ServerTimestamp   string                 `json:"server_timestamp"`
	Error             *ErrorResponse         `json:"error,omitempty"`
}

// ConfigSyncRequest represents the request payload for config sync
type ConfigSyncRequest struct {
	APIKey     string                 `json:"api_key"`
	ModemID    string                 `json:"modem_id,omitempty"` // Optional - for tracking metadata only
	Config     map[string]interface{} `json:"config"`
	Version    string                 `json:"version,omitempty"` // e.g., "v1_client" or empty for first sync
	ConfigHash string                 `json:"config_hash"`       // SHA256 of canonical JSON
	Timestamp  string                 `json:"timestamp"`         // ISO 8601
	Nonce      string                 `json:"nonce"`             // SHA256 hex
	Signature  string                 `json:"signature"`         // HMAC-SHA256 of "{timestamp}|{nonce}|{config_hash}"
}

// ConfigSyncResponse represents the server response with dual-track versioning
type ConfigSyncResponse struct {
	Success         bool                   `json:"success"`
	Config          map[string]interface{} `json:"config"`
	Version         string                 `json:"version"`          // e.g., "v1_server" or "v2_client"
	Status          string                 `json:"status"`           // 6 status states
	ConfigHash      string                 `json:"config_hash"`
	ServerTimestamp string                 `json:"server_timestamp"`
	ConfigChanged   bool                   `json:"config_changed"`
	ActiveTrack     string                 `json:"active_track"`     // "client" or "server"
	ClientVersion   int                    `json:"client_version"`   // Latest v#_client number
	ServerVersion   int                    `json:"server_version"`   // Latest v#_server number
	Error           *ErrorResponse         `json:"error,omitempty"`  // If success=false
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

// generatePreflightSignature creates HMAC-SHA256 signature for preflight check
// Message format: timestamp|nonce (no modem_id - not known yet)
func generatePreflightSignature(apiKey, timestamp, nonce string) string {
	message := fmt.Sprintf("%s|%s", timestamp, nonce)

	mac := hmac.New(sha256.New, []byte(apiKey))
	mac.Write([]byte(message))
	signature := hex.EncodeToString(mac.Sum(nil))

	return signature
}

// generateConfigSyncSignature creates HMAC-SHA256 signature for config sync
// Message format: timestamp|nonce|config_hash (no modem_id - API key is the primary key)
func generateConfigSyncSignature(apiKey, timestamp, nonce, configHash string) string {
	message := fmt.Sprintf("%s|%s|%s", timestamp, nonce, configHash)

	mac := hmac.New(sha256.New, []byte(apiKey))
	mac.Write([]byte(message))
	signature := hex.EncodeToString(mac.Sum(nil))

	return signature
}

// configToMap converts Configuration struct to map for JSON serialization
func configToMap(config *Configuration) map[string]interface{} {
	return map[string]interface{}{
		"ModemAddress":        config.ModemAddress,
		"IgnitePassword":      config.IgnitePassword,
		"SpeedTestEnabled":    config.SpeedTestEnabled,
		"SpeedTestInterval":   config.SpeedTestInterval,
		"PingCount":           config.PingCount,
		"AutoUpdateEnabled":   config.AutoUpdateEnabled,
		"UpdateChannel":       config.UpdateChannel,
		"Silent":              config.Silent,
		"NoLogs":              config.NoLogs,
		"LocalCleanupEnabled": config.LocalCleanupEnabled,
		"LocalRetentionDays":  config.LocalRetentionDays,
		"EnableCloud":         config.EnableCloud,
		"CloudHost":           config.CloudHost,
		"CloudPort":           config.CloudPort,
		"CloudAPIKey":         config.CloudAPIKey,
		"CloudPath":           config.CloudPath,
		"EnforceHTTPS":        config.EnforceHTTPS,
		"InsecureTLS":         config.InsecureTLS,
	}
}

// mapToConfig converts map back to Configuration struct
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
				return int(val)
			}
		}
		return defaultVal
	}

	// Map all fields
	config.ModemAddress = getString("ModemAddress", config.ModemAddress)
	config.IgnitePassword = getString("IgnitePassword", config.IgnitePassword)
	config.SpeedTestEnabled = getBool("SpeedTestEnabled", config.SpeedTestEnabled)
	config.SpeedTestInterval = getInt("SpeedTestInterval", config.SpeedTestInterval)
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
	config.CloudAPIKey = getString("CloudAPIKey", config.CloudAPIKey)
	config.CloudPath = getString("CloudPath", config.CloudPath)
	config.EnforceHTTPS = getBool("EnforceHTTPS", config.EnforceHTTPS)
	config.InsecureTLS = getBool("InsecureTLS", config.InsecureTLS)

	return nil
}

// PreflightCheck validates API key and checks for pending enforced config BEFORE modem login.
// This allows faster failure for invalid keys and pre-application of enforced configs.
// Returns: (apiKeyValid, hasEnforcedConfig, preflightResponse, error)
func PreflightCheck(config *Configuration) (bool, bool, *PreflightResponse, error) {
	// Check if cloud is enabled
	if !config.EnableCloud {
		return false, false, nil, fmt.Errorf("cloud sync disabled")
	}

	if config.CloudAPIKey == "" {
		return false, false, nil, fmt.Errorf("no API key configured")
	}

	// Build preflight URL (always HTTPS for security)
	scheme := "https"
	preflightURL := fmt.Sprintf("%s://%s:%s/api/config/preflight", scheme, config.CloudHost, config.CloudPort)

	// Generate nonce
	nonce, err := generateNonce()
	if err != nil {
		return false, false, nil, fmt.Errorf("failed to generate nonce: %w", err)
	}

	// Get current timestamp
	timestamp := time.Now().UTC().Format(time.RFC3339)

	// Generate signature (no modem_id in preflight)
	signature := generatePreflightSignature(config.CloudAPIKey, timestamp, nonce)

	// Build request
	preflightRequest := PreflightRequest{
		APIKey:    config.CloudAPIKey,
		Timestamp: timestamp,
		Nonce:     nonce,
		Signature: signature,
	}

	// Marshal request
	requestBody, err := json.Marshal(preflightRequest)
	if err != nil {
		return false, false, nil, fmt.Errorf("failed to marshal preflight request: %w", err)
	}

	// Create HTTP request
	req, err := http.NewRequest("POST", preflightURL, bytes.NewBuffer(requestBody))
	if err != nil {
		return false, false, nil, fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")

	// Send request using shared HTTP client
	resp, err := configSyncHTTPClient.Do(req)
	if err != nil {
		return false, false, nil, fmt.Errorf("failed to send preflight request: %w", err)
	}
	defer resp.Body.Close()

	// Read response
	responseBody, err := io.ReadAll(io.LimitReader(resp.Body, MaxResponseSize))
	if err != nil {
		return false, false, nil, fmt.Errorf("failed to read response: %w", err)
	}

	// Parse response
	var preflightResponse PreflightResponse
	if err := json.Unmarshal(responseBody, &preflightResponse); err != nil {
		return false, false, nil, fmt.Errorf("failed to parse preflight response: %w", err)
	}

	// Check if API key is valid
	if !preflightResponse.APIKeyValid {
		return false, false, &preflightResponse, nil
	}

	// Check if there's an enforced config to apply
	hasEnforcedConfig := false
	if preflightResponse.HasExistingConfig && preflightResponse.Config != nil {
		status := preflightResponse.Status
		if status == "enforced_ready" || status == "enforced_active" {
			hasEnforcedConfig = true
		}
	}

	return true, hasEnforcedConfig, &preflightResponse, nil
}

// SyncConfig syncs client configuration with the server
// modemID is optional - used for tracking metadata only, not as part of lookup key
// Returns true if config was changed (client should save), false otherwise
func SyncConfig(config *Configuration, modemID string, state *ConfigState) (bool, error) {
	// Check if cloud is enabled
	if !config.EnableCloud {
		return false, fmt.Errorf("cloud sync disabled")
	}

	// Build sync URL (always HTTPS for security)
	scheme := "https"
	syncURL := fmt.Sprintf("%s://%s:%s/api/config/sync", scheme, config.CloudHost, config.CloudPort)

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

	// Generate signature (no modem_id in signature - API key is the primary key)
	signature := generateConfigSyncSignature(config.CloudAPIKey, timestamp, nonce, configHash)

	// Build request (modem_id is optional tracking metadata)
	syncRequest := ConfigSyncRequest{
		APIKey:     config.CloudAPIKey,
		ModemID:    modemID, // Optional - for tracking only
		Config:     configMap,
		Version:    state.Version,
		ConfigHash: configHash,
		Timestamp:  timestamp,
		Nonce:      nonce,
		Signature:  signature,
	}

	// Marshal request
	requestBody, err := json.Marshal(syncRequest)
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
	resp, err := configSyncHTTPClient.Do(req)
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

	if !syncResponse.Success {
		if syncResponse.Error != nil {
			return false, fmt.Errorf("sync failed: %s", syncResponse.Error.Message)
		}
		return false, fmt.Errorf("sync failed: unknown error")
	}

	// Check if config changed
	configChanged := syncResponse.ConfigChanged

	// Update state with dual-track versioning info
	state.Version = syncResponse.Version
	state.Status = syncResponse.Status
	state.ActiveTrack = syncResponse.ActiveTrack
	state.ClientVersion = syncResponse.ClientVersion
	state.ServerVersion = syncResponse.ServerVersion
	state.ServerConfigHash = syncResponse.ConfigHash
	state.LastSync = time.Now()

	// Clear deprecated Mode field
	state.Mode = ""

	// If config changed or in enforced status, apply server config
	isEnforced := syncResponse.Status == "enforced_ready" || syncResponse.Status == "enforced_active"
	if isEnforced || configChanged {
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

// SyncWithRetry attempts to sync config with automatic retries and failover support
// Tries primary server first, then failover servers if configured
func SyncWithRetry(config *Configuration, modemID string, state *ConfigState, maxRetries int) (bool, error) {
	var lastErr error

	// Build list of servers to try (primary + failovers)
	servers := []struct {
		host string
		port string
	}{
		{host: config.CloudHost, port: config.CloudPort}, // Primary server
	}

	// Add failover servers if configured
	for i := range config.FailoverHosts {
		servers = append(servers, struct {
			host string
			port string
		}{
			host: config.FailoverHosts[i],
			port: config.FailoverPorts[i],
		})
	}

	// Try each server with retries
	for serverIdx, server := range servers {
		serverName := server.host
		if serverIdx == 0 {
			serverName = server.host + " (primary)"
		} else {
			serverName = server.host + fmt.Sprintf(" (failover %d)", serverIdx)
		}

		for attempt := 0; attempt < maxRetries; attempt++ {
			if attempt > 0 {
				// Exponential backoff: 1s, 2s, 4s
				backoff := time.Duration(1<<uint(attempt-1)) * time.Second
				time.Sleep(backoff)
			}

			// Temporarily override config with current server
			origHost := config.CloudHost
			origPort := config.CloudPort
			config.CloudHost = server.host
			config.CloudPort = server.port

			configChanged, err := SyncConfig(config, modemID, state)

			// Restore original config
			config.CloudHost = origHost
			config.CloudPort = origPort

			if err == nil {
				// Success! Return immediately
				return configChanged, nil
			}

			lastErr = fmt.Errorf("server %s: %w", serverName, err)

			// Check if it's a non-retryable error
			if strings.Contains(err.Error(), "locked") {
				// Config is locked by server - not retryable
				return false, lastErr
			}
			if strings.Contains(err.Error(), "nonce") {
				// Nonce replay - not retryable (would need new nonce)
				return false, lastErr
			}

			// If this is a network error, try next server immediately (don't retry same server)
			if isNetworkError(err) {
				break // Move to next server
			}
		}
	}

	return false, fmt.Errorf("sync failed after trying %d server(s) with %d retries: %w", len(servers), maxRetries, lastErr)
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
