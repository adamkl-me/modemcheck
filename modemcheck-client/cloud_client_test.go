package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func init() {
	// Use HTTP for tests (HTTPS in production)
	SetCloudUploadURLScheme("http")
}

// TestGenerateRequestSignature tests HMAC-SHA256 signature generation
func TestGenerateRequestSignature(t *testing.T) {
	tests := []struct {
		name      string
		apiKey    string
		timestamp string
		modemID   string
		filename  string
		checksum  string
		wantSig   string
	}{
		{
			name:      "basic signature",
			apiKey:    "test-api-key-123",
			timestamp: "1234567890",
			modemID:   "XB8-AA:BB:CC:DD:EE:FF",
			filename:  "check_1234567890.json",
			checksum:  "abc123def456",
			wantSig:   computeHMAC("test-api-key-123", "1234567890|XB8-AA:BB:CC:DD:EE:FF|check_1234567890.json|abc123def456"),
		},
		{
			name:      "empty values",
			apiKey:    "",
			timestamp: "",
			modemID:   "",
			filename:  "",
			checksum:  "",
			wantSig:   computeHMAC("", "|||"),
		},
		{
			name:      "special characters in modem ID",
			apiKey:    "key123",
			timestamp: "9999999999",
			modemID:   "DM1000-12:34:56:78:90:AB",
			filename:  "test.json",
			checksum:  "deadbeef",
			wantSig:   computeHMAC("key123", "9999999999|DM1000-12:34:56:78:90:AB|test.json|deadbeef"),
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := generateRequestSignature(tt.apiKey, tt.timestamp, tt.modemID, tt.filename, tt.checksum)
			if got != tt.wantSig {
				t.Errorf("generateRequestSignature() = %s, want %s", got, tt.wantSig)
			}
		})
	}
}

// TestGenerateRequestSignatureDeterministic tests that signature generation is deterministic
func TestGenerateRequestSignatureDeterministic(t *testing.T) {
	apiKey := "test-key"
	timestamp := "1234567890"
	modemID := "XB8-AA:BB:CC:DD:EE:FF"
	filename := "test.json"
	checksum := "abc123"

	sig1 := generateRequestSignature(apiKey, timestamp, modemID, filename, checksum)
	sig2 := generateRequestSignature(apiKey, timestamp, modemID, filename, checksum)

	if sig1 != sig2 {
		t.Error("generateRequestSignature() should be deterministic - same inputs should produce same output")
	}
}

// TestGenerateRequestSignatureDifferentKeys tests that different API keys produce different signatures
func TestGenerateRequestSignatureDifferentKeys(t *testing.T) {
	timestamp := "1234567890"
	modemID := "XB8-AA:BB:CC:DD:EE:FF"
	filename := "test.json"
	checksum := "abc123"

	sig1 := generateRequestSignature("key1", timestamp, modemID, filename, checksum)
	sig2 := generateRequestSignature("key2", timestamp, modemID, filename, checksum)

	if sig1 == sig2 {
		t.Error("Different API keys should produce different signatures")
	}
}

