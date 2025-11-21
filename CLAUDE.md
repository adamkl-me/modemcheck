# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

ModemCheck is a cross-platform cable modem diagnostic tool with optional cloud storage:

- **Go client** (`modemcheck-client/`): Cross-platform binary that scrapes modem data, runs network diagnostics, and uploads to cloud
- **Cloud server** (`cloudserver/`): FastAPI-based platform with PostgreSQL storage and web UI

## Quick Start

### Build Commands
```bash
make                    # Cross-compile all platforms + auto-sign binaries
make build              # Build for current platform only
make test               # Go compilation test

# Platform-specific (no signing)
make linux linux-arm linux-arm64 linux-mipsle linux-mips windows macos
```

### Security & Signing
```bash
make setup-keys         # Generate Minisign keypair (one-time)
make update-public-key  # Embed public key in updater.go
make validate-public-key # Verify embedded key matches minisign.pub
make sign-binary BINARY=dist/modem-check-linux-x64
./sign-all.sh           # Batch-sign (requires 'expect' for automation)
```

**Note:** `validate-public-key` runs automatically during builds to detect key compromise or rotation issues.

### Testing
```bash
cd cloudserver && ./run_all_tests.sh              # Full suite (374 tests, 100% pass)
cd cloudserver && ./run_all_tests.sh --keep-env   # Keep test environment
cd cloudserver && ./run_all_tests.sh tests/api/   # Specific test directory
cd cloudserver && ./run_all_tests.sh -m rbac      # Tests by marker

# Coverage reports (see TESTING.md for details)
cd cloudserver && ./run_unit_coverage.sh          # Unit test coverage (80-95%)
cd cloudserver && ./run_e2e_coverage.sh           # E2E test coverage (85-95%)
cd cloudserver && ./run_combined_coverage.sh      # Combined coverage (90-98%)
```

## Architecture

### Cloud Server Stack (FastAPI v2)

**Technology:**
- **FastAPI**: Async web framework with OpenAPI docs at `/docs`
- **PostgreSQL 16**: JSONB storage for modem data
- **SQLAlchemy 2.0**: Async ORM with type hints
- **Redis 7**: Session storage and API key caching
- **Gunicorn + Uvicorn**: Production ASGI server
- **nginx**: Reverse proxy and static file serving

**Upload flow:** Client POST → FastAPI endpoint → Pydantic validation → PostgreSQL JSONB insert → JSON response

**Scalability:** v2 handles 1000+ clients vs v1's 100-200 (50-100ms upload latency vs 150-250ms)

### Auto-Update Security

**Protects against:** GitHub compromise, MITM attacks, CDN hijacking, tampered binaries

**Verification process:**
1. Public key hardcoded in `updater.go:31` (`MinisignPublicKey`)
2. Download binary + `.minisig` signature to temp files
3. Verify Ed25519 signature before execution
4. Test binary with `--version` flag
5. Atomic rename to prevent TOCTOU races
6. Automatic rollback using `.old` backup on failure

**Critical:** Signature file mtime must be ≥ binary mtime. The `sign-all.sh` script removes old `.minisig` files before re-signing.

### Modem Scraper Interface

Three modem implementations (Arris, Motorola, Xfinity) sharing common interface:

```go
type ModemScraper interface {
    Login() error
    GetMAC() (string, error)
    GetData(checkTime int64) (*ModemData, error)
    ClearFEC() error
    GetModemType() string
}
```

**Auto-detection:** Tries IPs 192.168.100.1, 192.168.0.1, 10.0.0.1, 172.20.0.1, matching HTML patterns to select implementation. Falls back to `last_successful_modem.json` on failure.

### Update Channels

- **stable** (default): Production releases via `/releases/latest`
- **beta/test**: Pre-releases via `/releases` (prerelease: true)

**Note:** Version comparison is lexicographic (works for `5.01.0` vs `5.02.0`, fails for `5.10.0` vs `5.9.0`)

## Security

### Upload Protection (v6.0.0+)
- **HMAC signatures**: Mandatory `X-Request-Timestamp` and `X-Request-Signature` headers
- **API key validation**: Timing-safe comparison with Redis caching (5min TTL, 10-100x faster)
- **Replay protection**: Timestamp validation prevents replay attacks
- **Implementation**: `app/routers/upload.py:158-195`

### Credential Management
- **Rotation script**: `cloudserver/update-db-password.sh` (32-byte DB password, 48-byte secrets)
- **File permissions**: `.env` restricted to chmod 600
- **Password hashing**: Argon2id (64MB, 3 iterations) with PBKDF2 fallback + auto-upgrade

### Session Management (Redis)
- **Session ID**: 32-byte token with 1-hour TTL (sliding window refresh)
- **Cookie flags**: HttpOnly, SameSite=Strict, Secure (HTTPS only)
- **Device fingerprinting**: SHA256(user-agent + IP), lenient mode allows IP changes
- **Concurrent sessions**: Max 5 per user, oldest auto-terminated
- **Anomaly logging**: IP/user-agent changes logged to Redis (30-day retention)

