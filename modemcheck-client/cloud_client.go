package main

import (
	"bufio"
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"
)

// cloudUploadURLScheme allows tests to use HTTP instead of HTTPS
var cloudUploadURLScheme = "https"

// SetCloudUploadURLScheme allows tests to use HTTP instead of HTTPS
// This should only be used in tests
func SetCloudUploadURLScheme(scheme string) {
	cloudUploadURLScheme = scheme
}

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

// UploadQueue manages failed uploads with O(1) lookups.
type UploadQueue struct {
	FailedUploads []UploadQueueEntry       `json:"failed_uploads"`
	fileIndex     map[string]int           `json:"-"` // Maps file path to slice index for O(1) lookup
	mu            sync.RWMutex             `json:"-"` // Protects concurrent access
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

// isRetryableError determines if an upload error should be retried.
// Returns true for transient failures (network errors, 5xx server errors).
// Returns false for permanent failures (validation errors, auth errors, 4xx client errors).
func isRetryableError(err error) bool {
	if err == nil {
		return false
	}

	errMsg := err.Error()

	// Network-level errors (connection refused, timeout, DNS, etc.) - RETRY
	if strings.Contains(errMsg, "connection refused") ||
		strings.Contains(errMsg, "timeout") ||
		strings.Contains(errMsg, "no such host") ||
		strings.Contains(errMsg, "network is unreachable") ||
		strings.Contains(errMsg, "connection reset") ||
		strings.Contains(errMsg, "TLS handshake") {
		return true
	}

	// Parse HTTP status code from error message format: "upload failed with status %d: %s"
	if strings.Contains(errMsg, "upload failed with status ") {
		// Extract status code
		parts := strings.SplitN(errMsg, "upload failed with status ", 2)
		if len(parts) == 2 {
			statusParts := strings.SplitN(parts[1], ":", 2)
			if len(statusParts) >= 1 {
				statusCode, err := strconv.Atoi(strings.TrimSpace(statusParts[0]))
				if err == nil {
					// 4xx client errors are permanent - DON'T RETRY
					// (400 Bad Request, 401 Unauthorized, 403 Forbidden, 422 Validation Error, etc.)
					if statusCode >= 400 && statusCode < 500 {
						return false
					}
					// 5xx server errors are transient - RETRY
					// (500 Internal Server Error, 502 Bad Gateway, 503 Service Unavailable, 504 Gateway Timeout)
					if statusCode >= 500 && statusCode < 600 {
						return true
					}
				}
			}
		}
	}

	// Unknown error - be conservative and retry
	return true
}

const queueFilePath = "ModemCheck-Results/.upload_queue.json"

// buildIndex constructs the file path index for O(1) lookups.
// Must be called after modifying FailedUploads slice directly or after unmarshaling.
func (q *UploadQueue) buildIndex() {
	q.fileIndex = make(map[string]int, len(q.FailedUploads))
	for i, entry := range q.FailedUploads {
		q.fileIndex[entry.FilePath] = i
	}
}

// loadUploadQueue loads the upload queue from disk.
// Returns an empty queue if the file doesn't exist.
func loadUploadQueue() (*UploadQueue, error) {
	queue := &UploadQueue{
		FailedUploads: []UploadQueueEntry{},
		fileIndex:     make(map[string]int),
	}

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

	// Build index after unmarshaling
	queue.buildIndex()

	return queue, nil
}

// saveUploadQueue saves the upload queue to disk using atomic write.
// Uses temp file + rename to prevent corruption if the process crashes during write.
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

	// Write to temporary file first (atomic write pattern)
	tmpFile := queueFilePath + ".tmp"
	if err := os.WriteFile(tmpFile, data, 0644); err != nil {
		return fmt.Errorf("failed to write temp file: %w", err)
	}

	// Atomic rename (on most filesystems, rename is atomic)
	if err := os.Rename(tmpFile, queueFilePath); err != nil {
		// Clean up temp file on failure
		os.Remove(tmpFile)
		return fmt.Errorf("failed to rename temp file: %w", err)
	}

	return nil
}