// TestAddToUploadQueue tests adding entries to the upload queue
func TestAddToUploadQueue(t *testing.T) {
	t.Run("add new entry", func(t *testing.T) {
		queue := &UploadQueue{
			FailedUploads: []UploadQueueEntry{},
			fileIndex:     make(map[string]int),
		}
		entry := UploadQueueEntry{
			FilePath:  "/test/path/file1.json",
			ModemID:   "XB8-AA:BB:CC:DD:EE:FF",
			Timestamp: "1234567890",
			LastError: "connection timeout",
		}

		addToUploadQueue(queue, entry)

		if len(queue.FailedUploads) != 1 {
			t.Errorf("Queue should have 1 entry, got %d", len(queue.FailedUploads))
		}

		if queue.FailedUploads[0].FilePath != entry.FilePath {
			t.Error("Entry was not added correctly")
		}

		if queue.FailedUploads[0].Attempts != 1 {
			t.Errorf("New entry should have Attempts=1, got %d", queue.FailedUploads[0].Attempts)
		}
	})

	t.Run("update existing entry", func(t *testing.T) {
		queue := &UploadQueue{
			FailedUploads: []UploadQueueEntry{
				{
					FilePath:     "/test/path/file1.json",
					ModemID:      "XB8-AA:BB:CC:DD:EE:FF",
					Timestamp:    "1234567890",
					Attempts:     1,
					FirstFailure: time.Now().Add(-1 * time.Hour),
					LastAttempt:  time.Now().Add(-1 * time.Hour),
					LastError:    "first error",
				},
			},
		}
		queue.buildIndex() // Build index for existing entries

		entry := UploadQueueEntry{
			FilePath:  "/test/path/file1.json",
			ModemID:   "XB8-AA:BB:CC:DD:EE:FF",
			Timestamp: "1234567890",
			LastError: "second error",
		}

		addToUploadQueue(queue, entry)

		// Should still have only 1 entry
		if len(queue.FailedUploads) != 1 {
			t.Errorf("Queue should have 1 entry, got %d", len(queue.FailedUploads))
		}

		// Attempts should increment
		if queue.FailedUploads[0].Attempts != 2 {
			t.Errorf("Attempts should be 2, got %d", queue.FailedUploads[0].Attempts)
		}

		// LastError should update
		if queue.FailedUploads[0].LastError != "second error" {
			t.Errorf("LastError should update to 'second error', got %q", queue.FailedUploads[0].LastError)
		}
	})

	t.Run("enforce max queue size", func(t *testing.T) {
		queue := &UploadQueue{
			FailedUploads: []UploadQueueEntry{},
			fileIndex:     make(map[string]int),
		}

		// Add more than MaxQueueSize entries
		for i := 0; i < MaxQueueSize+10; i++ {
			entry := UploadQueueEntry{
				FilePath:  fmt.Sprintf("/test/file%d.json", i),
				ModemID:   "XB8-AA:BB:CC:DD:EE:FF",
				Timestamp: "1234567890",
				LastError: "error",
			}
			addToUploadQueue(queue, entry)
		}

		// Queue should be capped at MaxQueueSize
		if len(queue.FailedUploads) != MaxQueueSize {
			t.Errorf("Queue should be capped at MaxQueueSize (%d), got %d", MaxQueueSize, len(queue.FailedUploads))
		}

		// Should keep the most recent entries (FIFO eviction from beginning)
		// The last entry added should still be in the queue
		lastFile := fmt.Sprintf("/test/file%d.json", MaxQueueSize+9)
		found := false
		for _, e := range queue.FailedUploads {
			if e.FilePath == lastFile {
				found = true
				break
			}
		}
		if !found {
			t.Error("Most recent entry should be retained after eviction")
		}
	})
}

// TestRemoveFromUploadQueue tests removing entries from the queue
func TestRemoveFromUploadQueue(t *testing.T) {
	t.Run("remove existing entry", func(t *testing.T) {
		queue := &UploadQueue{
			FailedUploads: []UploadQueueEntry{
				{FilePath: "/test/file1.json", ModemID: "XB8-AA"},
				{FilePath: "/test/file2.json", ModemID: "XB8-BB"},
				{FilePath: "/test/file3.json", ModemID: "XB8-CC"},
			},
		}
		queue.buildIndex() // Build index for existing entries

		removeFromUploadQueue(queue, "/test/file2.json")

		if len(queue.FailedUploads) != 2 {
			t.Errorf("Queue should have 2 entries, got %d", len(queue.FailedUploads))
		}

		// Verify file2 is gone
		for _, entry := range queue.FailedUploads {
			if entry.FilePath == "/test/file2.json" {
				t.Error("Entry should have been removed")
			}
		}

		// Verify file1 and file3 remain
		found1, found3 := false, false
		for _, entry := range queue.FailedUploads {
			if entry.FilePath == "/test/file1.json" {
				found1 = true
			}
			if entry.FilePath == "/test/file3.json" {
				found3 = true
			}
		}
		if !found1 || !found3 {
			t.Error("Other entries should remain in queue")
		}
	})

	t.Run("remove non-existent entry", func(t *testing.T) {
		queue := &UploadQueue{
			FailedUploads: []UploadQueueEntry{
				{FilePath: "/test/file1.json", ModemID: "XB8-AA"},
			},
		}
		queue.buildIndex() // Build index for existing entries

		removeFromUploadQueue(queue, "/test/nonexistent.json")

		// Queue should remain unchanged
		if len(queue.FailedUploads) != 1 {
			t.Errorf("Queue should still have 1 entry, got %d", len(queue.FailedUploads))
		}
	})
}

