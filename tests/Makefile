# Modemcheck Testing Makefile
# Provides convenient shortcuts for running tests

.PHONY: all setup cleanup go-test python-test e2e-test coverage help

# Default target - run all tests
all: test

# Run complete test suite with setup and cleanup
test:
	@echo "Running complete test suite..."
	@./test_env_setup.sh all

# Set up test environment only
setup:
	@echo "Setting up test environment..."
	@./test_env_setup.sh setup

# Clean up test environment only
cleanup:
	@echo "Cleaning up test environment..."
	@./test_env_setup.sh cleanup

# Run Go unit tests only
go-test:
	@echo "Running Go unit tests..."
	@cd .. && go test -v -cover ./...

# Run Go tests with coverage report
go-coverage:
	@echo "Running Go tests with coverage..."
	@cd .. && go test -coverprofile=coverage.out ./...
	@cd .. && go tool cover -html=coverage.out -o tests/coverage-go.html
	@echo "Coverage report: tests/coverage-go.html"

# Run Python integration tests only
python-test:
	@echo "Running Python integration tests..."
	@pytest test_cloud_api.py -v

# Run Python tests with coverage
python-coverage:
	@echo "Running Python tests with coverage..."
	@pytest test_cloud_api.py -v --cov --cov-report=html
	@echo "Coverage report: htmlcov/index.html"

# Run end-to-end tests only (requires setup first)
e2e-test:
	@echo "Running end-to-end tests..."
	@./test_e2e.sh

# Run all coverage reports
coverage: go-coverage python-coverage
	@echo "All coverage reports generated!"

# Quick test - Go unit tests only (no Docker needed)
quick:
	@echo "Running quick tests (Go unit tests only)..."
	@cd .. && go test -v ./...

# Install test dependencies
install:
	@echo "Installing test dependencies..."
	@pip3 install -r requirements.txt

# Check if dependencies are installed
check:
	@echo "Checking dependencies..."
	@command -v go >/dev/null 2>&1 || { echo "ERROR: Go not installed"; exit 1; }
	@command -v python3 >/dev/null 2>&1 || { echo "ERROR: Python3 not installed"; exit 1; }
	@command -v docker >/dev/null 2>&1 || { echo "ERROR: Docker not installed"; exit 1; }
	@command -v pytest >/dev/null 2>&1 || { echo "WARNING: pytest not installed. Run 'make install'"; }
	@echo "All dependencies OK!"

# Watch mode - run Go tests on file changes (requires entr)
watch:
	@echo "Watching for changes... (Ctrl+C to stop)"
	@cd .. && ls *.go | entr -c go test -v ./...

# Benchmark Go code
bench:
	@echo "Running Go benchmarks..."
	@cd .. && go test -bench=. -benchmem ./...

# Show test logs from container
logs:
	@docker logs modemcheck-cloud-test

# Interactive shell in test container
shell:
	@docker exec -it modemcheck-cloud-test sh

# Show test statistics
stats:
	@echo "=== Test Statistics ==="
	@echo ""
	@echo "Go Tests:"
	@cd .. && go test -v ./... 2>&1 | grep -E "^(PASS|FAIL|ok|---)" | tail -5 || echo "Run 'make go-test' first"
	@echo ""
	@echo "Python Tests:"
	@pytest test_cloud_api.py --collect-only -q 2>/dev/null || echo "Run 'make python-test' first"
	@echo ""
	@echo "E2E Tests:"
	@grep -c "^test_" test_e2e.sh || echo "13 tests defined"

# Help target
help:
	@echo "Modemcheck Test Makefile"
	@echo ""
	@echo "Usage:"
	@echo "  make [target]"
	@echo ""
	@echo "Common Targets:"
	@echo "  all, test      - Run complete test suite (default)"
	@echo "  quick          - Run Go unit tests only (fast, no Docker)"
	@echo "  setup          - Set up test environment"
	@echo "  cleanup        - Clean up test environment"
	@echo "  coverage       - Generate coverage reports for all tests"
	@echo ""
	@echo "Individual Test Suites:"
	@echo "  go-test        - Run Go unit tests"
	@echo "  python-test    - Run Python integration tests"
	@echo "  e2e-test       - Run end-to-end tests"
	@echo ""
	@echo "Coverage:"
	@echo "  go-coverage    - Go tests with HTML coverage report"
	@echo "  python-coverage - Python tests with HTML coverage report"
	@echo ""
	@echo "Utilities:"
	@echo "  install        - Install Python test dependencies"
	@echo "  check          - Check if dependencies are installed"
	@echo "  bench          - Run Go benchmarks"
	@echo "  logs           - Show test container logs"
	@echo "  shell          - Interactive shell in test container"
	@echo "  stats          - Show test statistics"
	@echo "  watch          - Watch for changes and re-run tests (requires entr)"
	@echo ""
	@echo "Examples:"
	@echo "  make test              # Run all tests"
	@echo "  make quick             # Quick test (Go only)"
	@echo "  make setup && make e2e-test && make cleanup"
	@echo "  make coverage          # Generate coverage reports"
