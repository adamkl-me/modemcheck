#!/bin/bash
# Test Environment Setup and Cleanup Script
# Sets up isolated test databases and directories, runs tests, then cleans up

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CLOUDSERVER_DIR="$PROJECT_DIR/cloudserver"
TEST_DATA_DIR="$CLOUDSERVER_DIR/test-data"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

cleanup_test_env() {
    log_info "Cleaning up test environment..."

    # Stop and remove test container
    cd "$CLOUDSERVER_DIR"
    if docker compose -f docker-compose.test.yml ps -q modemcheck-cloud-test 2>/dev/null | grep -q .; then
        log_info "Stopping test container..."
        docker compose -f docker-compose.test.yml down -v 2>/dev/null || true
    fi

    # Remove test data directory
    if [ -d "$TEST_DATA_DIR" ]; then
        log_info "Removing test data directory..."
        rm -rf "$TEST_DATA_DIR"
    fi

    log_info "Cleanup complete!"
}

setup_test_env() {
    log_info "Setting up test environment..."

    # Check for venv in project root
    if [ -d "$PROJECT_DIR/venv" ]; then
        log_info "Found venv at $PROJECT_DIR/venv, activating..."
        source "$PROJECT_DIR/venv/bin/activate"

        # Install pytest in venv if not present
        if ! command -v pytest &> /dev/null; then
            log_info "Installing pytest in venv..."
            pip install -q -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null || \
            log_warn "Failed to install pytest in venv"
        fi
    else
        # No venv, check for pytest installation
        if ! command -v pytest &> /dev/null; then
            log_warn "pytest not found. Installing test dependencies..."

            # Try system packages first (Ubuntu/Debian)
            if command -v apt &> /dev/null; then
                log_info "Attempting to install via apt (system packages)..."
                if sudo apt-get update -qq && sudo apt-get install -y -qq python3-pytest python3-requests 2>/dev/null; then
                    log_info "Installed pytest via apt"
                else
                    log_warn "apt install failed, trying pip..."
                    # Fall back to pip with --break-system-packages for Ubuntu 24.04+
                    if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
                        pip3 install --user --break-system-packages -q -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null || \
                        log_warn "Failed to install pytest. Install manually: sudo apt install python3-pytest python3-requests"
                    fi
                fi
            else
                # Non-Debian systems, use pip
                if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
                    pip3 install --user -q -r "$SCRIPT_DIR/requirements.txt" || \
                    log_warn "Failed to install pytest, some tests may be skipped"
                fi
            fi
        fi
    fi

    # Create test data directories
    mkdir -p "$TEST_DATA_DIR/datafiles"
    mkdir -p "$TEST_DATA_DIR/data"
    mkdir -p "$TEST_DATA_DIR/config/sessions"

    # Create test users
    log_info "Creating test users..."
    cat > "$TEST_DATA_DIR/config/users.json" <<EOF
{
  "testuser": {
    "password": "pbkdf2:sha256:100000:test_salt:test_hash_basic",
    "role": "basic",
    "must_change_password": false
  },
  "testadmin": {
    "password": "pbkdf2:sha256:100000:test_salt:test_hash_admin",
    "role": "admin",
    "must_change_password": false
  }
}
EOF

    # Create test API keys
    log_info "Creating test API keys..."
    cat > "$TEST_DATA_DIR/config/api_keys.json" <<EOF
{
  "test_key_active": {
    "active": true,
    "last_used": null
  },
  "test_key_inactive": {
    "active": false,
    "last_used": null
  }
}
EOF

    log_info "Test environment setup complete!"
}

start_test_container() {
    log_info "Starting test container..."
    cd "$CLOUDSERVER_DIR"

    # Build and start
    docker compose -f docker-compose.test.yml up -d --build

    # Wait for container to be healthy
    log_info "Waiting for container to be ready..."
    timeout=60
    elapsed=0
    while [ $elapsed -lt $timeout ]; do
        if docker compose -f docker-compose.test.yml ps | grep -q "healthy"; then
            log_info "Container is ready!"
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done

    log_error "Container failed to become healthy within ${timeout}s"
    docker compose -f docker-compose.test.yml logs
    return 1
}

