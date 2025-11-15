# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ModemCheck is a cross-platform cable modem diagnostic tool with optional cloud storage. The architecture consists of:
- **Go client** (`modemcheck-client/`): Single binary that scrapes modem data, runs network tests, and optionally uploads to cloud
- **Python CGI cloud server** (`cloudserver/`): Docker-based storage and web viewer using nginx + fcgiwrap + SQLite + Redis

## Build Commands

```bash
# Primary workflows
make                    # Cross-compile all platforms + auto-sign binaries
make build              # Build for current platform only (validates public key first)
make cross-compile      # Explicit cross-platform build with signing (validates public key first)

# Platform-specific builds (no signing, no validation)
make linux linux-arm linux-arm64 linux-mipsle linux-mips windows macos

# Security/signing workflow
make setup-keys         # Generate Minisign keypair (one-time, creates .signing-keys/)
make update-public-key  # Embed public key in updater.go source
make validate-public-key # Validate embedded key matches .signing-keys/minisign.pub (prevents build compromise)
make sign-binary BINARY=dist/modem-check-linux-x64  # Sign specific binary
./sign-all.sh           # Batch-sign all binaries in dist/ (requires 'expect' for single password prompt)

# Testing
./test_cloud_server.sh              # Full integration test suite (80+ tests)
./test_cloud_server.sh --keep-env   # Keep test container for debugging
make test                            # Go compilation test only
```

**Build security note:** The `validate-public-key` target runs automatically during `make build` and `make cross-compile` to detect:
- Build system compromise (different key embedded in source)
- Manual code modification
- Key rotation without updating source code

This prevents shipping binaries that would fail signature verification or accept signatures from unauthorized keys.

## Key Architecture Decisions

### Why CGI Instead of Modern Frameworks?

The cloud server uses **Python CGI scripts behind nginx**, not Flask/Django/FastAPI.

**Rationale:**
- Simplicity: ~200 lines per script, easy to audit
- Stateless execution: Each request is an isolated process (security boundary)
- Zero daemon management: nginx handles process spawning via fcgiwrap
- Small codebase: No framework complexity

**Trade-offs:**
- Slower request handling due to process spawn overhead
- Mitigated by: nginx caching, fcgiwrap connection pooling, SQLite WAL mode

### Direct Database Insertion

Upload flow: Client POST → nginx → CGI script → **parse JSON in memory** → insert to SQLite → return database_id

No intermediate file I/O. JSON stored in `full_data` TEXT column.

### Auto-Update Security Model

**Threat protection:**
- GitHub account compromise
- Man-in-the-middle attacks
- CDN hijacking
- Tampered binaries

**Defense mechanism:**
1. Public key hardcoded in `updater.go` (line 31: `MinisignPublicKey`)
2. Binary + `.minisig` signature downloaded to temp files
3. **Signature verified before any execution** (Ed25519)
4. Binary tested with `--version` flag before installation
5. Atomic rename to prevent TOCTOU races
6. Automatic rollback on failure using `.old` backup

**Critical:** Signature file timestamps must be ≥ binary modification time. The `sign-all.sh` script removes old `.minisig` files before re-signing to prevent this issue.

## Authentication & Session Management

### Session Storage (Redis)
- **Why Redis**: Atomic operations (`SETEX`), auto-expiration, horizontal scaling
- **Session ID**: 32-byte URL-safe token (`secrets.token_urlsafe(32)`)
- **TTL**: 1 hour (3600 seconds) with sliding window refresh
- **Sliding window**: TTL refreshes on each `verify_session()` call (default behavior)
- **Keys**: `session:<token>` → JSON with username/role/expiry
- **User tracking**: `user_sessions:<username>` → Set of active session IDs
- **Cookie security**:
  - HttpOnly flag (prevents JavaScript access)
  - SameSite=Strict (prevents CSRF)
  - Secure flag (HTTPS only, based on X-Forwarded-Proto header)
  - Path=/ (application-wide)
