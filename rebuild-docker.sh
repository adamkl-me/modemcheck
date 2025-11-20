#!/bin/bash
#
# Zero-downtime deployment script for ModemCheck
#
# This script rebuilds the Docker image and performs a rolling restart
# without stopping the database services, preserving active sessions.
#
# Usage: ./rebuild-docker.sh
#
# Recommended: Create a backup before deployment
#   cd cloudserver && sudo ./backup-all.sh --verify
#

set -e  # Exit on error

echo "========================================="
echo "ModemCheck Zero-Downtime Deployment"
echo "========================================="
echo ""

# Optional: Prompt for backup confirmation
read -p "Have you created a backup? (y/n, or press Enter to skip) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Nn]$ ]]; then
    echo "⚠️  Deployment cancelled. Create a backup first:"
    echo "   cd cloudserver && sudo ./backup-all.sh --verify"
    exit 0
elif [[ ! -z $REPLY && ! $REPLY =~ ^[Yy]$ ]]; then
    echo "⚠️  Invalid input. Deployment cancelled."
    exit 0
fi
echo ""

cd /home/adamkl/projects/modemcheck/cloudserver

# Step 1: Build new image without stopping services
echo "Step 1: Building new Docker image..."
sudo docker compose build
echo "✓ Image built successfully"
echo ""

# Step 2: Rolling restart of application container only
echo "Step 2: Performing rolling restart..."
echo "  • PostgreSQL and Redis will remain running"
echo "  • Application container will restart with new code"
sudo docker compose up -d --no-deps modemcheck-cloud
echo "✓ Application restarted"
echo ""

# Step 3: Wait for health check
echo "Step 3: Waiting for application to be healthy..."
sleep 5

HEALTH_CHECK_MAX_ATTEMPTS=12  # 60 seconds total
HEALTH_CHECK_ATTEMPT=0

while [ $HEALTH_CHECK_ATTEMPT -lt $HEALTH_CHECK_MAX_ATTEMPTS ]; do
    if curl -sf http://localhost:22560/health > /dev/null 2>&1; then
        echo "✓ Application is healthy!"
        break
    fi
    HEALTH_CHECK_ATTEMPT=$((HEALTH_CHECK_ATTEMPT + 1))
    if [ $HEALTH_CHECK_ATTEMPT -eq $HEALTH_CHECK_MAX_ATTEMPTS ]; then
        echo "✗ Health check failed after 60 seconds"
        echo ""
        echo "Container logs:"
        sudo docker logs modemcheck-cloud --tail 50
        exit 1
    fi
    echo "  Waiting for health check... (${HEALTH_CHECK_ATTEMPT}/${HEALTH_CHECK_MAX_ATTEMPTS})"
    sleep 5
done

echo ""
echo "========================================="
echo "Deployment Complete!"
echo "========================================="
echo ""
echo "Services:"
sudo docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep modemcheck
echo ""
echo "Access:"
echo "  • Web UI:  http://localhost:23890"
echo "  • API:     http://localhost:22560"
echo "  • Health:  http://localhost:22560/health"
echo ""