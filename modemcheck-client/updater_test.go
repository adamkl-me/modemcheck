package main

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

// TestParseSemanticVersion tests semantic version parsing
func TestParseSemanticVersion(t *testing.T) {
	tests := []struct {
		name        string
		version     string
		wantMajor   int
		wantMinor   int
		wantPatch   int
		wantPre     string
		wantErr     bool
	}{
		// Valid versions
		{name: "simple version", version: "1.2.3", wantMajor: 1, wantMinor: 2, wantPatch: 3, wantPre: "", wantErr: false},
		{name: "version with v prefix", version: "v1.2.3", wantMajor: 1, wantMinor: 2, wantPatch: 3, wantPre: "", wantErr: false},
		{name: "version with prerelease", version: "7.0.0-test.1", wantMajor: 7, wantMinor: 0, wantPatch: 0, wantPre: "test.1", wantErr: false},
		{name: "version with beta", version: "2.5.1-beta.3", wantMajor: 2, wantMinor: 5, wantPatch: 1, wantPre: "beta.3", wantErr: false},
		{name: "zero version", version: "0.0.0", wantMajor: 0, wantMinor: 0, wantPatch: 0, wantPre: "", wantErr: false},
		{name: "high version numbers", version: "10.20.30", wantMajor: 10, wantMinor: 20, wantPatch: 30, wantPre: "", wantErr: false},

		// Invalid versions
		{name: "missing patch", version: "1.2", wantErr: true},
		{name: "missing minor and patch", version: "1", wantErr: true},
		{name: "too many parts", version: "1.2.3.4", wantErr: true},
		{name: "non-numeric major", version: "a.2.3", wantErr: true},
		{name: "non-numeric minor", version: "1.b.3", wantErr: true},
		{name: "non-numeric patch", version: "1.2.c", wantErr: true},
		{name: "empty string", version: "", wantErr: true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			major, minor, patch, pre, err := parseSemanticVersion(tt.version)

			if (err != nil) != tt.wantErr {
				t.Errorf("parseSemanticVersion() error = %v, wantErr %v", err, tt.wantErr)
				return
			}

			if !tt.wantErr {
				if major != tt.wantMajor || minor != tt.wantMinor || patch != tt.wantPatch || pre != tt.wantPre {
					t.Errorf("parseSemanticVersion() = (%d, %d, %d, %q), want (%d, %d, %d, %q)",
						major, minor, patch, pre, tt.wantMajor, tt.wantMinor, tt.wantPatch, tt.wantPre)
				}
			}
		})
	}
}

// TestShouldUpdateVersion tests version comparison logic
func TestShouldUpdateVersion(t *testing.T) {
	tests := []struct {
		name           string
		currentVersion string
		latestVersion  string
		wantUpdate     bool
		wantErr        bool
	}{
		// Major version changes
		{name: "major upgrade", currentVersion: "1.0.0", latestVersion: "2.0.0", wantUpdate: true, wantErr: false},
		{name: "major downgrade", currentVersion: "2.0.0", latestVersion: "1.0.0", wantUpdate: false, wantErr: false},

		// Minor version changes
		{name: "minor upgrade", currentVersion: "1.0.0", latestVersion: "1.1.0", wantUpdate: true, wantErr: false},
		{name: "minor downgrade", currentVersion: "1.1.0", latestVersion: "1.0.0", wantUpdate: false, wantErr: false},

		// Patch version changes
		{name: "patch upgrade", currentVersion: "1.0.0", latestVersion: "1.0.1", wantUpdate: true, wantErr: false},
		{name: "patch downgrade", currentVersion: "1.0.1", latestVersion: "1.0.0", wantUpdate: false, wantErr: false},

		// Same version
		{name: "same version", currentVersion: "1.0.0", latestVersion: "1.0.0", wantUpdate: false, wantErr: false},

		// Pre-release versions
		{name: "pre-release to stable", currentVersion: "7.0.0-test.1", latestVersion: "7.0.0", wantUpdate: true, wantErr: false},
		{name: "stable to pre-release", currentVersion: "7.0.0", latestVersion: "7.0.0-test.1", wantUpdate: false, wantErr: false},
		{name: "pre-release upgrade", currentVersion: "7.0.0-test.1", latestVersion: "7.0.0-test.2", wantUpdate: true, wantErr: false},
		{name: "pre-release downgrade", currentVersion: "7.0.0-test.2", latestVersion: "7.0.0-test.1", wantUpdate: false, wantErr: false},
		{name: "same pre-release", currentVersion: "7.0.0-test.1", latestVersion: "7.0.0-test.1", wantUpdate: false, wantErr: false},

		// Complex scenarios
		{name: "major upgrade with pre-release", currentVersion: "6.0.0", latestVersion: "7.0.0-test.1", wantUpdate: true, wantErr: false},
		{name: "minor upgrade overrides pre-release", currentVersion: "6.9.0-beta.1", latestVersion: "7.0.0-test.1", wantUpdate: true, wantErr: false},

		// Invalid versions
		{name: "invalid current version", currentVersion: "invalid", latestVersion: "1.0.0", wantUpdate: false, wantErr: true},
		{name: "invalid latest version", currentVersion: "1.0.0", latestVersion: "invalid", wantUpdate: false, wantErr: true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			gotUpdate, err := shouldUpdateVersion(tt.currentVersion, tt.latestVersion)

			if (err != nil) != tt.wantErr {
				t.Errorf("shouldUpdateVersion() error = %v, wantErr %v", err, tt.wantErr)
				return
			}

			if !tt.wantErr && gotUpdate != tt.wantUpdate {
				t.Errorf("shouldUpdateVersion(%q, %q) = %v, want %v", tt.currentVersion, tt.latestVersion, gotUpdate, tt.wantUpdate)
			}
		})
	}
}

