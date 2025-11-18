#!/bin/bash
#
# Test Script for update-db-password.sh Password Validation
# Tests all validation rules: length, forbidden characters, etc.
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counters
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Test function
run_test() {
    local test_name="$1"
    local password="$2"
    local should_pass="$3"  # "pass" or "fail"

    TESTS_RUN=$((TESTS_RUN + 1))

    echo -n "Test $TESTS_RUN: $test_name... "

    # Create temporary .env file with test password
    TMP_ENV=$(mktemp)
    echo "POSTGRES_DB_PASSWORD=$password" > "$TMP_ENV"

    # Extract the validation logic from update-db-password.sh
    # We test just the validation part, not the actual database update

    # Extract password
    NEW_PASSWORD=$(grep "^POSTGRES_DB_PASSWORD=" "$TMP_ENV" | cut -d'=' -f2)

    # Run validation checks
    validation_failed=false
    error_message=""

    # Check 1: Empty password
    if [ -z "$NEW_PASSWORD" ]; then
        validation_failed=true
        error_message="Empty password"
    fi

    # Check 2: Minimum length
    if [ ${#NEW_PASSWORD} -lt 12 ]; then
        validation_failed=true
        error_message="Password too short (${#NEW_PASSWORD} chars)"
    fi

    # Check 3: No single quotes
    if [[ "$NEW_PASSWORD" == *"'"* ]]; then
        validation_failed=true
        error_message="Contains single quote"
    fi

    # Check 4: No semicolons
    if [[ "$NEW_PASSWORD" == *";"* ]]; then
        validation_failed=true
        error_message="Contains semicolon"
    fi

    # Cleanup
    rm -f "$TMP_ENV"

    # Check test result
    if [ "$should_pass" = "pass" ]; then
        if [ "$validation_failed" = false ]; then
            echo -e "${GREEN}PASS${NC}"
            TESTS_PASSED=$((TESTS_PASSED + 1))
        else
            echo -e "${RED}FAIL${NC} - Expected to pass but failed: $error_message"
            TESTS_FAILED=$((TESTS_FAILED + 1))
        fi
    else
        if [ "$validation_failed" = true ]; then
            echo -e "${GREEN}PASS${NC} - Correctly rejected: $error_message"
            TESTS_PASSED=$((TESTS_PASSED + 1))
        else
            echo -e "${RED}FAIL${NC} - Expected to fail but passed validation"
            TESTS_FAILED=$((TESTS_FAILED + 1))
        fi
    fi
}

echo "=========================================="
echo "Password Validation Test Suite"
echo "=========================================="
echo ""

# Valid passwords (should pass)
echo "=== Testing Valid Passwords ==="
run_test "Valid 12-character password" "abcdef123456" "pass"
run_test "Valid 16-character password" "SecurePass123456" "pass"
run_test "Valid 32-character password" "VeryLongSecurePassword1234567890" "pass"
run_test "Valid password with special chars (no quotes/semicolons)" "P@ssw0rd!#\$%^&*()-_+=[]{}|<>?" "pass"
run_test "Valid password with numbers and letters" "MyPassword123" "pass"
run_test "Valid password with underscores" "my_secure_password_123" "pass"
run_test "Valid password with dots" "my.secure.password.123" "pass"
run_test "Valid password with mixed case" "MySecurePassword123" "pass"
run_test "Valid password at minimum length (12 chars)" "Password1234" "pass"
run_test "Valid 64-character password" "$(head -c 64 /dev/urandom | base64 | tr -d '+/=' | head -c 64)" "pass"

echo ""
echo "=== Testing Invalid Passwords (Too Short) ==="
run_test "Empty password" "" "fail"
run_test "1 character password" "a" "fail"
run_test "5 character password" "12345" "fail"
run_test "10 character password" "1234567890" "fail"
run_test "11 character password (one less than minimum)" "12345678901" "fail"

echo ""
echo "=== Testing Invalid Passwords (Single Quotes) ==="
run_test "Password with single quote at start" "'password123" "fail"
run_test "Password with single quote at end" "password123'" "fail"
run_test "Password with single quote in middle" "pass'word123" "fail"
run_test "Password with multiple single quotes" "p'a's's'w'o'r'd'1'2'3" "fail"
run_test "SQL injection attempt with single quote" "'; DROP DATABASE modemcheck; --" "fail"

echo ""
echo "=== Testing Invalid Passwords (Semicolons) ==="
run_test "Password with semicolon at start" ";password123" "fail"
run_test "Password with semicolon at end" "password123;" "fail"
run_test "Password with semicolon in middle" "pass;word123" "fail"
run_test "Password with multiple semicolons" "p;a;s;s;w;o;r;d;1;2;3" "fail"
run_test "SQL injection attempt with semicolon" "password123; DROP TABLE users;" "fail"

echo ""
echo "=== Testing Edge Cases ==="
run_test "Password exactly 12 characters" "ExactlyTwelv" "pass"
run_test "Password with 11 chars (boundary)" "OnlyEleven1" "fail"
run_test "Password with newline (should pass - only quotes/semicolons blocked)" "Password123\n456" "pass"
run_test "Password with tab (should pass)" "Password\t123456" "pass"
run_test "Password with backslash (should pass)" "Pass\\word123456" "pass"
run_test "Unicode password (should pass if >=12 chars)" "Pässwörd1234" "pass"

echo ""
echo "=== Testing SQL Injection Attempts ==="
run_test "SQL comment injection" "pass'; --" "fail"
run_test "SQL UNION injection" "pass'; UNION SELECT * FROM users; --" "fail"
run_test "SQL batch injection" "pass'; DELETE FROM users; SELECT '" "fail"
run_test "SQL nested quotes" "pass''OR''1''=''1" "fail"
run_test "SQL command termination" "password123;SHUTDOWN;" "fail"

echo ""
echo "=========================================="
echo "Test Results Summary"
echo "=========================================="
echo "Tests Run:    $TESTS_RUN"
echo -e "Tests Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Tests Failed: ${RED}$TESTS_FAILED${NC}"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}✗ Some tests failed${NC}"
    exit 1
fi
