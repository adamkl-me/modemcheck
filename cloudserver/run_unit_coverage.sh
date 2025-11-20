#!/bin/bash
#
# Run unit tests only and generate coverage report
#
# This script runs only pure unit tests (tests/unit/) and generates
# a coverage report showing what's covered by unit tests alone.
#
# Note: Even though these are unit tests, they still need the test environment
# (PostgreSQL/Redis containers) because conftest.py imports database fixtures.
#
# Output: htmlcov-unit/ directory with HTML coverage report
#
# Usage:
#   ./run_unit_coverage.sh
#   ./run_unit_coverage.sh --keep-env  # Keep containers running

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
echo -e "${BLUE}Unit Test Coverage Report${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${YELLOW}ℹ Unit tests require test environment (PostgreSQL/Redis)${NC}"
echo -e "${YELLOW}  Starting test containers...${NC}"
echo ""

# Remove previous coverage data
rm -f .coverage

# Run unit tests via main test script (handles Docker setup)
if $KEEP_ENV; then
    if ./run_all_tests.sh --keep-env tests/unit/; then
        TEST_PASSED=true
    else
        TEST_PASSED=false
    fi
else
    if ./run_all_tests.sh tests/unit/; then
        TEST_PASSED=true
    else
        TEST_PASSED=false
    fi
fi

# Generate HTML report in separate directory
if [ -f ".coverage" ]; then
    echo ""
    echo -e "${BLUE}ℹ Generating unit test coverage HTML report...${NC}"

    # Activate venv if it exists
    if [ -d ".venv" ]; then
        source .venv/bin/activate
    fi

    # Generate HTML report
    coverage html -d htmlcov-unit --show-contexts

    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}Unit Test Coverage Complete${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo -e "${GREEN}✓ Unit test coverage report: htmlcov-unit/index.html${NC}"
    echo ""
    echo -e "${BLUE}To view the report:${NC}"
    echo -e "  open htmlcov-unit/index.html"
    echo ""
    echo -e "${BLUE}What this shows:${NC}"
    echo -e "  - Coverage from unit tests only (tests/unit/)"
    echo -e "  - Pure function testing (ZIP security, cache stats, etc.)"
    echo -e "  - Target: 80-90% coverage on app/core/* modules"
    echo -e "  - Click lines to see which unit test covered them"
    echo ""

    if ! $TEST_PASSED; then
        echo -e "${RED}⚠  Some unit tests failed (see above for details)${NC}"
        exit 1
    fi
else
    echo -e "${RED}✗ No coverage data generated${NC}"
    exit 1
fi
