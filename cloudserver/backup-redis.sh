#!/bin/bash
#
# Redis backup script for ModemCheck cloud server
#
# Creates Redis snapshots and copies them to backup directory with timestamps.
#
# Usage:
#   ./backup-redis.sh                # Create backup with default settings
#   ./backup-redis.sh --retention 14 # Keep 14 days of backups
#
# Cron example (daily at 2:30 AM):
#   30 2 * * * cd /path/to/cloudserver && ./backup-redis.sh >> logs/backup.log 2>&1

set -euo pipefail

# Configuration
BACKUP_DIR="${BACKUP_DIR:-./backups/redis}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
CONTAINER_NAME="${REDIS_CONTAINER:-modemcheck-redis}"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --retention)
            RETENTION_DAYS="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [--retention DAYS]"
            echo ""
            echo "Options:"
            echo "  --retention DAYS    Keep backups for DAYS days (default: 30)"
            echo "  --help              Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Generate timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/redis_${TIMESTAMP}.rdb"

echo "========================================================================"
echo "ModemCheck Redis Backup"
echo "========================================================================"
echo "Timestamp: $(date)"
echo "Container: $CONTAINER_NAME"
echo "Backup file: $BACKUP_FILE"
echo "Retention: $RETENTION_DAYS days"
echo ""

# Check if container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "ERROR: Container $CONTAINER_NAME is not running"
    exit 1
fi

# Trigger Redis SAVE command (creates snapshot)
echo "Triggering Redis snapshot..."
docker exec "$CONTAINER_NAME" redis-cli SAVE

# Copy RDB file from container
echo "Copying snapshot from container..."
docker cp "$CONTAINER_NAME:/data/dump.rdb" "$BACKUP_FILE"

# Get backup file size
BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "Backup created: $BACKUP_FILE ($BACKUP_SIZE)"

# Cleanup old backups
echo ""
echo "Cleaning up old backups (retention: $RETENTION_DAYS days)..."

# Find and delete old backups
OLD_BACKUPS=$(find "$BACKUP_DIR" -name "redis_*.rdb" -type f -mtime +$RETENTION_DAYS)
if [ -n "$OLD_BACKUPS" ]; then
    echo "$OLD_BACKUPS" | while read -r old_backup; do
        echo "Deleting old backup: $old_backup"
        rm -f "$old_backup"
    done
    DELETED_COUNT=$(echo "$OLD_BACKUPS" | wc -l)
    echo "Deleted $DELETED_COUNT old backup(s)"
else
    echo "No old backups to delete"
fi

# Show current backups
echo ""
echo "Current backups:"
ls -lh "$BACKUP_DIR"/redis_*.rdb 2>/dev/null | tail -n 10 || echo "No backups found"

# Summary
BACKUP_COUNT=$(ls -1 "$BACKUP_DIR"/redis_*.rdb 2>/dev/null | wc -l)
TOTAL_SIZE=$(du -sh "$BACKUP_DIR" | cut -f1)

echo ""
echo "========================================================================"
echo "Backup Summary"
echo "========================================================================"
echo "Status: ✅ SUCCESS"
echo "Backup file: $BACKUP_FILE"
echo "Backup size: $BACKUP_SIZE"
echo "Total backups: $BACKUP_COUNT"
echo "Total backup size: $TOTAL_SIZE"
echo "Completed: $(date)"
echo "========================================================================"

exit 0
