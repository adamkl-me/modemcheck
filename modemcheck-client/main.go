package main

import (
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
	"time"

	"modemcheck-client/scraper"
)

// Version is set via ldflags at build time (see Makefile)
var Version = "dev"

// ModemCheck represents the main application state.
type ModemCheck struct {
	config          Configuration
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
}

// NewModemCheck creates a new ModemCheck instance.
func NewModemCheck(config Configuration) *ModemCheck {
	// Create HTTP client with custom transport (ignore SSL errors)
	jar, _ := cookiejar.New(nil)
	transport := &http.Transport{
		TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
	}
	client := &http.Client{
		Transport: transport,
		Jar:       jar,
		Timeout:   DefaultHTTPTimeout,
	}

	now := time.Now()
	return &ModemCheck{
		config:          config,
		client:          client,
		checkTime:       now.Unix(),
		checkTimeString: now.Format("2006-01-02_15-04-05"),
	}
}

// VerifyUpdateSuccess checks if a previous update succeeded and clears the lock if so.
func (m *ModemCheck) VerifyUpdateSuccess() {
	exePath, err := os.Executable()
	if err != nil {
		return
	}
	exeDir := filepath.Dir(exePath)
	lockPath := filepath.Join(exeDir, ".update_lock")

	data, err := os.ReadFile(lockPath)
	if err != nil {
		// No lock file exists
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
			fmt.Printf("Successfully verified update to v%s\n", lock.Version)
		}
	}
	// If current version < lock version, keep the lock (update failed)
}

// Log writes to both stdout and log file.
func (m *ModemCheck) Log(message string) {
	timestamp := time.Now().Format("Mon Jan 2 03:04:05 PM MST 2006")
	logMessage := fmt.Sprintf("%s: %s\n", timestamp, message)

	// Print to stdout unless silent mode is enabled
	if !m.config.Silent {
		fmt.Print(logMessage)
	}

	// Write to log file unless NoLogs is enabled
	if m.logFile != nil && !m.config.NoLogs {
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

	// Load last successful modem state
	lastSuccessful, _ := LoadLastSuccessfulModem()

	// Detect modem
	detectionFailed := false
	var detectionErr error

	if m.config.ModemAddress == "autodetect" {
		if err := m.AutoDetectModem(); err != nil {
			m.Log(err.Error())
			detectionErr = err
			detectionFailed = true
		}
	} else {
		m.modemAddress = m.config.ModemAddress
		m.Log(fmt.Sprintf("Using configured modem address: %s", m.modemAddress))
		m.Log("Attempting to detect modem model...")
		m.modemType = scraper.DetectModem(m.modemAddress, m.client)
		if m.modemType == "Unknown" {
			detectionErr = fmt.Errorf("modem model not detected at %s", m.modemAddress)
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
			m.Log("Modem detection failed and no previous successful modem found")
			return detectionErr
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
	jsonData, _ := json.MarshalIndent(data, "", "  ")
	if err := os.WriteFile(m.checkFile, jsonData, 0644); err != nil {
		return err
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
	jsonData, _ = json.MarshalIndent(data, "", "  ")
	os.WriteFile(m.checkFile, jsonData, 0644)

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
		fmt.Fprintf(os.Stderr, "Command-Line Options:\n")
		flag.PrintDefaults()
		fmt.Fprintf(os.Stderr, "\nConfiguration File Options (use with -config):\n")
		fmt.Fprintf(os.Stderr, "  ModemAddress          Modem IP address or 'autodetect'\n")
		fmt.Fprintf(os.Stderr, "  IgnitePassword        Password for Rogers Xfinity modems\n")
		fmt.Fprintf(os.Stderr, "  SpeedTestEnabled      Enable/disable speed tests (default: true)\n")
		fmt.Fprintf(os.Stderr, "  SpeedTestInterval     Run speed test every N runs (default: 1)\n")
		fmt.Fprintf(os.Stderr, "  AutoUpdateEnabled     Enable/disable automatic updates (default: true)\n")
		fmt.Fprintf(os.Stderr, "  Silent                Suppress console output (default: false)\n")
		fmt.Fprintf(os.Stderr, "  NoLogs                Disable log file creation (default: false)\n")
		fmt.Fprintf(os.Stderr, "  LocalCleanupEnabled   Enable automatic cleanup of old files (default: true)\n")
		fmt.Fprintf(os.Stderr, "  LocalRetentionDays    Days to retain local files (default: 90)\n")
		fmt.Fprintf(os.Stderr, "  EnableCloud           Enable cloud upload (default: false)\n")
		fmt.Fprintf(os.Stderr, "  CloudHost             Cloud server hostname or IP\n")
		fmt.Fprintf(os.Stderr, "  CloudPort             Cloud server port (default: 22557)\n")
		fmt.Fprintf(os.Stderr, "  CloudAPIKey           API key for cloud authentication\n")
		fmt.Fprintf(os.Stderr, "\nExamples:\n")
		fmt.Fprintf(os.Stderr, "  %s                                    # Auto-detect modem\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "  %s -address 192.168.100.1            # Specify modem IP\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "  %s -config config.json               # Use config file\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "  %s -silent -nologs -noupdate         # Silent mode for cron\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "\nFor more information, visit: https://github.com/adamkl-me/modemcheck\n")
	}

	// Command-line flags
	modemAddress := flag.String("address", "autodetect", "Modem IP address or 'autodetect'")
	xfinityPassword := flag.String("xfinitypassword", "password", "Password for Rogers Xfinity modems")
	speedTestEnabled := flag.Bool("speedtest", true, "Enable speed tests using public servers")
	noUpdate := flag.Bool("noupdate", false, "Disable automatic updates")
	silent := flag.Bool("silent", false, "Suppress output to terminal")
	noLogs := flag.Bool("nologs", false, "Disable log file creation")
	enableCloud := flag.Bool("enablecloud", false, "Enable cloud upload (always saves locally)")
	configFile := flag.String("config", "", "Path to configuration file")

	flag.Parse()

	config := Configuration{
		ModemAddress:        *modemAddress,
		IgnitePassword:      *xfinityPassword,
		SpeedTestEnabled:    *speedTestEnabled,
		SpeedTestInterval:   1,     // Default: run every time
		AutoUpdateEnabled:   !*noUpdate, // Auto-update enabled by default
		Silent:              *silent,
		NoLogs:              *noLogs,
		LocalCleanupEnabled: true,  // Default: cleanup enabled
		LocalRetentionDays:  90,    // Default: 90 days
		// Cloud settings default to disabled, loaded from config file if provided
		EnableCloud: *enableCloud,
		CloudHost:   "",
		CloudPort:   "",
		CloudAPIKey: "",
		CloudPath:   "",
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
			log.Fatalf("Error loading config file: %v", err)
		}
	}

	// Create and run modem check
	modemCheck := NewModemCheck(config)

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
		log.Fatalf("Error: %v", err)
	}
}