// addToUploadQueue adds a failed upload to the queue or updates an existing entry.
// Enforces the maximum queue size by removing oldest entries when exceeded.
// Uses map index for O(1) lookup instead of O(n) linear search.
func addToUploadQueue(queue *UploadQueue, entry UploadQueueEntry) {
	queue.mu.Lock()
	defer queue.mu.Unlock()

	now := time.Now()

	// Check if entry already exists using map index (O(1) instead of O(n))
	if idx, exists := queue.fileIndex[entry.FilePath]; exists {
		// Update existing entry
		queue.FailedUploads[idx].Attempts++
		queue.FailedUploads[idx].LastAttempt = now
		queue.FailedUploads[idx].LastError = entry.LastError
		return
	}

	// Add new entry
	entry.Attempts = 1
	entry.FirstFailure = now
	entry.LastAttempt = now
	queue.FailedUploads = append(queue.FailedUploads, entry)

	// Update index with new entry's position
	queue.fileIndex[entry.FilePath] = len(queue.FailedUploads) - 1

	// Enforce max queue size (remove oldest entries)
	if len(queue.FailedUploads) > MaxQueueSize {
		// Remove oldest entries and update index incrementally
		removedCount := len(queue.FailedUploads) - MaxQueueSize

		// Remove old entries from map
		for i := 0; i < removedCount; i++ {
			delete(queue.fileIndex, queue.FailedUploads[i].FilePath)
		}

		// Remove from slice
		queue.FailedUploads = queue.FailedUploads[removedCount:]

		// Update indices for remaining entries (shift down by removedCount)
		for i, entry := range queue.FailedUploads {
			queue.fileIndex[entry.FilePath] = i
		}
	}
}

// removeFromUploadQueue removes an entry from the queue by file path.
// Uses map index for O(1) lookup instead of O(n) linear search.
func removeFromUploadQueue(queue *UploadQueue, filePath string) {
	queue.mu.Lock()
	defer queue.mu.Unlock()

	// Check if entry exists using map index (O(1) instead of O(n))
	idx, exists := queue.fileIndex[filePath]
	if !exists {
		return // Entry not found
	}

	// Remove from map first
	delete(queue.fileIndex, filePath)

	// Remove from slice
	queue.FailedUploads = append(queue.FailedUploads[:idx], queue.FailedUploads[idx+1:]...)

	// Update indices for entries after the removed entry (O(n) but unavoidable)
	// This is still better than O(n) rebuild since we only update affected entries
	for i := idx; i < len(queue.FailedUploads); i++ {
		queue.fileIndex[queue.FailedUploads[i].FilePath] = i
	}
}

