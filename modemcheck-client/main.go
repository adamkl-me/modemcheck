package main

import (
	"bufio"
	"crypto/tls"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"net/http/cookiejar"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"time"

	"modemcheck-client/scraper"
)

// Version is set via ldflags at build time (see Makefile)
var Version = "dev"

// ModemCheck represents the main application state.
type ModemCheck struct {
	config          Configuration
	configFilePath  string // Path to configuration file for atomic saves
	client          *http.Client
	modemScraper    scraper.ModemScraper
	modemType       string
	modemAddress    string
	modemMAC        string
	checkTime       int64  // Unix epoch timestamp
	checkTimeString string // Formatted string for filenames
	checkDir        string
	checkFile       string
	logFile         *os.File
	logMutex        sync.Mutex // Protects concurrent access to logFile
}

// NewModemCheck creates a new ModemCheck instance.
// Returns an error if initialization fails (e.g., cookie jar creation).
func NewModemCheck(config Configuration, configFilePath string) (*ModemCheck, error) {
	// Create HTTP client with secure TLS configuration (v3.0+: always enforce TLS)
	jar, err := cookiejar.New(nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create cookie jar: %w", err)
	}
	tlsConfig := &tls.Config{
		InsecureSkipVerify: false, // Always verify TLS certificates (v3.0+)
	}
	transport := &http.Transport{
		TLSClientConfig: tlsConfig,
	}
	client := &http.Client{
		Transport: transport,
		Jar:       jar,
		Timeout:   DefaultHTTPTimeout,
	}

	now := time.Now()
	return &ModemCheck{
		config:          config,
		configFilePath:  configFilePath,
		client:          client,
		checkTime:       now.Unix(),
		checkTimeString: now.Format("2006-01-02_15-04-05"),
	}, nil
}

// VerifyUpdateSuccess checks if a previous update succeeded and clears the lock if so.
// If the update failed (current version doesn't match the expected version in the lock),
// it will attempt to automatically rollback to the previous working version.
func (m *ModemCheck) VerifyUpdateSuccess() {
	exePath, err := os.Executable()
	if err != nil {
		return
	}

	// Normalize executable path to prevent .old chaining
	exePath = normalizeExecutablePath(exePath)

	exeDir := filepath.Dir(exePath)
	lockPath := filepath.Join(exeDir, ".update_lock")

	data, err := os.ReadFile(lockPath)
	if err != nil {
		// No lock file exists - no recent update to verify
		return
	}

	var lock struct {
		Version   string    `json:"version"`
		Timestamp time.Time `json:"timestamp"`
	}

	if err := json.Unmarshal(data, &lock); err != nil {
		// Invalid lock file, remove it
		os.Remove(lockPath)
		return
	}

	// Remove 'v' prefix for comparison
	lockVersion := strings.TrimPrefix(lock.Version, "v")
	currentVersion := strings.TrimPrefix(Version, "v")

	// If current version is >= lock version, the update succeeded
	if currentVersion >= lockVersion {
		// Update was successful, remove lock
		os.Remove(lockPath)
		if !m.config.Silent {
			fmt.Printf("✓ Successfully verified update to v%s\n", lock.Version)
		}

		// Clean up old backup file if update succeeded
		backupFile := exePath + ".old"
		if _, err := os.Stat(backupFile); err == nil {
			os.Remove(backupFile)
		}
		return
	}

	// If we get here, the update failed (current version < lock version)
	// This means an update was attempted but we're still running an older version
	m.Log(fmt.Sprintf("⚠ Update to v%s appears to have failed (currently running v%s)", lock.Version, currentVersion))

	// Check if there's a backup available for rollback
	backupFile := exePath + ".old"
	if _, err := os.Stat(backupFile); err == nil {
		m.Log("Attempting automatic rollback to previous version...")

		// Perform rollback
		if err := m.RollbackUpdate(); err != nil {
			m.Log(fmt.Sprintf("Automatic rollback failed: %v", err))
			m.Log("Manual intervention may be required")
		} else {
			m.Log("✓ Rollback successful, restarting with previous version...")

			// Restart the process with the rolled-back version
			if err := RestartProcess(); err != nil {
				m.Log(fmt.Sprintf("Failed to restart after rollback: %v", err))
				m.Log("Please restart manually")
			}
			// If restart succeeds, this line won't be reached
		}
	} else {
		// No backup available, just clear the lock and continue
		m.Log("No backup available for rollback, continuing with current version")
		os.Remove(lockPath)
	}
}

