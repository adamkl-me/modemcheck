#!/bin/bash
#
# Run mutation testing inside the test Docker environment.
#
# Mutation testing systematically modifies source code to verify tests detect changes.
# A "killed" mutant means tests caught the change; a "surviving" mutant means tests missed it.
#
# Usage:
#   ./scripts/run_mutation_tests.sh                    # Test app/core/security.py (default)
#   ./scripts/run_mutation_tests.sh app/routers/auth.py
#   ./scripts/run_mutation_tests.sh --module app/core/config_encryption.py --tests tests/unit/
#   ./scripts/run_mutation_tests.sh --quick            # Quick mode: fewer mutants, faster feedback
#
# Priority modules for mutation testing:
#   - app/core/security.py - Password hashing, session management
#   - app/routers/auth.py - Login/logout logic
#   - app/routers/upload.py - HMAC validation
#   - app/core/config_encryption.py - AES encryption
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
DOCKER_COMPOSE_FILE="docker-compose.test.yml"
CONTAINER_NAME="modemcheck-cloud-test"
DEFAULT_MODULE="app/core/security.py"
DEFAULT_TESTS="tests/"
MAX_WAIT_TIME=60
HEALTH_CHECK_INTERVAL=2

# Parse command line arguments
MODULE=""
TESTS=""
QUICK_MODE=false
SHOW_RESULTS_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --module|-m)
            MODULE="$2"
            shift 2
            ;;
        --tests|-t)
            TESTS="$2"
            shift 2
            ;;
        --quick|-q)
            QUICK_MODE=true
            shift
            ;;
        --results|-r)
            SHOW_RESULTS_ONLY=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS] [MODULE]"
            echo ""
            echo "Run mutation testing on Python source files."
            echo ""
            echo "Arguments:"
            echo "  MODULE                 Path to module to mutate (default: $DEFAULT_MODULE)"
            echo ""
            echo "Options:"
            echo "  -m, --module PATH      Path to module to mutate"
            echo "  -t, --tests PATH       Path to test directory (default: $DEFAULT_TESTS)"
            echo "  -q, --quick            Quick mode: faster feedback with subset of mutants"
            echo "  -r, --results          Show results from previous run only"
            echo "  -h, --help             Show this help message"
            echo ""
            echo "Priority modules for testing:"
            echo "  - app/core/security.py       Password hashing, sessions"
            echo "  - app/routers/auth.py        Login/logout logic"
            echo "  - app/routers/upload.py      HMAC validation"
            echo "  - app/core/config_encryption.py  AES encryption"
            exit 0
            ;;
        *)
            # Positional argument - treat as module
            MODULE="$1"
            shift
            ;;
    esac
done

# Set defaults
MODULE="${MODULE:-$DEFAULT_MODULE}"
TESTS="${TESTS:-$DEFAULT_TESTS}"

print_header() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}\n"
}

print_success() {
    echo -e "${GREEN}$1${NC}"
}

print_error() {
    echo -e "${RED}$1${NC}"
}

print_warning() {
    echo -e "${YELLOW}$1${NC}"
}

# Check if Docker is running
check_docker() {
    if ! docker info > /dev/null 2>&1; then
        print_error "Error: Docker is not running. Please start Docker and try again."
        exit 1
    fi
}

# Start test environment if not running
ensure_test_env() {
    if ! docker ps --format "{{.Names}}" | grep -q "^${CONTAINER_NAME}$"; then
        print_header "Starting Test Environment"

        # Stop any existing containers
        docker compose -f "$DOCKER_COMPOSE_FILE" down -v > /dev/null 2>&1 || true

        # Build and start
        docker compose -f "$DOCKER_COMPOSE_FILE" up -d --build

        # Wait for health check
        local elapsed=0
        print_warning "Waiting for services to be ready..."
        while [ $elapsed -lt $MAX_WAIT_TIME ]; do
            if curl -s -f "http://localhost:22560/health" > /dev/null 2>&1; then
                print_success "Services are healthy (took ${elapsed}s)"
                return 0
            fi
            sleep $HEALTH_CHECK_INTERVAL
            elapsed=$((elapsed + HEALTH_CHECK_INTERVAL))
            echo -n "."
        done

        print_error "Services did not become healthy within ${MAX_WAIT_TIME}s"
        exit 1
    else
        print_success "Test environment already running"
    fi
}

# Run mutation tests
run_mutation_tests() {
    print_header "Running Mutation Tests"
    echo "Module: $MODULE"
    echo "Tests: $TESTS"
    echo ""

    # Build mutmut command
    local mutmut_cmd="python -m mutmut run --paths-to-mutate=\"$MODULE\" --tests-dir=\"$TESTS\""

    if [ "$QUICK_MODE" = true ]; then
        print_warning "Quick mode: Using fail-fast and limited mutants"
        mutmut_cmd="$mutmut_cmd --runner=\"python -m pytest -x --timeout=30\""
    else
        mutmut_cmd="$mutmut_cmd --runner=\"python -m pytest --timeout=60\""
    fi

    # Execute inside container
    docker exec -it "$CONTAINER_NAME" bash -c "
        cd /app && \
        export PYTHONPATH=/app && \
        $mutmut_cmd
    "

    local exit_code=$?

    if [ $exit_code -eq 0 ]; then
        print_success "Mutation testing complete"
    else
        print_warning "Mutation testing finished with surviving mutants"
    fi

    return $exit_code
}

# Show mutation test results
show_results() {
    print_header "Mutation Test Results"

    docker exec -it "$CONTAINER_NAME" bash -c "
        cd /app && \
        python -m mutmut results
    " 2>/dev/null || true

    echo ""
    print_header "Surviving Mutants (tests didn't catch these changes)"

    docker exec -it "$CONTAINER_NAME" bash -c "
        cd /app && \
        python -m mutmut results --status=survived 2>/dev/null | head -50
    " 2>/dev/null || true
}

# Show specific mutant details
show_mutant_details() {
    local mutant_id=$1
    docker exec -it "$CONTAINER_NAME" bash -c "
        cd /app && \
        python -m mutmut show $mutant_id
    "
}

# Main execution
main() {
    print_header "ModemCheck Mutation Testing"

    check_docker

    if [ "$SHOW_RESULTS_ONLY" = true ]; then
        ensure_test_env
        show_results
        exit 0
    fi

    ensure_test_env
    run_mutation_tests
    show_results
}

main
