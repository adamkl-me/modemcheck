package main

import (
	"encoding/json"
	"fmt"
	"os"
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
	ModemAddress      string
	IgnitePassword    string
	SpeedTestEnabled  bool   // Enable speed tests (default: true)
	AutoUpdateEnabled bool   // Enable automatic updates (default: true)
	Silent            bool   // Suppress console output
	NoLogs            bool   // Disable log file creation
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
