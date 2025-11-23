package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"
)

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
