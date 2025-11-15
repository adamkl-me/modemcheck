# Modem-Check Makefile

BINARY_NAME=modem-check
SOURCE_DIR=modemcheck-client

# Version info
VERSION?=6.0.0-test.1
BUILD_TIME=$(shell date -u '+%Y-%m-%d_%H:%M:%S')
LDFLAGS=-ldflags "-s -w -X main.Version=$(VERSION) -X main.BuildTime=$(BUILD_TIME)"

# Signing keys
MINISIGN_KEY_DIR=.signing-keys
MINISIGN_SECRET_KEY=$(MINISIGN_KEY_DIR)/minisign.key
MINISIGN_PUBLIC_KEY=$(MINISIGN_KEY_DIR)/minisign.pub

.PHONY: all build clean test cross-compile help setup-keys sign-binary update-public-key

# Default target: cross-compile for all platforms
all: cross-compile

# Setup Minisign signing keys (auto-generates if not present)
setup-keys:
	@echo "Checking for Minisign installation..."
	@if ! command -v minisign > /dev/null 2>&1; then \
		echo "ERROR: minisign is not installed!"; \
		echo ""; \
		echo "Please install minisign:"; \
		echo "  macOS:   brew install minisign"; \
		echo "  Debian:  apt-get install minisign"; \
		echo "  Fedora:  dnf install minisign"; \
		echo "  Arch:    pacman -S minisign"; \
		echo "  Other:   https://jedisct1.github.io/minisign/"; \
		exit 1; \
	fi
	@if [ ! -f "$(MINISIGN_SECRET_KEY)" ]; then \
		echo "No signing keys found. Generating new Minisign key pair..."; \
		mkdir -p $(MINISIGN_KEY_DIR); \
		echo ""; \
		echo "========================================"; \
		echo "You will be prompted to set a password for the secret key."; \
		echo "Press Enter for no password (not recommended for production)."; \
		echo "========================================"; \
		echo ""; \
		cd $(MINISIGN_KEY_DIR) && minisign -G -p minisign.pub -s minisign.key; \
		echo ""; \
		echo "✓ Keys generated in $(MINISIGN_KEY_DIR)/"; \
		echo "✓ IMPORTANT: Backup your secret key securely!"; \
		echo "✓ Add $(MINISIGN_KEY_DIR)/ to .gitignore to prevent committing keys"; \
		$(MAKE) update-public-key; \
	else \
		echo "✓ Signing keys already exist at $(MINISIGN_KEY_DIR)/"; \
	fi

# Update the public key in the Go source code
update-public-key:
	@if [ ! -f "$(MINISIGN_PUBLIC_KEY)" ]; then \
		echo "ERROR: Public key file not found at $(MINISIGN_PUBLIC_KEY)"; \
		echo "Run 'make setup-keys' first"; \
		exit 1; \
	fi
	@echo "Updating public key in source code..."
	@PUBLIC_KEY=$$(cat $(MINISIGN_PUBLIC_KEY)); \
	if grep -q "PLACEHOLDER.*REPLACE_WITH_ACTUAL_KEY" $(SOURCE_DIR)/updater.go; then \
		sed -i "s|MinisignPublicKey = \"RWQ.*PLACEHOLDER.*REPLACE_WITH_ACTUAL_KEY\"|MinisignPublicKey = \"$$PUBLIC_KEY\"|g" $(SOURCE_DIR)/updater.go; \
		echo "✓ Public key embedded in $(SOURCE_DIR)/updater.go"; \
	else \
		echo "✓ Public key already configured (or placeholder not found)"; \
		echo "  Current key: $$PUBLIC_KEY"; \
	fi

# Validate that the hardcoded public key matches the actual public key file
# This prevents build system compromise from embedding a different key
validate-public-key:
	@if [ ! -f "$(MINISIGN_PUBLIC_KEY)" ]; then \
		echo "ERROR: Public key file not found at $(MINISIGN_PUBLIC_KEY)"; \
		echo "Cannot validate embedded public key without reference key file"; \
		exit 1; \
	fi
	@echo "Validating embedded public key..."
	@EXPECTED_KEY=$$(tail -n 1 $(MINISIGN_PUBLIC_KEY)); \
	EMBEDDED_KEY=$$(grep "MinisignPublicKey = " $(SOURCE_DIR)/updater.go | sed 's/.*"\(RW[^"]*\)".*/\1/'); \
	if [ "$$EMBEDDED_KEY" != "$$EXPECTED_KEY" ]; then \
		echo ""; \
		echo "❌ SECURITY ERROR: Embedded public key does NOT match key file!"; \
		echo ""; \
		echo "Expected (from $(MINISIGN_PUBLIC_KEY)):"; \
		echo "  $$EXPECTED_KEY"; \
		echo ""; \
		echo "Found in $(SOURCE_DIR)/updater.go:"; \
		echo "  $$EMBEDDED_KEY"; \
		echo ""; \
		echo "This could indicate:"; \
		echo "  1. Build system compromise"; \
		echo "  2. Manual code modification"; \
		echo "  3. Key rotation without updating source code"; \
		echo ""; \
		echo "ACTION REQUIRED:"; \
		echo "  Run 'make update-public-key' to sync keys"; \
		echo "  Or investigate potential security breach"; \
		echo ""; \
		exit 1; \
	fi
	@echo "✓ Embedded public key matches $(MINISIGN_PUBLIC_KEY)"

