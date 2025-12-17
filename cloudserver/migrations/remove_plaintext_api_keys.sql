-- Migration: Remove plaintext API key columns (Phase 8)
-- Version: 8.0.0
-- Date: 2025-12-16
--
-- PREREQUISITES:
--   - All api_keys must have api_key_hash populated (run migrate_api_keys_to_dual_storage.py first)
--   - All client_configs must have api_key_hash populated (add_client_config_hash_column.sql)
--   - Backup database before running!
--
-- CHANGES:
--   1. api_keys: Change PK from api_key to api_key_hash, drop api_key column
--   2. client_configs: Change PK from api_key to api_key_hash, drop api_key column
--   3. config_versions: Add api_key_hash column, drop api_key column
--   4. config_audit_logs: Drop deprecated api_key column

BEGIN;

-- ============================================================================
-- STEP 0: Validation - Ensure all data is ready for migration
-- ============================================================================

DO $$
DECLARE
    null_hash_count INTEGER;
    null_config_hash_count INTEGER;
BEGIN
    -- Check api_keys have hashes
    SELECT COUNT(*) INTO null_hash_count
    FROM api_keys WHERE api_key_hash IS NULL;

    IF null_hash_count > 0 THEN
        RAISE EXCEPTION 'ABORT: % api_keys have NULL api_key_hash. Run migrate_api_keys_to_dual_storage.py first.', null_hash_count;
    END IF;

    -- Check client_configs have hashes
    SELECT COUNT(*) INTO null_config_hash_count
    FROM client_configs WHERE api_key_hash IS NULL;

    IF null_config_hash_count > 0 THEN
        RAISE EXCEPTION 'ABORT: % client_configs have NULL api_key_hash. Run add_client_config_hash_column.sql first.', null_config_hash_count;
    END IF;

    RAISE NOTICE '✓ Validation passed: All records have api_key_hash populated';
END $$;

-- ============================================================================
-- STEP 1: config_versions - Add api_key_hash column and populate
-- ============================================================================

-- Add api_key_hash column to config_versions
ALTER TABLE config_versions
    ADD COLUMN IF NOT EXISTS api_key_hash VARCHAR(64);

-- Populate api_key_hash from api_keys table (join on plaintext api_key)
UPDATE config_versions cv
SET api_key_hash = ak.api_key_hash
FROM api_keys ak
WHERE cv.api_key = ak.api_key
  AND cv.api_key_hash IS NULL;

-- Verify all config_versions have hash
DO $$
DECLARE
    null_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO null_count FROM config_versions WHERE api_key_hash IS NULL;
    IF null_count > 0 THEN
        RAISE EXCEPTION 'ABORT: % config_versions have NULL api_key_hash after population', null_count;
    END IF;
    RAISE NOTICE '✓ config_versions: api_key_hash populated for all rows';
END $$;

-- Make api_key_hash NOT NULL
ALTER TABLE config_versions
    ALTER COLUMN api_key_hash SET NOT NULL;

