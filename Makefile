# Modem-Check Makefile

BINARY_NAME=modem-check
GO_FILES=modem-check.go

# Version info
VERSION?=4.4.0
BUILD_TIME=$(shell date -u '+%Y-%m-%d_%H:%M:%S')
LDFLAGS=-ldflags "-s -w -X main.Version=$(VERSION) -X main.BuildTime=$(BUILD_TIME)"

.PHONY: all build clean test cross-compile help

all: build

# Build for current platform
build:
	@echo "Building $(BINARY_NAME)..."
	go build $(LDFLAGS) -o $(BINARY_NAME) $(GO_FILES)
	@echo "Build complete: ./$(BINARY_NAME)"

# Build with all optimizations for smallest size
build-small:
	@echo "Building optimized $(BINARY_NAME)..."
	go build $(LDFLAGS) -o $(BINARY_NAME) $(GO_FILES)
	@if command -v upx > /dev/null; then \
		echo "Compressing with UPX..."; \
		upx --best --lzma $(BINARY_NAME); \
	else \
		echo "UPX not found, skipping compression"; \
	fi

# Cross-compile for all platforms
cross-compile:
	@echo "Cross-compiling for multiple platforms..."
	@mkdir -p dist
	
	@echo "Building for Linux x64..."
	GOOS=linux GOARCH=amd64 go build $(LDFLAGS) -o dist/$(BINARY_NAME)-linux-x64 $(GO_FILES)
	
	@echo "Building for Linux ARM (32-bit)..."
	GOOS=linux GOARCH=arm go build $(LDFLAGS) -o dist/$(BINARY_NAME)-linux-arm $(GO_FILES)
	
	@echo "Building for Linux ARM64..."
	GOOS=linux GOARCH=arm64 go build $(LDFLAGS) -o dist/$(BINARY_NAME)-linux-arm64 $(GO_FILES)
	
	@echo "Building for Windows x64..."
	GOOS=windows GOARCH=amd64 go build $(LDFLAGS) -o dist/$(BINARY_NAME)-windows-x64.exe $(GO_FILES)
	
	@echo "Building for macOS x64 (Intel)..."
	GOOS=darwin GOARCH=amd64 go build $(LDFLAGS) -o dist/$(BINARY_NAME)-darwin-x64 $(GO_FILES)
	
	@echo "Building for macOS ARM64 (Apple Silicon)..."
	GOOS=darwin GOARCH=arm64 go build $(LDFLAGS) -o dist/$(BINARY_NAME)-darwin-arm64 $(GO_FILES)
	
	@echo "Building for FreeBSD x64..."
	GOOS=freebsd GOARCH=amd64 go build $(LDFLAGS) -o dist/$(BINARY_NAME)-freebsd-x64 $(GO_FILES)
	
	@echo ""
	@echo "Cross-compilation complete! Binaries in ./dist/"
	@ls -lh dist/

# Individual platform targets
linux:
	GOOS=linux GOARCH=amd64 go build $(LDFLAGS) -o $(BINARY_NAME)-linux-x64 $(GO_FILES)

linux-arm:
	GOOS=linux GOARCH=arm go build $(LDFLAGS) -o $(BINARY_NAME)-linux-arm $(GO_FILES)

linux-arm64:
	GOOS=linux GOARCH=arm64 go build $(LDFLAGS) -o $(BINARY_NAME)-linux-arm64 $(GO_FILES)

windows:
	GOOS=windows GOARCH=amd64 go build $(LDFLAGS) -o $(BINARY_NAME).exe $(GO_FILES)

macos:
	GOOS=darwin GOARCH=amd64 go build $(LDFLAGS) -o $(BINARY_NAME)-mac-intel $(GO_FILES)
	GOOS=darwin GOARCH=arm64 go build $(LDFLAGS) -o $(BINARY_NAME)-mac-arm $(GO_FILES)

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	@rm -f $(BINARY_NAME)
	@rm -f $(BINARY_NAME)-*
	@rm -rf dist/
	@echo "Clean complete"

# Run the program
run: build
	./$(BINARY_NAME)

# Test compilation
test:
	@echo "Testing compilation..."
	go build -o /tmp/$(BINARY_NAME)-test $(GO_FILES)
	@rm /tmp/$(BINARY_NAME)-test
	@echo "Compilation test passed!"

# Check dependencies
deps:
	@echo "Checking Go installation..."
	@go version
	@echo "Checking Go modules..."
	@go mod verify
	@echo "All dependencies OK! (No external dependencies required)"

# Show help
help:
	@echo "Modem-Check Build System"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
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
	@echo "  make                    # Build for current platform"
	@echo "  make cross-compile      # Build for all platforms"
	@echo "  make linux-arm          # Build for ARM devices"
	@echo "  make clean build        # Clean and rebuild"