# Sign a binary with Minisign
# Usage: make sign-binary BINARY=path/to/binary
sign-binary:
	@if [ -z "$(BINARY)" ]; then \
		echo "ERROR: BINARY parameter required"; \
		echo "Usage: make sign-binary BINARY=path/to/binary"; \
		exit 1; \
	fi
	@if [ ! -f "$(BINARY)" ]; then \
		echo "ERROR: Binary not found: $(BINARY)"; \
		exit 1; \
	fi
	@if [ ! -f "$(MINISIGN_SECRET_KEY)" ]; then \
		echo "ERROR: Secret key not found. Run 'make setup-keys' first"; \
		exit 1; \
	fi
	@echo "Signing $(BINARY)..."
	@minisign -Sm "$(BINARY)" -s "$(MINISIGN_SECRET_KEY)" -t "modem-check v$(VERSION)"
	@echo "✓ Signature created: $(BINARY).minisig"

# Build for current platform
build: validate-public-key
	@echo "Building $(BINARY_NAME)..."
	cd $(SOURCE_DIR) && go build $(LDFLAGS) -o ../$(BINARY_NAME) .
	@echo "Build complete: ./$(BINARY_NAME)"

# Build with all optimizations for smallest size
build-small:
	@echo "Building optimized $(BINARY_NAME)..."
	cd $(SOURCE_DIR) && go build $(LDFLAGS) -o ../$(BINARY_NAME) .
	@if command -v upx > /dev/null; then \
		echo "Compressing with UPX..."; \
		upx --best --lzma ../$(BINARY_NAME); \
	else \
		echo "UPX not found, skipping compression"; \
	fi

# Cross-compile for all platforms
cross-compile: setup-keys validate-public-key
	@echo "Cross-compiling for multiple platforms (v$(VERSION))..."
	@mkdir -p dist
	@echo ""
	@echo "Building for Linux x64..."
	-cd $(SOURCE_DIR) && GOOS=linux GOARCH=amd64 go build $(LDFLAGS) -o ../dist/$(BINARY_NAME)-linux-x64 .

	@echo "Building for Linux ARM (32-bit)..."
	-cd $(SOURCE_DIR) && GOOS=linux GOARCH=arm go build $(LDFLAGS) -o ../dist/$(BINARY_NAME)-linux-arm .

	@echo "Building for Linux ARM64..."
	-cd $(SOURCE_DIR) && GOOS=linux GOARCH=arm64 go build $(LDFLAGS) -o ../dist/$(BINARY_NAME)-linux-arm64 .

	@echo "Building for Linux MIPS (little-endian)..."
	-cd $(SOURCE_DIR) && GOOS=linux GOARCH=mipsle GOMIPS=softfloat go build $(LDFLAGS) -o ../dist/$(BINARY_NAME)-linux-mipsle .

	@echo "Building for Linux MIPS (big-endian)..."
	-cd $(SOURCE_DIR) && GOOS=linux GOARCH=mips GOMIPS=softfloat go build $(LDFLAGS) -o ../dist/$(BINARY_NAME)-linux-mips .

	@echo "Building for Windows x64..."
	-cd $(SOURCE_DIR) && GOOS=windows GOARCH=amd64 go build $(LDFLAGS) -o ../dist/$(BINARY_NAME)-windows-x64.exe .

	@echo "Building for macOS x64 (Intel)..."
	-cd $(SOURCE_DIR) && GOOS=darwin GOARCH=amd64 go build $(LDFLAGS) -o ../dist/$(BINARY_NAME)-darwin-x64 . || echo "  Warning: macOS x64 build failed (cross-compile limitation)"

	@echo "Building for macOS ARM64 (Apple Silicon)..."
	-cd $(SOURCE_DIR) && GOOS=darwin GOARCH=arm64 go build $(LDFLAGS) -o ../dist/$(BINARY_NAME)-darwin-arm64 . || echo "  Warning: macOS ARM64 build failed (cross-compile limitation)"

	@echo "Building for FreeBSD x64..."
	-cd $(SOURCE_DIR) && GOOS=freebsd GOARCH=amd64 go build $(LDFLAGS) -o ../dist/$(BINARY_NAME)-freebsd-x64 . || echo "  Warning: FreeBSD build failed (cross-compile limitation)"

	@echo ""
	@echo "========================================"
	@echo "Builds complete! Now signing binaries..."
	@echo "========================================"
	@VERSION=$(VERSION) ./sign-all.sh

