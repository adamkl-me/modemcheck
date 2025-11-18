#!/bin/bash

# ModemCheck Cloud v2 - Comprehensive Test Runner
# Manages test environment lifecycle and executes all test suites

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
TEST_ENV="test"
TEST_BASE_URL="http://localhost:22560"
DOCKER_COMPOSE_FILE="docker-compose.test.yml"
MAX_WAIT_TIME=60
HEALTH_CHECK_INTERVAL=2

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Functions
print_header() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

# Check if Docker is running
check_docker() {
    if ! docker info > /dev/null 2>&1; then
        print_error "Docker is not running. Please start Docker and try again."
        exit 1
    fi
    print_success "Docker is running"
}

# Start test environment
start_test_env() {
    print_header "Starting Test Environment"
    
    # Stop any existing test containers
    print_info "Stopping any existing test containers..."
    docker compose -f "$DOCKER_COMPOSE_FILE" down -v > /dev/null 2>&1 || true

    # Build and start containers
    print_info "Building and starting test containers..."
    docker compose -f "$DOCKER_COMPOSE_FILE" up -d --build
    
    if [ $? -eq 0 ]; then
        print_success "Test containers started"
    else
        print_error "Failed to start test containers"
        exit 1
    fi
}

# Wait for services to be healthy
wait_for_health() {
    print_header "Waiting for Services to be Ready"
    
    local elapsed=0
    local healthy=false
    
    while [ $elapsed -lt $MAX_WAIT_TIME ]; do
        # Check if health endpoint responds
        if curl -s -f "$TEST_BASE_URL/health" > /dev/null 2>&1; then
            healthy=true
            break
        fi
        
        sleep $HEALTH_CHECK_INTERVAL
        elapsed=$((elapsed + HEALTH_CHECK_INTERVAL))
        echo -n "."
    done
    
    echo ""
    
    if [ "$healthy" = true ]; then
        print_success "All services are healthy (took ${elapsed}s)"
    else
        print_error "Services did not become healthy within ${MAX_WAIT_TIME}s"
        print_info "Showing container logs:"
        docker compose -f "$DOCKER_COMPOSE_FILE" logs --tail=50
        exit 1
    fi
}

# Setup virtual environment
setup_venv() {
    if [ ! -d ".venv" ]; then
        print_info "Creating virtual environment..."
        python3 -m venv .venv
    fi

    print_info "Activating virtual environment..."
    source .venv/bin/activate

    print_info "Installing test dependencies..."
    pip install -q --upgrade pip
    pip install -q -r requirements-test.txt

    # Install Playwright browsers if not already installed
    print_info "Checking Playwright browser installation..."
    if ! python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); p.chromium.launch()" > /dev/null 2>&1; then
        print_info "Installing Playwright browsers (this may take a few minutes)..."
        playwright install chromium
        print_success "Playwright browsers installed"
    else
        print_success "Playwright browsers already installed"
    fi

    print_success "Virtual environment ready"
}

# Run tests
run_tests() {
    print_header "Running Test Suite"

    # Setup and activate virtual environment
    setup_venv

    # Export test configuration
    export TEST_BASE_URL="$TEST_BASE_URL"
    export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"

    # Export required environment variables for Settings
    export SECRET_KEY="test-secret-key-for-testing-only-not-production"
    export CSRF_SECRET_KEY="test-csrf-secret-key-for-testing-only"
    export DATABASE_URL="postgresql+asyncpg://modemcheck:modemcheck_test_password@localhost:5433/modemcheck_test"
    export REDIS_HOST="localhost"
    export REDIS_PORT="6380"
    export APP_ENV="test"
    export DEBUG="true"

    # Parse command line arguments
    local test_args=("$@")

    # Default: run all tests
    if [ ${#test_args[@]} -eq 0 ]; then
        test_args=("tests/")
    fi

    # Run pytest with coverage
    print_info "Executing tests: ${test_args[*]}"

    if pytest "${test_args[@]}"; then
        print_success "All tests passed!"
        return 0
    else
        print_error "Some tests failed"
        return 1
    fi
}

# Stop test environment
stop_test_env() {
    print_header "Stopping Test Environment"
    
    docker compose -f "$DOCKER_COMPOSE_FILE" down -v
    
    if [ $? -eq 0 ]; then
        print_success "Test environment stopped and cleaned up"
    else
        print_warning "Failed to stop test environment cleanly"
    fi
}

# Show test results
show_results() {
    print_header "Test Results Summary"
    
    if [ -f "htmlcov/index.html" ]; then
        print_success "Coverage report: htmlcov/index.html"
    fi
    
    if [ -f "test-report.html" ]; then
        print_success "Test report: test-report.html"
    fi
    
    if [ -f "coverage.xml" ]; then
        print_success "Coverage XML: coverage.xml"
    fi
}

# Main execution
main() {
    local keep_env=false
    local test_args=()
    
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --keep-env)
                keep_env=true
                shift
                ;;
            --help|-h)
                echo "Usage: $0 [OPTIONS] [TEST_PATHS...]"
                echo ""
                echo "Options:"
                echo "  --keep-env        Keep test environment running after tests"
                echo "  --help, -h        Show this help message"
                echo ""
                echo "Examples:"
                echo "  $0                                  # Run all tests"
                echo "  $0 tests/api/                       # Run only API tests"
                echo "  $0 tests/security/                  # Run only security tests"
                echo "  $0 -m api                           # Run tests marked as 'api'"
                echo "  $0 -m \"not slow\"                    # Skip slow tests"
                echo "  $0 --keep-env                       # Keep environment running"
                echo "  $0 tests/api/test_auth.py::TestLogin::test_login_success  # Run specific test"
                exit 0
                ;;
            *)
                test_args+=("$1")
                shift
                ;;
        esac
    done
    
    # Trap to ensure cleanup
    if [ "$keep_env" = false ]; then
        trap stop_test_env EXIT
    fi
    
    # Execute test workflow
    check_docker
    start_test_env
    wait_for_health
    
    if run_tests "${test_args[@]}"; then
        show_results
        
        if [ "$keep_env" = true ]; then
            print_header "Test Environment Status"
            print_success "Test environment is still running"
            print_info "Access test server at: $TEST_BASE_URL"
            print_info "To stop: docker compose -f $DOCKER_COMPOSE_FILE down -v"
        fi
        
        exit 0
    else
        show_results
        
        if [ "$keep_env" = true ]; then
            print_warning "Test environment is still running for debugging"
            print_info "Access test server at: $TEST_BASE_URL"
            print_info "View logs: docker compose -f $DOCKER_COMPOSE_FILE logs -f"
            print_info "To stop: docker compose -f $DOCKER_COMPOSE_FILE down -v"
        fi
        
        exit 1
    fi
}

# Run main function
main "$@"
