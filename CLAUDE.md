# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ModemCheck is a cross-platform cable modem diagnostic tool with optional cloud storage. The architecture consists of:
- **Go client** (`modemcheck-client/`): Single binary that scrapes modem data, runs network tests, and optionally uploads to cloud
- **FastAPI cloud server** (`cloudserver/`): Docker-based storage and web viewer using nginx + PostgreSQL + Redis

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
cd cloudserver && ./run_tests.sh              # Full test suite (192+ tests)
cd cloudserver && ./run_tests.sh --keep-env   # Keep test environment for debugging
cd cloudserver && ./run_tests.sh tests/api/   # API tests only
cd cloudserver && ./run_tests.sh -m rbac      # RBAC tests only
make test                                      # Go compilation test only
```

**Build security note:** The `validate-public-key` target runs automatically during `make build` and `make cross-compile` to detect:
- Build system compromise (different key embedded in source)
- Manual code modification
- Key rotation without updating source code

This prevents shipping binaries that would fail signature verification or accept signatures from unauthorized keys.

## Key Architecture Decisions

### FastAPI v2 Architecture

The cloud server uses **FastAPI** with async PostgreSQL and Redis.

**Benefits:**
- Modern async/await support for high concurrency
- Automatic OpenAPI documentation at `/docs`
- Type safety with Pydantic schemas
- Built-in dependency injection
- WebSocket support (future use)
- Industry-standard framework

**Stack:**
- **FastAPI**: Async web framework
- **PostgreSQL 16**: Relational database with JSONB support
- **SQLAlchemy 2.0**: Async ORM with type hints
- **Redis 7**: Session storage and caching
- **Gunicorn + Uvicorn**: Production ASGI server
- **Pydantic**: Request/response validation

**Upload flow:** Client POST → FastAPI endpoint → Pydantic validation → async PostgreSQL insert → JSON response

Data stored in PostgreSQL JSONB column for efficient querying while maintaining full JSON structure.

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
- **Sliding window**: TTL refreshes on each session verification (default behavior)
- **Keys**: `session:<token>` → JSON with username/role/expiry
- **User tracking**: `user_sessions:<username>` → Set of active session IDs
- **Cookie security**:
  - HttpOnly flag (prevents JavaScript access)
  - SameSite=Strict (prevents CSRF)
  - Secure flag (HTTPS only, based on X-Forwarded-Proto header)
  - Path=/ (application-wide)
- **Benefit**: Active users stay logged in indefinitely; inactive sessions expire after 1 hour
- **Implementation**: FastAPI middleware with async Redis client

### Password Hashing Migration
- **Modern (preferred):** Argon2id with 64MB memory, 3 iterations, parallelism=4
- **Legacy (supported):** PBKDF2-HMAC-SHA256 with 100,000 iterations
- **Automatic upgrade:** On successful PBKDF2 login, password is rehashed with Argon2id and database updated

### RBAC Roles
- **basic**: View data, change own password
- **elevated**: basic + create API keys, bulk upload, view client logs
- **admin**: elevated + user management, delete checks, view user activity logs

### CSRF Protection
- **Token generation**: 32-byte URL-safe token stored in Redis
- **Token TTL**: 1 hour (matches session lifetime)
- **Token delivery**: Included in session check response as `csrf_token` field
- **Token validation**: Required for all state-changing operations (create, update, delete actions)
- **Token sources**: Accepts token from POST body, query parameter, or `X-CSRF-Token` header
- **One-time use**: Tokens can be deleted after use for critical operations
- **Protected endpoints**: API key management, data deletion, bulk upload, user management

### Account Lockout
- **Threshold**: 5 failed login attempts
- **Lockout duration**: 30 minutes (1800 seconds)
- **Storage**: Redis key `failed_logins:<username>` with automatic expiration
- **Counter reset**: Cleared immediately on successful login
- **Lockout bypass**: None - even valid credentials rejected during lockout period
- **User feedback**: Displays remaining lockout time in minutes (rounded up)
- **Implementation**: FastAPI dependency injection in authentication router

### Rate Limiting
- **Library**: SlowAPI 0.1.9 with Redis backend
- **Storage**: Redis DB 1 (separate from sessions in DB 0)
- **Key function**: Remote IP address (`get_remote_address`)
- **Limits**:
  - Authentication endpoints: 30 requests/minute (`/api/auth/login`, `/api/auth/logout`, etc.)
  - Upload endpoint: 60 requests/minute (`/api/upload`)
  - API endpoints: 300 requests/second (database queries, admin functions, user management)
- **Response**: HTTP 429 (Too Many Requests) when limit exceeded
- **Implementation**: Decorator-based (`@limiter.limit("30/minute")`) on each endpoint
- **Test environment**: Rate limiting disabled when `TESTING=true` to prevent test fixture failures
- **Location**: `app/core/limiter.py` (configuration), applied in all router files

**Critical for testing:** Rate limiting is automatically disabled in test environment to prevent login fixture failures. Test fixtures create 50+ sessions during setup, which would exhaust the 30/minute auth limit.

### Enhanced Rate Limiting (Per-User)
- **Dual-layer protection**: IP-based (SlowAPI) + Per-user (custom implementation)
- **Per-user limits**: 100 requests/hour across all IPs (prevents multi-IP abuse)
- **Endpoint-specific limits**: Configurable per endpoint (e.g., upload, query)
- **Implementation**: `app/core/enhanced_limiter.py`
- **Functions**:
  - `check_user_rate_limit()` - Global per-user limit
  - `check_endpoint_user_limit()` - Per-endpoint per-user limit
  - `get_user_request_stats()` - User request statistics
  - `reset_user_rate_limits()` - Admin reset functionality
- **Storage**: Redis keys `user_rate_limit:<username>` and `endpoint_rate_limit:<username>:<endpoint>`
- **Integrated**: Added to `/api/auth/login` (100 requests/hour per user)

### Session Security Enhancements
- **Device fingerprinting**: SHA256 hash of user-agent + IP address
- **Fingerprint storage**: Redis key `session_fingerprint:<session_id>` with session metadata
- **Verification modes**:
  - Strict mode: Rejects any IP or user-agent change
  - Lenient mode: Allows IP changes (mobile networks), rejects user-agent changes
- **Concurrent session limits**: Maximum 5 active sessions per user
- **Auto-termination**: Oldest sessions terminated when limit exceeded
- **Anomaly detection**: Logs IP changes, user-agent mismatches, fingerprint mismatches
- **Anomaly storage**: Redis LIST `session_anomaly:<username>:<YYYYMMDD>` (30-day retention)
- **Implementation**: `app/core/session_security.py`
- **Functions**:
  - `generate_device_fingerprint()` - Create fingerprint from request
  - `create_session_with_fingerprint()` - Store fingerprint on login
  - `verify_session_fingerprint()` - Verify request matches stored fingerprint
  - `enforce_concurrent_session_limit()` - Check session count
  - `terminate_oldest_sessions()` - Remove oldest sessions
  - `log_session_anomaly()` - Log security events
  - `get_session_anomalies()` - Retrieve anomaly history
- **Integrated**: Added to `/api/auth/login` and session verification

### Audit Log Retention
- **Default retention**: 90 days for both user activity and client submission logs
- **Separate policies**: Different retention periods per log type
- **Automated cleanup**: Script `cleanup-audit-logs.py` with dry-run support
- **Statistics**: `get_audit_log_statistics()` provides counts, age, timestamps
- **Implementation**: `app/core/audit_retention.py`
- **Functions**:
  - `cleanup_old_user_activity_logs()` - Remove old user logs
  - `cleanup_old_client_submission_logs()` - Remove old client logs
  - `cleanup_all_audit_logs()` - Combined cleanup with statistics
  - `get_audit_log_statistics()` - Audit log metrics
- **Scheduling**: Add to cron for weekly cleanup (see `cloudserver/cron-example.txt`)

### Automated Backup & Disaster Recovery
- **PostgreSQL backups**: Daily compressed backups with verification
- **Redis backups**: Daily RDB snapshots
- **Backup retention**: 30 days (configurable)
- **Backup verification**: gzip integrity + table count validation
- **Restore safety**: Pre-restore backup, confirmation prompt, automatic rollback
- **Scripts**:
  - `backup-all.sh` - Complete backup (PostgreSQL + Redis)
  - `backup-database.sh` - PostgreSQL only with verification
  - `backup-redis.sh` - Redis snapshot only
  - `restore-database.sh` - Safe restore with pre-restore backup
- **RTO**: < 10 minutes for database restore from latest backup
- **Documentation**: Complete procedures in `cloudserver/OPERATIONS.md`
- **Scheduling**: Add to cron for daily 2 AM backups (see `cloudserver/cron-example.txt`)

### Metric Extraction from Uploads
- **Purpose**: Extract individual metrics from modem check JSON for efficient database querying
- **Implementation**: `app/core/metric_extraction.py`
- **Extracted metrics** (40+ total):
  - **System info**: firmware, uptime, system_time, client version/OS/arch
  - **Signal quality**: avg downstream power/SNR, avg upstream power, total errors
  - **Speed tests**: iperf3 upload/download, speedtest.net results (latency, jitter, packet loss)
  - **Ping tests**: Google and Cloudflare (avg latency, loss, jitter, max latency)
  - **Network info**: public IP, ASN, ISP name, city, country, detection status
- **Storage**: Dedicated PostgreSQL columns in `modem_checks` table (already defined)
- **Benefits**: 10-100x faster queries on specific metrics, no JSONB parsing required
- **Integrated**: Added to `/api/upload` endpoint (extracts on every upload)
- **Backwards compatible**: Full JSON still stored in `full_data` column

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

### Comprehensive Test Suite

ModemCheck v2 includes a comprehensive test suite with 192+ tests (185+ passing, 5 skipped):

```bash
cd cloudserver
./run_tests.sh                  # Run all tests (192+ tests)
./run_tests.sh tests/api/       # API tests only
./run_tests.sh tests/security/  # Security tests only
./run_tests.sh -m rbac          # RBAC tests only
./run_tests.sh --keep-env       # Keep test environment for debugging
```

### Test Categories
- **API Tests** (77+ tests): All endpoints, validation, edge cases, metric extraction, audit retention
- **Security Tests** (50+ tests): SQL injection, XSS, CSRF, authentication bypass, rate limiting, session security, enhanced rate limiting
- **RBAC Tests** (20 tests): Role permissions for all endpoints
- **UI Tests** (10 tests): Playwright browser automation

### Test Results (Latest Run)
- **Passing**: 185+ tests (96%)
- **Skipped**: 5 tests (4%)
  - `test_login_rate_limiting` - Rate limiting disabled in test environment
  - `test_external_api_unavailable` - Requires network isolation
  - `test_database_connection_failure` - Requires database shutdown
  - `test_redis_connection_failure` - Requires Redis shutdown
  - `test_file_system_full` - Requires disk space manipulation
- **Coverage**: 88%+ (target: 80%+)

### Isolated Test Environment

**Separation from production:**
- Different ports: 22560 (API), 23894 (UI)
- Separate Docker Compose file: `docker-compose.test.yml`
- Separate database: `modemcheck_test` (PostgreSQL)
- Separate Redis instance: `redis-test`
- Separate network: `172.26.0.0/16` vs `172.25.0.0/16` (prod)
- Environment: `TESTING=true`

**Test workflow:**
1. `run_tests.sh` creates test environment
2. Starts Docker containers (PostgreSQL, Redis, FastAPI)
3. Initializes test database with fixtures
4. Runs pytest suite with coverage reporting
5. Runs Playwright UI tests
6. Cleanup (unless `--keep-env` flag)

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

### PostgreSQL Database
- **JSONB**: Efficient JSON storage with indexing capabilities
- **Async operations**: Non-blocking database queries via SQLAlchemy async
- **Connection pooling**: AsyncEngine with pool size limits prevents connection exhaustion
- **Transactions**: ACID compliance with automatic rollback on errors
- **Migrations**: Alembic for schema versioning (planned for future releases)

### Redis Connection Failures
If Redis unavailable, all authentication and rate limiting fails (no fallback). Test script checks Redis health before running tests. In production, monitor Redis connectivity.

**Redis database separation:**
- DB 0: Session storage (user sessions, CSRF tokens, failed login counters)
- DB 1: Rate limiting (request counters per IP)
- Isolation prevents rate limiting data from interfering with session management

### Version Injection at Build Time
Version set via Makefile `VERSION` variable, injected as `-ldflags "-X main.Version=$(VERSION)"`. Appears in `--version` flag and JSON output. Change in Makefile before building releases.

## Performance & Scalability (v2 Architecture)

The v2 FastAPI architecture provides significant performance improvements over the v1 CGI implementation:

### Async Architecture Benefits
- **Async I/O**: Non-blocking database and Redis operations
- **Request concurrency**: Handles 1000+ concurrent connections per worker
- **No process spawning overhead**: Persistent Python processes (vs 20-40ms CGI overhead)
- **Connection pooling**: Reused database connections (vs new connection per request)

### Resource Limits (docker-compose.yml)
**modemcheck-api container:**
- Limits: 2.0 CPUs, 4GB RAM
- Reservations: 1.0 CPUs, 1GB RAM
- Workers: 4 Gunicorn workers with Uvicorn

**postgres container:**
- Limits: 2.0 CPUs, 2GB RAM
- Reservations: 0.5 CPUs, 512MB RAM

**redis container:**
- Limits: 0.5 CPUs, 512MB RAM
- Reservations: 0.1 CPUs, 128MB RAM

**Impact:** Prevents OOM crashes and CPU saturation under load. Guarantees minimum resources during host contention.

### Static Asset Caching (nginx.conf)
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
- **v1 capacity:** 100-200 clients (CGI implementation)
- **v2 capacity:** 1000+ clients (FastAPI async implementation)
- **Database capacity:** PostgreSQL handles 10,000+ writes/sec (far exceeds current load)
- **Bottleneck:** Network bandwidth and nginx connection limits (not application layer)

### Performance Improvements
- **Upload latency**: 50-100ms (vs 150-250ms in v1)
- **Query response**: 10-30ms (vs 80-150ms in v1)
- **Memory efficiency**: Constant per-worker memory (vs linear growth in CGI)
- **Concurrent requests**: Limited by CPU cores, not process pool size

## Database Initialization

### Production Environment
On first startup, FastAPI application initializes database:
1. SQLAlchemy models create PostgreSQL tables automatically
2. `app/core/database.py` - Database connection and session management
3. `app/models/` - SQLAlchemy ORM models (User, ModemCheck, APIKey, AuditLog)
4. **Automatically creates default admin user** on first run (username: admin, password: changeme)
   - Admin creation only happens if users table is empty
   - Password hashed with Argon2id on creation

### Schema Structure
**modem_checks table:**
- Primary key: `id` (auto-increment)
- JSONB column: `full_data` (indexed for efficient querying)
- Indexes: modem_id, check_time, signal metrics

**users table:**
- Primary key: `id` (auto-increment)
- Columns: username, password_hash, role, created_at, last_login
- Unique constraint on username

**api_keys table:**
- Primary key: `id` (auto-increment)
- Foreign key: `user_id` references users
- Columns: key_hash, name, created_at, expires_at, is_active

**audit_logs table:**
- Primary key: `id` (auto-increment)
- Foreign key: `user_id` references users (nullable)
- Columns: action, resource, details (JSONB), ip_address, timestamp

### Test Environment
The test environment uses separate database:
- Database: `modemcheck_test` (isolated from production)
- `docker-compose.test.yml` includes `postgres-test` and `redis-test` services
- Test fixtures populate test data (users, API keys, sample modem checks)
- Automatic cleanup after tests complete

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
- `app/core/auth.py` - Password hashing and session management
- `app/core/security.py` - CSRF protection, rate limiting, input validation
- `app/core/passwords.py` - 10,000+ blocked weak passwords
- `app/core/enhanced_limiter.py` - Per-user rate limiting across multiple IPs
- `app/core/session_security.py` - Device fingerprinting and session anomaly detection
- `app/core/audit_retention.py` - Automated audit log cleanup
- `app/core/metric_extraction.py` - Extract metrics from modem check JSON
- `app/routers/upload.py` - API key validation with timing-safe comparison
- `backup-database.sh`, `restore-database.sh`, `backup-all.sh` - Backup and recovery scripts

**Key backup critical:** No recovery possible if private key lost. Backup `.signing-keys/` securely.

## File Locations

### Client Files
- Config: `config.json` (same dir as binary) or via `-config` flag
- Results: `ModemCheck-Results/[MODEL]-[MAC]/[TIMESTAMP].json`
- Upload queue: `ModemCheck-Results/.upload_queue.json`
- State files: `last_successful_modem.json`, `speedtest_state.json`, `.update_lock`
- Logs: `modem-check_logs.txt` (auto-cleanup 30 days)

### Server Files (v2)
- Application: `cloudserver/app/` (FastAPI application code)
- Routers: `cloudserver/app/routers/` (API endpoints)
- Models: `cloudserver/app/models/` (SQLAlchemy ORM)
- Core: `cloudserver/app/core/` (auth, database, security, enhanced_limiter, session_security, audit_retention, metric_extraction)
- Static files: `cloudserver/static/` (UI assets)
- Tests: `cloudserver/tests/` (pytest + Playwright)
- Config: `cloudserver/.env` (environment variables)
- Docker: `cloudserver/docker-compose.yml` (production) and `docker-compose.test.yml` (testing)
- Backup scripts: `cloudserver/backup-*.sh`, `cloudserver/restore-*.sh`
- Documentation: `cloudserver/README.md`, `OPERATIONS.md`, `TESTING-SUMMARY.md`

## Docker Compose Services

**Production (`docker-compose.yml`):**
- `modemcheck-api`: FastAPI + Gunicorn + Uvicorn (4 workers)
- `nginx`: Reverse proxy and static file serving
- `postgres`: PostgreSQL 16 database
- `redis`: Session storage and caching (256MB max memory, LRU eviction)
- Ports: 22557 (API), 23890 (UI)
- Volumes: `postgres-data`, `redis-data`, `static-files`
- Resource limits:
  - API: 2 CPU / 4GB RAM
  - Postgres: 2 CPU / 2GB RAM
  - Redis: 0.5 CPU / 512MB RAM
  - nginx: 0.5 CPU / 512MB RAM

**Test (`docker-compose.test.yml`):**
- `modemcheck-api-test`: Same as production with test configuration
- `postgres-test`: Separate PostgreSQL instance (modemcheck_test database)
- `redis-test`: Separate Redis instance for test isolation
- `nginx-test`: Test-specific nginx configuration
- Ports: 22560 (API), 23894 (UI)
- Volumes: `postgres-test-data`, `redis-test-data` (ephemeral)
- Network: `172.26.0.0/16` (isolated from production)
- No resource limits (test environment)

### Service Communication
- Client → nginx (port 22557/22560) → FastAPI (internal)
- FastAPI → PostgreSQL (internal port 5432)
- FastAPI → Redis (internal port 6379)
- Browser → nginx (port 23890/23894) → Static files + FastAPI