### Access Control
- **RBAC roles**:
  - `basic`: View data, change password
  - `elevated`: + create API keys, bulk upload, view logs
  - `admin`: + user management, delete checks, audit logs
- **CSRF protection**: 32-byte tokens (1hr TTL) required for state-changing operations
- **Account lockout**: 5 failed attempts → 30min lockout
- **Rate limiting**:
  - IP-based: 30/min (auth), 60/min (upload), 300/sec (API)
  - Per-user: 100/hr global across all IPs

### Audit & Backup
- **Retention**: 90 days for user activity and client submission logs
- **Cleanup**: `cleanup-audit-logs.py` with dry-run support
- **Backups**: Daily PostgreSQL/Redis backups (30-day retention, gzip verified)
- **RTO**: <10 minutes for database restore
- **Scripts**: `backup-all.sh`, `restore-database.sh` (see `cloudserver/OPERATIONS.md`)

## Performance (v6.0.1)

### Database Optimizations
- **8 indexes** added via `add_performance_indexes.py` (CONCURRENTLY for zero downtime):
  - API key composite index for upload validation
  - Modem-specific and time-based indexes
  - Signal quality, speedtest, ISP indexes
  - Audit log indexes (user + action timestamps)
- **Performance gain**: 5-100x faster queries on indexed columns
- **Metric extraction**: 40+ metrics extracted to dedicated columns (no JSONB parsing)

### Client Optimizations
- **HTTP client reuse**: Shared client in `diagnostics.go` (10 idle conns, 30s timeout)
- **TLS savings**: Eliminates 3-5 handshakes per check (75% reduction)
- **Code deduplication**: `fetchJSONFromService()` consolidates ~80 lines
- **Memory safety**: 2MB response limit in `readResponseBody()` prevents OOM

## Client Features

### Network Diagnostics
**Three-tier IP detection** (`diagnostics.go:365-530`):
1. **ipapi.co**: Full details (IP, ASN, org, city, country)
2. **ip-api.com**: Fallback with full details
3. **ipify.org**: IP only (ultra-reliable)

### Speed Test Intervals
Configurable via `SpeedTestInterval` in config.json:
- `1`: Run every check
- `N`: Run every Nth check
- **Auto-retry**: Retries immediately if last test failed

State: `ModemCheck-Results/[MODEM]/speedtest_state.json`

Output: Normal result, `-1` (disabled), `-2` (skipped per interval)

### Upload Queue & Retry
**File:** `ModemCheck-Results/.upload_queue.json` (max 100 entries, FIFO eviction)

**Retry logic:**
1. Failed upload → Add to queue
2. Next run → Process queue before new check
3. Success → Remove from queue
4. Failure → Increment attempts, update error
5. Age >14 days → Auto-remove

## Testing

### Test Suite (374 tests, 100% pass rate)

**Test Categories:**
- API (200+ tests): All endpoints, validation, metric extraction, audit retention
- Security (50+ tests): SQL injection, XSS, CSRF, auth bypass, rate limiting
- RBAC (20+ tests): Role permissions for all endpoints
- Unit (99 tests): ZIP security, cache stats, pure functions
- UI (10+ tests): Playwright browser automation

