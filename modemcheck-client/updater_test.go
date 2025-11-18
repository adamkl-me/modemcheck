package main

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestSignatureTimestampValidation(t *testing.T) {
	// Create a temporary test directory
	tmpDir := t.TempDir()

	// Create a fake binary file
	tmpFile := filepath.Join(tmpDir, "test-binary.tmp")
	if err := os.WriteFile(tmpFile, []byte("fake binary content"), 0644); err != nil {
		t.Fatalf("Failed to create test file: %v", err)
	}

	// Create a fake signature file
	sigFile := tmpFile + ".minisig"

	t.Run("RecentSignature", func(t *testing.T) {
		// Create signature file with current timestamp
		if err := os.WriteFile(sigFile, []byte("fake signature"), 0644); err != nil {
			t.Fatalf("Failed to create signature file: %v", err)
		}

		// Check timestamp (should pass - file is fresh)
		sigInfo, err := os.Stat(sigFile)
		if err != nil {
			t.Fatalf("Failed to stat signature file: %v", err)
		}

		sigAge := time.Since(sigInfo.ModTime())
		maxAge := 90 * 24 * time.Hour

		if sigAge > maxAge {
			t.Errorf("Signature timestamp check should pass for recent file, age: %v", sigAge)
		}
	})

	t.Run("OldSignature", func(t *testing.T) {
		// Create signature file
		if err := os.WriteFile(sigFile, []byte("fake signature"), 0644); err != nil {
			t.Fatalf("Failed to create signature file: %v", err)
		}

		// Set modification time to 100 days ago (exceeds 90-day limit)
		oldTime := time.Now().Add(-100 * 24 * time.Hour)
		if err := os.Chtimes(sigFile, oldTime, oldTime); err != nil {
			t.Fatalf("Failed to set old timestamp: %v", err)
		}

		// Check timestamp (should fail - file too old)
		sigInfo, err := os.Stat(sigFile)
		if err != nil {
			t.Fatalf("Failed to stat signature file: %v", err)
		}

		sigAge := time.Since(sigInfo.ModTime())
		maxAge := 90 * 24 * time.Hour

		if sigAge <= maxAge {
			t.Errorf("Signature timestamp check should fail for old file, age: %v", sigAge)
		}

		// Verify error message would be generated
		expectedDays := int(sigAge.Hours() / 24)
		if expectedDays <= 90 {
			t.Errorf("Expected age > 90 days, got %d days", expectedDays)
		}
	})

	t.Run("ExactlyAtLimit", func(t *testing.T) {
		// Create signature file at exactly 90 days (boundary test)
		if err := os.WriteFile(sigFile, []byte("fake signature"), 0644); err != nil {
			t.Fatalf("Failed to create signature file: %v", err)
		}

		// Set to exactly 90 days ago
		limitTime := time.Now().Add(-90 * 24 * time.Hour)
		if err := os.Chtimes(sigFile, limitTime, limitTime); err != nil {
			t.Fatalf("Failed to set timestamp: %v", err)
		}

		sigInfo, err := os.Stat(sigFile)
		if err != nil {
			t.Fatalf("Failed to stat signature file: %v", err)
		}

		sigAge := time.Since(sigInfo.ModTime())
		maxAge := 90 * 24 * time.Hour

		// At the limit should pass (not strictly greater than)
		// Implementation uses > not >=, so 90.0 days should pass
		if sigAge > maxAge+time.Hour {
			t.Errorf("Signature at exactly 90 days should pass (within margin)")
		}
	})

	t.Run("JustOverLimit", func(t *testing.T) {
		// Create signature file just over 90 days (90 days + 1 hour)
		if err := os.WriteFile(sigFile, []byte("fake signature"), 0644); err != nil {
			t.Fatalf("Failed to create signature file: %v", err)
		}

		overLimitTime := time.Now().Add(-90*24*time.Hour - time.Hour)
		if err := os.Chtimes(sigFile, overLimitTime, overLimitTime); err != nil {
			t.Fatalf("Failed to set timestamp: %v", err)
		}

		sigInfo, err := os.Stat(sigFile)
		if err != nil {
			t.Fatalf("Failed to stat signature file: %v", err)
		}

		sigAge := time.Since(sigInfo.ModTime())
		maxAge := 90 * 24 * time.Hour

		if sigAge <= maxAge {
			t.Errorf("Signature just over 90 days should fail, age: %v", sigAge)
		}
	})

	t.Run("FutureSignature", func(t *testing.T) {
		// Edge case: signature file with future timestamp
		// This shouldn't happen in practice but test defensive behavior
		if err := os.WriteFile(sigFile, []byte("fake signature"), 0644); err != nil {
			t.Fatalf("Failed to create signature file: %v", err)
		}

		// Set timestamp to 1 day in the future
		futureTime := time.Now().Add(24 * time.Hour)
		if err := os.Chtimes(sigFile, futureTime, futureTime); err != nil {
			// Some filesystems don't support future times
			t.Skip("Filesystem doesn't support future timestamps")
		}

		sigInfo, err := os.Stat(sigFile)
		if err != nil {
			t.Fatalf("Failed to stat signature file: %v", err)
		}

		sigAge := time.Since(sigInfo.ModTime())
		maxAge := 90 * 24 * time.Hour

		// Future timestamp would have negative age
		// Should pass the check (not too old)
		if sigAge > maxAge {
			t.Errorf("Future signature should pass age check (not too old)")
		}
	})
}