-- Create new index on api_key_hash
CREATE INDEX IF NOT EXISTS idx_config_version_hash ON config_versions(api_key_hash);
CREATE INDEX IF NOT EXISTS idx_config_version_hash_created ON config_versions(api_key_hash, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_config_version_unique_hash ON config_versions(api_key_hash, version_number);

-- Drop old indexes that use api_key
DROP INDEX IF EXISTS idx_config_version_unique_v3;
DROP INDEX IF EXISTS idx_config_version_history;

-- Drop api_key column from config_versions
ALTER TABLE config_versions DROP COLUMN api_key;

DO $$ BEGIN RAISE NOTICE '✓ config_versions: Migrated to api_key_hash'; END $$;

-- ============================================================================
-- STEP 2: config_audit_logs - Drop deprecated api_key column
-- ============================================================================

-- Drop api_key column (already deprecated, api_key_hash is used)
ALTER TABLE config_audit_logs DROP COLUMN IF EXISTS api_key;

-- Drop old index that references api_key
DROP INDEX IF EXISTS idx_config_audit_client;
DROP INDEX IF EXISTS idx_config_audit_modem_change;

-- Create new indexes using api_key_hash
CREATE INDEX IF NOT EXISTS idx_config_audit_hash ON config_audit_logs(api_key_hash, timestamp);
CREATE INDEX IF NOT EXISTS idx_config_audit_modem_change_hash ON config_audit_logs(api_key_hash, action, timestamp) WHERE action = 'modem_change';

DO $$ BEGIN RAISE NOTICE '✓ config_audit_logs: Dropped deprecated api_key column'; END $$;

-- ============================================================================
-- STEP 3: client_configs - Change PK from api_key to api_key_hash
-- ============================================================================

-- Drop the old FK constraint on api_key
ALTER TABLE client_configs DROP CONSTRAINT IF EXISTS client_configs_api_key_fkey;

-- Drop the primary key constraint (currently on api_key)
ALTER TABLE client_configs DROP CONSTRAINT IF EXISTS client_configs_pkey;

-- Add new primary key on api_key_hash
ALTER TABLE client_configs ADD PRIMARY KEY (api_key_hash);

-- Drop the api_key column
ALTER TABLE client_configs DROP COLUMN api_key;

DO $$ BEGIN RAISE NOTICE '✓ client_configs: Changed PK to api_key_hash, dropped api_key column'; END $$;

-- ============================================================================
-- STEP 4: api_keys - Change PK from api_key to api_key_hash
-- ============================================================================

-- First, drop the FK that depends on the unique constraint
ALTER TABLE client_configs DROP CONSTRAINT IF EXISTS fk_client_configs_api_key_hash;

-- Drop the existing primary key (on api_key)
ALTER TABLE api_keys DROP CONSTRAINT IF EXISTS api_keys_pkey;

-- Drop the unique constraint on api_key_hash (will become PK)
ALTER TABLE api_keys DROP CONSTRAINT IF EXISTS api_keys_hash_unique;

-- Add new primary key on api_key_hash
ALTER TABLE api_keys ADD PRIMARY KEY (api_key_hash);

-- Re-add the FK constraint now that PK exists
ALTER TABLE client_configs ADD CONSTRAINT fk_client_configs_api_key_hash
    FOREIGN KEY (api_key_hash) REFERENCES api_keys(api_key_hash) ON DELETE CASCADE;

-- Drop old indexes on api_key
DROP INDEX IF EXISTS ix_api_keys_api_key;

-- Drop the api_key column
ALTER TABLE api_keys DROP COLUMN api_key;

-- Drop the migrated flag (no longer needed)
ALTER TABLE api_keys DROP COLUMN IF EXISTS migrated;

DO $$ BEGIN RAISE NOTICE '✓ api_keys: Changed PK to api_key_hash, dropped api_key column'; END $$;

-- ============================================================================
-- STEP 5: Verify FK constraint
-- ============================================================================

DO $$
DECLARE
    fk_exists BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'fk_client_configs_api_key_hash'
          AND table_name = 'client_configs'
    ) INTO fk_exists;

    IF fk_exists THEN
        RAISE NOTICE '✓ FK constraint fk_client_configs_api_key_hash verified';
    ELSE
        RAISE EXCEPTION 'FK constraint fk_client_configs_api_key_hash is missing!';
    END IF;
END $$;

-- ============================================================================
-- STEP 6: Final validation
-- ============================================================================

DO $$
DECLARE
    api_keys_count INTEGER;
    client_configs_count INTEGER;
    config_versions_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO api_keys_count FROM api_keys;
    SELECT COUNT(*) INTO client_configs_count FROM client_configs;
    SELECT COUNT(*) INTO config_versions_count FROM config_versions;

    RAISE NOTICE '';
    RAISE NOTICE '============================================';
    RAISE NOTICE 'Migration Complete - Phase 8 Summary';
    RAISE NOTICE '============================================';
    RAISE NOTICE 'api_keys: % rows (PK: api_key_hash)', api_keys_count;
    RAISE NOTICE 'client_configs: % rows (PK: api_key_hash)', client_configs_count;
    RAISE NOTICE 'config_versions: % rows (uses api_key_hash)', config_versions_count;
    RAISE NOTICE '';
    RAISE NOTICE 'Removed columns:';
    RAISE NOTICE '  - api_keys.api_key (plaintext)';
    RAISE NOTICE '  - api_keys.migrated (no longer needed)';
    RAISE NOTICE '  - client_configs.api_key (plaintext)';
    RAISE NOTICE '  - config_versions.api_key (plaintext)';
    RAISE NOTICE '  - config_audit_logs.api_key (deprecated)';
    RAISE NOTICE '';
    RAISE NOTICE '✅ Plaintext API keys have been removed from database';
    RAISE NOTICE '============================================';
END $$;

COMMIT;
