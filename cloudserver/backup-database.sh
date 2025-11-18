#!/bin/bash
#
# PostgreSQL backup script for ModemCheck cloud server
#
# Creates compressed backups with timestamps and automatic cleanup of old backups.
#
# Usage:
#   ./backup-database.sh                # Create backup with default settings
#   ./backup-database.sh --retention 14 # Keep 14 days of backups
#   ./backup-database.sh --verify       # Verify backup after creation
#
# Cron example (daily at 2 AM):
#   0 2 * * * cd /path/to/cloudserver && ./backup-database.sh >> logs/backup.log 2>&1

set -euo pipefail

# Configuration
BACKUP_DIR="${BACKUP_DIR:-./backups/postgres}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
VERIFY_BACKUP="${VERIFY_BACKUP:-false}"
CONTAINER_NAME="${POSTGRES_CONTAINER:-modemcheck-postgres}"
DATABASE_NAME="${POSTGRES_DB:-modemcheck}"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --retention)
            RETENTION_DAYS="$2"
            shift 2
            ;;
        --verify)
            VERIFY_BACKUP=true
            shift
            ;;
        --help)
            echo "Usage: $0 [--retention DAYS] [--verify]"
            echo ""
            echo "Options:"
            echo "  --retention DAYS    Keep backups for DAYS days (default: 30)"
            echo "  --verify            Verify backup integrity after creation"
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
BACKUP_FILE="$BACKUP_DIR/modemcheck_${TIMESTAMP}.sql.gz"

echo "========================================================================"
echo "ModemCheck PostgreSQL Backup"
echo "========================================================================"
echo "Timestamp: $(date)"
echo "Container: $CONTAINER_NAME"
echo "Database: $DATABASE_NAME"
echo "Backup file: $BACKUP_FILE"
echo "Retention: $RETENTION_DAYS days"
echo ""

# Check if container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "ERROR: Container $CONTAINER_NAME is not running"
    exit 1
fi

# Create backup
echo "Creating backup..."
docker exec "$CONTAINER_NAME" pg_dump -U modemcheck "$DATABASE_NAME" | gzip > "$BACKUP_FILE"

# Get backup file size
BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "Backup created: $BACKUP_FILE ($BACKUP_SIZE)"

# Verify backup if requested
if [ "$VERIFY_BACKUP" = true ]; then
    echo ""
    echo "Verifying backup integrity..."

    # Test gzip integrity
    if gzip -t "$BACKUP_FILE"; then
        echo "✅ Backup file integrity: OK"
    else
        echo "❌ Backup file integrity: FAILED"
        exit 1
    fi

    # Check if backup contains tables
    TABLE_COUNT=$(zcat "$BACKUP_FILE" | grep -c "CREATE TABLE" || true)
    if [ "$TABLE_COUNT" -gt 0 ]; then
        echo "✅ Backup contains tables: OK ($TABLE_COUNT tables)"
    else
        echo "❌ Backup missing tables: FAILED"
        exit 1
    fi
fi

# Cleanup old backups
echo ""
echo "Cleaning up old backups (retention: $RETENTION_DAYS days)..."

# Find and delete old backups
OLD_BACKUPS=$(find "$BACKUP_DIR" -name "modemcheck_*.sql.gz" -type f -mtime +$RETENTION_DAYS)
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
ls -lh "$BACKUP_DIR"/modemcheck_*.sql.gz 2>/dev/null | tail -n 10 || echo "No backups found"

# Summary
BACKUP_COUNT=$(ls -1 "$BACKUP_DIR"/modemcheck_*.sql.gz 2>/dev/null | wc -l)
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