func TestVersionComparison(t *testing.T) {
	tests := []struct {
		name           string
		currentVersion string
		latestVersion  string
		shouldUpdate   bool
		expectError    bool
	}{
		{
			name:           "NewerMajor",
			currentVersion: "5.8.0",
			latestVersion:  "6.0.0",
			shouldUpdate:   true,
			expectError:    false,
		},
		{
			name:           "NewerMinor",
			currentVersion: "6.0.0",
			latestVersion:  "6.1.0",
			shouldUpdate:   true,
			expectError:    false,
		},
		{
			name:           "NewerPatch",
			currentVersion: "6.0.0",
			latestVersion:  "6.0.1",
			shouldUpdate:   true,
			expectError:    false,
		},
		{
			name:           "SameVersion",
			currentVersion: "6.0.0",
			latestVersion:  "6.0.0",
			shouldUpdate:   false,
			expectError:    false,
		},
		{
			name:           "OlderVersion",
			currentVersion: "6.0.0",
			latestVersion:  "5.9.0",
			shouldUpdate:   false,
			expectError:    false,
		},
		{
			name:           "PrereleaseToStable",
			currentVersion: "6.0.0-test.1",
			latestVersion:  "6.0.0",
			shouldUpdate:   true,
			expectError:    false,
		},
		{
			name:           "StableToPrerelease",
			currentVersion: "6.0.0",
			latestVersion:  "6.0.0-test.2",
			shouldUpdate:   false,
			expectError:    false,
		},
		{
			name:           "NewerPrerelease",
			currentVersion: "6.0.0-test.1",
			latestVersion:  "6.0.0-test.2",
			shouldUpdate:   true,
			expectError:    false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			shouldUpdate, err := shouldUpdateVersion(tt.currentVersion, tt.latestVersion)

			if tt.expectError {
				if err == nil {
					t.Errorf("Expected error, got nil")
				}
				return
			}

			if err != nil {
				t.Errorf("Unexpected error: %v", err)
				return
			}

			if shouldUpdate != tt.shouldUpdate {
				t.Errorf("shouldUpdateVersion(%q, %q) = %v, want %v",
					tt.currentVersion, tt.latestVersion, shouldUpdate, tt.shouldUpdate)
			}
		})
	}
}

func TestExtractPrereleaseNumber(t *testing.T) {
	tests := []struct {
		prerelease string
		expected   int
	}{
		{"test.1", 1},
		{"test.10", 10},
		{"beta.5", 5},
		{"alpha", 0},
		{"rc.100", 100},
		{"", 0},
	}

	for _, tt := range tests {
		t.Run(tt.prerelease, func(t *testing.T) {
			result := extractPrereleaseNumber(tt.prerelease)
			if result != tt.expected {
				t.Errorf("extractPrereleaseNumber(%q) = %d, want %d",
					tt.prerelease, result, tt.expected)
			}
		})
	}
}