// cleanupUploadQueue removes entries older than QueueMaxAgeDays and entries
// for files that no longer exist on disk.
func cleanupUploadQueue(queue *UploadQueue) {
	queue.mu.Lock()
	defer queue.mu.Unlock()

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

	// Rebuild index after modifying slice
	queue.buildIndex()
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

	// SECURITY: Cloud API key transmission always uses HTTPS in production (v3.0+)
	// Build upload URL with root path (scheme configurable for testing)
	uploadURL := fmt.Sprintf("%s://%s:%s/", cloudUploadURLScheme, m.config.CloudHost, m.config.CloudPort)

	// Generate timestamp for request signing (Unix timestamp as string)
	timestamp := strconv.FormatInt(time.Now().Unix(), 10)

	// Generate HMAC-SHA256 signature for request authentication
	signature := generateRequestSignature(m.config.CloudAPIKey, timestamp, remoteDirName, remoteFileName, checksum)

	// Create HTTP request with multipart form data using mime/multipart
	// This generates a unique boundary for each request (security best practice)
	body := &bytes.Buffer{}
	writer := multipart.NewWriter(body)

	// Add form fields
	if err := writer.WriteField("api_key", m.config.CloudAPIKey); err != nil {
		return fmt.Errorf("failed to write api_key field: %v", err)
	}
	if err := writer.WriteField("modem_id", remoteDirName); err != nil {
		return fmt.Errorf("failed to write modem_id field: %v", err)
	}
	if err := writer.WriteField("filename", remoteFileName); err != nil {
		return fmt.Errorf("failed to write filename field: %v", err)
	}
	if err := writer.WriteField("checksum", checksum); err != nil {
		return fmt.Errorf("failed to write checksum field: %v", err)
	}

	// Add file field with proper Content-Type
	filePart, err := writer.CreateFormFile("file", remoteFileName)
	if err != nil {
		return fmt.Errorf("failed to create file field: %v", err)
	}
	if _, err := filePart.Write(fileContents); err != nil {
		return fmt.Errorf("failed to write file contents: %v", err)
	}

	// Close writer to finalize the multipart message (writes closing boundary)
	if err := writer.Close(); err != nil {
		return fmt.Errorf("failed to close multipart writer: %v", err)
	}

	// Create POST request
	req, err := http.NewRequest("POST", uploadURL, body)
	if err != nil {
		return fmt.Errorf("failed to create HTTP request: %v", err)
	}
	req.Header.Set("Content-Type", writer.FormDataContentType())

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
		// Sanitize error message to avoid exposing sensitive server details
		// Try to extract just the error message from JSON response if possible
		var errResp struct {
			Error   string `json:"error"`
			Message string `json:"message"`
			Detail  string `json:"detail"`
		}
		errorMsg := ""
		if json.Unmarshal(respBody, &errResp) == nil {
			if errResp.Error != "" {
				errorMsg = errResp.Error
			} else if errResp.Message != "" {
				errorMsg = errResp.Message
			} else if errResp.Detail != "" {
				errorMsg = errResp.Detail
			}
		}

		// If we couldn't extract a clean error message, use truncated body
		if errorMsg == "" {
			bodyStr := string(respBody)
			// Limit to 200 characters to avoid exposing sensitive details
			if len(bodyStr) > 200 {
				bodyStr = bodyStr[:200] + "..."
			}
			errorMsg = bodyStr
		}

		return fmt.Errorf("upload failed with status %d: %s", resp.StatusCode, errorMsg)
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

	m.Log(fmt.Sprintf("Successfully uploaded %s to cloud/%s", remoteFileName, remoteDirName))
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

	// Create a map index for O(1) lookups by FilePath
	// This prevents O(n²) performance when updating entries after failed uploads
	entryMap := make(map[string]int, len(queue.FailedUploads))
	for i := range queue.FailedUploads {
		entryMap[queue.FailedUploads[i].FilePath] = i
	}

	for _, entry := range entries {
		// Check if file still exists
		if _, err := os.Stat(entry.FilePath); os.IsNotExist(err) {
			m.Log(fmt.Sprintf("  ✗ File no longer exists: %s", entry.FilePath))
			removeFromUploadQueue(queue, entry.FilePath)
			delete(entryMap, entry.FilePath) // Keep map in sync
			missingCount++
			continue
		}

		// Attempt upload using the modemID from the queue entry
		attemptTime := time.Now() // Capture time at start of attempt for consistency
		err := m.uploadToCloudWithModemID(entry.FilePath, entry.ModemID)
		if err == nil {
			m.Log(fmt.Sprintf("  ✓ Successfully uploaded: %s (was attempt #%d)", filepath.Base(entry.FilePath), entry.Attempts+1))
			removeFromUploadQueue(queue, entry.FilePath)
			delete(entryMap, entry.FilePath) // Keep map in sync
			successCount++
		} else {
			// Check if error is retryable (network errors, 5xx) or permanent (validation errors, 4xx)
			if isRetryableError(err) {
				m.Log(fmt.Sprintf("  ✗ Upload failed (will retry): %s - %v", filepath.Base(entry.FilePath), err))
				// Update the entry with new attempt info using O(1) map lookup
				if idx, exists := entryMap[entry.FilePath]; exists {
					queue.FailedUploads[idx].Attempts++
					queue.FailedUploads[idx].LastAttempt = attemptTime
					queue.FailedUploads[idx].LastError = err.Error()
				}
				failCount++
			} else {
				m.Log(fmt.Sprintf("  ✗ Upload failed (permanent error, removing from queue): %s - %v", filepath.Base(entry.FilePath), err))
				// Permanent error (validation, auth, etc.) - remove from queue
				removeFromUploadQueue(queue, entry.FilePath)
				delete(entryMap, entry.FilePath) // Keep map in sync
				failCount++
			}
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
		// Use ParseInLocation with time.Local to handle different timezone abbreviations correctly
		// (e.g., EST, PST, MST, MDT) without timezone conversion issues
		shouldKeep := true
		parts := strings.SplitN(line, ": ", 2)
		if len(parts) == 2 {
			timestampStr := parts[0]
			if logTime, err := time.ParseInLocation("Mon Jan 2 03:04:05 PM MST 2006", timestampStr, time.Local); err == nil {
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
