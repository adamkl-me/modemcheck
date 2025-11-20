#!/bin/bash
#
# Run E2E/integration tests and generate coverage report
#
# This script runs E2E and integration tests (tests/api/, tests/integration/,
# tests/security/) and generates a coverage report showing what's covered
# by E2E tests alone. This proves that routers, middleware, and endpoints
# ARE actually tested, even though they don't appear in unit test coverage.
#
# Output: htmlcov-e2e/ directory with HTML coverage report
#
# Usage:
#   ./run_e2e_coverage.sh
#   ./run_e2e_coverage.sh --keep-env  # Keep Docker containers running

set -euo pipefail

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Parse arguments
KEEP_ENV=false
if [[ "${1:-}" == "--keep-env" ]]; then
    KEEP_ENV=true
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}E2E Test Coverage Report${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Start test environment using main script's function
# We'll use the main run_tests.sh but only run E2E tests
echo -e "${BLUE}ℹ Starting test environment...${NC}"
echo -e "${YELLOW}  This requires Docker and will start test containers${NC}"
echo ""

# Remove previous coverage data to avoid contamination from unit tests
rm -f .coverage

# Run the main test script with E2E tests only
# Pass through the --keep-env flag if set
if $KEEP_ENV; then
    if ./run_tests.sh --keep-env tests/api/ tests/integration/ tests/security/; then
        TEST_PASSED=true
    else
        TEST_PASSED=false
    fi
else
    if ./run_tests.sh tests/api/ tests/integration/ tests/security/; then
        TEST_PASSED=true
    else
        TEST_PASSED=false
    fi
fi

# Generate HTML report with different directory
if [ -f ".coverage" ]; then
    echo ""
    echo -e "${BLUE}ℹ Generating E2E coverage HTML report...${NC}"

    # Activate venv if it exists
    if [ -d ".venv" ]; then
        source .venv/bin/activate
    fi

    # Generate HTML report
    coverage html -d htmlcov-e2e --show-contexts

    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}E2E Test Coverage Complete${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo -e "${GREEN}✓ E2E test coverage report: htmlcov-e2e/index.html${NC}"
    echo ""
    echo -e "${BLUE}To view the report:${NC}"
    echo -e "  open htmlcov-e2e/index.html"
    echo ""
    echo -e "${BLUE}What this shows:${NC}"
    echo -e "  - Coverage from E2E/integration tests only"
    echo -e "  - Tests that run against Docker environment via HTTP"
    echo -e "  - Proves app/routers/* and app/middleware/* ARE tested"
    echo -e "  - Click any line to see which E2E test covered it"
    echo ""

    if ! $TEST_PASSED; then
        echo -e "${RED}⚠  Some E2E tests failed (see above for details)${NC}"
        exit 1
    fi
else
    echo -e "${RED}✗ No coverage data generated${NC}"
    exit 1
fi