// TestExtractPrereleaseNumber tests pre-release number extraction
func TestExtractPrereleaseNumber(t *testing.T) {
	tests := []struct {
		name       string
		prerelease string
		want       int
	}{
		{name: "test.1", prerelease: "test.1", want: 1},
		{name: "test.12", prerelease: "test.12", want: 12},
		{name: "beta.3", prerelease: "beta.3", want: 3},
		{name: "alpha.0", prerelease: "alpha.0", want: 0},
		{name: "no number", prerelease: "alpha", want: 0},
		{name: "non-numeric", prerelease: "beta.x", want: 0},
		{name: "multiple dots", prerelease: "rc.1.2", want: 2}, // Last part
		{name: "empty", prerelease: "", want: 0},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := extractPrereleaseNumber(tt.prerelease)
			if got != tt.want {
				t.Errorf("extractPrereleaseNumber(%q) = %d, want %d", tt.prerelease, got, tt.want)
			}
		})
	}
}

// TestNormalizeExecutablePath tests executable path normalization
func TestNormalizeExecutablePath(t *testing.T) {
	tests := []struct {
		name string
		path string
		want string
	}{
		{name: "no .old suffix", path: "/usr/local/bin/modem-check", want: "/usr/local/bin/modem-check"},
		{name: "single .old suffix", path: "/usr/local/bin/modem-check.old", want: "/usr/local/bin/modem-check"},
		{name: "double .old suffix", path: "/usr/local/bin/modem-check.old.old", want: "/usr/local/bin/modem-check"},
		{name: "triple .old suffix", path: "/usr/local/bin/modem-check.old.old.old", want: "/usr/local/bin/modem-check"},
		{name: ".old in directory name", path: "/home/user/.old/modem-check", want: "/home/user/.old/modem-check"},
		{name: "old in filename", path: "/usr/bin/oldmodem-check", want: "/usr/bin/oldmodem-check"},
		{name: "empty path", path: "", want: ""},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := normalizeExecutablePath(tt.path)
			if got != tt.want {
				t.Errorf("normalizeExecutablePath(%q) = %q, want %q", tt.path, got, tt.want)
			}
		})
	}
}

// TestGetPlatformBinaryName tests platform-specific binary name generation
func TestGetPlatformBinaryName(t *testing.T) {
	// Test that the function returns a valid platform name
	platformName := getPlatformBinaryName()

	// Should contain the OS name
	if !contains(platformName, runtime.GOOS) {
		t.Errorf("getPlatformBinaryName() = %q, should contain OS %q", platformName, runtime.GOOS)
	}

	// Should contain an architecture indicator
	expectedArch := runtime.GOARCH
	switch runtime.GOARCH {
	case "amd64":
		expectedArch = "x64"
	case "386":
		expectedArch = "x86"
	}

	if !contains(platformName, expectedArch) {
		t.Errorf("getPlatformBinaryName() = %q, should contain arch %q", platformName, expectedArch)
	}

	// Windows binaries should have .exe extension
	if runtime.GOOS == "windows" {
		if !hasSuffix(platformName, ".exe") {
			t.Errorf("getPlatformBinaryName() = %q, Windows binary should end with .exe", platformName)
		}
	} else {
		// Unix-like systems should not have .exe extension
		if hasSuffix(platformName, ".exe") {
			t.Errorf("getPlatformBinaryName() = %q, non-Windows binary should not end with .exe", platformName)
		}
	}
}

