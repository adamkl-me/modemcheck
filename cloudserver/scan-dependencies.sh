#!/bin/bash
#
# Local Dependency Security Scanning Script
# Scans Python dependencies for known vulnerabilities
#
# Usage: ./scan-dependencies.sh
# Exit codes: 0 = no vulnerabilities, 1 = vulnerabilities found

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=================================="
echo "Dependency Security Scan"
echo "=================================="
echo ""

# Check if pip-audit is installed
if ! command -v pip-audit &> /dev/null; then
    echo -e "${YELLOW}Installing pip-audit...${NC}"
    pip install pip-audit
fi

# Check if safety is installed
if ! command -v safety &> /dev/null; then
    echo -e "${YELLOW}Installing safety...${NC}"
    pip install safety
fi

echo "[1/3] Running pip-audit (vulnerability scanner)..."
echo ""

if pip-audit --desc; then
    echo -e "${GREEN}✓ No vulnerabilities found by pip-audit${NC}"
    AUDIT_STATUS=0
else
    echo -e "${RED}✗ Vulnerabilities found by pip-audit${NC}"
    AUDIT_STATUS=1
fi

echo ""
echo "[2/3] Running Safety (security advisories)..."
echo ""

if safety check --output text; then
    echo -e "${GREEN}✓ No security advisories from Safety${NC}"
    SAFETY_STATUS=0
else
    echo -e "${RED}✗ Security advisories found by Safety${NC}"
    SAFETY_STATUS=1
fi

echo ""
echo "[3/3] Checking for outdated packages..."
echo ""

pip list --outdated --format=columns | head -20

echo ""
echo "=================================="
echo "Scan Summary"
echo "=================================="

if [ $AUDIT_STATUS -eq 0 ] && [ $SAFETY_STATUS -eq 0 ]; then
    echo -e "${GREEN}✓ No vulnerabilities detected${NC}"
    echo ""
    echo "All dependencies are secure."
    exit 0
else
    echo -e "${RED}✗ Vulnerabilities detected${NC}"
    echo ""
    echo "Please review the output above and update vulnerable packages."
    echo ""
    echo "To update a package:"
    echo "  pip install --upgrade <package-name>"
    echo ""
    echo "To update all packages:"
    echo "  pip install --upgrade -r requirements.txt"
    exit 1
fi
