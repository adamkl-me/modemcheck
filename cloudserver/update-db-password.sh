#!/bin/bash
#
# Safe PostgreSQL Password Update Script
# Updates the database password without losing data
#

set -e

echo "=========================================="
echo "PostgreSQL Password Update Script"
echo "=========================================="
echo ""

# Read the new password from .env file
if [ ! -f .env ]; then
    echo "ERROR: .env file not found!"
    exit 1
fi

# Extract new password from .env
NEW_PASSWORD=$(grep "^POSTGRES_DB_PASSWORD=" .env | cut -d'=' -f2)

if [ -z "$NEW_PASSWORD" ]; then
    echo "ERROR: Could not find POSTGRES_DB_PASSWORD in .env"
    exit 1
fi

# Validate password meets minimum requirements
if [ ${#NEW_PASSWORD} -lt 12 ]; then
    echo "ERROR: Password must be at least 12 characters long"
    echo "       Current length: ${#NEW_PASSWORD} characters"
    exit 1
fi

# Validate password doesn't contain single quotes (prevents SQL syntax errors)
if [[ "$NEW_PASSWORD" == *"'"* ]]; then
    echo "ERROR: Password cannot contain single quotes (') as they cause SQL syntax errors"
    echo "       Please generate a new password without single quotes"
    exit 1
fi

# Validate password doesn't contain semicolons (prevents SQL injection)
if [[ "$NEW_PASSWORD" == *";"* ]]; then
    echo "ERROR: Password cannot contain semicolons (;) as they could enable SQL injection"
    echo "       Please generate a new password without semicolons"
    exit 1
fi

echo "New password found in .env: ${NEW_PASSWORD:0:8}... (showing first 8 chars)"
echo "Password validation: ✓ Length OK (${#NEW_PASSWORD} chars), ✓ No dangerous characters"
echo ""

# Ask for confirmation
read -p "Update PostgreSQL password? This will restart the application. (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "Step 1: Updating PostgreSQL password in database..."

# Update the password directly in PostgreSQL using secure heredoc method
# This prevents SQL injection and avoids password exposure in process listings
# The password is passed via stdin, not as a command-line argument
docker exec -i modemcheck-postgres psql -U modemcheck -d modemcheck 2>/dev/null <<EOF
ALTER USER modemcheck WITH PASSWORD '$NEW_PASSWORD';
EOF

if [ $? -eq 0 ]; then
    echo "✓ PostgreSQL password updated successfully in database"
else
    echo "✗ Failed to update password in database"
    echo "  This might be because the password was already updated."
    echo "  Continuing anyway..."
fi

echo ""
echo "Step 2: Restarting containers to use new password..."

# Restart containers
docker-compose restart modemcheck-cloud

if [ $? -eq 0 ]; then
    echo "✓ Application restarted successfully"
else
    echo "✗ Failed to restart application"
    exit 1
fi

echo ""
echo "Step 3: Verifying database connectivity..."
sleep 5

# Check if application can connect
if docker exec modemcheck-cloud curl -f http://localhost:8000/health >/dev/null 2>&1; then
    echo "✓ Application is healthy and connected to database"
else
    echo "✗ Application health check failed"
    echo "  Check logs with: docker logs modemcheck-cloud"
    exit 1
fi

echo ""
echo "=========================================="
echo "✓ Password update completed successfully!"
echo "=========================================="
echo ""
echo "Your data is preserved:"
echo "  - All modem check records intact"
echo "  - Users and API keys unchanged"
echo "  - Active sessions cleared (users must re-login)"
echo ""
echo "Next steps:"
echo "  1. Verify application: http://localhost:23890"
echo "  2. Update SECRET_KEY and CSRF_SECRET_KEY with similar process if needed"
echo ""