// TestCleanupUploadQueue tests age-based cleanup
func TestCleanupUploadQueue(t *testing.T) {
	// Create temporary directory for test files
	tmpDir := t.TempDir()

	// Create test files
	existingFile := filepath.Join(tmpDir, "exists.json")
	if err := os.WriteFile(existingFile, []byte("test"), 0644); err != nil {
		t.Fatalf("Failed to create test file: %v", err)
	}

	t.Run("remove old entries", func(t *testing.T) {
		queue := &UploadQueue{
			FailedUploads: []UploadQueueEntry{
				{
					FilePath:     existingFile,
					ModemID:      "XB8-AA",
					FirstFailure: time.Now().AddDate(0, 0, -QueueMaxAgeDays-1), // Too old
				},
				{
					FilePath:     existingFile,
					ModemID:      "XB8-BB",
					FirstFailure: time.Now().AddDate(0, 0, -QueueMaxAgeDays+1), // Recent enough
				},
			},
		}
		queue.buildIndex() // Build index for existing entries

		cleanupUploadQueue(queue)

		// Should only have 1 entry (the recent one)
		if len(queue.FailedUploads) != 1 {
			t.Errorf("Queue should have 1 entry after cleanup, got %d", len(queue.FailedUploads))
		}

		if queue.FailedUploads[0].ModemID != "XB8-BB" {
			t.Error("Wrong entry remained after cleanup")
		}
	})

	t.Run("remove entries for missing files", func(t *testing.T) {
		queue := &UploadQueue{
			FailedUploads: []UploadQueueEntry{
				{
					FilePath:     existingFile,
					ModemID:      "XB8-AA",
					FirstFailure: time.Now(),
				},
				{
					FilePath:     filepath.Join(tmpDir, "nonexistent.json"),
					ModemID:      "XB8-BB",
					FirstFailure: time.Now(),
				},
			},
		}
		queue.buildIndex() // Build index for existing entries

		cleanupUploadQueue(queue)

		// Should only have 1 entry (existing file)
		if len(queue.FailedUploads) != 1 {
			t.Errorf("Queue should have 1 entry after cleanup, got %d", len(queue.FailedUploads))
		}

		if queue.FailedUploads[0].FilePath != existingFile {
			t.Error("Entry for existing file should remain")
		}
	})

	t.Run("keep recent entries with existing files", func(t *testing.T) {
		queue := &UploadQueue{
			FailedUploads: []UploadQueueEntry{
				{
					FilePath:     existingFile,
					ModemID:      "XB8-AA",
					FirstFailure: time.Now(),
				},
			},
		}
		queue.buildIndex() // Build index for existing entries

		cleanupUploadQueue(queue)

		// Should keep the entry
		if len(queue.FailedUploads) != 1 {
			t.Errorf("Queue should have 1 entry, got %d", len(queue.FailedUploads))
		}
	})
}