- **Benefit**: Active users stay logged in indefinitely; inactive sessions expire after 1 hour

### Password Hashing Migration
- **Modern (preferred):** Argon2id with 64MB memory, 3 iterations, parallelism=4
- **Legacy (supported):** PBKDF2-HMAC-SHA256 with 100,000 iterations
- **Automatic upgrade:** On successful PBKDF2 login, password is rehashed with Argon2id and database updated

### RBAC Roles
- **basic**: View data, change own password
- **elevated**: basic + create API keys, bulk upload, view client logs
- **admin**: elevated + user management, delete checks, view user activity logs

### CSRF Protection
- **Token generation**: `generate_csrf_token(session_id)` creates 32-byte URL-safe token stored in Redis
- **Token TTL**: 1 hour (matches session lifetime)
- **Token delivery**: Included in `/api/auth?action=session_check` response as `csrf_token` field
- **Token validation**: Required for all state-changing operations (create, update, delete actions)
- **Token sources**: Accepts token from POST body, query parameter, or `X-CSRF-Token` header
- **One-time use**: Tokens can be deleted after use via `delete_csrf_token()` for critical operations
- **Protected endpoints**: admin-api.py (API key management, config), data-management-api.py (delete, bulk upload)

### Account Lockout
- **Threshold**: 5 failed login attempts
- **Lockout duration**: 30 minutes (1800 seconds)
- **Storage**: Redis key `failed_logins:<username>` with automatic expiration
- **Counter reset**: Cleared immediately on successful login
- **Lockout bypass**: None - even valid credentials rejected during lockout period
- **User feedback**: Displays remaining lockout time in minutes (rounded up)
- **Implementation**: `check_account_locked()`, `record_failed_login()`, `clear_failed_logins()` in auth.py:338-383

## Modem Scraper Architecture

Interface-based design with three implementations:

```go
type ModemScraper interface {
    Login() error
    GetMAC() (string, error)
    GetData(checkTime int64) (*ModemData, error)
    ClearFEC() error
    GetModemType() string
}
```

**Detection flow:**
1. `AutoDetectModem()` tries IPs: 192.168.100.1, 192.168.0.1, 10.0.0.1, 172.20.0.1
2. For each IP, fetch HTML and match patterns in `scraper.DetectModem()`
3. First match instantiates appropriate scraper (coda.go, dm1000.go, or xfinity.go)
4. State saved to `last_successful_modem.json` for handling detection failures

**State persistence:** On detection failure, uses last known modem type/MAC from JSON file. Adds `"detection_status": "detection_failed"` to output.

## Update Channel System

Three channels controlled by `config.json` field `UpdateChannel`:

- **stable** (default): Production releases only
  - GitHub API: `/repos/adamkl-me/modemcheck/releases/latest`
  - Filters: `prerelease: false, draft: false`

- **beta**: Pre-release builds
  - GitHub API: `/repos/adamkl-me/modemcheck/releases`
  - Filters: `prerelease: true, draft: false`
  - Uses most recent pre-release

- **test**: Same as beta (for early testing)

**Version comparison caveat:** Currently uses lexicographic comparison. Works for standard semver like `5.01.0` vs `5.02.0`, but fails for `5.10.0` vs `5.9.0`. Future improvement: Use proper semver library.

## Network Diagnostics: Three-Tier IP Detection

**Graceful degradation for public IP/ISN/ASN detection:**

1. **Primary (ipapi.co):** Full details (IP, ASN, org, city, country)
2. **Secondary (ip-api.com):** Full details (fallback for rate limits)
3. **Tertiary (ipify.org):** IP only (ultra-reliable, no metadata)

Located in `diagnostics.go:365-530`. Ensures data collection continues even if primary service is down.

## Speed Test Interval Logic

Configurable via `SpeedTestInterval` in config.json:

