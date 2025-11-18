package main

import (
	"bufio"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// UploadQueueEntry represents a failed upload that needs to be retried.
type UploadQueueEntry struct {
	FilePath     string    `json:"file_path"`
	ModemID      string    `json:"modem_id"`
	Timestamp    string    `json:"timestamp"`
	Attempts     int       `json:"attempts"`
	LastAttempt  time.Time `json:"last_attempt"`
	LastError    string    `json:"last_error"`
	FirstFailure time.Time `json:"first_failure"`
}

// UploadQueue manages failed uploads.
type UploadQueue struct {
	FailedUploads []UploadQueueEntry `json:"failed_uploads"`
}

// generateRequestSignature creates an HMAC-SHA256 signature for API request authentication.
// This prevents replay attacks and ensures request integrity.
// Format: HMAC-SHA256(api_key, timestamp + modem_id + filename + checksum)
func generateRequestSignature(apiKey, timestamp, modemID, filename, checksum string) string {
	// Construct message to sign: timestamp|modem_id|filename|checksum
	message := fmt.Sprintf("%s|%s|%s|%s", timestamp, modemID, filename, checksum)

	// Create HMAC-SHA256 signature
	mac := hmac.New(sha256.New, []byte(apiKey))
	mac.Write([]byte(message))
	signature := hex.EncodeToString(mac.Sum(nil))

	return signature
}

const queueFilePath = "ModemCheck-Results/.upload_queue.json"

// loadUploadQueue loads the upload queue from disk.
// Returns an empty queue if the file doesn't exist.
func loadUploadQueue() (*UploadQueue, error) {
	queue := &UploadQueue{FailedUploads: []UploadQueueEntry{}}

	data, err := os.ReadFile(queueFilePath)
	if err != nil {
		if os.IsNotExist(err) {
			return queue, nil // Return empty queue if file doesn't exist
		}
		return nil, err
	}

	if err := json.Unmarshal(data, queue); err != nil {
		return nil, err
	}

	return queue, nil
}

// saveUploadQueue saves the upload queue to disk.
func saveUploadQueue(queue *UploadQueue) error {
	// Ensure directory exists
	dir := filepath.Dir(queueFilePath)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return err
	}

	data, err := json.MarshalIndent(queue, "", "  ")
	if err != nil {
		return err
	}

	return os.WriteFile(queueFilePath, data, 0644)
}

// addToUploadQueue adds a failed upload to the queue or updates an existing entry.
// Enforces the maximum queue size by removing oldest entries when exceeded.
func addToUploadQueue(queue *UploadQueue, entry UploadQueueEntry) {
	// Check if entry already exists
	for i, existing := range queue.FailedUploads {
		if existing.FilePath == entry.FilePath {
			// Update existing entry
			queue.FailedUploads[i].Attempts++
			queue.FailedUploads[i].LastAttempt = time.Now()
			queue.FailedUploads[i].LastError = entry.LastError
			return
		}
	}

	// Add new entry
	entry.Attempts = 1
	entry.FirstFailure = time.Now()
	entry.LastAttempt = time.Now()
	queue.FailedUploads = append(queue.FailedUploads, entry)

	// Enforce max queue size (remove oldest entries)
	if len(queue.FailedUploads) > MaxQueueSize {
		queue.FailedUploads = queue.FailedUploads[len(queue.FailedUploads)-MaxQueueSize:]
	}
}

// removeFromUploadQueue removes an entry from the queue by file path.
func removeFromUploadQueue(queue *UploadQueue, filePath string) {
	for i, entry := range queue.FailedUploads {
		if entry.FilePath == filePath {
			queue.FailedUploads = append(queue.FailedUploads[:i], queue.FailedUploads[i+1:]...)
			return
		}
	}
}

// cleanupUploadQueue removes entries older than QueueMaxAgeDays and entries
// for files that no longer exist on disk.
func cleanupUploadQueue(queue *UploadQueue) {
	cutoffDate := time.Now().AddDate(0, 0, -QueueMaxAgeDays)
	cleaned := []UploadQueueEntry{}

	for _, entry := range queue.FailedUploads {
		// Remove entries older than cutoff date
		if entry.FirstFailure.Before(cutoffDate) {
			continue
		}

		// Remove entries where file no longer exists
		if _, err := os.Stat(entry.FilePath); os.IsNotExist(err) {
			continue
		}

		cleaned = append(cleaned, entry)
	}

	queue.FailedUploads = cleaned
}