init_test_databases() {
    log_info "Initializing test databases..."

    # Initialize databases inside container
    docker exec modemcheck-cloud-test python3 <<'PYTHON'
import sys
sys.path.insert(0, '/modemcheck-cloud/cgi-bin')

import sqlite3
from pathlib import Path

# Initialize main database
db_path = '/modemcheck-cloud/data/modemcheck.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Clear any existing data from previous test runs
cursor.execute('DROP TABLE IF EXISTS modem_checks')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS modem_checks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        modem_id TEXT NOT NULL,
        filename TEXT UNIQUE NOT NULL,
        check_time TEXT NOT NULL,
        modem_type TEXT,
        modem_mac TEXT,
        upstream_power_avg REAL,
        downstream_power_avg REAL,
        upstream_snr_avg REAL,
        downstream_snr_avg REAL,
        codeword_errors_total INTEGER,
        upload_speed REAL,
        download_speed REAL,
        ping_avg REAL,
        raw_data TEXT
    )
''')

cursor.execute('CREATE INDEX IF NOT EXISTS idx_modem_id ON modem_checks(modem_id)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_check_time ON modem_checks(check_time)')

conn.commit()
conn.close()

# Initialize audit database
audit_path = '/modemcheck-cloud/data/audit.db'
conn = sqlite3.connect(audit_path)
cursor = conn.cursor()

# Clear any existing audit data from previous test runs
cursor.execute('DROP TABLE IF EXISTS user_activity_log')
cursor.execute('DROP TABLE IF EXISTS client_submission_log')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        username TEXT NOT NULL,
        action TEXT NOT NULL,
        ip_address TEXT,
        user_agent TEXT,
        details TEXT
    )
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS client_submission_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        modem_id TEXT NOT NULL,
        filename TEXT NOT NULL,
        ip_address TEXT,
        success INTEGER NOT NULL,
        error_message TEXT,
        api_key_preview TEXT
    )
''')

conn.commit()
conn.close()

print("Databases initialized successfully!")
PYTHON

    log_info "Databases initialized!"
}

# Main execution
main() {
    local action="${1:-all}"

    case "$action" in
        setup)
            setup_test_env
            start_test_container
            init_test_databases
            log_info "Test environment is ready!"
            log_info "Upload API: http://localhost:22558"
            log_info "Viewer:     http://localhost:23892"
            log_info "Admin:      http://localhost:23893"
            ;;
        cleanup)
            cleanup_test_env
            ;;
        all)
            # Full test cycle
            trap cleanup_test_env EXIT  # Ensure cleanup runs even on failure

            setup_test_env
            start_test_container
            init_test_databases

            log_info "Running tests..."
            cd "$SCRIPT_DIR"

            # Run Go tests
            if [ -f "$PROJECT_DIR/modem-check_test.go" ]; then
                log_info "Running Go unit tests..."
                cd "$PROJECT_DIR"
                go test -v -cover ./... || log_warn "Some Go tests failed"
            fi

            # Run Python tests
            if [ -f "$SCRIPT_DIR/test_cloud_api.py" ]; then
                log_info "Running Python integration tests..."
                cd "$SCRIPT_DIR"
                python3 -m pytest test_cloud_api.py -v --tb=short || log_warn "Some Python tests failed"
            fi

            # Run E2E tests if they exist
            if [ -f "$SCRIPT_DIR/test_e2e.sh" ]; then
                log_info "Running end-to-end tests..."
                bash "$SCRIPT_DIR/test_e2e.sh" || log_warn "Some E2E tests failed"
            fi

            log_info "All tests completed!"
            ;;
        *)
            echo "Usage: $0 {setup|cleanup|all}"
            echo "  setup   - Set up test environment and start container"
            echo "  cleanup - Clean up test environment"
            echo "  all     - Run full test suite (setup, test, cleanup)"
            exit 1
            ;;
    esac
}

main "$@"
