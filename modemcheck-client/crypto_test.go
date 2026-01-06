package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestEncryptDecryptAPIKey(t *testing.T) {
	tests := []struct {
		name    string
		apiKey  string
		wantErr bool
	}{
		{
			name:    "typical API key",
			apiKey:  "mc_test_abc123def456ghi789jkl012mno345pqr678stu901vwx234yz",
			wantErr: false,
		},
		{
			name:    "short key",
			apiKey:  "test123",
			wantErr: false,
		},
		{
			name:    "long key",
			apiKey:  "this_is_a_very_long_api_key_that_might_be_used_in_some_systems_with_extra_characters_1234567890",
			wantErr: false,
		},
		{
			name:    "special characters",
			apiKey:  "key-with_special.chars!@#$%^&*()",
			wantErr: false,
		},
		{
			name:    "empty key",
			apiKey:  "",
			wantErr: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Encrypt
			encrypted, err := encryptAPIKey(tt.apiKey)
			if (err != nil) != tt.wantErr {
				t.Errorf("encryptAPIKey() error = %v, wantErr %v", err, tt.wantErr)
				return
			}

			// Empty key should return nil
			if tt.apiKey == "" {
				if encrypted != nil {
					t.Errorf("encryptAPIKey() for empty key should return nil, got %v", encrypted)
				}
				return
			}

			// Verify encrypted struct has all fields
			if encrypted == nil {
				t.Fatal("encryptAPIKey() returned nil for non-empty key")
			}
			if encrypted.Version != encryptionVersion {
				t.Errorf("Version = %d, want %d", encrypted.Version, encryptionVersion)
			}
			if encrypted.Salt == "" {
				t.Error("Salt should not be empty")
			}
			if encrypted.Nonce == "" {
				t.Error("Nonce should not be empty")
			}
			if encrypted.Ciphertext == "" {
				t.Error("Ciphertext should not be empty")
			}

			// Decrypt
			decrypted, err := decryptAPIKey(encrypted)
			if err != nil {
				t.Errorf("decryptAPIKey() error = %v", err)
				return
			}

			// Verify round-trip
			if decrypted != tt.apiKey {
				t.Errorf("decryptAPIKey() = %v, want %v", decrypted, tt.apiKey)
			}
		})
	}
}

func TestDecryptAPIKeyNil(t *testing.T) {
	decrypted, err := decryptAPIKey(nil)
	if err != nil {
		t.Errorf("decryptAPIKey(nil) should not error, got %v", err)
	}
	if decrypted != "" {
		t.Errorf("decryptAPIKey(nil) should return empty string, got %q", decrypted)
	}
}

func TestDecryptAPIKeyInvalidVersion(t *testing.T) {
	encrypted := &EncryptedAPIKey{
		Version:    999, // Invalid version
		Salt:       "YWJjZGVmZ2hpamtsbW5vcA==",
		Nonce:      "YWJjZGVmZ2hpamts",
		Ciphertext: "dGVzdGNpcGhlcnRleHQ=",
	}

	_, err := decryptAPIKey(encrypted)
	if err == nil {
		t.Error("decryptAPIKey() should error on invalid version")
	}
}

func TestDecryptAPIKeyInvalidBase64(t *testing.T) {
	tests := []struct {
		name      string
		encrypted *EncryptedAPIKey
	}{
		{
			name: "invalid salt",
			encrypted: &EncryptedAPIKey{
				Version:    encryptionVersion,
				Salt:       "not-valid-base64!!!",
				Nonce:      "YWJjZGVmZ2hpamts",
				Ciphertext: "dGVzdGNpcGhlcnRleHQ=",
			},
		},
		{
			name: "invalid nonce",
			encrypted: &EncryptedAPIKey{
				Version:    encryptionVersion,
				Salt:       "YWJjZGVmZ2hpamtsbW5vcA==",
				Nonce:      "not-valid-base64!!!",
				Ciphertext: "dGVzdGNpcGhlcnRleHQ=",
			},
		},
		{
			name: "invalid ciphertext",
			encrypted: &EncryptedAPIKey{
				Version:    encryptionVersion,
				Salt:       "YWJjZGVmZ2hpamtsbW5vcA==",
				Nonce:      "YWJjZGVmZ2hpamts",
				Ciphertext: "not-valid-base64!!!",
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := decryptAPIKey(tt.encrypted)
			if err == nil {
				t.Errorf("decryptAPIKey() should error on %s", tt.name)
			}
		})
	}
}

func TestEncryptionProducesDifferentCiphertext(t *testing.T) {
	apiKey := "test_api_key_12345"

	// Encrypt the same key twice
	encrypted1, err := encryptAPIKey(apiKey)
	if err != nil {
		t.Fatalf("First encryption failed: %v", err)
	}

	encrypted2, err := encryptAPIKey(apiKey)
	if err != nil {
		t.Fatalf("Second encryption failed: %v", err)
	}

	// Salt and nonce should be different (random)
	if encrypted1.Salt == encrypted2.Salt {
		t.Error("Salt should be different for each encryption")
	}
	if encrypted1.Nonce == encrypted2.Nonce {
		t.Error("Nonce should be different for each encryption")
	}

	// Ciphertext should be different due to different nonce
	if encrypted1.Ciphertext == encrypted2.Ciphertext {
		t.Error("Ciphertext should be different for each encryption")
	}

	// Both should still decrypt to the same value
	decrypted1, _ := decryptAPIKey(encrypted1)
	decrypted2, _ := decryptAPIKey(encrypted2)
	if decrypted1 != apiKey || decrypted2 != apiKey {
		t.Error("Both encryptions should decrypt to the same original value")
	}
}