// Log writes to both stdout and log file.
func (m *ModemCheck) Log(message string) {
	timestamp := time.Now().Format("Mon Jan 2 03:04:05 PM MST 2006")
	logMessage := fmt.Sprintf("%s: %s\n", timestamp, message)

	// Print to stdout unless silent mode is enabled
	if !m.config.Silent {
		fmt.Print(logMessage)
	}

	// Write to log file unless NoLogs is enabled (protected by mutex for concurrent access)
	if m.logFile != nil && !m.config.NoLogs {
		m.logMutex.Lock()
		defer m.logMutex.Unlock() // Ensure lock is released even if WriteString panics
		m.logFile.WriteString(logMessage)
	}
}

// CleanupOldFiles removes JSON files older than the configured retention period.
func (m *ModemCheck) CleanupOldFiles(baseDir string) {
	m.Log(fmt.Sprintf("Performing local file cleanup (retention: %d days)", m.config.LocalRetentionDays))

	cutoffTime := time.Now().AddDate(0, 0, -m.config.LocalRetentionDays)
	deletedCount := 0
	totalSize := int64(0)

	// Walk through all modem directories
	err := filepath.Walk(baseDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return nil // Skip files that can't be accessed
		}

		// Only process JSON files
		if !info.IsDir() && strings.HasSuffix(info.Name(), ".json") {
			// Skip state files
			if info.Name() == "speedtest_state.json" || info.Name() == "upload_queue.json" {
				return nil
			}

			// Parse date from filename (format: YYYY-MM-DD_HH-MM-SS.json)
			fileDate, err := time.Parse("2006-01-02_15-04-05.json", info.Name())
			if err != nil {
				// If we can't parse the date, check file modification time instead
				if info.ModTime().Before(cutoffTime) {
					m.Log(fmt.Sprintf("Deleting old file (by mod time): %s", info.Name()))
					if err := os.Remove(path); err == nil {
						deletedCount++
						totalSize += info.Size()
					}
				}
				return nil
			}

			// Delete if older than retention period
			if fileDate.Before(cutoffTime) {
				m.Log(fmt.Sprintf("Deleting old file: %s (age: %d days)",
					info.Name(), int(time.Since(fileDate).Hours()/24)))
				if err := os.Remove(path); err == nil {
					deletedCount++
					totalSize += info.Size()
				}
			}
		}

		return nil
	})

	if err != nil {
		m.Log(fmt.Sprintf("Warning: Error during cleanup: %v", err))
	}

	if deletedCount > 0 {
		m.Log(fmt.Sprintf("Cleanup complete: deleted %d files (%.2f MB freed)",
			deletedCount, float64(totalSize)/(1024*1024)))
	} else {
		m.Log("Cleanup complete: no files to delete")
	}
}

