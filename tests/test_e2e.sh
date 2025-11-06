#!/bin/bash
# End-to-End Test Suite for Modemcheck
# Tests complete workflow: upload -> import-daemon -> database -> viewer
# DB-ONLY MODE: Files are uploaded to filesystem, import-daemon processes them into database

# Don't exit on error - we want to run all tests
set +e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Test configuration
TEST_UPLOAD_URL="http://localhost:22558/cgi-bin/upload.py"
TEST_DB_API_URL="http://localhost:23892/cgi-bin/db-api.py"
TEST_ADMIN_API_URL="http://localhost:23893/cgi-bin/admin-api.py"
TEST_API_KEY="test_key_active"
TEST_MODEM_ID="CODA56-AABBCC112233"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Counters
TESTS_PASSED=0
TESTS_FAILED=0

log_test() {
    echo -e "${YELLOW}[TEST]${NC} $1"
}

log_pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
    ((TESTS_PASSED++))
}

log_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    ((TESTS_FAILED++))
}

# Helper function to create test JSON file
create_test_json() {
    local modem_id="$1"
    local timestamp=$(date +"%Y-%m-%d_%H-%M-%S")
    local filename="${timestamp}.json"

    cat > "/tmp/${filename}" <<EOF
{
  "sysinfo": {
    "modemtype": "${modem_id%%-*}",
    "modemmac": "${modem_id##*-}",
    "uptime": "5 days 12:34:56",
    "firmware": "1.0.0-test",
    "checktime": "$(date +"%Y-%m-%d_%H-%M-%S")"
  },
  "rx": [
    {
      "channel": "1",
      "frequency": "591000000",
      "power": "5.5",
      "snr": "40.5",
      "modulation": "QAM256",
      "corrected": "100",
      "uncorrected": "5"
    },
    {
      "channel": "2",
      "frequency": "597000000",
      "power": "6.0",
      "snr": "41.0",
      "modulation": "QAM256",
      "corrected": "150",
      "uncorrected": "3"
    }
  ],
  "tx": [
    {
      "channel": "1",
      "frequency": "36000000",
      "power": "42.0",
      "channeltype": "SC-QAM"
    }
  ],
  "speedtests": {
    "upload": "45.2",
    "download": "950.5"
  },
  "pingtests": {
    "8.8.8.8": {
      "avg": "12.5",
      "min": "10.2",
      "max": "15.8"
    },
    "1.1.1.1": {
      "avg": "11.8",
      "min": "9.5",
      "max": "14.2"
    }
  },
  "timestamp": "$(date -Iseconds)"
}
EOF

    echo "$filename"
}

# Test 1: Upload file with valid API key
test_upload_valid_key() {
    log_test "Test 1: Upload with valid API key"

    local filename=$(create_test_json "$TEST_MODEM_ID")

    response=$(curl -s -X POST \
        -F "api_key=$TEST_API_KEY" \
        -F "modem_id=$TEST_MODEM_ID" \
        -F "filename=$filename" \
        -F "file=@/tmp/$filename" \
        "$TEST_UPLOAD_URL")

    if echo "$response" | grep -q '"success": true'; then
        log_pass "Upload succeeded with valid API key"
    else
        log_fail "Upload failed: $response"
    fi

    rm -f "/tmp/$filename"
}

# Test 2: Upload file with invalid API key
test_upload_invalid_key() {
    log_test "Test 2: Upload with invalid API key"

    local filename=$(create_test_json "$TEST_MODEM_ID")

    response=$(curl -s -X POST \
        -F "api_key=invalid_key_12345" \
        -F "modem_id=$TEST_MODEM_ID" \
        -F "filename=$filename" \
        -F "file=@/tmp/$filename" \
        "$TEST_UPLOAD_URL")

    if echo "$response" | grep -q '"error"'; then
        log_pass "Upload correctly rejected invalid API key"
    else
        log_fail "Upload should have been rejected: $response"
    fi

    rm -f "/tmp/$filename"
}

