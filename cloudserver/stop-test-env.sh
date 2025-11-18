#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}ModemCheck Test Environment Cleanup${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Stop and remove containers using docker compose
echo -e "${YELLOW}Stopping and removing test containers...${NC}"
docker compose -f docker-compose.test.yml down

# Remove test volumes
echo ""
echo -e "${YELLOW}Removing test volumes...${NC}"
docker volume rm modemcheck-test_postgres modemcheck-test_redis 2>/dev/null || true
echo -e "${GREEN}✓${NC} Test volumes removed"

# Remove test network
echo ""
echo -e "${YELLOW}Removing test network...${NC}"
docker network rm modemcheck-test 2>/dev/null || true
echo -e "${GREEN}✓${NC} Test network removed"

# Check for test image
if docker images | grep -q "modemcheck-cloud.*test"; then
    echo ""
    echo -e "${YELLOW}Test image 'modemcheck-cloud:test' still exists.${NC}"
    echo -e "Run 'docker rmi modemcheck-cloud:test' to remove it."
fi

echo ""
echo -e "${GREEN}Test environment cleanup complete!${NC}"
echo ""
