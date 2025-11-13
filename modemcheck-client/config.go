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

	// File size limits
	MaxFileUploadSize = 10 * 1024 * 1024 // 10MB
)

// Configuration holds all user-configurable settings.
type Configuration struct {
	ModemAddress        string
	IgnitePassword      string
	SpeedTestEnabled    bool   // Enable speed tests (default: true)
	SpeedTestInterval   int    // Run speed test every N runs (default: 1)
	AutoUpdateEnabled   bool   // Enable automatic updates (default: true)
	UpdateChannel       string // Update channel: "stable" (default), "beta", or "test" for pre-releases
	Silent              bool   // Suppress console output
	NoLogs              bool   // Disable log file creation
	LocalCleanupEnabled bool   // Enable automatic cleanup of old local files (default: true)
	LocalRetentionDays  int    // Days to retain local files (default: 90)
	// Cloud mode settings
	EnableCloud bool   // Enable cloud upload (always saves locally)
	CloudHost   string // Cloud server hostname or IP
	CloudPort   string // Cloud server port
	CloudAPIKey string // API key for authentication
	CloudPath   string // Cloud storage path
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

// SpeedTestState tracks speed test execution history.
type SpeedTestState struct {
	RunCount        int    `json:"run_count"`         // Total number of runs
	LastSpeedTest   int    `json:"last_speed_test"`   // Run number of last speed test attempt
	LastTestSuccess bool   `json:"last_test_success"` // Whether last speed test succeeded
	StateFilePath   string `json:"-"`                 // Path to state file (not serialized)
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
			// File doesn't exist, return default state
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

// SaveSpeedTestState saves the speed test state to a JSON file.
func (s *SpeedTestState) Save() error {
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

	return nil
}
