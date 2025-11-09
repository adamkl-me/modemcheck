package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// UploadQueueEntry represents a failed upload that needs to be retried
type UploadQueueEntry struct {
	FilePath     string    `json:"file_path"`
	ModemID      string    `json:"modem_id"`
	Timestamp    string    `json:"timestamp"`
	Attempts     int       `json:"attempts"`
	LastAttempt  time.Time `json:"last_attempt"`
	LastError    string    `json:"last_error"`
	FirstFailure time.Time `json:"first_failure"`
}

// UploadQueue manages failed uploads
type UploadQueue struct {
	FailedUploads []UploadQueueEntry `json:"failed_uploads"`
}

const queueFilePath = "ModemCheck-Results/.upload_queue.json"

// loadUploadQueue loads the upload queue from disk
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

// saveUploadQueue saves the upload queue to disk
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

// addToUploadQueue adds a failed upload to the queue
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

// removeFromUploadQueue removes an entry from the queue
func removeFromUploadQueue(queue *UploadQueue, filePath string) {
	for i, entry := range queue.FailedUploads {
		if entry.FilePath == filePath {
			queue.FailedUploads = append(queue.FailedUploads[:i], queue.FailedUploads[i+1:]...)
			return
		}
	}
}

// cleanupUploadQueue removes old and missing files from queue
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

// uploadToCloudWithModemID uploads a file to the cloud server with a specific modem ID
func (m *ModemCheck) uploadToCloudWithModemID(localFile string, modemID string) error {
	m.Log(fmt.Sprintf("Uploading to cloud server: %s:%s", m.config.CloudHost, m.config.CloudPort))

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

	// Prepare remote directory and filename
	remoteDirName := modemID
	remoteFileName := filepath.Base(localFile)

	// Smart protocol detection: use HTTP for localhost/local IPs, HTTPS for external domains
	protocol := "https"
	host := strings.ToLower(m.config.CloudHost)
	if strings.Contains(host, "localhost") || strings.Contains(host, "127.0.0.1") ||
		strings.HasPrefix(host, "192.168.") || strings.HasPrefix(host, "10.") ||
		strings.HasPrefix(host, "172.16.") {
		protocol = "http"
	}

	// Build upload URL
	uploadURL := fmt.Sprintf("%s://%s:%s/cgi-bin/upload.py", protocol, m.config.CloudHost, m.config.CloudPort)

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
	body.WriteString(fmt.Sprintf("Content-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n", remoteFileName))
	body.WriteString("Content-Type: application/json\r\n\r\n")
	body.Write(fileContents)
	body.WriteString("\r\n--boundary123--\r\n")

	// Create HTTP client with timeout
	client := &http.Client{
		Timeout: 30 * time.Second,
	}

	// Create POST request
	req, err := http.NewRequest("POST", uploadURL, strings.NewReader(body.String()))
	if err != nil {
		return fmt.Errorf("failed to create HTTP request: %v", err)
	}
	req.Header.Set("Content-Type", "multipart/form-data; boundary=boundary123")

	// Send request
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("failed to upload file: %v", err)
	}
	defer resp.Body.Close()

	// Check response
	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("upload failed with status %d: %s", resp.StatusCode, string(respBody))
	}

	m.Log(fmt.Sprintf("Successfully uploaded %s to %s/%s", remoteFileName, m.config.CloudPath, remoteDirName))
	return nil
}

// UploadToCloud uploads the JSON file to the cloud server using current modem info
func (m *ModemCheck) UploadToCloud(localFile string, modemType string, modemMAC string) error {
	if !m.config.EnableCloud {
		return nil // Silently skip if cloud is disabled
	}

	// Use current modem type and MAC to build modem ID
	modemID := fmt.Sprintf("%s-%s", modemType, modemMAC)
	return m.uploadToCloudWithModemID(localFile, modemID)
}

// retryFailedUploads attempts to upload all files in the queue
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

// cleanupLogFile purges log entries older than 30 days
func (m *ModemCheck) cleanupLogFile() error {
	logFileName := "modem-check_logs.txt"

	// Check if log file exists
	if _, err := os.Stat(logFileName); os.IsNotExist(err) {
		return nil // No log file to clean up
	}

	// Read the log file
	data, err := os.ReadFile(logFileName)
	if err != nil {
		return err
	}

	lines := strings.Split(string(data), "\n")
	cutoffDate := time.Now().AddDate(0, 0, -LogMaxAgeDays)
	var keptLines []string

	for _, line := range lines {
		// Skip empty lines
		if len(strings.TrimSpace(line)) == 0 {
			continue
		}

		// Try to parse timestamp from log line format: [YYYY-MM-DD HH:MM:SS]
		if len(line) > 21 && line[0] == '[' {
			timestampStr := line[1:20] // Extract YYYY-MM-DD HH:MM:SS
			if logTime, err := time.Parse("2006-01-02 15:04:05", timestampStr); err == nil {
				if logTime.Before(cutoffDate) {
					continue // Skip old entries
				}
			}
		}

		keptLines = append(keptLines, line)
	}

	// Write back the cleaned log
	if len(keptLines) < len(lines) {
		cleanedData := strings.Join(keptLines, "\n")
		if err := os.WriteFile(logFileName, []byte(cleanedData), 0644); err != nil {
			return err
		}
	}

	return nil
}