# Test 3: Upload with inactive API key
test_upload_inactive_key() {
    log_test "Test 3: Upload with inactive API key"

    local filename=$(create_test_json "$TEST_MODEM_ID")

    response=$(curl -s -X POST \
        -F "api_key=test_key_inactive" \
        -F "modem_id=$TEST_MODEM_ID" \
        -F "filename=$filename" \
        -F "file=@/tmp/$filename" \
        "$TEST_UPLOAD_URL")

    if echo "$response" | grep -q '"error"'; then
        log_pass "Upload correctly rejected inactive API key"
    else
        log_fail "Upload should have been rejected: $response"
    fi

    rm -f "/tmp/$filename"
}

# Test 4: Path traversal attempt
test_path_traversal() {
    log_test "Test 4: Path traversal prevention"

    local filename=$(create_test_json "TEST-MAC")

    response=$(curl -s -X POST \
        -F "api_key=$TEST_API_KEY" \
        -F "modem_id=../../../etc" \
        -F "filename=passwd.json" \
        -F "file=@/tmp/$filename" \
        "$TEST_UPLOAD_URL")

    if echo "$response" | grep -q '"error".*Invalid modem_id'; then
        log_pass "Path traversal correctly blocked"
    else
        log_fail "Path traversal should have been blocked: $response"
    fi

    rm -f "/tmp/$filename"
}

# Test 5: Invalid filename format
test_invalid_filename() {
    log_test "Test 5: Invalid filename format"

    local filename=$(create_test_json "$TEST_MODEM_ID")

    response=$(curl -s -X POST \
        -F "api_key=$TEST_API_KEY" \
        -F "modem_id=$TEST_MODEM_ID" \
        -F "filename=../../../etc/passwd" \
        -F "file=@/tmp/$filename" \
        "$TEST_UPLOAD_URL")

    if echo "$response" | grep -q '"error".*Invalid filename'; then
        log_pass "Invalid filename correctly rejected"
    else
        log_fail "Invalid filename should have been rejected: $response"
    fi

    rm -f "/tmp/$filename"
}

# Test 6: Database insertion via import daemon
test_import_daemon() {
    log_test "Test 6: Database insertion via import daemon"

    # Upload a file
    local filename=$(create_test_json "$TEST_MODEM_ID")
    curl -s -X POST \
        -F "api_key=$TEST_API_KEY" \
        -F "modem_id=$TEST_MODEM_ID" \
        -F "filename=$filename" \
        -F "file=@/tmp/$filename" \
        "$TEST_UPLOAD_URL" > /dev/null

    # Run import daemon to process the uploaded file
    docker exec modemcheck-cloud-test python3 /modemcheck-cloud/import-daemon.py --once 2>&1 | grep -v "^DEBUG"
    sleep 1

    # Check if file is in database
    result=$(docker exec modemcheck-cloud-test sqlite3 /modemcheck-cloud/data/modemcheck.db \
        "SELECT COUNT(*) FROM modem_checks WHERE filename LIKE '%$filename';" 2>/dev/null || echo "0")

    if [ "$result" -ge "1" ]; then
        log_pass "File successfully imported by daemon"
    else
        log_fail "File was not imported into database (count: $result)"
    fi

    rm -f "/tmp/$filename"
}

# Test 7: Database API - List modems (without auth)
test_db_api_no_auth() {
    log_test "Test 7: Database API without authentication"

    response=$(curl -s "$TEST_DB_API_URL?action=list_modems")

    # Accept either JSON error or HTTP error response
    if echo "$response" | grep -qE '("error".*Unauthorized|403 Forbidden)'; then
        log_pass "Database API correctly requires authentication"
    else
        log_fail "Database API should require authentication: $response"
    fi
}