// uploadToCloudWithModemID uploads a file to the cloud server with a specific modem ID.
// It uses multipart form data and automatically selects HTTP or HTTPS based on the host.
func (m *ModemCheck) uploadToCloudWithModemID(localFile string, modemID string) error {
	m.Log(fmt.Sprintf("Uploading to cloud server: %s:%s (with integrity checksum)", m.config.CloudHost, m.config.CloudPort))

	// Validate API key
	if m.config.CloudAPIKey == "" {
		return fmt.Errorf("no API key provided (CloudAPIKey is required)")
	}

	// Open local file
	file, err := os.Open(localFile)
	if err != nil {
		return fmt.Errorf("failed to open local file: %v", err)
	}
	defer file.Close()

	// Read file contents
	fileContents, err := io.ReadAll(file)
	if err != nil {
		return fmt.Errorf("failed to read local file: %v", err)
	}

	// Calculate SHA-256 checksum for data integrity validation
	checksumBytes := sha256.Sum256(fileContents)
	checksum := hex.EncodeToString(checksumBytes[:])

	// Prepare remote directory and filename
	remoteDirName := modemID
	remoteFileName := filepath.Base(localFile)

	// SECURITY: Cloud API key transmission uses HTTPS by default
	// HTTP is ONLY allowed when ALL of these conditions are met:
	// 1. EnforceHTTPS=false (not strictly enforcing HTTPS)
	// 2. InsecureTLS=true (explicitly allowing insecure connections)
	// 3. Host is on a private network (not public internet)
	protocol := "https"
	host := strings.ToLower(m.config.CloudHost)

	// Only allow HTTP if user explicitly disabled HTTPS enforcement AND enabled insecure TLS for private networks
	if !m.config.EnforceHTTPS && m.config.InsecureTLS && isPrivateNetwork(host) {
		m.Log("WARNING: Using HTTP for API key transmission (InsecureTLS enabled for private network)")
		protocol = "http"
	}

	// Build upload URL
	// Use CloudPath if specified, otherwise use root path "/"
	path := m.config.CloudPath
	if path == "" {
		path = "/"
	}
	uploadURL := fmt.Sprintf("%s://%s:%s%s", protocol, m.config.CloudHost, m.config.CloudPort, path)

	// Generate timestamp for request signing (Unix timestamp as string)
	timestamp := strconv.FormatInt(time.Now().Unix(), 10)

	// Generate HMAC-SHA256 signature for request authentication
	signature := generateRequestSignature(m.config.CloudAPIKey, timestamp, remoteDirName, remoteFileName, checksum)

	// Create HTTP request with multipart form data
	body := &strings.Builder{}
	body.WriteString("--boundary123\r\n")
	body.WriteString("Content-Disposition: form-data; name=\"api_key\"\r\n\r\n")
	body.WriteString(fmt.Sprintf("%s\r\n", m.config.CloudAPIKey))
	body.WriteString("--boundary123\r\n")
	body.WriteString("Content-Disposition: form-data; name=\"modem_id\"\r\n\r\n")
	body.WriteString(fmt.Sprintf("%s\r\n", remoteDirName))
	body.WriteString("--boundary123\r\n")
	body.WriteString("Content-Disposition: form-data; name=\"filename\"\r\n\r\n")
	body.WriteString(fmt.Sprintf("%s\r\n", remoteFileName))
	body.WriteString("--boundary123\r\n")
	body.WriteString("Content-Disposition: form-data; name=\"checksum\"\r\n\r\n")
	body.WriteString(fmt.Sprintf("%s\r\n", checksum))
	body.WriteString("--boundary123\r\n")
	body.WriteString(fmt.Sprintf("Content-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n", remoteFileName))
	body.WriteString("Content-Type: application/json\r\n\r\n")
	body.Write(fileContents)
	body.WriteString("\r\n--boundary123--\r\n")

	// Create POST request
	req, err := http.NewRequest("POST", uploadURL, strings.NewReader(body.String()))
	if err != nil {
		return fmt.Errorf("failed to create HTTP request: %v", err)
	}
	req.Header.Set("Content-Type", "multipart/form-data; boundary=boundary123")

	// Add authentication headers (HMAC signature + timestamp)
	req.Header.Set("X-Request-Timestamp", timestamp)
	req.Header.Set("X-Request-Signature", signature)

	// Send request using configured client (with proper TLS settings)
	resp, err := m.client.Do(req)
	if err != nil {
		return fmt.Errorf("failed to upload file: %v", err)
	}
	defer resp.Body.Close()

	// Read response body once (before status check to avoid double-read bug)
	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("failed to read response body: %w", err)
	}

	// Check response status after reading body
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("upload failed with status %d: %s", resp.StatusCode, string(respBody))
	}

	var uploadResp struct {
		Success bool   `json:"success"`
		Message string `json:"message"`
		Error   string `json:"error"`
	}

	if err := json.Unmarshal(respBody, &uploadResp); err != nil {
		return fmt.Errorf("invalid server response (not valid JSON): %v", err)
	}

	if !uploadResp.Success {
		errorMsg := uploadResp.Error
		if errorMsg == "" {
			errorMsg = uploadResp.Message
		}
		return fmt.Errorf("server rejected upload: %s", errorMsg)
	}

	m.Log(fmt.Sprintf("Successfully uploaded %s to %s/%s", remoteFileName, m.config.CloudPath, remoteDirName))
	return nil
}

