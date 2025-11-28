#!/bin/bash
#
# Clean up old config_audit_log partitions (>90 days retention)
#
# This script should be run quarterly to drop old audit log partitions.
# Safe to run multiple times - will skip if partitions don't exist.
#
# Usage:
#   ./cleanup_old_partitions.sh [--dry-run] [--retention-days DAYS]
#
# Options:
#   --dry-run          Show what would be deleted without deleting
#   --retention-days   Number of days to retain (default: 90)
#
# Cron example (run on 1st of Jan/Apr/Jul/Oct at 3am):
#   0 3 1 1,4,7,10 * /opt/modemcheck/scripts/cleanup_old_partitions.sh >> /var/log/modemcheck/partition-cleanup.log 2>&1

set -euo pipefail

# Default settings
DRY_RUN=false
RETENTION_DAYS=90

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --retention-days)
            RETENTION_DAYS="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--dry-run] [--retention-days DAYS]"
            exit 1
            ;;
    esac
done

# Source environment variables
if [ -f "/opt/modemcheck/.env" ]; then
    set -a
    source /opt/modemcheck/.env
    set +a
elif [ -f "../.env" ]; then
    set -a
    source ../.env
    set +a
elif [ -f ".env" ]; then
    set -a
    source .env
    set +a
else
    echo "ERROR: Cannot find .env file"
    exit 1
fi

echo "Config Audit Log Partition Cleanup"
echo "==================================="
echo "Retention period: $RETENTION_DAYS days"
echo "Dry run: $DRY_RUN"
echo ""

# Build PostgreSQL connection string
if [ -n "${DATABASE_URL:-}" ]; then
    PSQL_CMD="psql $DATABASE_URL"
else
    DB_HOST="${POSTGRES_HOST:-localhost}"
    DB_PORT="${POSTGRES_PORT:-5432}"
    DB_NAME="${POSTGRES_DB:-modemcheck}"
    DB_USER="${POSTGRES_USER:-modemcheck}"
    export PGPASSWORD="${POSTGRES_PASSWORD}"
    PSQL_CMD="psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -t -A"
fi

# Calculate cutoff date (YYYYMM format)
CUTOFF_DATE=$(date -d "-${RETENTION_DAYS} days" +%Y%m)

echo "Cutoff date: $CUTOFF_DATE (partitions before this will be dropped)"
echo ""

# Find all config_audit_log partitions
PARTITIONS=$($PSQL_CMD -c "
    SELECT tablename
    FROM pg_tables
    WHERE schemaname = 'public'
      AND tablename LIKE 'config_audit_logs_%'
      AND tablename ~ '^config_audit_logs_[0-9]{6}$'
    ORDER BY tablename;
")

if [ -z "$PARTITIONS" ]; then
    echo "No partitions found. Exiting."
    exit 0
fi

TOTAL_COUNT=0
DELETE_COUNT=0
TOTAL_SIZE=0

echo "Analyzing partitions..."
echo ""

# Process each partition
while IFS= read -r partition; do
    # Skip empty lines
    [ -z "$partition" ] && continue

    TOTAL_COUNT=$((TOTAL_COUNT + 1))

    # Extract YYYYMM from partition name
    PARTITION_DATE=$(echo "$partition" | grep -oP '[0-9]{6}$' || echo "")

    if [ -z "$PARTITION_DATE" ]; then
        echo "WARNING: Skipping malformed partition name: $partition"
        continue
    fi

    # Get partition size
    SIZE=$($PSQL_CMD -c "
        SELECT pg_size_pretty(pg_total_relation_size('$partition'));
    ")

    # Check if partition is old enough to delete
    if [ "$PARTITION_DATE" -lt "$CUTOFF_DATE" ]; then
        DELETE_COUNT=$((DELETE_COUNT + 1))

        # Get row count before deletion
        ROW_COUNT=$($PSQL_CMD -c "SELECT COUNT(*) FROM $partition;")

        echo "[ DELETE ] $partition (${SIZE}, ${ROW_COUNT} rows, date: ${PARTITION_DATE})"

        if [ "$DRY_RUN" = false ]; then
            # Drop the partition
            if $PSQL_CMD -c "DROP TABLE IF EXISTS $partition CASCADE;" > /dev/null 2>&1; then
                echo "           ✓ Dropped successfully"
            else
                echo "           ✗ Failed to drop"
            fi
        else
            echo "           (dry-run, not dropped)"
        fi

        # Track size
        SIZE_BYTES=$($PSQL_CMD -c "
            SELECT pg_total_relation_size('$partition');
        " 2>/dev/null || echo "0")
        TOTAL_SIZE=$((TOTAL_SIZE + SIZE_BYTES))
    else
        echo "[ KEEP   ] $partition (${SIZE}, date: ${PARTITION_DATE})"
    fi
done <<< "$PARTITIONS"

echo ""
echo "Summary:"
echo "--------"
echo "Total partitions: $TOTAL_COUNT"
echo "Partitions to delete: $DELETE_COUNT"
echo "Partitions to keep: $((TOTAL_COUNT - DELETE_COUNT))"

if [ "$DRY_RUN" = true ]; then
    echo ""
    echo "DRY RUN - No partitions were actually deleted"
    echo "Run without --dry-run to perform deletion"
fi

exit 0
