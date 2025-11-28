#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}ModemCheck Test Environment${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if test environment is already running
if docker ps --format '{{.Names}}' | grep -q "^modemcheck-cloud-test$"; then
    echo -e "${RED}Test environment is already running!${NC}"
    echo -e "${YELLOW}Please run ./stop-test-env.sh first.${NC}"
    exit 1
fi

# Build test image
echo -e "${YELLOW}Building test image...${NC}"
docker build -t modemcheck-cloud:test . 2>&1 | grep -E "(Step|Successfully|ERROR)" || true
echo -e "${GREEN}✓${NC} Test image built"

# Start test environment with docker compose
echo ""
echo -e "${YELLOW}Starting test services...${NC}"
docker compose -f docker-compose.test.yml up -d

# Wait for services
echo ""
echo -e "${YELLOW}Waiting for services to be healthy...${NC}"

# Wait for PostgreSQL
echo -n "  PostgreSQL... "
for i in {1..30}; do
    if docker exec modemcheck-postgres-test pg_isready -U modemcheck > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
        break
    fi
    sleep 1
    if [ $i -eq 30 ]; then
        echo -e "${RED}TIMEOUT${NC}"
        exit 1
    fi
done

# Wait for Redis
echo -n "  Redis... "
for i in {1..30}; do
    if docker exec modemcheck-redis-test redis-cli ping > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
        break
    fi
    sleep 1
    if [ $i -eq 30 ]; then
        echo -e "${RED}TIMEOUT${NC}"
        exit 1
    fi
done

# Wait for application
echo -n "  Application... "
for i in {1..60}; do
    if curl -sf http://localhost:22560/health > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
        break
    fi
    sleep 1
    if [ $i -eq 60 ]; then
        echo -e "${RED}TIMEOUT${NC}"
        docker logs modemcheck-cloud-test --tail 50
        exit 1
    fi
done

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Test Environment Started!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${BLUE}Access:${NC}"
echo "  • Health:      http://localhost:22560/health"
echo "  • API Docs:    http://localhost:22560/docs"
echo "  • Web UI:      http://localhost:23894"
echo "  • Upload API:  http://localhost:22560/api/upload"
echo ""
echo -e "${BLUE}Containers:${NC}"
echo "  • modemcheck-cloud-test"
echo "  • modemcheck-postgres-test"
echo "  • modemcheck-redis-test"
echo ""
echo -e "${BLUE}Default Login:${NC}"
echo "  • Username: admin"
echo "  • Password: TestPass123!"
echo ""
echo -e "${BLUE}Commands:${NC}"
echo "  • Run tests:    ./run_all_tests.sh"
echo "  • View logs:    docker logs -f modemcheck-cloud-test"
echo "  • Stop env:     ./stop-test-env.sh"
echo ""