**Coverage Reports:**
ModemCheck provides **four coverage report types** showing different test perspectives:
- **Standard** (`run_all_tests.sh`): 33% (unit tests, E2E code excluded for honest metrics)
- **Unit Only** (`run_unit_coverage.sh`): 80-95% on core utilities
- **E2E Only** (`run_e2e_coverage.sh`): 85-95% on routers/middleware (**proves they're tested**)
- **Combined** (`run_combined_coverage.sh`): 90-98% total coverage

**Dynamic Contexts:** All reports support click-through to see which specific test covered each line.

**Test Environment Isolation:**
- Ports: 22560 (API), 23894 (UI) vs production 22557/23890
- Separate database: `modemcheck_test`
- Separate network: `172.26.0.0/16`
- Credentials: admin/TestPass123!, test_elevated/TestPass123!, test_basic/TestPass123!

**Note:** Rate limiting auto-disabled (`TESTING=true`) to prevent fixture failures during setup (50+ sessions created)

## Troubleshooting

### Signature Verification Failures
- **Cause**: Signature file mtime < binary mtime
- **Solution**: `sign-all.sh` automatically removes old `.minisig` files before re-signing

### Batch Signing Prompts
- **Without expect**: Password prompted 9 times (once per binary)
- **With expect**: Single password prompt, automatic signing
- **Install**: `apt-get install expect` (Linux) or `brew install expect` (macOS)

### .old File Accumulation
Each update creates `.old` backup of previous binary (persists until manual deletion or next update)

### Redis Failures
**Critical dependency**: No fallback if Redis unavailable (breaks auth and rate limiting)
- **DB 0**: Sessions, CSRF tokens, failed login counters
- **DB 1**: Rate limiting counters
- **Monitoring**: Check Redis health in production

### Version Management
Set via `Makefile` `VERSION` variable, injected with `-ldflags "-X main.Version=$(VERSION)"` (appears in `--version` and JSON output)

## Docker Configuration

### Resource Limits (Production)
```
modemcheck-api:  2 CPU / 4GB RAM (reserved: 1 CPU / 1GB)
postgres:        2 CPU / 2GB RAM (reserved: 0.5 CPU / 512MB)
redis:           0.5 CPU / 512MB RAM (reserved: 0.1 CPU / 128MB)
nginx:           0.5 CPU / 512MB RAM
```

**Impact:** Prevents OOM crashes and CPU saturation; guarantees minimum resources during host contention

### nginx Caching
**File descriptors:** 1000 files cached, 30s validation, 20s inactive eviction
**Browser cache:**
- Static assets (images/fonts): 30 days immutable
- JS/CSS: 7 days must-revalidate
- HTML: no-cache

### Database Schema (PostgreSQL)

**Auto-initialization:** SQLAlchemy creates tables on first startup; default admin user (admin/changeme) auto-created if users table empty

**Tables:**
- `modem_checks`: id (PK), modem_id, check_time, filename, full_data (JSONB) + 40+ extracted metric columns
- `users`: id (PK), username (unique), password_hash, role, created_at, last_login
- `api_keys`: id (PK), user_id (FK), key_hash, name, created_at, expires_at, is_active
- `audit_logs`: id (PK), user_id (FK nullable), action, resource, details (JSONB), ip_address, timestamp

**Indexes:** See "Performance" section for 8 production indexes

## Client Stability (v6.0.0)

### Critical Fixes
**HTTP response body leaks (18 locations):**
- Impact: Crash after 12-48 hours ("too many open files")
- Solution: `defer resp.Body.Close()` in coda.go (6), dm1000.go (9), xfinity.go (3)

**Goroutine leak in ping tests:**
- Impact: Deadlock if panic occurs (2-8KB leak per goroutine)
- Solution: Panic recovery in `diagnostics.go:165-185`, sends default result

**Race condition in log writes:**
- Impact: Concurrent writes corrupted log file
- Solution: `sync.Mutex` in ModemCheck struct protects `Log()` method

**CookieJar error handling:**
- Impact: Nil pointer crashes if creation failed
- Solution: Changed `jar, _` to proper error checking with `log.Fatalf()`

**Log cleanup memory usage:**
- Impact: 10-100MB memory spikes loading entire log file
- Solution: Streaming with `bufio.Scanner` (constant ~4KB usage)

**Result:** Stable weeks/months operation, no resource leaks, thread-safe logging

## Key Files Reference

### Security-Critical
**Keys:**
- `.signing-keys/minisign.key` - Private key (gitignored, password-protected) **BACKUP CRITICAL**
- `.signing-keys/minisign.pub` - Public key (committed, embedded in updater.go:31)
- `cloudserver/.env` - Production credentials (chmod 600, NEVER commit)

**Server modules:**
- `app/core/auth.py` - Password hashing, session management
- `app/core/security.py` - CSRF, rate limiting, input validation
- `app/core/passwords.py` - 10,000+ blocked weak passwords
- `app/core/session_security.py` - Device fingerprinting, anomaly detection
- `app/core/api_key_cache.py` - Redis caching (5min TTL)
- `app/routers/upload.py` - HMAC validation, timing-safe comparison

**Client modules:**
- `modemcheck-client/diagnostics.go` - Hostname validation before ping
- `modemcheck-client/cloud_client.go` - Response body handling
- `modemcheck-client/updater.go` - HTTP timeouts

### Operations
**Scripts:**
- `backup-all.sh`, `backup-database.sh`, `restore-database.sh`
- `update-db-password.sh` - Credential rotation
- `add_performance_indexes.py` - Performance migration
- `cleanup-audit-logs.py` - Audit retention

**Tests:**
- `cloudserver/test-password-validation.sh` - 36 tests
- `modemcheck-client/diagnostics_test.go` - 34 sub-tests

### Directory Structure
**Client:**
- Config: `config.json` (binary dir or via `-config` flag)
- Results: `ModemCheck-Results/[MODEL]-[MAC]/[TIMESTAMP].json`
- State: `last_successful_modem.json`, `speedtest_state.json`, `.update_lock`, `.upload_queue.json`
- Logs: `modem-check_logs.txt` (30-day auto-cleanup)

**Server:**
- App: `cloudserver/app/` (routers/, models/, core/)
- Static: `cloudserver/static/`
- Tests: `cloudserver/tests/`
- Config: `cloudserver/.env`
- Docker: `docker-compose.yml` (prod), `docker-compose.test.yml` (test)
- Docs: `cloudserver/README.md`, `OPERATIONS.md`

### Docker Services
**Production (ports 22557/23890):**
- `modemcheck-api`: FastAPI + Gunicorn (4 workers)
- `nginx`: Reverse proxy + static files
- `postgres`: PostgreSQL 16
- `redis`: Session storage (256MB LRU)
- Volumes: `postgres-data`, `redis-data`, `static-files`

**Test (ports 22560/23894):**
- Same services with `-test` suffix
- Separate network: `172.26.0.0/16`
- Ephemeral volumes, no resource limits

**Flow:** Client → nginx → FastAPI → PostgreSQL/Redis
