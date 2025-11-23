package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

// Constants for configuration and limits.
const (
	// Queue configuration
	MaxQueueSize    = 100
	QueueMaxAgeDays = 14

	// Log configuration
	LogMaxAgeDays = 30

	// HTTP timeouts
	DefaultHTTPTimeout = 10 * time.Second
	SpeedTestTimeout   = 60 * time.Second
	PingTimeout        = 30 * time.Second

	// Test configuration
	DefaultPingCount = 25

	// Network limits
	MaxHostnameLength = 253 // RFC 1035 DNS hostname max length

	// File size limits
	MaxFileUploadSize      = 10 * 1024 * 1024  // 10MB
	MaxResponseSize        = 2 * 1024 * 1024   // 2MB
	MaxBinaryDownloadSize  = 100 * 1024 * 1024 // 100MB
)

// Configuration holds all user-configurable settings.
type Configuration struct {
	ModemAddress        string
	IgnitePassword      string
	SpeedTestEnabled    bool   // Enable speed tests (default: true)
	SpeedTestInterval   int    // Run speed test every N runs (default: 1)
	PingCount           int    // Number of pings to perform (default: 25)
	AutoUpdateEnabled   bool   // Enable automatic updates (default: true)
	UpdateChannel       string // Update channel: "stable" (default), "beta", or "test" for pre-releases
	Silent              bool   // Suppress console output
	NoLogs              bool   // Disable log file creation
	LocalCleanupEnabled bool   // Enable automatic cleanup of old local files (default: true)
	LocalRetentionDays  int    // Days to retain local files (default: 90)
	// Cloud mode settings
	EnableCloud  bool   // Enable cloud upload (always saves locally)
	CloudHost    string // Cloud server hostname or IP
	CloudPort    string // Cloud server port
	CloudAPIKey  string // API key for authentication
	CloudPath    string // Cloud storage path
	EnforceHTTPS bool   // Always use HTTPS, reject HTTP connections (default: true)
	InsecureTLS  bool   // Allow self-signed/invalid certificates for local dev (default: false)
}

// LoadConfigFile loads configuration from a JSON file and validates required settings.
func LoadConfigFile(path string, config *Configuration) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("failed to read config file: %w", err)
	}

	if err := json.Unmarshal(data, config); err != nil {
		return fmt.Errorf("failed to parse config file: %w", err)
	}

	// Set defaults for new fields if not specified
	if config.SpeedTestInterval == 0 {
		config.SpeedTestInterval = 1 // Default: run every time
	}
	if config.SpeedTestInterval < 1 {
		return fmt.Errorf("SpeedTestInterval must be at least 1")
	}

	if config.PingCount == 0 {
		config.PingCount = DefaultPingCount // Default: 25 pings
	}
	if config.PingCount < 1 || config.PingCount > 100 {
		return fmt.Errorf("PingCount must be between 1 and 100 (got: %d)", config.PingCount)
	}

	if config.LocalRetentionDays == 0 {
		config.LocalRetentionDays = 90 // Default: 90 days
	}
	if config.LocalRetentionDays < 1 {
		return fmt.Errorf("LocalRetentionDays must be at least 1")
	}

	// Set default update channel if not specified
	if config.UpdateChannel == "" {
		config.UpdateChannel = "stable" // Default: stable releases only
	}
	// Validate update channel
	validChannels := map[string]bool{"stable": true, "beta": true, "test": true}
	if !validChannels[config.UpdateChannel] {
		return fmt.Errorf("UpdateChannel must be 'stable', 'beta', or 'test' (got: %s)", config.UpdateChannel)
	}

	// Validate critical configuration
	if config.EnableCloud {
		if config.CloudHost == "" {
			return fmt.Errorf("CloudHost is required when EnableCloud is true")
		}
		if config.CloudAPIKey == "" {
			return fmt.Errorf("CloudAPIKey is required when EnableCloud is true")
		}
	}

	return nil
}

// LastSuccessfulModem tracks the most recently successful modem detection.
type LastSuccessfulModem struct {
	ModemType       string `json:"modem_type"`
	ModemMAC        string `json:"modem_mac"`
	LastSuccessTime int64  `json:"last_success_time"`
	ModemAddress    string `json:"modem_address"`
	StateFilePath   string `json:"-"` // Path to state file (not serialized)
}

// LoadLastSuccessfulModem loads the last successful modem state from executable directory.
func LoadLastSuccessfulModem() (*LastSuccessfulModem, error) {
	exePath, err := os.Executable()
	if err != nil {
		return nil, fmt.Errorf("failed to get executable path: %w", err)
	}
	exeDir := filepath.Dir(exePath)
	stateFile := filepath.Join(exeDir, "last_successful_modem.json")

	state := &LastSuccessfulModem{
		StateFilePath: stateFile,
	}

	data, err := os.ReadFile(stateFile)
	if err != nil {
		if os.IsNotExist(err) {
			// File doesn't exist, return empty state
			return state, nil
		}
		return nil, fmt.Errorf("failed to read state file: %w", err)
	}

	if err := json.Unmarshal(data, state); err != nil {
		return nil, fmt.Errorf("failed to parse state file: %w", err)
	}

	state.StateFilePath = stateFile
	return state, nil
}

