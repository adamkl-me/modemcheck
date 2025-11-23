#!/bin/bash
#
# Setup Docker Secrets for ModemCheck Cloud Server
#
# This script initializes Docker Swarm and creates all necessary secrets
# for production deployment with enhanced security.
#
# Usage:
#   ./scripts/setup-docker-secrets.sh [--regenerate]
#
# Options:
#   --regenerate    Regenerate and update existing secrets (requires service restart)
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

REGENERATE=false

# Parse arguments
if [ "$1" == "--regenerate" ]; then
    REGENERATE=true
fi

echo -e "${BLUE}=================================================${NC}"
echo -e "${BLUE}  ModemCheck Docker Secrets Setup${NC}"
echo -e "${BLUE}=================================================${NC}"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}ERROR: Docker is not running${NC}"
    exit 1
fi

# Initialize Docker Swarm if not already initialized
if ! docker info | grep -q "Swarm: active"; then
    echo -e "${YELLOW}⚠ Docker Swarm is not initialized${NC}"
    echo ""
    echo "Initializing Docker Swarm (safe for single-node setups)..."
    docker swarm init
    echo ""
    echo -e "${GREEN}✓ Docker Swarm initialized${NC}"
    echo ""
else
    echo -e "${GREEN}✓ Docker Swarm already active${NC}"
    echo ""
fi

# Function to create or update a secret
create_secret() {
    local SECRET_NAME=$1
    local SECRET_VALUE=$2
    local DESCRIPTION=$3

    # Check if secret already exists
    if docker secret inspect "$SECRET_NAME" > /dev/null 2>&1; then
        if [ "$REGENERATE" = true ]; then
            echo -e "${YELLOW}⚠ Secret '$SECRET_NAME' exists, regenerating...${NC}"
            # Docker secrets are immutable, so we create versioned secret
            local TIMESTAMP=$(date +%Y%m%d_%H%M%S)
            local VERSIONED_NAME="${SECRET_NAME}_${TIMESTAMP}"
            echo "$SECRET_VALUE" | docker secret create "$VERSIONED_NAME" -
            echo -e "${GREEN}✓ Created new version: $VERSIONED_NAME${NC}"
            echo -e "${YELLOW}  Note: Update docker-compose.secrets.yml to use new version${NC}"
        else
            echo -e "${GREEN}✓ Secret '$SECRET_NAME' already exists (use --regenerate to update)${NC}"
        fi
    else
        echo "$SECRET_VALUE" | docker secret create "$SECRET_NAME" -
        echo -e "${GREEN}✓ Created secret '$SECRET_NAME' - $DESCRIPTION${NC}"
    fi
}

# Generate secure random passwords
echo "Generating secrets..."
echo ""

DB_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
CSRF_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
REDIS_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

# Create secrets
create_secret "postgres_password" "$DB_PASSWORD" "PostgreSQL database password"
create_secret "app_secret_key" "$SECRET_KEY" "Application secret key (JWT/sessions)"
create_secret "csrf_secret_key" "$CSRF_SECRET" "CSRF protection secret key"
create_secret "redis_password" "$REDIS_PASSWORD" "Redis authentication password"

echo ""
echo -e "${BLUE}=================================================${NC}"
echo -e "${BLUE}  Secrets Summary${NC}"
echo -e "${BLUE}=================================================${NC}"
echo ""

# List all secrets
docker secret ls --format "table {{.Name}}\t{{.CreatedAt}}\t{{.UpdatedAt}}"

echo ""
echo -e "${GREEN}✓ All secrets created successfully!${NC}"
echo ""
echo -e "${YELLOW}IMPORTANT:${NC}"
echo "  1. Secrets are encrypted and cannot be read after creation"
echo "  2. Back up these secret IDs in a secure location (KeePass, 1Password, etc.)"
echo "  3. Update your application code to read from /run/secrets/* files"
echo "  4. Deploy with: docker stack deploy -c docker-compose.yml -c docker-compose.secrets.yml modemcheck"
echo ""
echo "Secret IDs for backup:"
echo ""
docker secret ls --format "  {{.Name}}: {{.ID}}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "  1. Review DOCKER_SECRETS.md for application code changes"
echo "  2. Test in staging environment first"
echo "  3. Deploy: docker stack deploy -c docker-compose.yml -c docker-compose.secrets.yml modemcheck"
echo "  4. Verify: docker exec \$(docker ps -q -f name=modemcheck_api) ls -la /run/secrets/"
echo ""
