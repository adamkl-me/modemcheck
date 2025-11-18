#!/bin/bash
#
# Complete backup script for ModemCheck cloud server
#
# Backs up PostgreSQL and Redis with verification.
#
# Usage:
#   ./backup-all.sh                # Create all backups
#   ./backup-all.sh --verify       # Verify PostgreSQL backup
#
# Cron example (daily at 2 AM):
#   0 2 * * * cd /path/to/cloudserver && ./backup-all.sh >> logs/backup.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "========================================================================"
echo "ModemCheck Complete Backup"
echo "========================================================================"
echo "Started: $(date)"
echo ""

# Parse arguments
VERIFY_ARG=""
if [[ $# -gt 0 ]] && [[ "$1" == "--verify" ]]; then
    VERIFY_ARG="--verify"
fi

# Backup PostgreSQL
echo "Step 1: Backing up PostgreSQL..."
echo "------------------------------------------------------------------------"
"$SCRIPT_DIR/backup-database.sh" $VERIFY_ARG
POSTGRES_STATUS=$?

echo ""
echo ""

# Backup Redis
echo "Step 2: Backing up Redis..."
echo "------------------------------------------------------------------------"
"$SCRIPT_DIR/backup-redis.sh"
REDIS_STATUS=$?

echo ""
echo ""

# Summary
echo "========================================================================"
echo "Complete Backup Summary"
echo "========================================================================"

if [ $POSTGRES_STATUS -eq 0 ]; then
    echo "PostgreSQL backup: ✅ SUCCESS"
else
    echo "PostgreSQL backup: ❌ FAILED (exit code: $POSTGRES_STATUS)"
fi

if [ $REDIS_STATUS -eq 0 ]; then
    echo "Redis backup: ✅ SUCCESS"
else
    echo "Redis backup: ❌ FAILED (exit code: $REDIS_STATUS)"
fi

echo ""
echo "Backup directory structure:"
tree -L 2 backups/ 2>/dev/null || ls -lR backups/

echo ""
echo "Completed: $(date)"
echo "========================================================================"

# Exit with error if any backup failed
if [ $POSTGRES_STATUS -ne 0 ] || [ $REDIS_STATUS -ne 0 ]; then
    exit 1
fi

exit 0