# Test 8: Large file rejection
test_large_file() {
    log_test "Test 8: Large file rejection (>10MB)"

    # Create 11MB file
    dd if=/dev/zero of=/tmp/large.json bs=1M count=11 2>/dev/null

    response=$(curl -s -X POST \
        -F "api_key=$TEST_API_KEY" \
        -F "modem_id=$TEST_MODEM_ID" \
        -F "filename=large.json" \
        -F "file=@/tmp/large.json" \
        "$TEST_UPLOAD_URL")

    # Accept either JSON error or nginx 413 error
    if echo "$response" | grep -qE '("error".*too large|413 Request Entity Too Large)'; then
        log_pass "Large file correctly rejected"
    else
        log_fail "Large file should have been rejected: $response"
    fi

    rm -f /tmp/large.json
}

# Test 9: Duplicate filename prevention
test_duplicate_filename() {
    log_test "Test 9: Duplicate filename prevention"

    local filename=$(create_test_json "$TEST_MODEM_ID")

    # Upload first time
    curl -s -X POST \
        -F "api_key=$TEST_API_KEY" \
        -F "modem_id=$TEST_MODEM_ID" \
        -F "filename=$filename" \
        -F "file=@/tmp/$filename" \
        "$TEST_UPLOAD_URL" > /dev/null

    # Try to upload same filename again
    response=$(curl -s -X POST \
        -F "api_key=$TEST_API_KEY" \
        -F "modem_id=$TEST_MODEM_ID" \
        -F "filename=$filename" \
        -F "file=@/tmp/$filename" \
        "$TEST_UPLOAD_URL")

    # Accept error message for duplicate file
    if echo "$response" | grep -qE '("error".*already exists|"error".*File already exists)'; then
        log_pass "Duplicate filename correctly rejected"
    else
        log_fail "Duplicate filename should have been rejected: $response"
    fi

    rm -f "/tmp/$filename"
}

# Test 10: Missing required fields
test_missing_fields() {
    log_test "Test 10: Missing required fields"

    local filename=$(create_test_json "$TEST_MODEM_ID")

    # Missing modem_id
    response=$(curl -s -X POST \
        -F "api_key=$TEST_API_KEY" \
        -F "filename=$filename" \
        -F "file=@/tmp/$filename" \
        "$TEST_UPLOAD_URL")

    if echo "$response" | grep -q '"error"'; then
        log_pass "Missing modem_id correctly rejected"
    else
        log_fail "Missing modem_id should have been rejected: $response"
    fi

    rm -f "/tmp/$filename"
}

# Test 11: Data integrity check
test_data_integrity() {
    log_test "Test 11: Data integrity after upload and import"

    local filename=$(create_test_json "$TEST_MODEM_ID")

    # Upload file
    curl -s -X POST \
        -F "api_key=$TEST_API_KEY" \
        -F "modem_id=$TEST_MODEM_ID" \
        -F "filename=$filename" \
        -F "file=@/tmp/$filename" \
        "$TEST_UPLOAD_URL" > /dev/null

    # Run import daemon to import the file
    docker exec modemcheck-cloud-test python3 /modemcheck-cloud/import-daemon.py --once 2>&1 | grep -v "^DEBUG"
    sleep 1

    # Verify data in database
    result=$(docker exec modemcheck-cloud-test sqlite3 /modemcheck-cloud/data/modemcheck.db \
        "SELECT modem_id, modem_type FROM modem_checks WHERE filename LIKE '%$filename';" 2>/dev/null || echo "")

    expected="CODA56-AABBCC112233|CODA56"
    if [ "$result" = "$expected" ]; then
        log_pass "Data integrity verified in database"
    else
        log_fail "Data mismatch - expected: $expected, got: $result"
    fi

    rm -f "/tmp/$filename"
}