// TestIsPrivateNetwork tests private network detection
func TestIsPrivateNetwork(t *testing.T) {
	tests := []struct {
		name    string
		host    string
		want    bool
	}{
		// Localhost
		{name: "localhost string", host: "localhost", want: true},
		{name: "localhost with subdomain", host: "api.localhost", want: true},
		{name: "127.0.0.1", host: "127.0.0.1", want: true},
		{name: "127.1.2.3", host: "127.1.2.3", want: true},
		{name: "IPv6 localhost", host: "::1", want: true},

		// Class A private (10.0.0.0/8)
		{name: "10.0.0.1", host: "10.0.0.1", want: true},
		{name: "10.255.255.255", host: "10.255.255.255", want: true},
		{name: "10.123.45.67", host: "10.123.45.67", want: true},

		// Class B private (172.16.0.0/12)
		{name: "172.16.0.1", host: "172.16.0.1", want: true},
		{name: "172.31.255.255", host: "172.31.255.255", want: true},
		{name: "172.20.0.1", host: "172.20.0.1", want: true},

		// Class C private (192.168.0.0/16)
		{name: "192.168.0.1", host: "192.168.0.1", want: true},
		{name: "192.168.1.1", host: "192.168.1.1", want: true},
		{name: "192.168.255.255", host: "192.168.255.255", want: true},

		// Link-local (169.254.0.0/16)
		{name: "169.254.1.1", host: "169.254.1.1", want: true},
		{name: "169.254.169.254", host: "169.254.169.254", want: true},

		// Public IPs
		{name: "8.8.8.8", host: "8.8.8.8", want: false},
		{name: "1.1.1.1", host: "1.1.1.1", want: false},
		{name: "172.15.0.1", host: "172.15.0.1", want: false}, // Just outside private range
		{name: "172.32.0.1", host: "172.32.0.1", want: false}, // Just outside private range
		{name: "172.99.0.1", host: "172.99.0.1", want: false}, // Bug test case
		{name: "192.167.0.1", host: "192.167.0.1", want: false},
		{name: "192.169.0.1", host: "192.169.0.1", want: false},

		// Invalid/unknown hosts
		{name: "empty string", host: "", want: false},
		{name: "invalid IP", host: "999.999.999.999", want: false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := isPrivateNetwork(tt.host)
			if got != tt.want {
				t.Errorf("isPrivateNetwork(%q) = %v, want %v", tt.host, got, tt.want)
			}
		})
	}
}

// TestUploadQueuePersistence tests saving and loading upload queue
func TestUploadQueuePersistence(t *testing.T) {
	// Save current working directory
	originalWd, err := os.Getwd()
	if err != nil {
		t.Fatalf("Failed to get working directory: %v", err)
	}
	defer os.Chdir(originalWd)

	// Create temporary directory and change to it
	tmpDir := t.TempDir()
	if err := os.Chdir(tmpDir); err != nil {
		t.Fatalf("Failed to change to temp directory: %v", err)
	}

	t.Run("save and load queue", func(t *testing.T) {
		// Create queue with entries
		queue := &UploadQueue{
			FailedUploads: []UploadQueueEntry{
				{
					FilePath:     "/test/file1.json",
					ModemID:      "XB8-AA:BB:CC:DD:EE:FF",
					Timestamp:    "1234567890",
					Attempts:     3,
					LastAttempt:  time.Now(),
					LastError:    "connection timeout",
					FirstFailure: time.Now().Add(-1 * time.Hour),
				},
			},
		}
		queue.buildIndex() // Build index for existing entries

		// Save queue
		if err := saveUploadQueue(queue); err != nil {
			t.Fatalf("Failed to save queue: %v", err)
		}

		// Load queue
		loadedQueue, err := loadUploadQueue()
		if err != nil {
			t.Fatalf("Failed to load queue: %v", err)
		}

		// Verify loaded queue matches
		if len(loadedQueue.FailedUploads) != 1 {
			t.Errorf("Loaded queue should have 1 entry, got %d", len(loadedQueue.FailedUploads))
		}

		if loadedQueue.FailedUploads[0].FilePath != "/test/file1.json" {
			t.Error("Loaded entry FilePath doesn't match")
		}

		if loadedQueue.FailedUploads[0].Attempts != 3 {
			t.Errorf("Loaded entry Attempts = %d, want 3", loadedQueue.FailedUploads[0].Attempts)
		}
	})

	t.Run("load non-existent queue", func(t *testing.T) {
		// Remove queue file
		os.Remove(queueFilePath)

		// Load should return empty queue, not error
		loadedQueue, err := loadUploadQueue()
		if err != nil {
			t.Fatalf("Loading non-existent queue should not error: %v", err)
		}

		if len(loadedQueue.FailedUploads) != 0 {
			t.Error("Loading non-existent queue should return empty queue")
		}
	})
}

