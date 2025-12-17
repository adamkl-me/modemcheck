# ModemCheck v7.1 Deployment Guide: API Key Security Migration

**Target Version**: v7.1.0
**Migration Type**: Database + Application (requires downtime)
**Estimated Downtime**: 30-60 minutes
**Risk Level**: MEDIUM (comprehensive testing done, rollback available)

---

## Overview

This deployment implements **Option C: Hash + Encrypted Plaintext** for API key security:

- **Hash-based validation** (SHA-256) - prevents plaintext exposure in queries
- **AES-256-GCM encryption** - allows admin reveal functionality
- **Redis cache security fix** - stores only hashes (no plaintext)

**Security Improvement**: ~85% risk reduction (HIGH → LOW/MEDIUM)

---

## Pre-Deployment Checklist

### 1. Environment Verification

```bash
# Verify you're on the correct branch
git status
git log -1 --oneline

# Verify SECRET_KEY is set and backed up
grep SECRET_KEY cloudserver/.env
# ⚠️ CRITICAL: Backup SECRET_KEY - required for decryption!

# Verify PostgreSQL version
docker exec modemcheck-postgres psql -U modemcheck -c "SELECT version();"
# Must be PostgreSQL 12+

# Verify Redis is running
docker exec modemcheck-redis redis-cli PING
# Should return: PONG
```

### 2. Backup Everything

```bash
# 1. Database backup
./cloudserver/backup-database.sh
# Creates: backups/postgres/modemcheck_YYYYMMDD_HHMMSS.sql.gz

# 2. Backup .env file (contains SECRET_KEY!)
cp cloudserver/.env cloudserver/.env.backup_$(date +%Y%m%d)
chmod 600 cloudserver/.env.backup_*

# 3. Redis backup (optional, cache data)
docker exec modemcheck-redis redis-cli SAVE
docker cp modemcheck-redis:/data/dump.rdb backups/redis/dump_$(date +%Y%m%d).rdb

# 4. Git commit checkpoint
git add -A
git commit -m "Pre-migration checkpoint for v7.1"
```

### 3. Test Environment Validation

```bash
# Run full test suite
cd cloudserver
./run_all_tests.sh

# Expected: All tests pass (~700 tests)
# If failures, investigate before proceeding
```

---

## Deployment Steps

### Phase 1: Database Schema Migration (5-10 minutes)

```bash
# 1. Enter maintenance mode
# (Optional: Update status page, notify users)

# 2. Stop application (prevents partial writes during migration)
docker-compose stop cloud-api

# 3. Run database migrations
docker exec modemcheck-postgres psql -U modemcheck -d modemcheck < cloudserver/migrations/add_api_key_dual_storage.sql

# Expected output:
# ✓ Migration successful: Added 4 columns to api_keys table

# 4. Verify migration
docker exec modemcheck-postgres psql -U modemcheck -d modemcheck -c "
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'api_keys'
AND column_name IN ('api_key_hash', 'api_key_encrypted', 'encryption_salt', 'migrated');
"

# Expected: 4 rows returned
```

### Phase 2: API Key Data Migration (10-20 minutes)

```bash
# 1. Run encryption migration
cd cloudserver
python migrations/migrate_api_keys_to_dual_storage.py

# Expected output:
# ================================================================
# API Key Migration to Dual Storage (Hash + Encrypted)
# ================================================================
# ✓ SECRET_KEY available (length: XX chars)
# Total API keys in database: N
# Keys requiring migration: N
# [1/N] ✓ Migrated: key_name (12345678...)
# ...
# ✓ Successfully migrated N keys
# ✓ All N keys validated successfully
# ✓ Decryption test passed for 3 sample keys
# ================================================================
# Migration Summary
# ================================================================
# Status: ✅ SUCCESS
# Total keys: N
# Migrated: N
# Failed: 0

# 2. Verify all keys migrated
docker exec modemcheck-postgres psql -U modemcheck -d modemcheck -c "
SELECT
    COUNT(*) as total,
    COUNT(*) FILTER (WHERE migrated = TRUE) as migrated_count,
    COUNT(*) FILTER (WHERE api_key_hash IS NOT NULL) as with_hash,
    COUNT(*) FILTER (WHERE api_key_encrypted IS NOT NULL) as with_encrypted
FROM api_keys;
"

# Expected: total = migrated_count = with_hash = with_encrypted
```