- Value of `1`: Run every check
- Value of `N`: Run every Nth check
- **Retry on failure:** If last test failed, retry on next run (ignores interval)

State tracked in `ModemCheck-Results/[MODEM]/speedtest_state.json`:
```json
{
  "run_count": 10,
  "last_speed_test": 8,
  "last_test_success": true
}
```

Output values: Normal result, `-1` (disabled), `-2` (skipped per interval)

## Upload Queue & Retry Mechanism

File: `ModemCheck-Results/.upload_queue.json`

**Structure:**
```json
[{
  "file_path": "path/to/check.json",
  "modem_id": "XB8-AABBCCDDEEFF",
  "attempts": 2,
  "last_error": "connection timeout",
  "first_failure": 1699900000
}]
```

**Retry flow:**
1. Failed upload → add to queue (max 100 entries, FIFO eviction)
2. Next run → `retryFailedUploads()` processes queue before new check
3. Success → remove from queue
4. Failure → increment attempts, update error
5. Age >14 days or file missing → remove from queue

## Testing Infrastructure

### Isolated Test Environment

**Separation from production:**
- Different ports: 22558 (upload), 23892 (viewer), 23893 (admin)
- Separate Docker Compose file: `docker-compose.test.yml`
- Separate volumes: `./test-data/` (ephemeral)
- Separate network: `172.26.0.0/16` vs `172.25.0.0/16` (prod)
- Environment: `TEST_MODE=true`

**Test workflow:**
1. `test_cloud_server.sh` creates test directories
2. Starts Docker container with test nginx config
3. Initializes databases with test data (`init_test_data.py`)
4. Runs 80+ tests across categories:
   - Authentication (7 tests)
   - RBAC (6 tests)
   - Upload API (7 tests)
   - Security (17 tests: SQL injection, XSS, path traversal, DoS prevention)
   - Database API (4 tests)
   - Admin API (6 tests)
   - User Management (5 tests)
   - Data Management (9 tests)
   - E2E (3 tests)
   - Performance (1 test)
5. Cleanup (unless `--keep-env` flag)

**Test credentials:**
- Admin: `admin / TestPass123!`
- Elevated: `test_elevated / TestPass123!`
- Basic: `test_basic / TestPass123!`
- API Key: `test_key_active`

## Common Gotchas

### Signature File Timestamps
Minisign includes timestamp in signatures. Signature file mtime must be ≥ binary mtime, otherwise verification fails. The `sign-all.sh` script automatically removes old `.minisig` files before signing to prevent this.

### Password Prompts During Batch Signing
Without `expect` installed: `sign-all.sh` prompts for password 9 times (once per binary).
With `expect` installed: Single password prompt, automatic signing.

Install: `apt-get install expect` (Linux) or `brew install expect` (macOS)

### .old File Accumulation
Each update creates a `.old` backup of the previous binary. These persist until manually deleted or next update. Located in same directory as binary.

### SQLite WAL Mode
Database uses Write-Ahead Logging (enabled in `db_schema.py:19-23`):
- Creates `modemcheck.db-wal` and `modemcheck.db-shm` files
- Don't delete these manually (corruption risk)
- Allows concurrent readers + writer (solves "database is locked" errors)

### Redis Connection Failures
If Redis unavailable, all authentication fails (no fallback). Test script checks Redis health before running tests. In production, monitor Redis connectivity.

### Version Injection at Build Time
Version set via Makefile `VERSION` variable, injected as `-ldflags "-X main.Version=$(VERSION)"`. Appears in `--version` flag and JSON output. Change in Makefile before building releases.

## Performance Optimizations (Phase 1 - Implemented)

The cloud server has been optimized to handle 100-200 concurrent clients (up from ~50) with the following changes:

### 1. fcgiwrap Process Pool (start.sh:14)
Changed from single worker to 10 concurrent workers:
```bash
spawn-fcgi -s /run/fcgiwrap/fcgiwrap.sock -U nginx -u nginx -F 10 -- /usr/bin/fcgiwrap &
```
**Impact:** Eliminates request queuing for <100 concurrent clients. Each worker can handle one CGI request simultaneously.