// Helper function to compute HMAC for testing
func computeHMAC(key, message string) string {
	mac := hmac.New(sha256.New, []byte(key))
	mac.Write([]byte(message))
	return hex.EncodeToString(mac.Sum(nil))
}

// createTestModemCheck creates a ModemCheck instance for testing with the given HTTP client
func createTestModemCheck(client *http.Client, config Configuration) *ModemCheck {
	if client == nil {
		client = &http.Client{Timeout: 10 * time.Second}
	}
	return &ModemCheck{
		config: config,
		client: client,
	}
}

// TestUploadToCloudWithModemID_Success tests successful upload
func TestUploadToCloudWithModemID_Success(t *testing.T) {
	// Create a temporary test file
	tmpDir := t.TempDir()
	testFile := filepath.Join(tmpDir, "test_check.json")
	testData := `{"check_time": 1234567890, "modem_type": "XB8"}`
	if err := os.WriteFile(testFile, []byte(testData), 0644); err != nil {
		t.Fatalf("Failed to create test file: %v", err)
	}

	// Create mock server
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Verify request method
		if r.Method != "POST" {
			t.Errorf("Expected POST method, got %s", r.Method)
		}

		// Verify content type
		contentType := r.Header.Get("Content-Type")
		if !strings.Contains(contentType, "multipart/form-data") {
			t.Errorf("Expected multipart/form-data content type, got %s", contentType)
		}

		// Verify authentication headers
		if r.Header.Get("X-Request-Timestamp") == "" {
			t.Error("Missing X-Request-Timestamp header")
		}
		if r.Header.Get("X-Request-Signature") == "" {
			t.Error("Missing X-Request-Signature header")
		}

		// Return success response
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"success": true,
			"message": "Upload successful",
		})
	}))
	defer server.Close()

	// Parse server URL
	serverURL := strings.TrimPrefix(server.URL, "http://")
	parts := strings.Split(serverURL, ":")
	host := parts[0]
	port := parts[1]

	// Create test config
	config := Configuration{
		EnableCloud: true,
		CloudHost:   host,
		CloudPort:   port,
		CloudAPIKey: "test-api-key-123",
	}

	m := createTestModemCheck(server.Client(), config)

	// Test upload
	err := m.uploadToCloudWithModemID(testFile, "XB8-AA:BB:CC:DD:EE:FF")
	if err != nil {
		t.Fatalf("uploadToCloudWithModemID() error = %v", err)
	}
}

// TestUploadToCloudWithModemID_NoAPIKey tests upload without API key
func TestUploadToCloudWithModemID_NoAPIKey(t *testing.T) {
	tmpDir := t.TempDir()
	testFile := filepath.Join(tmpDir, "test.json")
	os.WriteFile(testFile, []byte("{}"), 0644)

	config := Configuration{
		EnableCloud: true,
		CloudAPIKey: "", // Empty API key
	}

	m := createTestModemCheck(nil, config)

	err := m.uploadToCloudWithModemID(testFile, "XB8-AA:BB:CC:DD:EE:FF")
	if err == nil {
		t.Error("Expected error for missing API key")
	}
	if !strings.Contains(err.Error(), "no API key") {
		t.Errorf("Unexpected error: %v", err)
	}
}

// TestUploadToCloudWithModemID_ServerError tests handling of server error response
func TestUploadToCloudWithModemID_ServerError(t *testing.T) {
	tmpDir := t.TempDir()
	testFile := filepath.Join(tmpDir, "test.json")
	os.WriteFile(testFile, []byte(`{"test": true}`), 0644)

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"success": false,
			"error":   "Invalid checksum",
		})
	}))
	defer server.Close()

	serverURL := strings.TrimPrefix(server.URL, "http://")
	parts := strings.Split(serverURL, ":")

	config := Configuration{
		EnableCloud: true,
		CloudHost:   parts[0],
		CloudPort:   parts[1],
		CloudAPIKey: "test-key",
	}

	m := createTestModemCheck(server.Client(), config)

	err := m.uploadToCloudWithModemID(testFile, "XB8-AA:BB:CC:DD:EE:FF")
	if err == nil {
		t.Error("Expected error for server error response")
	}
}