### Phase 3: Client Configs FK Migration (2-5 minutes)

```bash
# 1. Run client_configs migration
docker exec modemcheck-postgres psql -U modemcheck -d modemcheck < cloudserver/migrations/add_client_config_hash_column.sql

# Expected output:
# ✓ Migration successful:
#   - Added api_key_hash column to client_configs
#   - Created index: idx_client_configs_hash
#   - Populated N rows with hash values
#   - Created FK constraint with CASCADE delete

# 2. Verify FK constraint
docker exec modemcheck-postgres psql -U modemcheck -d modemcheck -c "
SELECT conname, conrelid::regclass, confrelid::regclass
FROM pg_constraint
WHERE conname = 'fk_client_configs_api_key_hash';
"

# Expected: 1 row showing FK relationship
```

### Phase 4: Deploy Application (5-10 minutes)

```bash
# 1. Pull latest code (if using Git deployment)
git pull origin main

# 2. Rebuild and restart services
docker-compose build cloud-api
docker-compose up -d

# 3. Wait for services to be healthy
docker-compose ps

# Expected: All services "Up" and healthy

# 4. Check logs for errors
docker-compose logs -f --tail=100 cloud-api

# Look for:
# ✓ "Application startup complete"
# ✓ No errors about missing columns
# ✗ Any exceptions or tracebacks
```

### Phase 5: Smoke Tests (5-10 minutes)

```bash
# 1. Test API key creation (admin endpoint)
# Login to admin UI: https://your-domain/admin
# Navigate to: API Keys → Create New Key
# ✓ Should succeed and show plaintext key once
# ✓ Verify key appears in list with preview (XXXX...YYYY)

# 2. Test API key reveal (admin endpoint)
# Click "Reveal" on any existing key
# ✓ Should decrypt and show full key
# ✓ Check audit log shows reveal_api_key action

# 3. Test upload (client endpoint)
# Use existing client or curl:
curl -X POST https://your-domain/api/upload \
  -F "api_key=YOUR_TEST_KEY" \
  -F "modem_id=test_modem_123" \
  -F "filename=test_upload.json" \
  -F "checksum=$(sha256sum test.json | cut -d' ' -f1)" \
  -F "file=@test.json" \
  -H "X-Request-Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  -H "X-Request-Signature: YOUR_HMAC_SIG"

# ✓ Should return: {"success": true, ...}
# ✗ Should NOT return: "Invalid API key"

# 4. Test config sync (client endpoint)
# Run modemcheck client with config sync enabled
# ✓ Should sync successfully
# ✓ Check logs: "Config sync completed"

# 5. Verify cache behavior
docker exec modemcheck-redis redis-cli GET "api_keys:active"
# ✓ Should contain: [{"api_key_hash": "...", "name": "..."}]
# ✗ Should NOT contain: "api_key" field (no plaintext!)
```

### Phase 6: Monitoring (First Hour)

```bash
# 1. Monitor application logs
docker-compose logs -f cloud-api | grep -i error

# 2. Monitor database connections
docker exec modemcheck-postgres psql -U modemcheck -d modemcheck -c "
SELECT count(*) as active_connections
FROM pg_stat_activity
WHERE datname = 'modemcheck';
"

# 3. Check cache hit rates
# In admin UI: System Info → Cache Statistics
# Target: >80% cache hit rate

# 4. Monitor upload latency
# Check response times in logs
# Target: <500ms for uploads (should be similar to pre-migration)

# 5. Check audit logs
docker exec modemcheck-postgres psql -U modemcheck -d modemcheck -c "
SELECT action_type, COUNT(*)
FROM user_activity_log
WHERE timestamp > NOW() - INTERVAL '1 hour'
GROUP BY action_type;
"

# Look for:
# - reveal_api_key (admin reveals)
# - create_api_key (new key creations)
```

