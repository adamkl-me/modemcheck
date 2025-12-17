-- Migration: Add api_key_hash column to client_configs (Phase 4)
-- Version: 7.1.0
-- Date: 2025-12-16
--
-- Purpose:
--   Add api_key_hash column to client_configs table for future FK migration.
--   Maintains backward compatibility by keeping both plaintext and hash FKs during transition.
--
-- Security Benefits:
--   - Prepares for hash-based FK relationships
--   - Maintains CASCADE delete behavior
--   - No breaking changes during migration
--
-- Run with:
--   psql -U modemcheck -d modemcheck < migrations/add_client_config_hash_column.sql

BEGIN;

-- Step 1: Add api_key_hash column to client_configs
ALTER TABLE client_configs
  ADD COLUMN api_key_hash VARCHAR(64);

-- Step 2: Create index for performance (hash lookups)
CREATE INDEX idx_client_configs_hash
ON client_configs(api_key_hash);

-- Step 3: Populate api_key_hash from api_keys table (join by plaintext api_key)
-- This ensures all existing configs get their hash values
UPDATE client_configs cc
SET api_key_hash = ak.api_key_hash
FROM api_keys ak
WHERE cc.api_key = ak.api_key
  AND ak.api_key_hash IS NOT NULL;

-- Step 4: Add foreign key constraint on hash (with CASCADE delete)
-- CRITICAL: Must preserve ON DELETE CASCADE behavior from original FK
ALTER TABLE client_configs
  ADD CONSTRAINT fk_client_configs_api_key_hash
  FOREIGN KEY (api_key_hash)
  REFERENCES api_keys(api_key_hash)
  ON DELETE CASCADE;

-- Step 5: Verification
DO $$
DECLARE
  hash_column_exists BOOLEAN;
  fk_exists BOOLEAN;
  row_count INTEGER;
  null_hash_count INTEGER;
BEGIN
  -- Check column exists
  SELECT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_name = 'client_configs'
      AND column_name = 'api_key_hash'
  ) INTO hash_column_exists;

  IF NOT hash_column_exists THEN
    RAISE EXCEPTION 'Migration verification failed: api_key_hash column not found';
  END IF;

  -- Check FK constraint exists
  SELECT EXISTS (
    SELECT 1
    FROM information_schema.table_constraints
    WHERE constraint_name = 'fk_client_configs_api_key_hash'
      AND table_name = 'client_configs'
  ) INTO fk_exists;

  IF NOT fk_exists THEN
    RAISE EXCEPTION 'Migration verification failed: FK constraint not found';
  END IF;

  -- Check all rows have hash populated
  SELECT COUNT(*) INTO row_count FROM client_configs;
  SELECT COUNT(*) INTO null_hash_count FROM client_configs WHERE api_key_hash IS NULL;

  IF null_hash_count > 0 THEN
    RAISE WARNING 'Migration warning: % out of % client_configs have NULL api_key_hash', null_hash_count, row_count;
    RAISE WARNING 'This may indicate API keys that have not been migrated yet';
  END IF;

  RAISE NOTICE '✓ Migration successful:';
  RAISE NOTICE '  - Added api_key_hash column to client_configs';
  RAISE NOTICE '  - Created index: idx_client_configs_hash';
  RAISE NOTICE '  - Populated % rows with hash values', row_count - null_hash_count;
  RAISE NOTICE '  - Created FK constraint with CASCADE delete';
END $$;

COMMIT;

-- Post-migration notes:
-- 1. Both api_key and api_key_hash FKs now exist (dual storage during migration)
-- 2. Application code should start using api_key_hash for new queries
-- 3. Phase 8 cleanup will remove api_key FK after 30-day stabilization
-- 4. CASCADE delete behavior preserved: deleting API key → deletes all configs