// TestUploadToCloudWithModemID_RejectedUpload tests handling of rejected upload
func TestUploadToCloudWithModemID_RejectedUpload(t *testing.T) {
	tmpDir := t.TempDir()
	testFile := filepath.Join(tmpDir, "test.json")
	os.WriteFile(testFile, []byte(`{"test": true}`), 0644)

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"success": false,
			"error":   "Duplicate upload",
		})
	}))
	defer server.Close()

	serverURL := strings.TrimPrefix(server.URL, "http://")
	parts := strings.Split(serverURL, ":")

	config := Configuration{
		EnableCloud: true,
		CloudHost:   parts[0],
		CloudPort:   parts[1],
		CloudAPIKey: "test-key",
	}

	m := createTestModemCheck(server.Client(), config)

	err := m.uploadToCloudWithModemID(testFile, "XB8-AA:BB:CC:DD:EE:FF")
	if err == nil {
		t.Error("Expected error for rejected upload")
	}
	if !strings.Contains(err.Error(), "Duplicate upload") {
		t.Errorf("Unexpected error: %v", err)
	}
}

// TestUploadToCloudWithModemID_MissingFile tests upload with non-existent file
func TestUploadToCloudWithModemID_MissingFile(t *testing.T) {
	config := Configuration{
		EnableCloud: true,
		CloudAPIKey: "test-key",
	}

	m := createTestModemCheck(nil, config)

	err := m.uploadToCloudWithModemID("/nonexistent/file.json", "XB8-AA:BB:CC:DD:EE:FF")
	if err == nil {
		t.Error("Expected error for missing file")
	}
}

// TestUploadToCloud_CloudDisabled tests upload when cloud is disabled
func TestUploadToCloud_CloudDisabled(t *testing.T) {
	config := Configuration{
		EnableCloud: false,
	}

	m := createTestModemCheck(nil, config)

	err := m.UploadToCloud("/some/file.json", "XB8", "AA:BB:CC:DD:EE:FF")
	if err != nil {
		t.Errorf("UploadToCloud() should return nil when cloud is disabled, got %v", err)
	}
}

// TestUploadToCloud_Success tests successful upload via UploadToCloud wrapper
func TestUploadToCloud_Success(t *testing.T) {
	tmpDir := t.TempDir()
	testFile := filepath.Join(tmpDir, "test.json")
	os.WriteFile(testFile, []byte(`{"test": true}`), 0644)

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"success": true,
		})
	}))
	defer server.Close()

	serverURL := strings.TrimPrefix(server.URL, "http://")
	parts := strings.Split(serverURL, ":")

	config := Configuration{
		EnableCloud: true,
		CloudHost:   parts[0],
		CloudPort:   parts[1],
		CloudAPIKey: "test-key",
	}

	m := createTestModemCheck(server.Client(), config)

	err := m.UploadToCloud(testFile, "XB8", "AA:BB:CC:DD:EE:FF")
	if err != nil {
		t.Fatalf("UploadToCloud() error = %v", err)
	}
}