// UploadToCloud uploads the JSON file to the cloud server using current modem info.
func (m *ModemCheck) UploadToCloud(localFile string, modemType string, modemMAC string) error {
	if !m.config.EnableCloud {
		return nil // Silently skip if cloud is disabled
	}

	// Use current modem type and MAC to build modem ID
	modemID := fmt.Sprintf("%s-%s", modemType, modemMAC)
	return m.uploadToCloudWithModemID(localFile, modemID)
}

// retryFailedUploads attempts to upload all files in the queue and reports success/failure counts.
func (m *ModemCheck) retryFailedUploads(queue *UploadQueue) {
	if len(queue.FailedUploads) == 0 {
		return
	}

	m.Log(fmt.Sprintf("Found %d file(s) in upload queue, attempting retry...", len(queue.FailedUploads)))

	successCount := 0
	failCount := 0
	missingCount := 0

	// Create a copy to iterate over since we'll be modifying the original
	entries := make([]UploadQueueEntry, len(queue.FailedUploads))
	copy(entries, queue.FailedUploads)

	for _, entry := range entries {
		// Check if file still exists
		if _, err := os.Stat(entry.FilePath); os.IsNotExist(err) {
			m.Log(fmt.Sprintf("  ✗ File no longer exists: %s", entry.FilePath))
			removeFromUploadQueue(queue, entry.FilePath)
			missingCount++
			continue
		}

		// Attempt upload using the modemID from the queue entry
		err := m.uploadToCloudWithModemID(entry.FilePath, entry.ModemID)
		if err == nil {
			m.Log(fmt.Sprintf("  ✓ Successfully uploaded: %s (was attempt #%d)", filepath.Base(entry.FilePath), entry.Attempts+1))
			removeFromUploadQueue(queue, entry.FilePath)
			successCount++
		} else {
			m.Log(fmt.Sprintf("  ✗ Upload failed: %s - %v", filepath.Base(entry.FilePath), err))
			// Update the entry with new attempt info
			for i := range queue.FailedUploads {
				if queue.FailedUploads[i].FilePath == entry.FilePath {
					queue.FailedUploads[i].Attempts++
					queue.FailedUploads[i].LastAttempt = time.Now()
					queue.FailedUploads[i].LastError = err.Error()
					break
				}
			}
			failCount++
		}
	}

	// Save the queue to persist any removals or updates
	if err := saveUploadQueue(queue); err != nil {
		m.Log(fmt.Sprintf("Warning: Failed to save upload queue: %v", err))
	}

	if successCount > 0 || missingCount > 0 {
		m.Log(fmt.Sprintf("Retry summary: %d succeeded, %d failed, %d missing", successCount, failCount, missingCount))
	}
}