// InitLogFile initializes the log file.
func (m *ModemCheck) InitLogFile() error {
	// Skip log file creation if NoLogs is enabled
	if m.config.NoLogs {
		return nil
	}

	logPath := filepath.Join(filepath.Dir(os.Args[0]), "modem-check_logs.txt")
	file, err := os.OpenFile(logPath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	m.logFile = file
	return nil
}

// AutoDetectModem scans common modem addresses and detects the first supported modem found.
func (m *ModemCheck) AutoDetectModem() error {
	m.Log("Autodetect enabled. Scanning common modem addresses...")

	commonAddresses := []string{"192.168.100.1", "192.168.0.1", "10.0.0.1", "172.20.0.1"}

	for _, address := range commonAddresses {
		m.Log(fmt.Sprintf("Checking %s...", address))
		detected := scraper.DetectModem(address, m.client)

		if detected != "Unknown" {
			m.modemAddress = address
			m.modemType = detected
			m.Log(fmt.Sprintf("Modem detected at %s: %s", m.modemAddress, m.modemType))
			return nil
		}
	}

	return fmt.Errorf("no supported modem found at any common address. Tried: %v", commonAddresses)
}

// createScraper creates the appropriate scraper instance based on the detected modem type.
func (m *ModemCheck) createScraper() error {
	switch m.modemType {
	case "CODA45", "CODA56":
		m.modemScraper = scraper.NewCODAScraper(m.client, m.modemAddress, m.modemType, m)
	case "DM1000":
		m.modemScraper = scraper.NewDM1000Scraper(m.client, m.modemAddress, m)
	case "Xfinity", "Xfinity-XB7", "Xfinity-XB8", "XB7", "XB8":
		m.modemScraper = scraper.NewXfinityScraper(m.client, m.modemAddress, m.config.IgnitePassword, m)
	default:
		return fmt.Errorf("unsupported modem type: %s", m.modemType)
	}
	return nil
}

// Run executes the main modem check workflow including detection, login, data collection,
// diagnostics, and optional cloud upload.
func (m *ModemCheck) Run() error {
	// Initialize log file
	if err := m.InitLogFile(); err != nil {
		return err
	}
	if m.logFile != nil {
		defer m.logFile.Close()
	}

	m.Log(fmt.Sprintf("Modem check script (v%s) started at %s", Version, m.checkTimeString))

	// Clean up old log entries (30 days)
	if !m.config.NoLogs {
		if err := m.cleanupLogFile(); err != nil {
			m.Log(fmt.Sprintf("Warning: Failed to cleanup log file: %v", err))
		}
	}

	// Load upload queue
	queue, err := loadUploadQueue()
	if err != nil {
		m.Log(fmt.Sprintf("Warning: Failed to load upload queue: %v", err))
		queue = &UploadQueue{FailedUploads: []UploadQueueEntry{}}
	}

	// Clean up old queue entries
	cleanupUploadQueue(queue)

	// Retry failed uploads first (before modem detection for faster feedback)
	if m.config.EnableCloud {
		m.retryFailedUploads(queue)
	}

	// EARLY CONFIG SYNC: Sync config BEFORE modem detection
	// This allows server-pushed configs to control modem detection behavior
	// modem_id will be empty - server tracks via upload later
	if m.config.EnableCloud && m.config.CloudAPIKey != "" {
		m.Log("Performing configuration sync with server...")

		// Load config state (per-API-key, not per-modem)
		state, err := LoadConfigState()
		if err != nil {
			state = &ConfigState{}
		}

		// Sync with empty modem_id - server uses API key as primary key
		// modem_id will be populated on upload after successful modem detection
		configChanged, err := SyncWithRetry(&m.config, "", state, 3)
		if err != nil {
			m.Log(fmt.Sprintf("Warning: Config sync failed: %v", err))
			m.Log("Continuing with local configuration")
		} else {
			// Save state after successful sync
			if err := SaveConfigState(state); err != nil {
				m.Log(fmt.Sprintf("Warning: Failed to save config state: %v", err))
			}

			if configChanged {
				m.Log("✓ Configuration updated from server")

				// Save updated config atomically
				if m.configFilePath != "" {
					if err := SaveConfigurationAtomic(&m.config, m.configFilePath); err != nil {
						m.Log(fmt.Sprintf("ERROR: Failed to save updated configuration: %v", err))
					} else {
						m.Log("Configuration saved successfully")

						// If in enforced status, notify user
						if state.Status == "enforced_ready" || state.Status == "enforced_active" {
							m.Log("⚠ Configuration is ENFORCED by server - local changes will be overwritten")
						}
					}
				}
			} else {
				m.Log("✓ Configuration is up to date with server")
			}
		}
	}

	// Load last successful modem state
	lastSuccessful, _ := LoadLastSuccessfulModem()

	// Detect modem
	detectionFailed := false

	if m.config.ModemAddress == "autodetect" {
		if err := m.AutoDetectModem(); err != nil {
			m.Log(err.Error())
			detectionFailed = true
		}
	} else {
		m.modemAddress = m.config.ModemAddress
		m.Log(fmt.Sprintf("Using configured modem address: %s", m.modemAddress))
		m.Log("Attempting to detect modem model...")
		m.modemType = scraper.DetectModem(m.modemAddress, m.client)
		if m.modemType == "Unknown" {
			m.Log(fmt.Sprintf("Modem model not detected at %s", m.modemAddress))
			detectionFailed = true
		} else {
			m.Log(fmt.Sprintf("Modem model detected: %s", m.modemType))
		}
	}

	// Handle detection failure
	if detectionFailed {
		if lastSuccessful != nil && lastSuccessful.ModemType != "" {
			m.Log("Modem detection failed, but using last successful modem for diagnostics")
			m.modemType = lastSuccessful.ModemType
			m.modemMAC = lastSuccessful.ModemMAC
			m.modemAddress = lastSuccessful.ModemAddress
		} else {
			// Exit gracefully - config sync already succeeded (if enabled)
			// Next run will have the synced configuration
			m.Log("Modem detection failed and no previous successful modem found")
			if m.config.EnableCloud {
				m.Log("Configuration was synced successfully - next run will use the synced config")
			}
			m.Log("Exiting - please ensure modem is accessible and try again")
			return nil // Exit gracefully, not an error
		}
	} else {
		// Create appropriate scraper
		if err := m.createScraper(); err != nil {
			return err
		}

		// Login
		m.Log("Logging in to modem")
		if err := m.modemScraper.Login(); err != nil {
			return err
		}

		// Update modem type (may be more specific after login, e.g., Xfinity -> XB8)
		m.modemType = m.modemScraper.GetModemType()

		// Get MAC
		m.Log("Getting modem MAC address")
		mac, err := m.modemScraper.GetMAC()
		if err != nil {
			return err
		}
		m.modemMAC = mac

		// Save successful detection
		if err := SaveLastSuccessfulModem(m.modemType, m.modemMAC, m.modemAddress); err != nil {
			m.Log(fmt.Sprintf("Warning: Failed to save last successful modem: %v", err))
		}
	}

	// Create output directory
	m.Log("Creating folder to store check results")

	// Always store locally in ModemCheck-Results subdirectory
	baseDir := filepath.Join(filepath.Dir(os.Args[0]), "ModemCheck-Results")
	m.checkDir = filepath.Join(baseDir, fmt.Sprintf("%s-%s", m.modemType, m.modemMAC))
	os.MkdirAll(m.checkDir, 0755)
	m.checkFile = filepath.Join(m.checkDir, m.checkTimeString+".json")

	// Load speed test state
	speedTestState, err := LoadSpeedTestState(m.checkDir)
	if err != nil {
		m.Log(fmt.Sprintf("Warning: Failed to load speed test state: %v", err))
		// Continue with default state
		speedTestState = &SpeedTestState{
			RunCount:        0,
			LastSpeedTest:   0,
			LastTestSuccess: true,
			StateFilePath:   filepath.Join(m.checkDir, "speedtest_state.json"),
		}
	}

	// Increment run count
	speedTestState.RunCount++
	m.Log(fmt.Sprintf("Run count: %d", speedTestState.RunCount))

	// Perform local file cleanup if enabled
	if m.config.LocalCleanupEnabled {
		m.CleanupOldFiles(baseDir)
	}

	// Collect data
	var data *scraper.ModemData
	if detectionFailed {
		// Create empty ModemData with detection_failed status
		m.Log("Creating diagnostic check with failed detection status")
		data = &scraper.ModemData{
			SysInfo: scraper.SysInfo{
				SysTime:         0,
				Firmware:        "",
				Uptime:          0,
				ModemType:       m.modemType,
				ModemMAC:        m.modemMAC,
				CheckTime:       m.checkTime,
				DetectionStatus: "detection_failed",
			},
			RX:       []scraper.RXChannel{},
			RXOFDM:   []scraper.RXOFDMChannel{},
			TX:       []scraper.TXChannel{},
			TXOFDM:   []scraper.TXOFDMAChannel{},
			EventLog: []scraper.EventLog{},
		}
	} else {
		m.Log("Collecting modem diagnostic data")
		var err error
		data, err = m.modemScraper.GetData(m.checkTime)
		if err != nil {
			return err
		}
		data.SysInfo.DetectionStatus = "success"

		// Clear FEC after collecting data
		m.Log("Clearing FEC counters")
		m.modemScraper.ClearFEC()
	}

	// Add client version and platform information
	data.ClientVersion = Version
	data.ClientOS = runtime.GOOS
	data.ClientArch = runtime.GOARCH

	// Get public IP and network information
	m.GetPublicIPInfo(data)

	// Save data
	jsonData, err := json.MarshalIndent(data, "", "  ")
	if err != nil {
		m.Log(fmt.Sprintf("ERROR: Failed to marshal modem data to JSON: %v", err))
		return fmt.Errorf("failed to marshal modem data to JSON: %w", err)
	}
	if err := os.WriteFile(m.checkFile, jsonData, 0644); err != nil {
		m.Log(fmt.Sprintf("ERROR: Failed to write modem data to file: %v", err))
		return fmt.Errorf("failed to write modem data to file: %w", err)
	}
	m.Log(fmt.Sprintf("Modem data collected and saved to %s", m.checkFile))

	// Ping tests (run before speed tests)
	m.RunPingTests(data)

	// Speed tests (run after ping tests) - returns success status
	speedTestSuccess := m.RunSpeedTests(data, speedTestState)
	speedTestState.LastTestSuccess = speedTestSuccess

	// Save speed test state
	if err := speedTestState.Save(); err != nil {
		m.Log(fmt.Sprintf("Warning: Failed to save speed test state: %v", err))
	}

	// Save updated data with ping and speed test results
	m.Log(fmt.Sprintf("Adding test results to %s", m.checkFile))
	jsonData, err = json.MarshalIndent(data, "", "  ")
	if err != nil {
		m.Log(fmt.Sprintf("ERROR: Failed to marshal test results to JSON: %v", err))
		return fmt.Errorf("failed to marshal test results: %w", err)
	}
	if err := os.WriteFile(m.checkFile, jsonData, 0644); err != nil {
		m.Log(fmt.Sprintf("ERROR: Failed to write test results to file: %v", err))
		return fmt.Errorf("failed to write test results: %w", err)
	}

	// Upload to cloud if enabled
	if m.config.EnableCloud {
		if err := m.UploadToCloud(m.checkFile, m.modemType, m.modemMAC); err != nil {
			m.Log(fmt.Sprintf("Cloud upload failed: %v", err))

			// Add to upload queue for retry
			modemID := fmt.Sprintf("%s-%s", m.modemType, m.modemMAC)
			entry := UploadQueueEntry{
				FilePath:  m.checkFile,
				ModemID:   modemID,
				Timestamp: m.checkTimeString,
				LastError: err.Error(),
			}
			addToUploadQueue(queue, entry)

			// Save updated queue
			if err := saveUploadQueue(queue); err != nil {
				m.Log(fmt.Sprintf("Warning: Failed to save upload queue: %v", err))
			} else {
				m.Log("Added to upload queue for retry on next run")
			}
		} else {
			m.Log("Cloud upload successful!")
		}
	}

	// Save queue even if cloud is disabled (to persist any cleanup/retries)
	if err := saveUploadQueue(queue); err != nil {
		m.Log(fmt.Sprintf("Warning: Failed to save upload queue: %v", err))
	}

	m.Log("All done! See you next time.")
	return nil
}

func main() {
	// Custom usage function
	flag.Usage = func() {
		fmt.Fprintf(os.Stderr, "Modem Check v%s - Cable modem diagnostic tool\n\n", Version)
		fmt.Fprintf(os.Stderr, "Usage: %s [options]\n\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "Command-Line Flags:\n")
		fmt.Fprintf(os.Stderr, "  -a, --address <ip>        Modem IP address or hostname (default: autodetect)\n")
		fmt.Fprintf(os.Stderr, "  -c, --config <file>       Path to JSON configuration file\n")
		fmt.Fprintf(os.Stderr, "  -s, --server <host>       Cloud server hostname/IP (enables cloud mode)\n")
		fmt.Fprintf(os.Stderr, "  -p, --port <port>         Cloud server port (default: 443)\n")
		fmt.Fprintf(os.Stderr, "  -k, --apikey <key>        API key for cloud mode\n")
		fmt.Fprintf(os.Stderr, "  -q, --quiet               Suppress terminal output (default: false)\n")
		fmt.Fprintf(os.Stderr, "  -l, --nologs              Disable log file creation (default: false)\n")
		fmt.Fprintf(os.Stderr, "  -x, --xfinitypassword     Password for Xfinity modems\n")
		fmt.Fprintf(os.Stderr, "  -n, --nospeedtest         Disable speed tests (default: false)\n")
		fmt.Fprintf(os.Stderr, "      --version             Print version and exit\n")
		fmt.Fprintf(os.Stderr, "\nConfiguration File Options (use with -c config.json):\n")
		fmt.Fprintf(os.Stderr, "  ModemAddress          Modem IP address or 'autodetect'\n")
		fmt.Fprintf(os.Stderr, "  IgnitePassword        Password for Rogers Xfinity modems\n")
		fmt.Fprintf(os.Stderr, "  SpeedTestEnabled      Enable/disable speed tests (default: true)\n")
		fmt.Fprintf(os.Stderr, "  SpeedTestInterval     Run speed test every N runs (default: 1)\n")
		fmt.Fprintf(os.Stderr, "  PingCount             Number of pings to perform (default: 100, max: 100)\n")
		fmt.Fprintf(os.Stderr, "  AutoUpdateEnabled     Enable/disable automatic updates (default: true)\n")
		fmt.Fprintf(os.Stderr, "  Silent                Suppress console output (default: false)\n")
		fmt.Fprintf(os.Stderr, "  NoLogs                Disable log file creation (default: false)\n")
		fmt.Fprintf(os.Stderr, "  LocalCleanupEnabled   Enable automatic cleanup of old files (default: true)\n")
		fmt.Fprintf(os.Stderr, "  LocalRetentionDays    Days to retain local files (default: 90)\n")
		fmt.Fprintf(os.Stderr, "  EnableCloud           Enable cloud upload (default: false)\n")
		fmt.Fprintf(os.Stderr, "  CloudHost             Cloud server hostname or IP\n")
		fmt.Fprintf(os.Stderr, "  CloudPort             Cloud server port (default: 22557)\n")
		fmt.Fprintf(os.Stderr, "  CloudAPIKey           API key for cloud authentication\n")
		fmt.Fprintf(os.Stderr, "  EnforceHTTPS          Always use HTTPS for uploads (default: true for security)\n")
		fmt.Fprintf(os.Stderr, "  InsecureTLS           Allow self-signed certs for local dev (default: false)\n")
		fmt.Fprintf(os.Stderr, "\nExamples:\n")
		fmt.Fprintf(os.Stderr, "  %s                                 # Auto-detect modem\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "  %s -a 192.168.100.1                # Specify modem IP\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "  %s -c config.json                  # Use config file\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "  %s -q -l -n                        # Quiet, no logs, no speed test\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "  %s -x mypassword                   # Xfinity modem with password\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "  %s -s api.example.com -k KEY       # Cloud mode bootstrap\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "\nFor more information, visit: https://github.com/adamkl-me/modemcheck\n")
	}

	// Command-line flags - new simplified set
	modemAddress := flag.String("a", "autodetect", "Modem IP address or hostname")
	flag.StringVar(modemAddress, "address", "autodetect", "Modem IP address or hostname")

	configFile := flag.String("c", "", "Path to JSON config file")
	flag.StringVar(configFile, "config", "", "Path to JSON config file")

	// Cloud mode flags
	cloudServer := flag.String("s", "", "Cloud server hostname/IP (enables cloud mode)")
	flag.StringVar(cloudServer, "server", "", "Cloud server hostname/IP (enables cloud mode)")

	cloudPort := flag.String("p", "443", "Cloud server port")
	flag.StringVar(cloudPort, "port", "443", "Cloud server port")

	cloudAPIKey := flag.String("k", "", "API key for cloud mode")
	flag.StringVar(cloudAPIKey, "apikey", "", "API key for cloud mode")

	quiet := flag.Bool("q", false, "Suppress terminal output")
	flag.BoolVar(quiet, "quiet", false, "Suppress terminal output")

	noLogs := flag.Bool("l", false, "Disable log file creation")
	flag.BoolVar(noLogs, "nologs", false, "Disable log file creation")

	xfinityPassword := flag.String("x", "", "Password for Xfinity modems")
	flag.StringVar(xfinityPassword, "xfinitypassword", "", "Password for Xfinity modems")

	noSpeedTest := flag.Bool("n", false, "Disable speed tests")
	flag.BoolVar(noSpeedTest, "nospeedtest", false, "Disable speed tests")

	version := flag.Bool("version", false, "Print version and exit")

	flag.Parse()

	// Handle version flag
	if *version {
		fmt.Printf("Modem Check v%s\n", Version)
		os.Exit(0)
	}

	config := Configuration{
		ModemAddress:        *modemAddress,
		IgnitePassword:      "",     // Will be set below if provided
		SpeedTestEnabled:    !*noSpeedTest, // Speed tests enabled by default
		SpeedTestInterval:   1,      // Default: run every time
		PingCount:           DefaultPingCount, // Default: 25 pings
		AutoUpdateEnabled:   true,   // Auto-update enabled by default
		UpdateChannel:       "stable", // Default: stable releases only
		Silent:              *quiet,
		NoLogs:              *noLogs,
		LocalCleanupEnabled: true, // Default: cleanup enabled
		LocalRetentionDays:  90,   // Default: 90 days
		// Cloud settings default to disabled, loaded from config file if provided
		EnableCloud: false,
		CloudHost:   "",
		CloudPort:   "",
		CloudAPIKey: "",
	}

	// Only set the password if provided via command line
	if *xfinityPassword != "" {
		config.IgnitePassword = *xfinityPassword
	}

	// Determine config file path
	var configPath string
	if *configFile != "" {
		// User specified a config file
		configPath = *configFile
	} else {
		// Check for config.json in the same directory as the executable
		exePath, err := os.Executable()
		if err == nil {
			exeDir := filepath.Dir(exePath)
			defaultConfigPath := filepath.Join(exeDir, "config.json")
			if _, err := os.Stat(defaultConfigPath); err == nil {
				configPath = defaultConfigPath
				log.Printf("Found config.json in executable directory: %s", configPath)
			}
		}
	}

	// Load config file if found or specified
	if configPath != "" {
		if err := LoadConfigFile(configPath, &config); err != nil {
			log.Printf("Warning: Failed to load config file: %v", err)
			log.Printf("Continuing with default configuration...")
			// config already has defaults from flag.Parse()
		}
	}

	// Cloud flags override config.json values
	// Enable cloud mode if either -s or -k is provided, prompting for the missing value
	if *cloudServer != "" || *cloudAPIKey != "" {
		reader := bufio.NewReader(os.Stdin)

		// Get server (from flag or prompt)
		server := *cloudServer
		if server == "" {
			fmt.Print("Enter cloud server hostname: ")
			input, err := reader.ReadString('\n')
			if err != nil {
				log.Printf("Warning: failed to read server hostname: %v", err)
			} else {
				server = strings.TrimSpace(input)
			}
		}

		// Get API key (from flag or prompt)
		apiKey := *cloudAPIKey
		if apiKey == "" {
			fmt.Print("Enter API key: ")
			input, err := reader.ReadString('\n')
			if err != nil {
				log.Printf("Warning: failed to read API key: %v", err)
			} else {
				apiKey = strings.TrimSpace(input)
			}
		}

		if server != "" && apiKey != "" {
			config.EnableCloud = true
			config.CloudHost = server
			config.CloudPort = *cloudPort
			config.CloudAPIKey = apiKey
			log.Printf("Cloud mode enabled: %s:%s", config.CloudHost, config.CloudPort)

			// Set default config path for saving synced config if not already set
			// This allows bootstrap mode to save the server-pushed config for future runs
			if configPath == "" {
				exePath, err := os.Executable()
				if err == nil {
					exeDir := filepath.Dir(exePath)
					configPath = filepath.Join(exeDir, "config.json")
					log.Printf("Config will be saved to: %s", configPath)
				}
			}
		} else {
			log.Printf("Warning: Missing server or API key, cloud mode disabled")
		}
	}

	// Create and run modem check
	modemCheck, err := NewModemCheck(config, configPath)
	if err != nil {
		log.Printf("Error: Failed to initialize: %v", err)
		os.Exit(1)
	}

	// Check if a previous update was successful and clear the lock if needed
	if config.AutoUpdateEnabled {
		modemCheck.VerifyUpdateSuccess()
	}

	// Check for updates before running the modem check
	if config.AutoUpdateEnabled {
		if updateAvailable, newVersion, downloadURL := modemCheck.CheckForUpdates(); updateAvailable {
			if err := modemCheck.DownloadAndApplyUpdate(downloadURL, newVersion); err != nil {
				modemCheck.Log(fmt.Sprintf("Failed to apply update: %v", err))
				modemCheck.Log("Continuing with current version...")
			} else {
				// Update successful, restart with new version
				if err := RestartProcess(); err != nil {
					modemCheck.Log(fmt.Sprintf("Failed to restart: %v", err))
					modemCheck.Log("Please restart manually to use the new version")
				}
				// If restart succeeds, this line won't be reached
				return
			}
		}
	}

	if err := modemCheck.Run(); err != nil {
		log.Printf("Error: %v", err)
		os.Exit(1)
	}
}
