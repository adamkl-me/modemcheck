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
	"time"

	"modemcheck-client/scraper"
)

// Version is set via ldflags at build time (see Makefile)
var Version = "dev"

// ModemCheck represents the main application state
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

// NewModemCheck creates a new ModemCheck instance
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

// Log writes to both stdout and log file
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

// InitLogFile initializes the log file
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

// AutoDetectModem scans common addresses for modems
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

// createScraper creates the appropriate scraper based on modem type
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

// Run executes the main modem check workflow
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

	// Detect modem
	if m.config.ModemAddress == "autodetect" {
		if err := m.AutoDetectModem(); err != nil {
			m.Log(err.Error())
			return err
		}
	} else {
		m.modemAddress = m.config.ModemAddress
		m.Log(fmt.Sprintf("Using configured modem address: %s", m.modemAddress))
		m.Log("Attempting to detect modem model...")
		m.modemType = scraper.DetectModem(m.modemAddress, m.client)
		if m.modemType == "Unknown" {
			return fmt.Errorf("modem model not detected at %s", m.modemAddress)
		}
		m.Log(fmt.Sprintf("Modem model detected: %s", m.modemType))
	}

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

	// Create output directory
	m.Log("Creating folder to store check results")

	// Always store locally in ModemCheck-Results subdirectory
	baseDir := filepath.Join(filepath.Dir(os.Args[0]), "ModemCheck-Results")
	m.checkDir = filepath.Join(baseDir, fmt.Sprintf("%s-%s", m.modemType, m.modemMAC))
	os.MkdirAll(m.checkDir, 0755)
	m.checkFile = filepath.Join(m.checkDir, m.checkTimeString+".json")

	// Collect data
	m.Log("Collecting modem diagnostic data")
	data, err := m.modemScraper.GetData(m.checkTime)
	if err != nil {
		return err
	}

	// Add client version and platform information
	data.ClientVersion = Version
	data.ClientOS = runtime.GOOS
	data.ClientArch = runtime.GOARCH

	// Save data
	jsonData, _ := json.MarshalIndent(data, "", "  ")
	if err := os.WriteFile(m.checkFile, jsonData, 0644); err != nil {
		return err
	}
	m.Log(fmt.Sprintf("Modem data collected and saved to %s", m.checkFile))

	// Clear FEC
	m.Log("Clearing FEC counters")
	m.modemScraper.ClearFEC()

	// Ping tests (run before speed tests)
	m.RunPingTests(data)

	// Speed tests (run after ping tests)
	m.RunSpeedTests(data)

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
	// Command-line flags
	modemAddress := flag.String("address", "autodetect", "Modem IP address or 'autodetect'")
	xfinityPassword := flag.String("xfinitypassword", "password", "Password for Rogers Xfinity modems")
	speedTestEnabled := flag.Bool("speedtest", true, "Enable speed tests using public servers (default: true)")
	noUpdate := flag.Bool("noupdate", false, "Disable automatic updates (default: false, updates enabled)")
	silent := flag.Bool("silent", false, "Suppress output to terminal")
	noLogs := flag.Bool("nologs", false, "Disable log file creation")
	enableCloud := flag.Bool("enablecloud", false, "Enable cloud upload (always saves locally)")
	configFile := flag.String("config", "", "Path to configuration file (optional)")

	flag.Parse()

	config := Configuration{
		ModemAddress:      *modemAddress,
		IgnitePassword:    *xfinityPassword,
		SpeedTestEnabled:  *speedTestEnabled,
		AutoUpdateEnabled: !*noUpdate, // Auto-update enabled by default
		Silent:            *silent,
		NoLogs:            *noLogs,
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
