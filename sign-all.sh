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

# Remove old signature files
OLD_SIGS=$(find "$DIST_DIR" -type f -name "*.minisig" 2>/dev/null | wc -l)
if [ "$OLD_SIGS" -gt 0 ]; then
    echo "Removing $OLD_SIGS old signature file(s)..."
    rm -f "$DIST_DIR"/*.minisig
    echo ""
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

# Check if expect is available for automated password entry
if command -v expect > /dev/null 2>&1; then
    # Prompt for password once
    echo "Enter signing key password (or press Enter if no password):"
    read -s MINISIGN_PASSWORD
    echo ""

    # Create temporary expect script
    EXPECT_SCRIPT=$(mktemp)
    cat > "$EXPECT_SCRIPT" <<'EXPECT_EOF'
#!/usr/bin/expect -f
set timeout 10
set password [lindex $argv 0]
set binary [lindex $argv 1]
set secret_key [lindex $argv 2]
set version [lindex $argv 3]

spawn minisign -Sm $binary -s $secret_key -t "modem-check v$version"
expect {
    "Password: " {
        send "$password\r"
        exp_continue
    }
    eof
}
EXPECT_EOF
    chmod +x "$EXPECT_SCRIPT"

    # Sign each binary
    COUNT=0
    for BINARY in $BINARIES; do
        COUNT=$((COUNT + 1))
        echo "[$COUNT/$BINARY_COUNT] Signing $(basename "$BINARY")..."

        "$EXPECT_SCRIPT" "$MINISIGN_PASSWORD" "$BINARY" "$MINISIGN_SECRET_KEY" "$VERSION" > /dev/null 2>&1

        if [ -f "${BINARY}.minisig" ]; then
            echo "  ✓ Signature created: $(basename "$BINARY").minisig"
        else
            echo "  ✗ Failed to create signature for $(basename "$BINARY")"
        fi
    done

    # Clean up
    rm -f "$EXPECT_SCRIPT"
else
    # No expect available, sign interactively
    echo "Note: 'expect' not found, you'll need to enter password for each binary"
    echo ""

    COUNT=0
    for BINARY in $BINARIES; do
        COUNT=$((COUNT + 1))
        echo "[$COUNT/$BINARY_COUNT] Signing $(basename "$BINARY")..."

        minisign -Sm "$BINARY" -s "$MINISIGN_SECRET_KEY" -t "modem-check v$VERSION"

        if [ -f "${BINARY}.minisig" ]; then
            echo "  ✓ Signature created: $(basename "$BINARY").minisig"
        else
            echo "  ✗ Failed to create signature"
        fi
    done
fi

echo ""
echo "========================================"
echo "All binaries signed successfully!"
echo ""
echo "Signatures created:"
ls -1 "$DIST_DIR"/*.minisig 2>/dev/null | sed 's/^/  /' || echo "  No signatures found"
echo "========================================"