### 2. Docker Resource Limits (docker-compose.yml)
**modemcheck-cloud container:**
- Limits: 2.0 CPUs, 2GB RAM
- Reservations: 0.5 CPUs, 512MB RAM

**redis container:**
- Limits: 0.5 CPUs, 512MB RAM
- Reservations: 0.1 CPUs, 128MB RAM

**Impact:** Prevents OOM crashes and CPU saturation under load. Guarantees minimum resources during host contention.

### 3. Static Asset Caching (nginx.conf:14-18)
File descriptor caching with `open_file_cache`:
- Max 1000 files cached in memory
- 30-second validation interval
- Files inactive for 20s evicted

Browser-side caching:
- Static assets (images/fonts): 30 days immutable
- JS/CSS: 7 days with must-revalidate
- HTML: no-cache

**Impact:** Reduces disk I/O for repeated file access. Browser caching reduces bandwidth and server load.

### Scalability Thresholds
- **Current capacity:** 10-50 clients (pre-optimization)
- **Phase 1 capacity:** 100-200 clients (current)
- **Bottleneck:** CGI process spawning (20-40ms Python interpreter overhead per request)
- **SQLite capacity:** 1,000-5,000 writes/sec (NOT the bottleneck - current load at 1,000 clients: 0.278 writes/sec)

**Note:** Response caching was tested but removed due to stale data issues - users expect to see uploads immediately, and cache invalidation would require architectural changes better suited for future phases if needed.

### Known Limitations (Not Critical at Current Scale)

**Memory usage in upload.py (Line 118):**
- Reads entire file (up to 10MB) into RAM per upload
- With 10 fcgiwrap workers: max 500MB memory usage (10 × 50MB per process)
- Protected by: Docker 2GB limit, nginx size enforcement, fcgiwrap pool cap
- Safe for 100-200 clients; consider streaming for 1,000+ clients in future phases

## Database Initialization

### Production Environment
On first startup, `start.sh` runs:
1. `db_schema.py` - Creates `modemcheck.db` (modem_checks table)
2. `audit_schema.py` - Creates `audit.db` (users, api_keys, logs tables)
   - **Automatically creates default admin user** (username: admin, password: changeme)
   - Admin creation only happens if users table is empty
   - Password hashed with Argon2id on creation

### Test Environment
The test environment requires Redis for session management:
- `docker-compose.test.yml` includes `redis-test` service
- Test script runs `init_test_data.py` to populate test data (API keys, etc.)
- Both production and test databases are initialized identically

**Important:** All CGI responses must include `Content-Type: application/json` header before the blank line and JSON body, otherwise browsers reject the response.

## Client Stability Fixes (v6.0.0)

The Go client has been hardened against memory leaks, crashes, and resource exhaustion through comprehensive fixes:

### HTTP Response Body Leaks (CRITICAL - Fixed)
**Impact:** System would crash with "too many open files" after 12-48 hours of operation.

**Fixed locations (18 total):**
- `coda.go`: 6 leaks in GetData() and ClearFEC() methods
- `dm1000.go`: 9 leaks in Login(), GetData(), and ClearFEC() methods
- `xfinity.go`: 3 leaks in Login() and GetData() methods

**Solution:** All HTTP response bodies now use `defer resp.Body.Close()` immediately after error checking. Added proper error handling for all HTTP requests with descriptive error wrapping using `fmt.Errorf("%w")`.

### Goroutine Leak in Ping Tests (HIGH - Fixed)
**Location:** `diagnostics.go:165-185`

**Impact:** If ping test goroutine panicked, main thread would deadlock waiting for results, leaking 2-8KB per goroutine.

