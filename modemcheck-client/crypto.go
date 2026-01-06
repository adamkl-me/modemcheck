package main

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"fmt"
	"os"
	"runtime"

	"github.com/denisbrodbeck/machineid"
	"golang.org/x/crypto/pbkdf2"
)

const (
	// AppID is used to derive a unique machine ID for this application
	AppID = "modemcheck-client-v1"

	// PBKDF2 parameters for key derivation
	pbkdf2Iterations = 100000
	keyLen           = 32 // AES-256
	saltLen          = 16 // 128-bit salt
	nonceLen         = 12 // GCM standard nonce size

	// EncryptionVersion allows future algorithm changes
	encryptionVersion = 1
)

// EncryptedAPIKey stores the encrypted API key with all components needed for decryption.
// This is stored in the config file when API key encryption is enabled.
type EncryptedAPIKey struct {
	Version    int    `json:"version"`    // Encryption version for future compatibility
	Salt       string `json:"salt"`       // Base64 encoded salt for key derivation
	Nonce      string `json:"nonce"`      // Base64 encoded nonce for AES-GCM
	Ciphertext string `json:"ciphertext"` // Base64 encoded encrypted API key
}

// getMachineID returns a stable, application-specific machine identifier.
// The ID is derived from the machine's unique identifier and the application ID,
// making it unique per application while being stable across reboots.
func getMachineID() (string, error) {
	id, err := machineid.ProtectedID(AppID)
	if err != nil {
		return "", fmt.Errorf("failed to get machine ID: %w", err)
	}
	return id, nil
}

// deriveKey derives an AES-256 key from the machine ID and a random salt.
// Uses PBKDF2 with SHA-256 and 100,000 iterations.
func deriveKey(salt []byte) ([]byte, error) {
	machineID, err := getMachineID()
	if err != nil {
		return nil, err
	}

	key := pbkdf2.Key([]byte(machineID), salt, pbkdf2Iterations, keyLen, sha256.New)
	return key, nil
}

// encryptAPIKey encrypts an API key using AES-256-GCM with a machine-derived key.
// Returns nil if the input key is empty.
func encryptAPIKey(plainKey string) (*EncryptedAPIKey, error) {
	if plainKey == "" {
		return nil, nil // Nothing to encrypt
	}

	// Generate random salt for key derivation
	salt := make([]byte, saltLen)
	if _, err := rand.Read(salt); err != nil {
		return nil, fmt.Errorf("failed to generate salt: %w", err)
	}

	// Derive encryption key from machine ID and salt
	key, err := deriveKey(salt)
	if err != nil {
		return nil, err
	}

	// Create AES cipher
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, fmt.Errorf("failed to create cipher: %w", err)
	}

	// Create GCM mode for authenticated encryption
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, fmt.Errorf("failed to create GCM: %w", err)
	}

	// Generate random nonce
	nonce := make([]byte, nonceLen)
	if _, err := rand.Read(nonce); err != nil {
		return nil, fmt.Errorf("failed to generate nonce: %w", err)
	}

	// Encrypt the API key
	// #nosec G407 -- nonce is randomly generated via crypto/rand.Read() above, not hardcoded
	ciphertext := gcm.Seal(nil, nonce, []byte(plainKey), nil)

	return &EncryptedAPIKey{
		Version:    encryptionVersion,
		Salt:       base64.StdEncoding.EncodeToString(salt),
		Nonce:      base64.StdEncoding.EncodeToString(nonce),
		Ciphertext: base64.StdEncoding.EncodeToString(ciphertext),
	}, nil
}

// decryptAPIKey decrypts an encrypted API key using AES-256-GCM.
// Returns empty string if the input is nil.
func decryptAPIKey(encrypted *EncryptedAPIKey) (string, error) {
	if encrypted == nil {
		return "", nil // Nothing to decrypt
	}

	// Verify encryption version
	if encrypted.Version != encryptionVersion {
		return "", fmt.Errorf("unsupported encryption version: %d (expected %d)", encrypted.Version, encryptionVersion)
	}

	// Decode base64 components
	salt, err := base64.StdEncoding.DecodeString(encrypted.Salt)
	if err != nil {
		return "", fmt.Errorf("failed to decode salt: %w", err)
	}

	nonce, err := base64.StdEncoding.DecodeString(encrypted.Nonce)
	if err != nil {
		return "", fmt.Errorf("failed to decode nonce: %w", err)
	}

	ciphertext, err := base64.StdEncoding.DecodeString(encrypted.Ciphertext)
	if err != nil {
		return "", fmt.Errorf("failed to decode ciphertext: %w", err)
	}

	// Derive key from machine ID and salt
	key, err := deriveKey(salt)
	if err != nil {
		return "", err
	}

	// Create AES cipher
	block, err := aes.NewCipher(key)
	if err != nil {
		return "", fmt.Errorf("failed to create cipher: %w", err)
	}

	// Create GCM mode
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", fmt.Errorf("failed to create GCM: %w", err)
	}

	// Decrypt and verify
	plaintext, err := gcm.Open(nil, nonce, ciphertext, nil)
	if err != nil {
		return "", fmt.Errorf("decryption failed (wrong machine or corrupted data): %w", err)
	}

	return string(plaintext), nil
}

// fixConfigPermissions ensures the config file has secure permissions (0600).
// On Windows, this is a no-op since Windows uses ACLs instead of Unix permissions.
func fixConfigPermissions(configPath string) error {
	if runtime.GOOS == "windows" {
		// Windows uses ACLs, not Unix permissions
		// The file inherits permissions from the directory
		return nil
	}

	// Set restrictive permissions: owner read/write only
	if err := chmodFunc(configPath, 0600); err != nil {
		return fmt.Errorf("failed to set config file permissions: %w", err)
	}
	return nil
}

// chmodFunc is a variable to allow mocking in tests
var chmodFunc = defaultChmod

// defaultChmod is the default chmod implementation using os.Chmod
func defaultChmod(name string, mode uint32) error {
	return osChmodWrapper(name, mode)
}

// osChmodWrapper wraps os.Chmod with uint32 mode for easier testing
func osChmodWrapper(name string, mode uint32) error {
	return os.Chmod(name, os.FileMode(mode))
}
