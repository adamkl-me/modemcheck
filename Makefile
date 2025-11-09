# Modem-Check Makefile

BINARY_NAME=modem-check
SOURCE_DIR=modemcheck-client

# Version info
VERSION?=5.0.0
BUILD_TIME=$(shell date -u '+%Y-%m-%d_%H:%M:%S')
LDFLAGS=-ldflags "-s -w -X main.Version=$(VERSION) -X main.BuildTime=$(BUILD_TIME)"

.PHONY: all build clean test cross-compile help

# Default target: cross-compile for all platforms
all: cross-compile

# Build for current platform
build:
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
cross-compile:
	@echo "Cross-compiling for multiple platforms..."
	@mkdir -p dist

	@echo "Building for Linux x64..."
	-cd $(SOURCE_DIR) && GOOS=linux GOARCH=amd64 go build $(LDFLAGS) -o ../dist/$(BINARY_NAME)-linux-x64 .

	@echo "Building for Linux ARM (32-bit)..."
	-cd $(SOURCE_DIR) && GOOS=linux GOARCH=arm go build $(LDFLAGS) -o ../dist/$(BINARY_NAME)-linux-arm .

	@echo "Building for Linux ARM64..."
	-cd $(SOURCE_DIR) && GOOS=linux GOARCH=arm64 go build $(LDFLAGS) -o ../dist/$(BINARY_NAME)-linux-arm64 .

	@echo "Building for Windows x64..."
	-cd $(SOURCE_DIR) && GOOS=windows GOARCH=amd64 go build $(LDFLAGS) -o ../dist/$(BINARY_NAME)-windows-x64.exe .

	@echo "Building for macOS x64 (Intel)..."
	-cd $(SOURCE_DIR) && GOOS=darwin GOARCH=amd64 go build $(LDFLAGS) -o ../dist/$(BINARY_NAME)-darwin-x64 . || echo "  Warning: macOS x64 build failed (cross-compile limitation)"

	@echo "Building for macOS ARM64 (Apple Silicon)..."
	-cd $(SOURCE_DIR) && GOOS=darwin GOARCH=arm64 go build $(LDFLAGS) -o ../dist/$(BINARY_NAME)-darwin-arm64 . || echo "  Warning: macOS ARM64 build failed (cross-compile limitation)"

	@echo "Building for FreeBSD x64..."
	-cd $(SOURCE_DIR) && GOOS=freebsd GOARCH=amd64 go build $(LDFLAGS) -o ../dist/$(BINARY_NAME)-freebsd-x64 . || echo "  Warning: FreeBSD build failed (cross-compile limitation)"

	@echo ""
	@echo "Cross-compilation complete! Built binaries:"
	@ls -lh dist/ 2>/dev/null || echo "No binaries built"

# Individual platform targets
linux:
	cd $(SOURCE_DIR) && GOOS=linux GOARCH=amd64 go build $(LDFLAGS) -o ../$(BINARY_NAME)-linux-x64 .

linux-arm:
	cd $(SOURCE_DIR) && GOOS=linux GOARCH=arm go build $(LDFLAGS) -o ../$(BINARY_NAME)-linux-arm .

linux-arm64:
	cd $(SOURCE_DIR) && GOOS=linux GOARCH=arm64 go build $(LDFLAGS) -o ../$(BINARY_NAME)-linux-arm64 .

windows:
	cd $(SOURCE_DIR) && GOOS=windows GOARCH=amd64 go build $(LDFLAGS) -o ../$(BINARY_NAME).exe .

macos:
	cd $(SOURCE_DIR) && GOOS=darwin GOARCH=amd64 go build $(LDFLAGS) -o ../$(BINARY_NAME)-mac-intel .
	cd $(SOURCE_DIR) && GOOS=darwin GOARCH=arm64 go build $(LDFLAGS) -o ../$(BINARY_NAME)-mac-arm .

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	@rm -f $(BINARY_NAME)
	@rm -f $(BINARY_NAME)-*
	@rm -f dist/$(BINARY_NAME)-*
	@echo "Clean complete"

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
	@echo "Targets:"
	@echo "  all              Cross-compile for all platforms (default)"
	@echo "  build            Build for current platform"
	@echo "  build-small      Build optimized binary with compression"
	@echo "  cross-compile    Build for all supported platforms"
	@echo "  linux            Build for Linux x64"
	@echo "  linux-arm        Build for Linux ARM (32-bit)"
	@echo "  linux-arm64      Build for Linux ARM64"
	@echo "  windows          Build for Windows x64"
	@echo "  macos            Build for macOS (Intel + Apple Silicon)"
	@echo "  run              Build and run the program"
	@echo "  test             Test that code compiles"
	@echo "  clean            Remove build artifacts"
	@echo "  deps             Check dependencies"
	@echo "  help             Show this help message"
	@echo ""
	@echo "Examples:"
	@echo "  make                    # Cross-compile for all platforms (default)"
	@echo "  make build              # Build for current platform only"
	@echo "  make linux-arm64        # Build for ARM64 devices"
	@echo "  make clean all          # Clean and rebuild all platforms"