// TestRetryFailedUploads_Success tests successful retry of failed uploads
func TestRetryFailedUploads_Success(t *testing.T) {
	tmpDir := t.TempDir()

	// Create test files
	testFile1 := filepath.Join(tmpDir, "test1.json")
	testFile2 := filepath.Join(tmpDir, "test2.json")
	os.WriteFile(testFile1, []byte(`{"file": 1}`), 0644)
	os.WriteFile(testFile2, []byte(`{"file": 2}`), 0644)

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"success": true,
		})
	}))
	defer server.Close()

	serverURL := strings.TrimPrefix(server.URL, "http://")
	parts := strings.Split(serverURL, ":")

	config := Configuration{
		EnableCloud: true,
		CloudHost:   parts[0],
		CloudPort:   parts[1],
		CloudAPIKey: "test-key",
	}

	m := createTestModemCheck(server.Client(), config)

	// Create queue with failed uploads
	queue := &UploadQueue{
		FailedUploads: []UploadQueueEntry{
			{
				FilePath:     testFile1,
				ModemID:      "XB8-AA:BB:CC:DD:EE:FF",
				Timestamp:    "1234567890",
				Attempts:     1,
				FirstFailure: time.Now().Add(-1 * time.Hour),
				LastAttempt:  time.Now().Add(-1 * time.Hour),
				LastError:    "connection timeout",
			},
			{
				FilePath:     testFile2,
				ModemID:      "XB8-11:22:33:44:55:66",
				Timestamp:    "1234567891",
				Attempts:     2,
				FirstFailure: time.Now().Add(-2 * time.Hour),
				LastAttempt:  time.Now().Add(-1 * time.Hour),
				LastError:    "server error",
			},
		},
	}
	queue.buildIndex()

	// Run retry
	m.retryFailedUploads(queue)

	// All uploads should succeed, so queue should be empty
	if len(queue.FailedUploads) != 0 {
		t.Errorf("Queue should be empty after successful retries, got %d entries", len(queue.FailedUploads))
	}
}

// TestRetryFailedUploads_MissingFiles tests retry with missing files
func TestRetryFailedUploads_MissingFiles(t *testing.T) {
	config := Configuration{
		EnableCloud: true,
		CloudAPIKey: "test-key",
	}

	m := createTestModemCheck(nil, config)

	queue := &UploadQueue{
		FailedUploads: []UploadQueueEntry{
			{
				FilePath:     "/nonexistent/file.json",
				ModemID:      "XB8-AA:BB:CC:DD:EE:FF",
				Timestamp:    "1234567890",
				Attempts:     1,
				FirstFailure: time.Now(),
			},
		},
	}
	queue.buildIndex()

	m.retryFailedUploads(queue)

	// Entry should be removed because file doesn't exist
	if len(queue.FailedUploads) != 0 {
		t.Errorf("Queue should be empty after removing missing files, got %d entries", len(queue.FailedUploads))
	}
}

// TestRetryFailedUploads_EmptyQueue tests retry with empty queue
func TestRetryFailedUploads_EmptyQueue(t *testing.T) {
	config := Configuration{
		EnableCloud: true,
		CloudAPIKey: "test-key",
	}

	m := createTestModemCheck(nil, config)

	queue := &UploadQueue{
		FailedUploads: []UploadQueueEntry{},
	}
	queue.buildIndex()

	// Should not panic or error
	m.retryFailedUploads(queue)
}

// TestRetryFailedUploads_AllFail tests retry when all uploads fail
func TestRetryFailedUploads_AllFail(t *testing.T) {
	tmpDir := t.TempDir()

	testFile1 := filepath.Join(tmpDir, "fail1.json")
	testFile2 := filepath.Join(tmpDir, "fail2.json")
	os.WriteFile(testFile1, []byte(`{"file": 1}`), 0644)
	os.WriteFile(testFile2, []byte(`{"file": 2}`), 0644)

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		// All uploads fail
		json.NewEncoder(w).Encode(map[string]interface{}{
			"success": false,
			"error":   "server error",
		})
	}))
	defer server.Close()

	serverURL := strings.TrimPrefix(server.URL, "http://")
	parts := strings.Split(serverURL, ":")

	config := Configuration{
		EnableCloud: true,
		CloudHost:   parts[0],
		CloudPort:   parts[1],
		CloudAPIKey: "test-key",
	}

	m := createTestModemCheck(server.Client(), config)

	queue := &UploadQueue{
		FailedUploads: []UploadQueueEntry{
			{
				FilePath:     testFile1,
				ModemID:      "XB8-AA:BB:CC:DD:EE:FF",
				Timestamp:    "1234567890",
				Attempts:     1,
				FirstFailure: time.Now(),
			},
			{
				FilePath:     testFile2,
				ModemID:      "XB8-11:22:33:44:55:66",
				Timestamp:    "1234567891",
				Attempts:     1,
				FirstFailure: time.Now(),
			},
		},
	}
	queue.buildIndex()

	m.retryFailedUploads(queue)

	// Both should remain in queue
	if len(queue.FailedUploads) != 2 {
		t.Errorf("Queue should have 2 entries after all failures, got %d", len(queue.FailedUploads))
	}

	// Verify attempts were incremented
	for _, entry := range queue.FailedUploads {
		if entry.Attempts != 2 {
			t.Errorf("Attempts should be 2 for %s, got %d", entry.FilePath, entry.Attempts)
		}
	}
}

