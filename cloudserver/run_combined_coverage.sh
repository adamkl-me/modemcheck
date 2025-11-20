#!/bin/bash
#
# Run all tests and generate combined coverage report
#
# This script runs BOTH unit tests and E2E/integration tests, combining
# their coverage data to show total coverage across all test types.
# This provides the most comprehensive view of what code is tested.
#
# Output: htmlcov-combined/ directory with HTML coverage report
#
# Usage:
#   ./run_combined_coverage.sh
#   ./run_combined_coverage.sh --keep-env  # Keep Docker containers running

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
echo -e "${BLUE}Combined Test Coverage Report${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${BLUE}This will run:${NC}"
echo -e "  1. Unit tests (tests/unit/)"
echo -e "  2. E2E tests (tests/api/, tests/integration/, tests/security/)"
echo -e "  3. Combine coverage from both"
echo ""

# Remove previous coverage data
rm -f .coverage .coverage.*

# Step 1: Run unit tests
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Step 1/3: Running Unit Tests${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}ℹ Setting up virtual environment...${NC}"
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -q -r requirements.txt
else
    source .venv/bin/activate
fi

# Run unit tests with coverage
if pytest --cov-context=test --cov=app --cov-report= tests/unit/; then
    echo -e "${GREEN}✓ Unit tests passed${NC}"
    UNIT_PASSED=true
else
    echo -e "${RED}✗ Some unit tests failed${NC}"
    UNIT_PASSED=false
fi

# Save unit test coverage with unique suffix
if [ -f ".coverage" ]; then
    mv .coverage .coverage.unit
fi

# Step 2: Run E2E tests
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Step 2/3: Running E2E Tests${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Run E2E tests with the main script (handles Docker setup)
if $KEEP_ENV; then
    if ./run_all_tests.sh --keep-env tests/api/ tests/integration/ tests/security/; then
        echo -e "${GREEN}✓ E2E tests passed${NC}"
        E2E_PASSED=true
    else
        echo -e "${RED}✗ Some E2E tests failed${NC}"
        E2E_PASSED=false
    fi
else
    if ./run_all_tests.sh tests/api/ tests/integration/ tests/security/; then
        echo -e "${GREEN}✓ E2E tests passed${NC}"
        E2E_PASSED=true
    else
        echo -e "${RED}✗ Some E2E tests failed${NC}"
        E2E_PASSED=false
    fi
fi

# Save E2E coverage with unique suffix
if [ -f ".coverage" ]; then
    mv .coverage .coverage.e2e
fi

# Step 3: Combine coverage
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Step 3/3: Combining Coverage Data${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

if [ -f ".coverage.unit" ] && [ -f ".coverage.e2e" ]; then
    echo -e "${BLUE}ℹ Merging coverage from unit and E2E tests...${NC}"

    # Combine coverage data
    coverage combine .coverage.unit .coverage.e2e

    # Generate combined HTML report
    coverage html -d htmlcov-combined --show-contexts
    coverage report --format=markdown > coverage-combined.md

    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}Combined Coverage Report Complete${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo -e "${GREEN}✓ Combined coverage report: htmlcov-combined/index.html${NC}"
    echo -e "${GREEN}✓ Markdown summary: coverage-combined.md${NC}"
    echo ""
    echo -e "${BLUE}To view the report:${NC}"
    echo -e "  open htmlcov-combined/index.html"
    echo ""
    echo -e "${BLUE}What this shows:${NC}"
    echo -e "  - Combined coverage from ALL test types"
    echo -e "  - Shows what's tested by unit tests, E2E tests, or both"
    echo -e "  - Click any line to see which test(s) covered it"
    echo -e "  - Most comprehensive coverage view"
    echo ""

    # Print summary
    echo -e "${BLUE}Coverage Summary:${NC}"
    coverage report | tail -3

    # Cleanup temporary files
    rm -f .coverage.unit .coverage.e2e

    # Check if all tests passed
    if ! $UNIT_PASSED || ! $E2E_PASSED; then
        echo ""
        echo -e "${RED}⚠  Some tests failed (see above for details)${NC}"
        exit 1
    fi
else
    echo -e "${RED}✗ Missing coverage data files${NC}"
    echo -e "${RED}  Expected: .coverage.unit and .coverage.e2e${NC}"
    exit 1
fi