---

## Post-Deployment Validation

### Functional Tests

```bash
# Run full test suite against production
cd cloudserver
TESTING=false pytest tests/ -v

# Expected: All tests pass
```

### Security Validation

```bash
# 1. Verify Redis has no plaintext
docker exec modemcheck-redis redis-cli --scan --pattern "api_keys:*" | \
  xargs docker exec modemcheck-redis redis-cli GET | \
  grep -i "api_key_hash"

# ✓ Should find: "api_key_hash"
# ✗ Should NOT find: plaintext API keys

# 2. Verify database encryption
docker exec modemcheck-postgres psql -U modemcheck -d modemcheck -c "
SELECT
    name,
    LENGTH(api_key_hash) as hash_length,
    LENGTH(api_key_encrypted) as encrypted_length,
    migrated
FROM api_keys
LIMIT 5;
"

# ✓ hash_length should be 64
# ✓ encrypted_length should be > 100
# ✓ migrated should be TRUE

# 3. Test decryption (admin access required)
# Login to admin → API Keys → Reveal any key
# ✓ Should show full plaintext key
# ✓ Check audit_log for reveal_api_key entry
```

---

## Rollback Procedure

**If critical issues found within 24 hours:**

### Quick Rollback (10-15 minutes)

```bash
# 1. Stop application
docker-compose stop cloud-api

# 2. Restore database from backup
./cloudserver/restore-database.sh backups/postgres/modemcheck_YYYYMMDD_HHMMSS.sql.gz

# 3. Revert application code
git revert <migration_commit_hash>
docker-compose build cloud-api
docker-compose up -d

# 4. Verify rollback
docker-compose logs -f cloud-api
# Check for successful startup

# 5. Run smoke tests (same as Phase 5 above)
```

### Manual Rollback SQL

**If restore script unavailable:**

```sql
BEGIN;

-- Revert client_configs
ALTER TABLE client_configs DROP CONSTRAINT fk_client_configs_api_key_hash;
ALTER TABLE client_configs DROP COLUMN api_key_hash;

-- Revert api_keys
ALTER TABLE api_keys DROP COLUMN api_key_hash;
ALTER TABLE api_keys DROP COLUMN api_key_encrypted;
ALTER TABLE api_keys DROP COLUMN encryption_salt;
ALTER TABLE api_keys DROP COLUMN migrated;

-- Drop indexes
DROP INDEX IF EXISTS idx_api_keys_hash;
DROP INDEX IF EXISTS idx_client_configs_hash;

-- Drop function
DROP FUNCTION IF EXISTS find_api_key(TEXT);

COMMIT;
```

---

## Troubleshooting

### Issue: Migration script fails with "SECRET_KEY not set"

**Solution:**
```bash
# Verify .env file
cat cloudserver/.env | grep SECRET_KEY

# If missing, restore from backup
cp cloudserver/.env.backup_YYYYMMDD cloudserver/.env

# Re-run migration
python cloudserver/migrations/migrate_api_keys_to_dual_storage.py
```

### Issue: Upload returns "Invalid API key" after migration

**Diagnosis:**
```bash
# Check if key was migrated
docker exec modemcheck-postgres psql -U modemcheck -d modemcheck -c "
SELECT name, migrated, api_key_hash IS NOT NULL as has_hash
FROM api_keys
WHERE name = 'YOUR_KEY_NAME';
"
```

**Solution:**
- If `migrated = FALSE`: Re-run migration script
- If `has_hash = FALSE`: Key not encrypted, re-run migration
- If both TRUE: Check application logs for hash mismatch