// TestCleanupLogFile_NoLogFile tests cleanup when log file doesn't exist
func TestCleanupLogFile_NoLogFile(t *testing.T) {
	// Save and change working directory
	origDir, _ := os.Getwd()
	tmpDir := t.TempDir()
	os.Chdir(tmpDir)
	defer os.Chdir(origDir)

	config := Configuration{}
	m := createTestModemCheck(nil, config)

	// Should not error when log file doesn't exist
	err := m.cleanupLogFile()
	if err != nil {
		t.Errorf("cleanupLogFile() error = %v", err)
	}
}

// TestCleanupLogFile_RemovesOldEntries tests that old entries are removed
func TestCleanupLogFile_RemovesOldEntries(t *testing.T) {
	origDir, _ := os.Getwd()
	tmpDir := t.TempDir()
	os.Chdir(tmpDir)
	defer os.Chdir(origDir)

	// Create log file with old and new entries
	oldDate := time.Now().AddDate(0, 0, -LogMaxAgeDays-5)
	newDate := time.Now()

	logContent := fmt.Sprintf("%s: Old log entry\n%s: New log entry\n",
		oldDate.Format("Mon Jan 2 03:04:05 PM MST 2006"),
		newDate.Format("Mon Jan 2 03:04:05 PM MST 2006"))

	if err := os.WriteFile("modem-check_logs.txt", []byte(logContent), 0644); err != nil {
		t.Fatalf("Failed to create log file: %v", err)
	}

	config := Configuration{}
	m := createTestModemCheck(nil, config)

	err := m.cleanupLogFile()
	if err != nil {
		t.Fatalf("cleanupLogFile() error = %v", err)
	}

	// Read cleaned log file
	data, err := os.ReadFile("modem-check_logs.txt")
	if err != nil {
		t.Fatalf("Failed to read cleaned log file: %v", err)
	}

	content := string(data)
	if strings.Contains(content, "Old log entry") {
		t.Error("Old log entry should have been removed")
	}
	if !strings.Contains(content, "New log entry") {
		t.Error("New log entry should have been kept")
	}
}

// TestCleanupLogFile_KeepsAllRecentEntries tests that recent entries are preserved
func TestCleanupLogFile_KeepsAllRecentEntries(t *testing.T) {
	origDir, _ := os.Getwd()
	tmpDir := t.TempDir()
	os.Chdir(tmpDir)
	defer os.Chdir(origDir)

	// Create log file with only recent entries
	recentDate := time.Now().AddDate(0, 0, -1) // 1 day old

	logContent := fmt.Sprintf("%s: Recent entry 1\n%s: Recent entry 2\n",
		recentDate.Format("Mon Jan 2 03:04:05 PM MST 2006"),
		time.Now().Format("Mon Jan 2 03:04:05 PM MST 2006"))

	if err := os.WriteFile("modem-check_logs.txt", []byte(logContent), 0644); err != nil {
		t.Fatalf("Failed to create log file: %v", err)
	}

	config := Configuration{}
	m := createTestModemCheck(nil, config)

	err := m.cleanupLogFile()
	if err != nil {
		t.Fatalf("cleanupLogFile() error = %v", err)
	}

	// Read log file
	data, err := os.ReadFile("modem-check_logs.txt")
	if err != nil {
		t.Fatalf("Failed to read log file: %v", err)
	}

	content := string(data)
	if !strings.Contains(content, "Recent entry 1") || !strings.Contains(content, "Recent entry 2") {
		t.Error("Recent entries should all be kept")
	}
}