// TestVerifySignature tests cryptographic signature verification
func TestVerifySignature(t *testing.T) {
	// Create temporary directory for test files
	tmpDir := t.TempDir()

	// Create test file
	testFile := filepath.Join(tmpDir, "test.bin")
	testContent := []byte("test content for signature verification")
	if err := os.WriteFile(testFile, testContent, 0644); err != nil {
		t.Fatalf("Failed to create test file: %v", err)
	}

	// Test 1: Missing signature file
	t.Run("missing signature file", func(t *testing.T) {
		missingSigFile := filepath.Join(tmpDir, "nonexistent.minisig")
		err := verifySignature(testFile, missingSigFile)
		if err == nil {
			t.Error("verifySignature() should fail with missing signature file")
		}
	})

	// Test 2: Invalid signature file
	t.Run("invalid signature file", func(t *testing.T) {
		invalidSigFile := filepath.Join(tmpDir, "invalid.minisig")
		if err := os.WriteFile(invalidSigFile, []byte("invalid signature data"), 0644); err != nil {
			t.Fatalf("Failed to create invalid signature file: %v", err)
		}

		err := verifySignature(testFile, invalidSigFile)
		if err == nil {
			t.Error("verifySignature() should fail with invalid signature")
		}
	})

	// Test 3: Missing file to verify
	t.Run("missing file to verify", func(t *testing.T) {
		sigFile := filepath.Join(tmpDir, "test.minisig")
		// Create a dummy signature file
		if err := os.WriteFile(sigFile, []byte("untrusted comment: signature\n"), 0644); err != nil {
			t.Fatalf("Failed to create signature file: %v", err)
		}

		missingFile := filepath.Join(tmpDir, "nonexistent.bin")
		err := verifySignature(missingFile, sigFile)
		if err == nil {
			t.Error("verifySignature() should fail with missing file")
		}
	})

	// Note: Testing valid signature verification would require:
	// 1. A real private key to sign test data
	// 2. Embedding the corresponding public key
	// This is skipped in unit tests to avoid key management complexity
	// Integration tests should cover real signature verification
}

// TestCheckUpdateLock tests update lock file handling
func TestCheckUpdateLock(t *testing.T) {
	// This test is challenging because checkUpdateLock() uses os.Executable()
	// which returns the test binary path, not a controllable path.
	// We'll test the logic indirectly by verifying the expected behavior.

	t.Run("no lock file", func(t *testing.T) {
		// With no lock file, should return false (allow update)
		blocked := checkUpdateLock("1.0.0")
		if blocked {
			t.Error("checkUpdateLock() should return false when no lock file exists")
		}
	})

	// Note: Full testing of lock file behavior requires file system mocking
	// or dependency injection, which is beyond the scope of these unit tests.
	// Integration tests should cover lock file creation and expiration.
}

// TestUpdateLockWorkflow tests the complete update lock workflow
func TestUpdateLockWorkflow(t *testing.T) {
	// Get executable directory
	exePath, err := os.Executable()
	if err != nil {
		t.Skip("Cannot get executable path")
	}
	exeDir := filepath.Dir(exePath)
	lockPath := filepath.Join(exeDir, UpdateLockFile)

	// Clean up any existing lock file
	os.Remove(lockPath)
	defer os.Remove(lockPath)

	version := "test-version-1.0.0"

	// Test 1: Create lock
	t.Run("create lock", func(t *testing.T) {
		createUpdateLock(version)

		// Verify lock file exists
		if _, err := os.Stat(lockPath); os.IsNotExist(err) {
			t.Error("Lock file was not created")
		}
	})

	// Test 2: Check lock blocks same version
	t.Run("lock blocks same version", func(t *testing.T) {
		blocked := checkUpdateLock(version)
		if !blocked {
			t.Error("Lock should block update to same version")
		}
	})

	// Test 3: Different version not blocked
	t.Run("different version allowed", func(t *testing.T) {
		blocked := checkUpdateLock("different-version-2.0.0")
		if blocked {
			t.Error("Lock should not block update to different version")
		}
	})

	// Test 4: Clear lock
	t.Run("clear lock", func(t *testing.T) {
		clearUpdateLock()

		// Verify lock file removed
		if _, err := os.Stat(lockPath); !os.IsNotExist(err) {
			t.Error("Lock file was not removed")
		}
	})

	// Test 5: After clearing, update allowed
	t.Run("update allowed after clear", func(t *testing.T) {
		blocked := checkUpdateLock(version)
		if blocked {
			t.Error("Update should be allowed after lock is cleared")
		}
	})
}

// Helper functions

func contains(s, substr string) bool {
	return len(s) >= len(substr) && findSubstring(s, substr) >= 0
}

func findSubstring(s, substr string) int {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return i
		}
	}
	return -1
}

func hasSuffix(s, suffix string) bool {
	return len(s) >= len(suffix) && s[len(s)-len(suffix):] == suffix
}
