#!/bin/bash
#
# Security Verification Script for ModemCheck Cloud Server
# Validates security configuration before deployment
#
# Usage: ./verify-security.sh
# Exit codes: 0 = passed, 1 = failed

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PASSED=0
FAILED=0
WARNINGS=0

echo "=================================="
echo "ModemCheck Security Verification"
echo "=================================="
echo ""

# Function to print test results
pass() {
    echo -e "${GREEN}✓${NC} $1"
    ((PASSED++))
}

fail() {
    echo -e "${RED}✗${NC} $1"
    ((FAILED++))
}

warn() {
    echo -e "${YELLOW}⚠${NC} $1"
    ((WARNINGS++))
}

# Test 1: Check if .env file exists
echo "[1/10] Checking .env file existence..."
if [ -f ".env" ]; then
    pass ".env file exists"
else
    fail ".env file not found - create from .env.example"
fi

# Test 2: Check if .env is in .gitignore
echo ""
echo "[2/10] Checking .gitignore..."
if grep -q "^cloudserver/.env$" ../.gitignore 2>/dev/null || grep -q "^\.env$" .gitignore 2>/dev/null; then
    pass ".env is in .gitignore"
else
    fail ".env not in .gitignore - risk of committing secrets!"
fi

# Test 3: Check if .env is tracked by git
echo ""
echo "[3/10] Checking if .env is tracked by git..."
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
    fail ".env is tracked by git - CRITICAL SECURITY ISSUE!"
    echo "   Run: git rm --cached .env"
else
    pass ".env is not tracked by git"
fi

# Test 4: Check .env file permissions
echo ""
echo "[4/10] Checking .env file permissions..."
if [ -f ".env" ]; then
    PERMS=$(stat -c "%a" .env 2>/dev/null || stat -f "%OLp" .env 2>/dev/null)
    if [ "$PERMS" == "600" ] || [ "$PERMS" == "400" ]; then
        pass ".env has restrictive permissions ($PERMS)"
    else
        warn ".env permissions are $PERMS (should be 600) - run: chmod 600 .env"
    fi
fi

# Test 5: Check for hardcoded secrets in docker-compose.yml
echo ""
echo "[5/10] Checking for hardcoded secrets in docker-compose.yml..."
HARDCODED_FOUND=0

if grep -q "POSTGRES_PASSWORD=modemcheck_secure_password" docker-compose.yml 2>/dev/null; then
    fail "Hardcoded database password found in docker-compose.yml"
    HARDCODED_FOUND=1
fi

if grep -q "SECRET_KEY=change-this" docker-compose.yml 2>/dev/null; then
    fail "Hardcoded SECRET_KEY found in docker-compose.yml"
    HARDCODED_FOUND=1
fi

if grep -q "CSRF_SECRET_KEY=change-this" docker-compose.yml 2>/dev/null; then
    fail "Hardcoded CSRF_SECRET_KEY found in docker-compose.yml"
    HARDCODED_FOUND=1
fi

if grep -q "ALLOWED_ORIGINS=\*" docker-compose.yml 2>/dev/null; then
    fail "CORS wildcard (*) found in docker-compose.yml - security risk!"
    HARDCODED_FOUND=1
fi

if [ $HARDCODED_FOUND -eq 0 ]; then
    pass "No hardcoded secrets in docker-compose.yml"
fi

# Test 6: Check for environment variable usage in docker-compose.yml
echo ""
echo "[6/10] Checking environment variable usage..."
ENV_VARS_FOUND=0

if grep -q "POSTGRES_PASSWORD=\${POSTGRES_DB_PASSWORD}" docker-compose.yml; then
    ((ENV_VARS_FOUND++))
fi

if grep -q "SECRET_KEY=\${SECRET_KEY}" docker-compose.yml; then
    ((ENV_VARS_FOUND++))
fi

if grep -q "CSRF_SECRET_KEY=\${CSRF_SECRET_KEY}" docker-compose.yml; then
    ((ENV_VARS_FOUND++))
fi

if grep -q "ALLOWED_ORIGINS=\${ALLOWED_ORIGINS}" docker-compose.yml; then
    ((ENV_VARS_FOUND++))
fi

if [ $ENV_VARS_FOUND -eq 4 ]; then
    pass "All secrets use environment variables"
elif [ $ENV_VARS_FOUND -gt 0 ]; then
    warn "Some secrets use environment variables ($ENV_VARS_FOUND/4)"
else
    fail "No environment variables found in docker-compose.yml"
fi