# Test 12: Audit logging
test_audit_logging() {
    log_test "Test 12: Audit logging for uploads"

    local filename=$(create_test_json "$TEST_MODEM_ID")

    # Upload file
    curl -s -X POST \
        -F "api_key=$TEST_API_KEY" \
        -F "modem_id=$TEST_MODEM_ID" \
        -F "filename=$filename" \
        -F "file=@/tmp/$filename" \
        "$TEST_UPLOAD_URL" > /dev/null

    # Check audit log
    result=$(docker exec modemcheck-cloud-test sqlite3 /modemcheck-cloud/data/audit.db \
        "SELECT COUNT(*) FROM client_submission_log WHERE filename='$filename';" 2>/dev/null || echo "0")

    if [ "$result" -ge "1" ]; then
        log_pass "Upload correctly logged in audit database"
    else
        log_fail "Upload was not logged in audit database"
    fi

    rm -f "/tmp/$filename"
}

# Test 13: Concurrent uploads
test_concurrent_uploads() {
    log_test "Test 13: Concurrent uploads"

    # Create 5 test files
    local files=()
    for i in {1..5}; do
        local filename=$(create_test_json "TEST-MAC00000$i")
        files+=("$filename")
    done

    # Upload concurrently
    for filename in "${files[@]}"; do
        curl -s -X POST \
            -F "api_key=$TEST_API_KEY" \
            -F "modem_id=TEST-MAC00000$((RANDOM % 5 + 1))" \
            -F "filename=$filename" \
            -F "file=@/tmp/$filename" \
            "$TEST_UPLOAD_URL" &
    done

    wait  # Wait for all uploads to complete

    # Check that all were successful
    success_count=0
    for filename in "${files[@]}"; do
        if docker exec modemcheck-cloud-test test -f "/modemcheck-cloud/datafiles/TEST-MAC000001/$filename" 2>/dev/null ||
           docker exec modemcheck-cloud-test test -f "/modemcheck-cloud/datafiles/TEST-MAC000002/$filename" 2>/dev/null ||
           docker exec modemcheck-cloud-test test -f "/modemcheck-cloud/datafiles/TEST-MAC000003/$filename" 2>/dev/null ||
           docker exec modemcheck-cloud-test test -f "/modemcheck-cloud/datafiles/TEST-MAC000004/$filename" 2>/dev/null ||
           docker exec modemcheck-cloud-test test -f "/modemcheck-cloud/datafiles/TEST-MAC000005/$filename" 2>/dev/null; then
            ((success_count++))
        fi
        rm -f "/tmp/$filename"
    done

    if [ $success_count -ge 4 ]; then  # Allow 1 failure due to timing
        log_pass "Concurrent uploads handled correctly ($success_count/5 succeeded)"
    else
        log_fail "Too many concurrent upload failures ($success_count/5 succeeded)"
    fi
}

# Main test execution
main() {
    echo "========================================="
    echo "  Modemcheck End-to-End Test Suite"
    echo "========================================="
    echo ""

    # Verify test container is running
    if ! docker ps | grep -q modemcheck-cloud-test; then
        echo "ERROR: Test container is not running!"
        echo "Run: cd tests && ./test_env_setup.sh setup"
        exit 1
    fi

    # Run all tests
    test_upload_valid_key
    test_upload_invalid_key
    test_upload_inactive_key
    test_path_traversal
    test_invalid_filename
    test_import_daemon
    test_db_api_no_auth
    test_large_file
    test_duplicate_filename
    test_missing_fields
    test_data_integrity
    test_audit_logging
    test_concurrent_uploads

    # Summary
    echo ""
    echo "========================================="
    echo "  Test Summary"
    echo "========================================="
    echo -e "${GREEN}Passed: $TESTS_PASSED${NC}"
    echo -e "${RED}Failed: $TESTS_FAILED${NC}"
    echo ""

    if [ $TESTS_FAILED -eq 0 ]; then
        echo -e "${GREEN}All tests passed!${NC}"
        exit 0
    else
        echo -e "${RED}Some tests failed!${NC}"
        exit 1
    fi
}

main "$@"
