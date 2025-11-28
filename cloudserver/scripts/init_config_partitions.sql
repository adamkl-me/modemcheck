-- ============================================================================
-- Config Management Tables Initialization
-- ============================================================================
-- This script creates the partitioned parent table for config_audit_logs
-- and the first partition for the current month.
--
-- Run this ONCE before starting the application for the first time.
-- Monthly partitions are then created automatically by create_audit_partition.sh
--
-- Usage:
--   psql -U modemcheck -d modemcheck -f init_config_partitions.sql
-- ============================================================================

-- Create config_audit_logs as a partitioned table
-- Note: The ConfigAuditLog SQLAlchemy model defines columns, but partitioning
-- must be done manually as SQLAlchemy doesn't support declarative partitioning

CREATE TABLE IF NOT EXISTS config_audit_logs (
    id BIGSERIAL,
    timestamp TIMESTAMPTZ NOT NULL,
    username VARCHAR(255),
    api_key_hash VARCHAR(64),
    ip_address VARCHAR(45) NOT NULL,
    api_key VARCHAR(255) NOT NULL,
    modem_id VARCHAR(255) NOT NULL,
    action VARCHAR(100) NOT NULL,
    config_summary JSONB,
    old_version INTEGER,
    new_version INTEGER,
    old_mode VARCHAR(50),
    new_mode VARCHAR(50),
    success BOOLEAN NOT NULL,
    failure_reason TEXT,
    PRIMARY KEY (id, timestamp)
) PARTITION BY RANGE (timestamp);

COMMENT ON TABLE config_audit_logs IS 'Configuration audit log (partitioned by month)';

-- Create indexes on parent table (inherited by partitions)
CREATE INDEX IF NOT EXISTS idx_config_audit_timestamp ON config_audit_logs (timestamp);
CREATE INDEX IF NOT EXISTS idx_config_audit_username ON config_audit_logs (username);
CREATE INDEX IF NOT EXISTS idx_config_audit_api_key_hash ON config_audit_logs (api_key_hash);
CREATE INDEX IF NOT EXISTS idx_config_audit_api_key ON config_audit_logs (api_key);
CREATE INDEX IF NOT EXISTS idx_config_audit_modem_id ON config_audit_logs (modem_id);
CREATE INDEX IF NOT EXISTS idx_config_audit_action ON config_audit_logs (action);
CREATE INDEX IF NOT EXISTS idx_config_audit_success ON config_audit_logs (success);

-- Composite indexes (for efficient queries)
CREATE INDEX IF NOT EXISTS idx_config_audit_client ON config_audit_logs (api_key, modem_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_config_audit_user_action ON config_audit_logs (username, action, timestamp);
CREATE INDEX IF NOT EXISTS idx_config_audit_action_success ON config_audit_logs (action, success, timestamp);

-- Create first partition for current month
DO $$
DECLARE
    current_month_start DATE := DATE_TRUNC('month', CURRENT_DATE);
    next_month_start DATE := DATE_TRUNC('month', CURRENT_DATE + INTERVAL '1 month');
    partition_name TEXT := 'config_audit_logs_' || TO_CHAR(current_month_start, 'YYYYMM');
BEGIN
    -- Create partition for current month
    EXECUTE format('
        CREATE TABLE IF NOT EXISTS %I PARTITION OF config_audit_logs
        FOR VALUES FROM (%L) TO (%L)
    ', partition_name, current_month_start, next_month_start);

    RAISE NOTICE 'Created partition: %', partition_name;
END $$;

-- Verify partitions
SELECT
    parent.relname AS parent_table,
    child.relname AS partition_name,
    pg_get_expr(child.relpartbound, child.oid) AS partition_range
FROM pg_inherits
JOIN pg_class parent ON pg_inherits.inhparent = parent.oid
JOIN pg_class child ON pg_inherits.inhrelid = child.oid
WHERE parent.relname = 'config_audit_logs'
ORDER BY child.relname;

RAISE NOTICE 'Config audit log partitioning initialized successfully';
