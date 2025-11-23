#!/bin/bash
# ModemCheck Security Scan Script
# Scans Python and Go dependencies for known vulnerabilities

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "=================================================="
echo "  ModemCheck Security Dependency Scan"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "=================================================="
echo ""

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Track overall status
PYTHON_VULNS=0
GO_VULNS=0
SCANS_RUN=0

# ============================================================================
# PYTHON DEPENDENCY SCANNING (Safety)
# ============================================================================
echo "=== Python Dependency Scan (Safety) ==="
echo ""

cd "$PROJECT_ROOT/cloudserver"

# Check if safety is installed
if ! command -v safety &> /dev/null; then
    echo -e "${YELLOW}⚠ 'safety' not installed - skipping Python scan${NC}"
    echo ""
    echo -e "${BLUE}To install safety:${NC}"
    echo "  pip install safety"
    echo "  OR"
    echo "  pipx install safety  (recommended for externally-managed environments)"
    echo ""
else
    # Run safety check
    echo "Scanning Python dependencies in requirements.txt..."
    if safety check -r requirements.txt --json > /tmp/safety-report.json 2>&1; then
        echo -e "${GREEN}✓ No Python vulnerabilities found${NC}"
        PYTHON_VULNS=0
        SCANS_RUN=$((SCANS_RUN + 1))
    else
        PYTHON_STATUS=$?
        if [ $PYTHON_STATUS -eq 64 ]; then
            # Exit code 64 = vulnerabilities found
            PYTHON_VULNS=$(python3 -c "import json; data=json.load(open('/tmp/safety-report.json')); print(len(data.get('vulnerabilities', [])))" 2>/dev/null || echo "unknown")
            echo -e "${RED}✗ Found $PYTHON_VULNS Python vulnerabilities${NC}"
            echo ""
            echo "Summary:"
            safety check -r requirements.txt --short-report || true
            echo ""
            echo "Full report saved to: /tmp/safety-report.json"
            SCANS_RUN=$((SCANS_RUN + 1))
        else
            echo -e "${YELLOW}⚠ Safety check had issues (exit code: $PYTHON_STATUS)${NC}"
            PYTHON_VULNS=0
        fi
    fi
    echo ""
fi

# ============================================================================
# GO DEPENDENCY SCANNING (govulncheck)
# ============================================================================
echo "=== Go Dependency Scan (govulncheck) ==="
echo ""

cd "$PROJECT_ROOT/modemcheck-client"

# Check if govulncheck is installed
if ! command -v govulncheck &> /dev/null; then
    echo -e "${YELLOW}⚠ 'govulncheck' not installed - skipping Go scan${NC}"
    echo ""
    echo -e "${BLUE}To install govulncheck:${NC}"
    echo "  go install golang.org/x/vuln/cmd/govulncheck@latest"
    echo "  export PATH=\"\$PATH:\$(go env GOPATH)/bin\""
    echo ""
else
    # Run govulncheck
    echo "Scanning Go dependencies..."
    if govulncheck ./... > /tmp/govulncheck-report.txt 2>&1; then
        echo -e "${GREEN}✓ No Go vulnerabilities found${NC}"
        GO_VULNS=0
        SCANS_RUN=$((SCANS_RUN + 1))
    else
        GO_STATUS=$?
        # govulncheck exits with 3 when vulnerabilities are found
        if [ $GO_STATUS -eq 3 ] || grep -q "Vulnerability" /tmp/govulncheck-report.txt; then
            GO_VULNS=$(grep -c "Vulnerability" /tmp/govulncheck-report.txt || echo "unknown")
            echo -e "${RED}✗ Found $GO_VULNS Go vulnerabilities${NC}"
            echo ""
            echo "Summary:"
            head -n 50 /tmp/govulncheck-report.txt
            echo ""
            echo "Full report saved to: /tmp/govulncheck-report.txt"
            SCANS_RUN=$((SCANS_RUN + 1))
        else
            echo -e "${YELLOW}⚠ govulncheck had issues (exit code: $GO_STATUS)${NC}"
            head -n 20 /tmp/govulncheck-report.txt
            GO_VULNS=0
        fi
    fi
    echo ""
fi

# ============================================================================
# SUMMARY
# ============================================================================
echo "=================================================="
echo "  Security Scan Summary"
echo "=================================================="
echo ""
echo "Scans completed:        $SCANS_RUN/2"
echo "Python vulnerabilities: $PYTHON_VULNS"
echo "Go vulnerabilities:     $GO_VULNS"
echo ""

if [ $SCANS_RUN -eq 0 ]; then
    echo -e "${YELLOW}⚠ No scans were run - please install security tools${NC}"
    echo ""
    echo "Install both tools:"
    echo "  pip install safety  (or: pipx install safety)"
    echo "  go install golang.org/x/vuln/cmd/govulncheck@latest"
    exit 2
fi

TOTAL_VULNS=$((PYTHON_VULNS + GO_VULNS))

if [ "$TOTAL_VULNS" = "0" ]; then
    echo -e "${GREEN}✅ Security scan complete - No vulnerabilities found${NC}"
    echo ""
    echo "Next scan recommended: $(date -d '+7 days' '+%Y-%m-%d' 2>/dev/null || date -v +7d '+%Y-%m-%d' 2>/dev/null || echo 'in 7 days')"
    exit 0
else
    echo -e "${RED}❌ Security scan complete - vulnerabilities found${NC}"
    echo ""
    echo "Action required:"
    echo "  1. Review reports in /tmp/safety-report.json and /tmp/govulncheck-report.txt"
    echo "  2. Update vulnerable dependencies"
    echo "  3. Test thoroughly after updates"
    echo "  4. Re-run this scan to verify fixes"
    echo ""
    exit 1
fi