### Issue: Reveal endpoint returns 500 error

**Diagnosis:**
```bash
# Check logs
docker-compose logs cloud-api | grep reveal_api_key

# Common error: "Invalid tag" → Decryption failure
```

**Solution:**
```bash
# Verify SECRET_KEY hasn't changed
# SECRET_KEY must match the one used during encryption!

# If SECRET_KEY changed, restore from backup
cp cloudserver/.env.backup_YYYYMMDD cloudserver/.env
docker-compose restart cloud-api
```

### Issue: Cache hit rate drops significantly

**Diagnosis:**
```bash
# Check cache contents
docker exec modemcheck-redis redis-cli GET "api_keys:active"
```

**Solution:**
```bash
# Invalidate and repopulate cache
docker exec modemcheck-redis redis-cli DEL "api_keys:active"

# Trigger cache population (make any upload request)
# Cache should repopulate automatically
```

---

## Success Metrics

After 24 hours, verify:

✅ **Functional**:
- All uploads successful (same success rate as pre-migration)
- Config sync working (no client errors)
- Admin UI working (create/reveal keys)

✅ **Performance**:
- Upload latency < +5ms from baseline
- Reveal endpoint < 100ms
- Cache hit rate > 80%

✅ **Security**:
- Redis stores only hashes (no plaintext)
- Audit logs show all reveal_api_key access
- No API key exposure in application logs

---

## Phase 8: Cleanup (After 30 Days)

**⚠️ ONLY run after 30 days of stable operation**

See: `migrations/remove_api_key_plaintext_column.sql` (to be created)

This will:
- Remove `api_key` plaintext column from `api_keys` table
- Make `api_key_hash` the new primary key
- Update `client_configs` FK to use hash only
- Remove migration compatibility code

---

## Support

**Questions or Issues:**
- Check logs: `docker-compose logs -f`
- Review audit logs in database
- Consult: `IMPLEMENTATION_STATUS.md`
- Reference: `~/.claude/plans/composed-moseying-aurora.md`

**Emergency Rollback Contact:**
- Follow rollback procedure above
- Document issues for post-mortem

---

## Appendix: SQL Verification Queries

```sql
-- Verify migration status
SELECT
    COUNT(*) as total_keys,
    COUNT(*) FILTER (WHERE migrated = TRUE) as migrated,
    COUNT(*) FILTER (WHERE api_key_hash IS NOT NULL) as with_hash,
    COUNT(*) FILTER (WHERE api_key_encrypted IS NOT NULL) as with_encrypted,
    COUNT(*) FILTER (WHERE encryption_salt IS NOT NULL) as with_salt
FROM api_keys;

-- Check foreign keys
SELECT
    con.conname AS constraint_name,
    rel.relname AS table_name,
    att.attname AS column_name,
    fnrel.relname AS foreign_table,
    fnatt.attname AS foreign_column
FROM pg_constraint con
JOIN pg_class rel ON con.conrelid = rel.oid
JOIN pg_attribute att ON att.attrelid = rel.oid AND att.attnum = ANY(con.conkey)
JOIN pg_class fnrel ON con.confrelid = fnrel.oid
JOIN pg_attribute fnatt ON fnatt.attrelid = fnrel.oid AND fnatt.attnum = ANY(con.confkey)
WHERE rel.relname IN ('api_keys', 'client_configs')
ORDER BY rel.relname, con.conname;

-- Check indexes
SELECT
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename IN ('api_keys', 'client_configs')
AND indexname LIKE '%hash%'
ORDER BY tablename, indexname;

-- Recent audit log activity
SELECT
    action_type,
    COUNT(*) as count,
    MAX(timestamp) as most_recent
FROM user_activity_log
WHERE timestamp > NOW() - INTERVAL '1 day'
GROUP BY action_type
ORDER BY count DESC;
```