**Solution:** Added panic recovery to both ping test goroutines. Each goroutine now sends a default result (empty strings) if a panic occurs, preventing deadlock and ensuring the main thread never blocks forever.

### Race Condition in Log Writes (HIGH - Fixed)
**Location:** `main.go:37, 155-157`

**Impact:** Concurrent goroutines (ping tests, retries) could corrupt log file with interleaved writes.

**Solution:** Added `sync.Mutex` to ModemCheck struct to protect all log file writes. The `Log()` method now acquires the mutex before writing and releases it after, ensuring thread-safe operation.

### CookieJar Error Handling (HIGH - Fixed)
**Location:** `main.go:43-46`

**Impact:** Silent error ignoring could lead to nil pointer crashes if cookiejar creation failed.

**Solution:** Changed from `jar, _ := cookiejar.New(nil)` to proper error checking with `log.Fatalf()`. While cookiejar.New() rarely fails, proper error handling prevents unexpected crashes.

### Memory Usage in Log Cleanup (MEDIUM - Fixed)
**Location:** `cloud_client.go:341-426`

**Impact:** Loading entire log file (10-100 MB for 30 days) into memory during cleanup could cause memory spikes.

**Solution:** Replaced in-memory file loading with streaming approach using `bufio.Scanner`. Now processes log file line-by-line using only ~4KB memory (scanner buffer). Creates temporary file, writes kept lines, then atomically renames on success.

### Stability Guarantees
**Before fixes:**
- Crash after 12-48 hours (file descriptor exhaustion)
- Potential crashes from nil pointer dereferences during network issues
- Risk of deadlock if ping tests panicked
- Log file corruption from concurrent writes
- Memory spikes during log cleanup (10-100 MB)

**After fixes:**
- Stable operation for weeks/months without resource leaks
- Graceful error handling for all network failures
- No deadlock risk in concurrent operations
- Thread-safe logging with mutex protection
- Constant ~4KB memory usage for log cleanup
- Production-ready for long-term unattended operation

## Security-Critical Files

- `.signing-keys/minisign.key` - Private key (gitignored, password-protected)
- `.signing-keys/minisign.pub` - Public key (committed, embedded in updater.go)
- `updater.go:31` - Hardcoded public key (must match minisign.pub)
- `auth.py` - Password hashing and session management
- `common_passwords.py` - 10,000+ blocked weak passwords
- `upload.py` - API key validation with timing-safe comparison

**Key backup critical:** No recovery possible if private key lost. Backup `.signing-keys/` securely.

## File Locations

- Config: `config.json` (same dir as binary) or via `-config` flag
- Results: `ModemCheck-Results/[MODEL]-[MAC]/[TIMESTAMP].json`
- Upload queue: `ModemCheck-Results/.upload_queue.json`
- State files: `last_successful_modem.json`, `speedtest_state.json`, `.update_lock`
- Logs: `modem-check_logs.txt` (auto-cleanup 30 days)
- Test data: `test-data/` (ephemeral, Docker bind mount)

## Docker Compose Services

**Production (`docker-compose.yml`):**
- `modemcheck-cloud`: nginx + fcgiwrap (10 workers) + Python CGI
- `redis`: Session storage (256MB max memory, LRU eviction)
- Ports: 22557 (upload), 23890 (viewer), 23891 (admin)
- Volumes: `modemcheck-cloud_db`, `modemcheck-cloud_config`, `modemcheck-cloud_redis`
- Resource limits: 2 CPU / 2GB RAM (cloud), 0.5 CPU / 512MB RAM (redis)

**Test (`docker-compose.test.yml`):**
- `modemcheck-cloud-test`: Same as production with relaxed rate limits
- `redis-test`: Separate Redis instance for test isolation
- Ports: 22558 (upload), 23892 (viewer), 23893 (admin)
- Volumes: `./test-data/` bind mounts (ephemeral), `redis-test-data`
- Network: `172.26.0.0/16` (isolated from production)
- No resource limits (test environment)