// cleanupLogFile purges log entries older than LogMaxAgeDays (30 days) to prevent
// unbounded log file growth. Uses streaming to minimize memory usage.
func (m *ModemCheck) cleanupLogFile() error {
	logFileName := "modem-check_logs.txt"

	// Check if log file exists
	if _, err := os.Stat(logFileName); os.IsNotExist(err) {
		return nil // No log file to clean up
	}

	// Open log file for reading
	logFile, err := os.Open(logFileName)
	if err != nil {
		return err
	}
	defer logFile.Close()

	// Create temporary file for cleaned log
	tmpFile, err := os.CreateTemp("", "modem-check_logs_*.txt")
	if err != nil {
		return err
	}
	tmpFileName := tmpFile.Name()
	defer os.Remove(tmpFileName) // Clean up temp file if we error out

	cutoffDate := time.Now().AddDate(0, 0, -LogMaxAgeDays)
	scanner := bufio.NewScanner(logFile)
	writer := bufio.NewWriter(tmpFile)
	linesProcessed := 0
	linesKept := 0

	// Process file line by line (streaming)
	for scanner.Scan() {
		line := scanner.Text()
		linesProcessed++

		// Skip empty lines
		if len(strings.TrimSpace(line)) == 0 {
			continue
		}

		// Try to parse timestamp from log line format: "Mon Jan 2 03:04:05 PM MST 2006"
		// The actual format varies, so we look for the first 20 characters after the first space
		shouldKeep := true
		parts := strings.SplitN(line, ": ", 2)
		if len(parts) == 2 {
			timestampStr := parts[0]
			if logTime, err := time.Parse("Mon Jan 2 03:04:05 PM MST 2006", timestampStr); err == nil {
				if logTime.Before(cutoffDate) {
					shouldKeep = false
				}
			}
		}

		if shouldKeep {
			if _, err := writer.WriteString(line + "\n"); err != nil {
				tmpFile.Close()
				return err
			}
			linesKept++
		}
	}

	if err := scanner.Err(); err != nil {
		tmpFile.Close()
		return err
	}

	// Flush and close files
	if err := writer.Flush(); err != nil {
		tmpFile.Close()
		return err
	}
	if err := tmpFile.Close(); err != nil {
		return err
	}

	// Only replace log file if we removed some lines
	if linesKept < linesProcessed {
		if err := os.Rename(tmpFileName, logFileName); err != nil {
			return err
		}
	}

	return nil
}

// isPrivateNetwork checks if the host is on a private network using proper IP parsing.
// This prevents the string comparison bug where "172.99.0.1" would incorrectly be treated as private.
func isPrivateNetwork(host string) bool {
	// Handle localhost strings
	if strings.Contains(host, "localhost") {
		return true
	}

	// Parse the host as an IP address
	// If it's a hostname, try to resolve it first
	ip := net.ParseIP(host)
	if ip == nil {
		// Might be a hostname, try to resolve
		ips, err := net.LookupIP(host)
		if err != nil || len(ips) == 0 {
			// Can't resolve, assume public for safety
			return false
		}
		ip = ips[0]
	}

	// Check against private IP ranges using proper CIDR notation
	privateRanges := []string{
		"10.0.0.0/8",        // Class A private network
		"172.16.0.0/12",     // Class B private networks (172.16.0.0 - 172.31.255.255)
		"192.168.0.0/16",    // Class C private networks
		"127.0.0.0/8",       // Loopback
		"169.254.0.0/16",    // Link-local
		"::1/128",           // IPv6 loopback
		"fc00::/7",          // IPv6 unique local addresses
		"fe80::/10",         // IPv6 link-local
	}

	for _, cidr := range privateRanges {
		_, ipNet, err := net.ParseCIDR(cidr)
		if err != nil {
			continue
		}
		if ipNet.Contains(ip) {
			return true
		}
	}

	return false
}