# Test 7: Check if required secrets are defined in .env
echo ""
echo "[7/10] Checking required secrets in .env..."
if [ -f ".env" ]; then
    SECRETS_OK=1

    if ! grep -q "^POSTGRES_DB_PASSWORD=" .env; then
        fail "POSTGRES_DB_PASSWORD not defined in .env"
        SECRETS_OK=0
    elif grep -q "^POSTGRES_DB_PASSWORD=CHANGE_THIS" .env; then
        fail "POSTGRES_DB_PASSWORD still has placeholder value"
        SECRETS_OK=0
    fi

    if ! grep -q "^SECRET_KEY=" .env; then
        fail "SECRET_KEY not defined in .env"
        SECRETS_OK=0
    elif grep -q "^SECRET_KEY=CHANGE_THIS" .env; then
        fail "SECRET_KEY still has placeholder value"
        SECRETS_OK=0
    fi

    if ! grep -q "^CSRF_SECRET_KEY=" .env; then
        fail "CSRF_SECRET_KEY not defined in .env"
        SECRETS_OK=0
    elif grep -q "^CSRF_SECRET_KEY=CHANGE_THIS" .env; then
        fail "CSRF_SECRET_KEY still has placeholder value"
        SECRETS_OK=0
    fi

    if ! grep -q "^ALLOWED_ORIGINS=" .env; then
        fail "ALLOWED_ORIGINS not defined in .env"
        SECRETS_OK=0
    elif grep -q "^ALLOWED_ORIGINS=CHANGE_THIS" .env; then
        fail "ALLOWED_ORIGINS still has placeholder value"
        SECRETS_OK=0
    fi

    if [ $SECRETS_OK -eq 1 ]; then
        pass "All required secrets defined in .env"
    fi
fi

# Test 8: Check secret strength
echo ""
echo "[8/10] Checking secret strength..."
if [ -f ".env" ]; then
    DB_PASS_LEN=$(grep "^POSTGRES_DB_PASSWORD=" .env | cut -d'=' -f2 | tr -d ' ' | wc -c)
    SECRET_KEY_LEN=$(grep "^SECRET_KEY=" .env | cut -d'=' -f2 | tr -d ' ' | wc -c)
    CSRF_KEY_LEN=$(grep "^CSRF_SECRET_KEY=" .env | cut -d'=' -f2 | tr -d ' ' | wc -c)

    if [ "$DB_PASS_LEN" -ge 32 ]; then
        pass "POSTGRES_DB_PASSWORD length adequate ($DB_PASS_LEN chars)"
    else
        warn "POSTGRES_DB_PASSWORD is short ($DB_PASS_LEN chars, recommend 32+)"
    fi

    if [ "$SECRET_KEY_LEN" -ge 48 ]; then
        pass "SECRET_KEY length adequate ($SECRET_KEY_LEN chars)"
    else
        warn "SECRET_KEY is short ($SECRET_KEY_LEN chars, recommend 48+)"
    fi

    if [ "$CSRF_KEY_LEN" -ge 48 ]; then
        pass "CSRF_SECRET_KEY length adequate ($CSRF_KEY_LEN chars)"
    else
        warn "CSRF_SECRET_KEY is short ($CSRF_KEY_LEN chars, recommend 48+)"
    fi
fi

# Test 9: Check CORS configuration
echo ""
echo "[9/10] Checking CORS configuration..."
if [ -f ".env" ]; then
    CORS_ORIGINS=$(grep "^ALLOWED_ORIGINS=" .env | cut -d'=' -f2)
    if [ "$CORS_ORIGINS" == "*" ]; then
        fail "CORS allows all origins (*) - major security risk!"
    elif [ -z "$CORS_ORIGINS" ]; then
        warn "ALLOWED_ORIGINS is empty"
    elif [[ "$CORS_ORIGINS" == *"localhost"* ]]; then
        warn "CORS includes localhost - OK for development, change for production"
    else
        pass "CORS configuration looks production-ready"
    fi
fi

# Test 10: Check for common security files
echo ""
echo "[10/10] Checking security infrastructure..."
if [ -f ".env.example" ]; then
    pass ".env.example exists for documentation"
else
    warn ".env.example not found"
fi

if [ -f "requirements.txt" ]; then
    pass "requirements.txt exists"
else
    warn "requirements.txt not found"
fi

# Summary
echo ""
echo "=================================="
echo "Security Verification Summary"
echo "=================================="
echo -e "${GREEN}Passed:${NC}   $PASSED"
echo -e "${YELLOW}Warnings:${NC} $WARNINGS"
echo -e "${RED}Failed:${NC}   $FAILED"
echo ""

if [ $FAILED -gt 0 ]; then
    echo -e "${RED}SECURITY VERIFICATION FAILED${NC}"
    echo "Fix the failed checks before deploying to production!"
    exit 1
elif [ $WARNINGS -gt 0 ]; then
    echo -e "${YELLOW}SECURITY VERIFICATION PASSED WITH WARNINGS${NC}"
    echo "Review warnings before production deployment."
    exit 0
else
    echo -e "${GREEN}SECURITY VERIFICATION PASSED${NC}"
    echo "Configuration meets security requirements."
    exit 0
fi