func TestMigrateAPIKey(t *testing.T) {
	t.Run("encrypted key present", func(t *testing.T) {
		// First encrypt a key to get valid encrypted data
		original := "test_api_key"
		encrypted, err := encryptAPIKey(original)
		if err != nil {
			t.Fatalf("Failed to encrypt key: %v", err)
		}

		config := &Configuration{
			CloudAPIKey:          "",
			EncryptedCloudAPIKey: encrypted,
		}

		migrated, err := migrateAPIKey(config)
		if err != nil {
			t.Errorf("migrateAPIKey() error = %v", err)
		}
		if migrated {
			t.Error("migrateAPIKey() should return false when key is already encrypted")
		}
		if config.CloudAPIKey != original {
			t.Errorf("CloudAPIKey = %q, want %q", config.CloudAPIKey, original)
		}
	})

	t.Run("plain text key present", func(t *testing.T) {
		config := &Configuration{
			CloudAPIKey:          "plain_text_key",
			EncryptedCloudAPIKey: nil,
		}

		migrated, err := migrateAPIKey(config)
		if err != nil {
			t.Errorf("migrateAPIKey() error = %v", err)
		}
		if !migrated {
			t.Error("migrateAPIKey() should return true when migrating plain text")
		}
		// Key should still be in CloudAPIKey (migration happens on save)
		if config.CloudAPIKey != "plain_text_key" {
			t.Errorf("CloudAPIKey should remain unchanged until save")
		}
	})

	t.Run("no key present", func(t *testing.T) {
		config := &Configuration{
			CloudAPIKey:          "",
			EncryptedCloudAPIKey: nil,
		}

		migrated, err := migrateAPIKey(config)
		if err != nil {
			t.Errorf("migrateAPIKey() error = %v", err)
		}
		if migrated {
			t.Error("migrateAPIKey() should return false when no key present")
		}
	})
}

func TestFixConfigPermissions(t *testing.T) {
	// Create a temp file
	tmpDir := t.TempDir()
	configPath := filepath.Join(tmpDir, "config.json")

	// Write a test file with permissive permissions
	if err := os.WriteFile(configPath, []byte("{}"), 0644); err != nil {
		t.Fatalf("Failed to create test file: %v", err)
	}

	// Fix permissions
	err := fixConfigPermissions(configPath)
	if err != nil {
		t.Errorf("fixConfigPermissions() error = %v", err)
	}

	// Check permissions (skip on Windows)
	if os.Getenv("GOOS") != "windows" {
		info, err := os.Stat(configPath)
		if err != nil {
			t.Fatalf("Failed to stat file: %v", err)
		}
		mode := info.Mode().Perm()
		if mode != 0600 {
			t.Errorf("File permissions = %o, want 0600", mode)
		}
	}
}

func TestSaveConfigurationAtomicEncrypts(t *testing.T) {
	tmpDir := t.TempDir()
	configPath := filepath.Join(tmpDir, "config.json")

	// Create config with plain text API key
	config := &Configuration{
		CloudHost:   "test.example.com",
		CloudPort:   "443",
		CloudAPIKey: "test_api_key_to_encrypt",
		EnableCloud: true,
	}

	// Save config
	err := SaveConfigurationAtomic(config, configPath)
	if err != nil {
		t.Fatalf("SaveConfigurationAtomic() error = %v", err)
	}

	// Load the saved config
	var loadedConfig Configuration
	err = LoadConfigFile(configPath, &loadedConfig)
	if err != nil {
		t.Fatalf("LoadConfigFile() error = %v", err)
	}

	// The loaded config should have the decrypted key
	if loadedConfig.CloudAPIKey != "test_api_key_to_encrypt" {
		t.Errorf("Loaded CloudAPIKey = %q, want %q", loadedConfig.CloudAPIKey, "test_api_key_to_encrypt")
	}

	// Read raw file to verify encryption
	data, err := os.ReadFile(configPath)
	if err != nil {
		t.Fatalf("Failed to read config file: %v", err)
	}

	// Raw file should NOT contain plain text API key
	if stringContains(string(data), "test_api_key_to_encrypt") {
		t.Error("Config file should not contain plain text API key")
	}

	// Raw file should contain EncryptedCloudAPIKey
	if !stringContains(string(data), "EncryptedCloudAPIKey") {
		t.Error("Config file should contain EncryptedCloudAPIKey")
	}
}

func stringContains(s, substr string) bool {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}

func TestGetMachineID(t *testing.T) {
	// This test verifies the machine ID can be obtained
	// The actual value varies per machine
	id, err := getMachineID()
	if err != nil {
		t.Fatalf("getMachineID() error = %v", err)
	}

	if id == "" {
		t.Error("getMachineID() returned empty string")
	}

	// Machine ID should be consistent
	id2, _ := getMachineID()
	if id != id2 {
		t.Error("getMachineID() should return consistent values")
	}
}
