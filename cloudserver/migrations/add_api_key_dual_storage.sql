-- Migration: Add dual storage for API keys (hash + encrypted)
-- Version: 7.1.0
-- Date: 2025-12-16
--
-- Purpose:
--   Migrate from plaintext-only API key storage to dual storage:
--   - api_key_hash: SHA-256 hash for fast validation (indexed)
--   - api_key_encrypted: AES-256-GCM encrypted plaintext (admin reveal)
--   - encryption_salt: Random salt for encryption
--   - migrated: Track migration progress
--
-- Security Benefits:
--   - Hash-based validation (one-way, cannot reverse)
--   - Encrypted plaintext for admin UX (requires SECRET_KEY to decrypt)
--   - Defense-in-depth: Database compromise doesn't expose plaintext
--
-- Run with:
--   psql -U modemcheck -d modemcheck < migrations/add_api_key_dual_storage.sql

BEGIN;

-- Step 1: Add new columns to api_keys table
ALTER TABLE api_keys
  ADD COLUMN api_key_hash VARCHAR(64),           -- SHA-256 hash (64 hex chars)
  ADD COLUMN api_key_encrypted TEXT,             -- AES-256-GCM encrypted (variable length)
  ADD COLUMN encryption_salt VARCHAR(32),        -- 16-byte salt as hex (32 chars)
  ADD COLUMN migrated BOOLEAN DEFAULT FALSE;     -- Migration tracking flag

-- Step 2: Create index on hash for fast lookups
-- This is a partial index (only indexes rows with non-null hash)
-- Improves performance and reduces index size
CREATE INDEX idx_api_keys_hash
ON api_keys(api_key_hash)
WHERE api_key_hash IS NOT NULL;

-- Step 3: Create backward compatibility function
-- Allows queries by either plaintext OR hash during migration period
-- Usage: SELECT * FROM find_api_key('...')
CREATE OR REPLACE FUNCTION find_api_key(key_input TEXT)
RETURNS TABLE (
  api_key VARCHAR(255),
  api_key_hash VARCHAR(64),
  api_key_encrypted TEXT,
  encryption_salt VARCHAR(32),
  name VARCHAR(255),
  is_active BOOLEAN,
  created_at TIMESTAMP WITH TIME ZONE,
  last_used TIMESTAMP WITH TIME ZONE,
  expires_at TIMESTAMP WITH TIME ZONE,
  migrated BOOLEAN
) AS $$
BEGIN
  -- Try hash lookup first (new way, fast with index)
  RETURN QUERY
  SELECT
    ak.api_key,
    ak.api_key_hash,
    ak.api_key_encrypted,
    ak.encryption_salt,
    ak.name,
    ak.is_active,
    ak.created_at,
    ak.last_used,
    ak.expires_at,
    ak.migrated
  FROM api_keys ak
  WHERE ak.api_key_hash = key_input
  LIMIT 1;

  IF NOT FOUND THEN
    -- Fall back to plaintext lookup (old way, during migration only)
    RETURN QUERY
    SELECT
      ak.api_key,
      ak.api_key_hash,
      ak.api_key_encrypted,
      ak.encryption_salt,
      ak.name,
      ak.is_active,
      ak.created_at,
      ak.last_used,
      ak.expires_at,
      ak.migrated
    FROM api_keys ak
    WHERE ak.api_key = key_input
    LIMIT 1;
  END IF;
END;
$$ LANGUAGE plpgsql;

-- Step 4: Verify migration
-- Check that columns were added successfully
DO $$
DECLARE
  column_count INTEGER;
BEGIN
  SELECT COUNT(*) INTO column_count
  FROM information_schema.columns
  WHERE table_name = 'api_keys'
    AND column_name IN ('api_key_hash', 'api_key_encrypted', 'encryption_salt', 'migrated');

  IF column_count != 4 THEN
    RAISE EXCEPTION 'Migration verification failed: Expected 4 new columns, found %', column_count;
  END IF;

  RAISE NOTICE '✓ Migration successful: Added 4 columns to api_keys table';
END $$;

COMMIT;

-- Post-migration instructions:
-- 1. Run Python migration script: python migrations/migrate_api_keys_to_dual_storage.py
-- 2. Verify all keys migrated: SELECT COUNT(*) FROM api_keys WHERE migrated = TRUE;
-- 3. Deploy updated application code
-- 4. Monitor for 30 days before Phase 8 cleanup