// SaveLastSuccessfulModem saves the last successful modem state to executable directory.
func SaveLastSuccessfulModem(modemType, modemMAC, modemAddress string) error {
	exePath, err := os.Executable()
	if err != nil {
		return fmt.Errorf("failed to get executable path: %w", err)
	}
	exeDir := filepath.Dir(exePath)
	stateFile := filepath.Join(exeDir, "last_successful_modem.json")

	state := &LastSuccessfulModem{
		ModemType:       modemType,
		ModemMAC:        modemMAC,
		LastSuccessTime: time.Now().Unix(),
		ModemAddress:    modemAddress,
	}

	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal state: %w", err)
	}

	if err := os.WriteFile(stateFile, data, 0644); err != nil {
		return fmt.Errorf("failed to write state file: %w", err)
	}

	return nil
}

// IPInfoCache stores cached IP/ASN information to reduce API calls
type IPInfoCache struct {
	PublicIP  string    `json:"public_ip"`
	ASN       string    `json:"asn"`
	ISPName   string    `json:"isp_name"`
	IPCity    string    `json:"ip_city"`
	IPCountry string    `json:"ip_country"`
	Timestamp time.Time `json:"timestamp"`
}

// LoadIPInfoCache loads cached IP info from executable directory
func LoadIPInfoCache() (*IPInfoCache, error) {
	exePath, err := os.Executable()
	if err != nil {
		return nil, fmt.Errorf("failed to get executable path: %w", err)
	}
	exeDir := filepath.Dir(exePath)
	cacheFile := filepath.Join(exeDir, ".ip_info_cache.json")

	data, err := os.ReadFile(cacheFile)
	if err != nil {
		if os.IsNotExist(err) {
			// File doesn't exist, return nil (no cache)
			return nil, nil
		}
		return nil, fmt.Errorf("failed to read cache file: %w", err)
	}

	var cache IPInfoCache
	if err := json.Unmarshal(data, &cache); err != nil {
		return nil, fmt.Errorf("failed to parse cache file: %w", err)
	}

	// Check if cache is older than 24 hours
	if time.Since(cache.Timestamp) > 24*time.Hour {
		// Cache is too old, return nil to force refresh
		return nil, nil
	}

	return &cache, nil
}

// SaveIPInfoCache saves IP info cache to executable directory
func SaveIPInfoCache(publicIP, asn, ispName, ipCity, ipCountry string) error {
	exePath, err := os.Executable()
	if err != nil {
		return fmt.Errorf("failed to get executable path: %w", err)
	}
	exeDir := filepath.Dir(exePath)
	cacheFile := filepath.Join(exeDir, ".ip_info_cache.json")

	cache := IPInfoCache{
		PublicIP:  publicIP,
		ASN:       asn,
		ISPName:   ispName,
		IPCity:    ipCity,
		IPCountry: ipCountry,
		Timestamp: time.Now(),
	}

	data, err := json.MarshalIndent(cache, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal cache: %w", err)
	}

	if err := os.WriteFile(cacheFile, data, 0644); err != nil {
		return fmt.Errorf("failed to write cache file: %w", err)
	}

	return nil
}

// SpeedTestState tracks speed test execution history.
type SpeedTestState struct {
	RunCount        int    `json:"run_count"`         // Total number of runs
	LastSpeedTest   int    `json:"last_speed_test"`   // Run number of last speed test attempt
	LastTestSuccess bool   `json:"last_test_success"` // Whether last speed test succeeded
	StateFilePath   string `json:"-"`                 // Path to state file (not serialized)
	previousHash    string // Hash of previous state for change detection (not serialized)
}

// LoadSpeedTestState loads the speed test state from a JSON file.
func LoadSpeedTestState(stateDir string) (*SpeedTestState, error) {
	stateFile := filepath.Join(stateDir, "speedtest_state.json")
	state := &SpeedTestState{
		RunCount:        0,
		LastSpeedTest:   0,
		LastTestSuccess: true, // Assume success initially to follow normal interval
		StateFilePath:   stateFile,
	}

	data, err := os.ReadFile(stateFile)
	if err != nil {
		if os.IsNotExist(err) {
			// File doesn't exist, return default state with hash
			state.previousHash = state.computeHash()
			return state, nil
		}
		return nil, fmt.Errorf("failed to read state file: %w", err)
	}

	if err := json.Unmarshal(data, state); err != nil {
		return nil, fmt.Errorf("failed to parse state file: %w", err)
	}

	state.StateFilePath = stateFile
	// Store hash of loaded state for change detection
	state.previousHash = state.computeHash()
	return state, nil
}

// computeHash computes a simple hash of the state for change detection.
func (s *SpeedTestState) computeHash() string {
	return fmt.Sprintf("%d:%d:%t", s.RunCount, s.LastSpeedTest, s.LastTestSuccess)
}

// SaveSpeedTestState saves the speed test state to a JSON file.
// Performance: Only writes to disk if state has changed, avoiding unnecessary I/O.
func (s *SpeedTestState) Save() error {
	// Check if state has changed (avoid unnecessary disk I/O)
	currentHash := s.computeHash()
	if currentHash == s.previousHash {
		// State unchanged, skip write
		return nil
	}

	// Ensure directory exists
	dir := filepath.Dir(s.StateFilePath)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return fmt.Errorf("failed to create state directory: %w", err)
	}

	data, err := json.MarshalIndent(s, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal state: %w", err)
	}

	if err := os.WriteFile(s.StateFilePath, data, 0644); err != nil {
		return fmt.Errorf("failed to write state file: %w", err)
	}

	// Update hash after successful write
	s.previousHash = currentHash
	return nil
}
