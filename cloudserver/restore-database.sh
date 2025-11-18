#!/bin/bash
#
# PostgreSQL restore script for ModemCheck cloud server
#
# Restores database from a backup file.
#
# ⚠️  WARNING: This will DROP and RECREATE the database!
#
# Usage:
#   ./restore-database.sh backups/postgres/modemcheck_20250117_020000.sql.gz
#   ./restore-database.sh --latest  # Restore from most recent backup
#
# Safety features:
#   - Requires confirmation before proceeding
#   - Creates backup before restore
#   - Can use --force to skip confirmation (for automation)

set -euo pipefail

# Configuration
BACKUP_DIR="${BACKUP_DIR:-./backups/postgres}"
CONTAINER_NAME="${POSTGRES_CONTAINER:-modemcheck-postgres}"
DATABASE_NAME="${POSTGRES_DB:-modemcheck}"
FORCE=false

# Parse command line arguments
BACKUP_FILE=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --latest)
            # Find most recent backup
            BACKUP_FILE=$(ls -t "$BACKUP_DIR"/modemcheck_*.sql.gz 2>/dev/null | head -n 1)
            if [ -z "$BACKUP_FILE" ]; then
                echo "ERROR: No backups found in $BACKUP_DIR"
                exit 1
            fi
            shift
            ;;
        --force)
            FORCE=true
            shift
            ;;
        --help)
            echo "Usage: $0 <backup_file> [--force]"
            echo "       $0 --latest [--force]"
            echo ""
            echo "Options:"
            echo "  --latest    Restore from most recent backup"
            echo "  --force     Skip confirmation prompt (for automation)"
            echo "  --help      Show this help message"
            exit 0
            ;;
        *)
            BACKUP_FILE="$1"
            shift
            ;;
    esac
done

# Validate backup file
if [ -z "$BACKUP_FILE" ]; then
    echo "ERROR: No backup file specified"
    echo "Usage: $0 <backup_file> or $0 --latest"
    exit 1
fi

if [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: Backup file not found: $BACKUP_FILE"
    exit 1
fi

echo "========================================================================"
echo "ModemCheck PostgreSQL Restore"
echo "========================================================================"
echo "⚠️  WARNING: This will DROP and RECREATE the database!"
echo ""
echo "Restore details:"
echo "  Container: $CONTAINER_NAME"
echo "  Database: $DATABASE_NAME"
echo "  Backup file: $BACKUP_FILE"
echo "  Backup size: $(du -h "$BACKUP_FILE" | cut -f1)"
echo "  Backup date: $(stat -c %y "$BACKUP_FILE" 2>/dev/null || stat -f %Sm "$BACKUP_FILE")"
echo ""

# Check if container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "ERROR: Container $CONTAINER_NAME is not running"
    exit 1
fi

# Confirmation prompt
if [ "$FORCE" = false ]; then
    echo "This operation will:"
    echo "  1. Create a pre-restore backup"
    echo "  2. DROP the current database"
    echo "  3. RECREATE the database from backup"
    echo ""
    read -p "Are you sure you want to continue? (yes/no): " CONFIRM
    if [ "$CONFIRM" != "yes" ]; then
        echo "Restore cancelled"
        exit 0
    fi
fi

# Create pre-restore backup
echo ""
echo "Creating pre-restore backup..."
PRE_RESTORE_BACKUP="$BACKUP_DIR/pre_restore_$(date +%Y%m%d_%H%M%S).sql.gz"
docker exec "$CONTAINER_NAME" pg_dump -U modemcheck "$DATABASE_NAME" | gzip > "$PRE_RESTORE_BACKUP"
echo "Pre-restore backup created: $PRE_RESTORE_BACKUP"

# Drop and recreate database
echo ""
echo "Dropping and recreating database..."
docker exec "$CONTAINER_NAME" psql -U modemcheck -d postgres -c "DROP DATABASE IF EXISTS $DATABASE_NAME;"
docker exec "$CONTAINER_NAME" psql -U modemcheck -d postgres -c "CREATE DATABASE $DATABASE_NAME;"

# Restore from backup
echo ""
echo "Restoring from backup..."
zcat "$BACKUP_FILE" | docker exec -i "$CONTAINER_NAME" psql -U modemcheck -d "$DATABASE_NAME"

# Verify restore
echo ""
echo "Verifying restore..."
TABLE_COUNT=$(docker exec "$CONTAINER_NAME" psql -U modemcheck -d "$DATABASE_NAME" -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';" | tr -d ' ')
echo "Tables restored: $TABLE_COUNT"

if [ "$TABLE_COUNT" -gt 0 ]; then
    echo "✅ Restore successful"
else
    echo "❌ Restore may have failed - no tables found"
    echo ""
    echo "Pre-restore backup available at: $PRE_RESTORE_BACKUP"
    exit 1
fi

# Summary
echo ""
echo "========================================================================"
echo "Restore Summary"
echo "========================================================================"
echo "Status: ✅ SUCCESS"
echo "Database: $DATABASE_NAME"
echo "Tables restored: $TABLE_COUNT"
echo "Pre-restore backup: $PRE_RESTORE_BACKUP"
echo "Completed: $(date)"
echo "========================================================================"

exit 0
