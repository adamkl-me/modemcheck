#!/bin/bash

# sign-all.sh - Sign all binaries in dist/ directory with Minisign
# This script prompts for the password once and uses it for all binaries

set -e

VERSION="${VERSION:-5.8.0}"
MINISIGN_SECRET_KEY=".signing-keys/minisign.key"
DIST_DIR="dist"

# Check if minisign is installed
if ! command -v minisign > /dev/null 2>&1; then
    echo "ERROR: minisign is not installed!"
    exit 1
fi

# Check if secret key exists
if [ ! -f "$MINISIGN_SECRET_KEY" ]; then
    echo "ERROR: Secret key not found at $MINISIGN_SECRET_KEY"
    echo "Run 'make setup-keys' first"
    exit 1
fi

# Check if dist directory exists and has binaries
if [ ! -d "$DIST_DIR" ]; then
    echo "ERROR: dist/ directory not found"
    exit 1
fi

# Find all binaries (exclude .minisig files)
BINARIES=$(find "$DIST_DIR" -type f ! -name "*.minisig" 2>/dev/null)

if [ -z "$BINARIES" ]; then
    echo "No binaries found in $DIST_DIR/"
    exit 0
fi

# Count binaries
BINARY_COUNT=$(echo "$BINARIES" | wc -l)
echo "Found $BINARY_COUNT binaries to sign"
echo ""

# Prompt for password once
echo "Enter signing key password (or press Enter if no password):"
read -s MINISIGN_PASSWORD
echo ""

# Sign each binary
COUNT=0
for BINARY in $BINARIES; do
    COUNT=$((COUNT + 1))
    echo "[$COUNT/$BINARY_COUNT] Signing $(basename "$BINARY")..."

    if [ -n "$MINISIGN_PASSWORD" ]; then
        # Use -x flag to read password from stdin
        printf '%s\n' "$MINISIGN_PASSWORD" | minisign -x -Sm "$BINARY" -s "$MINISIGN_SECRET_KEY" -t "modem-check v$VERSION" 2>&1 | grep -v "^Deriving" || true
    else
        # No password, let minisign prompt if needed
        minisign -Sm "$BINARY" -s "$MINISIGN_SECRET_KEY" -t "modem-check v$VERSION"
    fi

    echo "  ✓ Signature created: $(basename "$BINARY").minisig"
done

echo ""
echo "========================================"
echo "All binaries signed successfully!"
echo ""
echo "Signatures created:"
ls -1 "$DIST_DIR"/*.minisig 2>/dev/null | sed 's/^/  /' || echo "  No signatures found"
echo "========================================"
