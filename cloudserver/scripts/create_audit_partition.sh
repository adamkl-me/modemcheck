#!/bin/bash
#
# Create monthly partition for config_audit_logs table
#
# This script should be run monthly (via cron) to create the next month's partition.
# It's safe to run multiple times - will skip if partition already exists.
#
# Usage:
#   ./create_audit_partition.sh [YYYY-MM]
#
# If no date specified, creates partition for next month.
#
# Cron example (run on 1st of each month at 2am):
#   0 2 1 * * /opt/modemcheck/scripts/create_audit_partition.sh >> /var/log/modemcheck/partition-create.log 2>&1

set -euo pipefail

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
    echo "ERROR: Cannot find .env file. Please run from cloudserver/ directory or set environment variables."
    exit 1
fi

# Determine target month (next month by default)
if [ $# -eq 1 ]; then
    TARGET_MONTH="$1"
else
    TARGET_MONTH=$(date -d "+1 month" +%Y-%m)
fi

# Parse year and month
YEAR=$(echo "$TARGET_MONTH" | cut -d- -f1)
MONTH=$(echo "$TARGET_MONTH" | cut -d- -f2)

# Validate format
if ! [[ "$YEAR" =~ ^[0-9]{4}$ ]] || ! [[ "$MONTH" =~ ^[0-9]{2}$ ]]; then
    echo "ERROR: Invalid date format. Use YYYY-MM"
    exit 1
fi

# Calculate partition bounds
PARTITION_NAME="config_audit_logs_${YEAR}${MONTH}"
START_DATE="${YEAR}-${MONTH}-01"
NEXT_MONTH=$(date -d "${START_DATE} +1 month" +%Y-%m-01)

echo "Creating partition: $PARTITION_NAME"
echo "  Range: $START_DATE to $NEXT_MONTH"

# Build PostgreSQL connection string
if [ -n "${DATABASE_URL:-}" ]; then
    # Use DATABASE_URL if available (Docker environment)
    PSQL_CMD="psql $DATABASE_URL"
else
    # Build from individual components (local development)
    DB_HOST="${POSTGRES_HOST:-localhost}"
    DB_PORT="${POSTGRES_PORT:-5432}"
    DB_NAME="${POSTGRES_DB:-modemcheck}"
    DB_USER="${POSTGRES_USER:-modemcheck}"
    export PGPASSWORD="${POSTGRES_PASSWORD}"
    PSQL_CMD="psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME"
fi

# Create partition (idempotent - fails gracefully if exists)
SQL="
DO \$\$
BEGIN
    -- Create partition
    EXECUTE format('
        CREATE TABLE IF NOT EXISTS %I PARTITION OF config_audit_logs
        FOR VALUES FROM (%L) TO (%L)
    ', '$PARTITION_NAME', '$START_DATE', '$NEXT_MONTH');

    -- Create indexes on the partition for performance
    -- These inherit from parent table but we create them explicitly for better control
    EXECUTE format('
        CREATE INDEX IF NOT EXISTS %I ON %I (api_key, modem_id, timestamp)
    ', '${PARTITION_NAME}_api_key_modem_ts_idx', '$PARTITION_NAME');

    EXECUTE format('
        CREATE INDEX IF NOT EXISTS %I ON %I (username, action, timestamp)
    ', '${PARTITION_NAME}_user_action_ts_idx', '$PARTITION_NAME');

    EXECUTE format('
        CREATE INDEX IF NOT EXISTS %I ON %I (action, success, timestamp)
    ', '${PARTITION_NAME}_action_success_ts_idx', '$PARTITION_NAME');

    EXECUTE format('
        CREATE INDEX IF NOT EXISTS %I ON %I (timestamp)
    ', '${PARTITION_NAME}_timestamp_idx', '$PARTITION_NAME');

    RAISE NOTICE 'Partition % created successfully', '$PARTITION_NAME';

EXCEPTION
    WHEN duplicate_table THEN
        RAISE NOTICE 'Partition % already exists, skipping', '$PARTITION_NAME';
    WHEN OTHERS THEN
        RAISE EXCEPTION 'Failed to create partition %: %', '$PARTITION_NAME', SQLERRM;
END;
\$\$;
"

# Execute SQL
if $PSQL_CMD -v ON_ERROR_STOP=1 <<< "$SQL"; then
    echo "SUCCESS: Partition $PARTITION_NAME created/verified"

    # Verify partition exists
    VERIFY_SQL="
        SELECT schemaname, tablename,
               pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
        FROM pg_tables
        WHERE tablename = '$PARTITION_NAME';
    "

    echo ""
    echo "Partition details:"
    $PSQL_CMD -c "$VERIFY_SQL"

    exit 0
else
    echo "ERROR: Failed to create partition $PARTITION_NAME"
    exit 1
fi