# Individual platform targets (without version in filename)
linux:
	cd $(SOURCE_DIR) && GOOS=linux GOARCH=amd64 go build $(LDFLAGS) -o ../$(BINARY_NAME)-linux-x64 .

linux-arm:
	cd $(SOURCE_DIR) && GOOS=linux GOARCH=arm go build $(LDFLAGS) -o ../$(BINARY_NAME)-linux-arm .

linux-arm64:
	cd $(SOURCE_DIR) && GOOS=linux GOARCH=arm64 go build $(LDFLAGS) -o ../$(BINARY_NAME)-linux-arm64 .

linux-mipsle:
	cd $(SOURCE_DIR) && GOOS=linux GOARCH=mipsle GOMIPS=softfloat go build $(LDFLAGS) -o ../$(BINARY_NAME)-linux-mipsle .

linux-mips:
	cd $(SOURCE_DIR) && GOOS=linux GOARCH=mips GOMIPS=softfloat go build $(LDFLAGS) -o ../$(BINARY_NAME)-linux-mips .

windows:
	cd $(SOURCE_DIR) && GOOS=windows GOARCH=amd64 go build $(LDFLAGS) -o ../$(BINARY_NAME)-windows-x64.exe .

macos:
	cd $(SOURCE_DIR) && GOOS=darwin GOARCH=amd64 go build $(LDFLAGS) -o ../$(BINARY_NAME)-darwin-x64 .
	cd $(SOURCE_DIR) && GOOS=darwin GOARCH=arm64 go build $(LDFLAGS) -o ../$(BINARY_NAME)-darwin-arm64 .

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	@rm -f $(BINARY_NAME)
	@rm -f $(BINARY_NAME)-*
	@rm -rf dist/
	@echo "Clean complete"

# Clean everything including signing keys (use with caution!)
clean-all: clean
	@echo "WARNING: This will delete signing keys!"
	@echo "Press Ctrl+C to cancel, or Enter to continue..."
	@read dummy
	@rm -rf $(MINISIGN_KEY_DIR)/
	@echo "All artifacts and keys removed"

# Run the program
run: build
	./$(BINARY_NAME)

# Test compilation
test:
	@echo "Testing compilation..."
	cd $(SOURCE_DIR) && go build -o /tmp/$(BINARY_NAME)-test .
	@rm /tmp/$(BINARY_NAME)-test
	@echo "Compilation test passed!"

# Check dependencies
deps:
	@echo "Checking Go installation..."
	@go version
	@echo "Checking Go modules..."
	cd $(SOURCE_DIR) && go mod verify
	@echo "Dependencies OK!"

# Show help
help:
	@echo "Modem-Check Build System"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Build Targets:"
	@echo "  all              Cross-compile for all platforms with signing (default)"
	@echo "  build            Build for current platform"
	@echo "  build-small      Build optimized binary with UPX compression"
	@echo "  cross-compile    Build for all supported platforms with signing"
	@echo "  linux            Build for Linux x64"
	@echo "  linux-arm        Build for Linux ARM (32-bit)"
	@echo "  linux-arm64      Build for Linux ARM64"
	@echo "  linux-mipsle     Build for Linux MIPS (little-endian, most routers)"
	@echo "  linux-mips       Build for Linux MIPS (big-endian)"
	@echo "  windows          Build for Windows x64"
	@echo "  macos            Build for macOS (Intel + Apple Silicon)"
	@echo ""
	@echo "Security Targets:"
	@echo "  setup-keys       Generate Minisign keys for signing releases"
	@echo "  update-public-key Update embedded public key in source code"
	@echo "  sign-binary      Sign a binary (Usage: make sign-binary BINARY=path)"
	@echo ""
	@echo "Utility Targets:"
	@echo "  run              Build and run the program"
	@echo "  test             Test that code compiles"
	@echo "  clean            Remove build artifacts"
	@echo "  clean-all        Remove build artifacts AND signing keys"
	@echo "  deps             Check dependencies"
	@echo "  help             Show this help message"
	@echo ""
	@echo "Examples:"
	@echo "  make                           # Cross-compile all platforms with auto-signing"
	@echo "  make setup-keys                # Generate signing keys (one-time setup)"
	@echo "  make build                     # Build for current platform only"
	@echo "  make linux-arm64               # Build for ARM64 devices"
	@echo "  make clean all                 # Clean and rebuild all platforms"
	@echo "  make sign-binary BINARY=dist/modem-check-linux-x64  # Sign a specific binary"
	@echo ""
	@echo "Note: Cross-compilation automatically generates keys and signs binaries"
