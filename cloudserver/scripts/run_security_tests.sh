#!/bin/bash
#
# Run security tests that require production-like settings.
#
# These tests are skipped in normal test runs because they require:
# - Rate limiting enabled (TESTING=false)
# - Account lockout enabled
# - Full security enforcement
#
# Usage:
#   ./scripts/run_security_tests.sh              # Run all production-settings tests
#   ./scripts/run_security_tests.sh --keep-env   # Keep environment running after tests
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
TEST_BASE_URL="http://localhost:22560"
MAX_WAIT_TIME=60
HEALTH_CHECK_INTERVAL=2

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

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

# Create a modified docker-compose for production-like settings
create_security_compose() {
    print_header "Creating Security Test Environment"

    # Create temporary compose file with TESTING=false
    cat > docker-compose.security-test.yml << 'EOF'
name: modemcheck-security-test

services:
  redis-security-test:
    container_name: modemcheck-redis-security-test
    image: redis:7-alpine
    command: redis-server --appendonly yes --maxmemory 256mb --maxmemory-policy allkeys-lru
    environment:
      - TZ=America/Toronto
    ports:
      - "6381:6379"
    networks:
      - modemcheck-security-test
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 3

  postgres-security-test:
    container_name: modemcheck-postgres-security-test
    image: postgres:16-alpine
    command: postgres -c max_connections=200
    ports:
      - "5434:5432"
    environment:
      - TZ=America/Toronto
      - POSTGRES_USER=modemcheck
      - POSTGRES_PASSWORD=modemcheck_security_test_password
      - POSTGRES_DB=modemcheck_security_test
      - PGDATA=/var/lib/postgresql/data/pgdata
    networks:
      - modemcheck-security-test
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U modemcheck"]
      interval: 5s
      timeout: 3s
      retries: 5

  modemcheck-cloud-security-test:
    container_name: modemcheck-cloud-security-test
    image: modemcheck-cloud:security-test
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "22561:8000"
    environment:
      - TZ=America/Toronto
      - DATABASE_URL=postgresql+asyncpg://modemcheck:modemcheck_security_test_password@postgres-security-test:5432/modemcheck_security_test
      - REDIS_HOST=redis-security-test
      - REDIS_PORT=6379
      # CRITICAL: Production-like settings for security tests
      - APP_ENV=production
      - DEBUG=false
      - TESTING=false
      - SECRET_KEY=security-test-secret-key-not-for-production
      - SESSION_TTL=3600
      - CSRF_SECRET_KEY=security-test-csrf-secret-key
      - ALLOWED_ORIGINS=*
      - WORKERS=2
      - MAX_UPLOAD_SIZE=52428800
      - MAX_BULK_UPLOAD_FILES=100
    networks:
      - modemcheck-security-test
    depends_on:
      redis-security-test:
        condition: service_healthy
      postgres-security-test:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 20s

networks:
  modemcheck-security-test:
    driver: bridge

EOF

    print_success "Security test compose file created"
}

# Start security test environment
start_security_env() {
    print_header "Starting Security Test Environment"

    # Stop any existing containers
    docker compose -f docker-compose.security-test.yml down -v > /dev/null 2>&1 || true

    # Build and start
    docker compose -f docker-compose.security-test.yml up -d --build

    if [ $? -eq 0 ]; then
        print_success "Security test containers started"
    else
        print_error "Failed to start security test containers"
        exit 1
    fi
}

# Wait for services to be healthy
wait_for_health() {
    print_header "Waiting for Services to be Ready"

    local elapsed=0
    local healthy=false
    local security_url="http://localhost:22561"

    while [ $elapsed -lt $MAX_WAIT_TIME ]; do
        if curl -s -f "$security_url/health" > /dev/null 2>&1; then
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
        docker compose -f docker-compose.security-test.yml logs --tail=50
        exit 1
    fi
}

# Setup virtual environment
setup_venv() {
    if [ ! -d ".venv" ]; then
        python3 -m venv .venv
    fi

    source .venv/bin/activate
    pip install -q --upgrade pip
    pip install -q -r requirements-test.txt

    print_success "Virtual environment ready"
}

# Run security tests
run_security_tests() {
    print_header "Running Security Tests (Production Settings)"

    setup_venv

    # Export test configuration for security test environment
    export TEST_BASE_URL="http://localhost:22561"
    export PYTHONPATH="$SCRIPT_DIR/..:$PYTHONPATH"

    # Export required environment variables
    export SECRET_KEY="security-test-secret-key-not-for-production"
    export CSRF_SECRET_KEY="security-test-csrf-secret-key"
    export DATABASE_URL="postgresql+asyncpg://modemcheck:modemcheck_security_test_password@localhost:5434/modemcheck_security_test"
    export REDIS_HOST="localhost"
    export REDIS_PORT="6381"
    export APP_ENV="production"
    export DEBUG="false"
    # Note: TESTING is NOT set to true - this enables rate limiting

    print_warning "Running with TESTING=false (rate limiting and lockout ENABLED)"

    # Run only tests marked as requiring production settings
    if pytest -m "requires_production_settings" -v --no-cov "$@"; then
        print_success "Security tests passed!"
        return 0
    else
        print_error "Some security tests failed"
        return 1
    fi
}

# Stop security test environment
stop_security_env() {
    print_header "Stopping Security Test Environment"

    docker compose -f docker-compose.security-test.yml down -v
    rm -f docker-compose.security-test.yml

    print_success "Security test environment stopped and cleaned up"
}

# Main execution
main() {
    local keep_env=false

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --keep-env)
                keep_env=true
                shift
                ;;
            --help|-h)
                echo "Usage: $0 [OPTIONS]"
                echo ""
                echo "Run security tests with production-like settings (rate limiting, account lockout)."
                echo ""
                echo "Options:"
                echo "  --keep-env    Keep test environment running after tests"
                echo "  --help, -h    Show this help message"
                echo ""
                echo "Tests that run:"
                echo "  - test_login_rate_limiting"
                echo "  - test_login_account_lockout"
                echo "  - Other tests marked @pytest.mark.requires_production_settings"
                exit 0
                ;;
            *)
                shift
                ;;
        esac
    done

    # Trap for cleanup
    if [ "$keep_env" = false ]; then
        trap stop_security_env EXIT
    fi

    # Execute workflow
    check_docker
    create_security_compose
    start_security_env
    wait_for_health

    if run_security_tests; then
        if [ "$keep_env" = true ]; then
            print_success "Security test environment still running at http://localhost:22561"
            print_warning "To stop: docker compose -f docker-compose.security-test.yml down -v"
        fi
        exit 0
    else
        if [ "$keep_env" = true ]; then
            print_warning "Security test environment still running for debugging"
        fi
        exit 1
    fi
}

main "$@"
