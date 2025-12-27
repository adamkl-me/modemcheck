# ModemCheck Cloud Server

FastAPI-based cloud storage and visualization platform for cable modem diagnostic data.

## Overview

The ModemCheck cloud server provides a modern, high-performance API for storing and visualizing cable modem diagnostics. Built with FastAPI and PostgreSQL, it offers comprehensive web dashboards, role-based access control, and a complete test suite.

### Key Features

- **High Performance**: FastAPI with async I/O, supports 1000+ concurrent clients
- **PostgreSQL**: JSONB storage with efficient querying and indexing
- **Modern Stack**: Python 3.11, SQLAlchemy 2.0, Pydantic validation, Redis sessions
- **Production-Ready**: Gunicorn + Uvicorn workers, connection pooling, comprehensive logging
- **Comprehensive Security**: Rate limiting, CSRF protection, account lockout, Argon2id password hashing
- **Complete Test Suite**: API, security, RBAC, and UI tests

## Architecture

```
nginx (reverse proxy)
  ↓
Gunicorn (process manager, 4 workers)
  ↓
Uvicorn Workers (async request handling)
  ↓
FastAPI Application
  ├── Auth (login, sessions, passwords)
  ├── Upload (client data with HMAC validation)
  ├── Database API (query checks)
  ├── Admin (API keys, logs)
  ├── Users (user management)
  └── Data Management (bulk ops, delete)
  ↓
PostgreSQL (modem_checks, users, api_keys, audit logs)
Redis (sessions, CSRF tokens, account lockout, rate limiting)
```

## Quick Start

### 1. Configure Environment (REQUIRED)

**⚠️ SECURITY CRITICAL**: You MUST configure secrets before starting services!

```bash
# Copy example environment file
cp .env.example .env

# Generate secure secrets
python3 -c "import secrets; print('POSTGRES_DB_PASSWORD=' + secrets.token_urlsafe(32))"
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))"
python3 -c "import secrets; print('CSRF_SECRET_KEY=' + secrets.token_urlsafe(48))"
python3 -c "import secrets; print('REDIS_PASSWORD=' + secrets.token_urlsafe(32))"

# Edit .env and replace CHANGE_THIS_REQUIRED with generated values
# Also configure ALLOWED_ORIGINS (see Security Configuration below)
nano .env

# Set restrictive permissions
chmod 600 .env

# NEVER commit .env to version control (already in .gitignore)
```

**Required .env variables:**
- `POSTGRES_DB_PASSWORD` - Database password (32+ chars)
- `SECRET_KEY` - Session encryption key (48+ chars)
- `CSRF_SECRET_KEY` - CSRF token encryption key (48+ chars)
- `REDIS_PASSWORD` - Redis authentication password (32+ chars, REQUIRED for security)
- `ALLOWED_ORIGINS` - Comma-separated allowed domains (e.g., `https://example.com`)

### 2. Start Services

```bash
# Start all containers (PostgreSQL, Redis, FastAPI)
docker compose up -d

# View logs
docker compose logs -f modemcheck-cloud
```

### 3. Verify Health

```bash
# Overall health
curl http://localhost:22557/health

# Database connection pool status
curl http://localhost:22557/health/db

# Cache backend status (Redis vs in-memory fallback)
curl http://localhost:22557/health/cache

# API documentation
open http://localhost:22557/docs
```

**Health Endpoints:**
- `/health` - Overall application status
- `/health/db` - Database pool utilization and connection stats
- `/health/cache` - Cache backend status (Redis/memory), degraded mode warnings

### 4. First Login & Password Change

- **Web UI**: http://localhost:23890
- **Default credentials**:
  - Username: `admin`
  - Password: `changeme`
- **⚠️ CRITICAL**: You MUST change the password on first login!

**After login, you will be forced to change your password** before accessing any other features. This security measure prevents unauthorized access with the default credentials.

Database initialization happens automatically on first startup.

## API Endpoints

### Authentication (`/api/auth`)
- `POST /api/auth/login` - Login
- `POST /api/auth/logout` - Logout
- `GET /api/auth/session_check` - Check session + get CSRF token
- `POST /api/auth/change_password` - Change password

### Upload (`/api/upload`)
- `POST /api/upload` - Upload modem check (requires API key + HMAC signature)

### Database (`/api/db`)
- `GET /api/db/list_modems` - List all modems
- `GET /api/db/list_checks` - List checks for modem/date range
- `GET /api/db/get_check/{id}` - Get full check data
- `POST /api/db/get_all_checks` - Bulk check retrieval

### Admin (`/api/admin`)
- `POST /api/admin/api_keys` - Create API key
- `GET /api/admin/api_keys` - List API keys
- `PUT /api/admin/api_keys/toggle` - Enable/disable API key
- `DELETE /api/admin/api_keys` - Delete API key
- `GET /api/admin/logs/user_activity` - View user logs (admin only)
- `GET /api/admin/logs/client_submissions` - View client logs (elevated+)

#### API Key Rotation
To rotate an API key (e.g., suspected compromise or periodic rotation):
1. Create a new API key in the admin dashboard
2. Update the client's `config.json` with the new `CloudAPIKey`
3. Verify the client can upload with the new key
4. Delete the old API key

**Note:** No automatic key versioning - rotation requires brief coordination
between key creation and client update. For zero-downtime rotation,
create the new key first, update all clients, then delete the old key.

### Users (`/api/users`)
- `POST /api/users` - Create user
- `GET /api/users` - List users
- `DELETE /api/users` - Delete user
- `PUT /api/users/change_role` - Change user role
- `PUT /api/users/reset_password` - Admin password reset
- `POST /api/users/force_logout` - Force user logout

### Data Management (`/api/data`)
- `DELETE /api/data/check` - Delete single check
- `DELETE /api/data/modem_checks` - Delete all checks for modem
- `POST /api/data/bulk_upload` - Bulk upload JSON files (elevated+)
- `GET /api/data/bulk_download` - Download checks as ZIP (elevated+)

## Security Features

### Authentication & Authorization
- **Argon2id password hashing** (64MB memory, 3 iterations)
- **PBKDF2 backward compatibility** with automatic upgrade
- **Redis session management** with 1-hour sliding window
- **RBAC**: admin, elevated, basic roles
- **Account lockout**: 5 failed attempts → 30-minute lockout

### API Security
- **Rate limiting** (Dual-layer protection)
  - IP-based: 30/min (auth), 60/min (upload), 300/sec (API)
  - Per-user: 100 requests/hour (prevents multi-IP abuse)
  - Endpoint-specific limits available
  - Returns HTTP 429 when exceeded
- **Session security enhancements**
  - Device fingerprinting (user-agent + IP)
  - Session anomaly detection
  - Concurrent session limits (max 5 per user)
  - Automatic termination of oldest sessions
- **CSRF protection** for all state-changing operations
- **HMAC-SHA256 signatures** for client uploads
- **Replay attack prevention** (5-minute timestamp window)
- **Timing-safe comparisons** for passwords and API keys
- **Comprehensive audit logging** with 90-day retention

### Input Validation
- **Pydantic schemas** for automatic validation
- **File size limits** (10MB per upload)
- **Format validation** (modem_id, filename patterns)
- **SHA-256 checksums** for upload integrity

### HTTP Security Headers
- **Strict-Transport-Security** (HSTS) - Enforces HTTPS for 1 year
- **X-Content-Type-Options** - Prevents MIME type sniffing
- **X-Frame-Options** - Prevents clickjacking attacks
- **Content-Security-Policy** - Restricts resource loading (XSS protection)
- **Referrer-Policy** - Controls referrer information sharing
- **Permissions-Policy** - Disables geolocation, camera, microphone, etc.

### Automated Security Monitoring
- **Pre-commit hooks** - Prevents secret commits (detect-secrets, bandit)
- **GitHub Actions** - Weekly dependency vulnerability scanning
- **pip-audit & safety** - Python security advisories
- **govulncheck** - Go vulnerability detection
- **Dependency review** - Blocks PRs with vulnerable dependencies

## Database Schema

### PostgreSQL Tables

**users** - Authentication
- username (PK), password_hash, role, created_at, last_login, must_change_password

**api_keys** - Client authentication
- api_key_hash (PK), api_key_encrypted, encryption_salt, name, created_at, last_used, is_active

**modem_checks** - Diagnostic data
- id (PK), modem_id, modem_type, check_time, filename, full_data (JSONB), created_at
- Extracted metrics: signal quality, speed tests, ping results, traceroute (hop count, status), client info

**user_activity_log** - Audit trail
- id (PK), timestamp, username, action_type, ip_address, success, failure_reason

**client_submission_log** - Upload audit
- id (PK), timestamp, modem_id, api_key_hash, ip_address, success, processing_time_ms

## Configuration

All configuration via environment variables. See `.env.example` for complete documentation.

### Security Configuration (CRITICAL)

**Never use default/example values in production!** All secrets must be cryptographically random.

**Required Secrets:**
```bash
# Generate unique secrets for each environment:
POSTGRES_DB_PASSWORD=<32+ character random string>
SECRET_KEY=<48+ character random string>
CSRF_SECRET_KEY=<48+ character random string>
```

**CORS Configuration:**
```bash
# ⚠️ NEVER use * in production!
# Development:
ALLOWED_ORIGINS=http://localhost:23890,http://localhost:22557

# Production (specify exact domains):
ALLOWED_ORIGINS=https://modemcheck.example.com,https://admin.example.com
```

**Database:**
- `DATABASE_URL` - PostgreSQL connection (uses `${POSTGRES_DB_PASSWORD}`)

**Optional:**
- `REDIS_HOST`, `REDIS_PORT` - Redis connection
- `SESSION_TTL` - Session timeout (default: 3600s = 1 hour)
- `MAX_FAILED_LOGINS` - Account lockout threshold (default: 5)
- `ACCOUNT_LOCKOUT_DURATION` - Lockout time in seconds (default: 1800 = 30 min)
- `MIN_PASSWORD_LENGTH` - Minimum password length (default: 12)

### Credential Rotation

Rotate secrets every 90 days:

```bash
# 1. Generate new secrets
python3 -c "import secrets; print(secrets.token_urlsafe(48))"

# 2. Update .env file
nano .env

# 3. Restart containers
docker compose down && docker compose up -d

# 4. Invalidate all sessions (automatic on restart)

# 5. Force users to change passwords (admin function)
```

**After SECRET_KEY rotation:**
- All active sessions become invalid
- All users must log in again
- Consider forcing password changes for all users

### Docker Secrets (Production)

For enhanced security in production, use Docker Secrets instead of environment variables:

```bash
# Initialize Docker Swarm and create secrets
./scripts/setup-docker-secrets.sh

# Deploy with secrets
docker stack deploy -c docker-compose.yml -c docker-compose.secrets.yml modemcheck

# Verify secrets are mounted
docker exec $(docker ps -q -f name=modemcheck_api) ls -la /run/secrets/
```

**Benefits:**
- Secrets encrypted at rest and in transit
- Not visible in `docker inspect` or process listings
- Mounted as read-only files at `/run/secrets/`
- Only accessible to services that explicitly declare them

**When to use:**
- ✅ Production environments with compliance requirements
- ✅ Multi-service deployments with shared secrets
- ❌ Development/testing (overkill for non-production)

See [DOCKER_SECRETS.md](DOCKER_SECRETS.md) for complete implementation guide.

## Development

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment
export DATABASE_URL="postgresql+asyncpg://user:pass@localhost/modemcheck"
export SECRET_KEY="dev-secret-key"
export CSRF_SECRET_KEY="dev-csrf-key"
export DEBUG=true

# Initialize database
python init_database.py

# Run with auto-reload
python -m uvicorn app.main:app --reload --port 8000
```

### Testing

The cloud server includes a comprehensive test suite:

```bash
# Run all tests
./run_all_tests.sh

# Keep test environment for debugging
./run_all_tests.sh --keep-env

# Run specific test categories
./run_all_tests.sh tests/api/        # API tests
./run_all_tests.sh tests/security/   # Security tests
./run_all_tests.sh tests/unit/       # Unit tests
./run_all_tests.sh -m rbac           # RBAC tests only
```

**Test Environment:**
- Isolated PostgreSQL and Redis containers
- Separate ports: 22560 (API), 23894 (UI)
- Test database: `modemcheck_test`
- Rate limiting disabled to prevent fixture failures
- Automatic cleanup after tests complete

**Test Categories:**
- API Tests: All endpoints, validation, edge cases, metric extraction
- Security Tests: SQL injection, XSS, CSRF, auth bypass, session security
- RBAC Tests: Role permissions for all endpoints
- Unit Tests: ZIP security, cache stats, pure functions
- UI Tests: Playwright browser automation

#### Coverage Reports

ModemCheck provides **multiple coverage reports** to show both unit and E2E test coverage:

```bash
# Unit test coverage only
./run_unit_coverage.sh
open htmlcov-unit/index.html

# E2E test coverage only
./run_e2e_coverage.sh
open htmlcov-e2e/index.html

# Combined coverage from all tests (most comprehensive)
./run_combined_coverage.sh
open htmlcov-combined/index.html
```

**Coverage Reports:**
- **Unit Test Coverage**: Core utilities and pure functions
- **E2E Test Coverage**: Routers and middleware
- **Combined Coverage**: All modules
- **Dynamic Contexts**: Click any line to see which test covered it

See [TESTING.md](TESTING.md) for detailed testing philosophy and strategy.

## Migration from v1 (CGI)

### Parallel Deployment Strategy

1. **Deploy v2 on new ports** (22560, 23894, 23895)
2. **Test with subset of clients** (update client config)
3. **Monitor logs and performance**
4. **Gradual cutover** (update nginx upstream)
5. **Keep v1 running** on backup ports for 1 week
6. **Full cutover** once validated

### Data Migration

**Option A:** Fresh start (no historical data)
- Initialize new PostgreSQL database
- Clients upload to new system

**Option B:** Migrate SQLite → PostgreSQL
- Export checks from SQLite
- Bulk import to PostgreSQL
- Update modem_id/filename references

## Performance

### Capacity

- **Current (v1 CGI):** ~50 concurrent clients, 30-75ms latency
- **v2 (FastAPI):** ~10,000 concurrent clients, <20ms latency (estimated)

### Optimizations

- **Connection pooling:** 20 PostgreSQL connections
- **Async I/O:** Non-blocking database and Redis operations
- **Worker processes:** 4 Gunicorn workers (configurable)
- **JSONB indexing:** Fast queries on extracted metrics

## Monitoring

### Health Checks

```bash
# Application health
curl http://localhost:8000/health

# PostgreSQL health
docker exec modemcheck-postgres pg_isready

# Redis health
docker exec modemcheck-redis-v2 redis-cli ping
```

### Logs

```bash
# Application logs
docker logs modemcheck-cloud-v2

# PostgreSQL logs
docker logs modemcheck-postgres

# Redis logs
docker logs modemcheck-redis-v2
```

## Troubleshooting

### Database Connection Errors

```bash
# Check PostgreSQL is running
docker ps | grep postgres

# Verify credentials
docker exec modemcheck-postgres psql -U modemcheck -d modemcheck -c "SELECT 1"
```

### Redis Connection Errors

```bash
# Check Redis is running
docker exec modemcheck-redis-v2 redis-cli ping

# Check session keys
docker exec modemcheck-redis-v2 redis-cli KEYS "session:*"
```

### Application Won't Start

```bash
# Check logs
docker logs modemcheck-cloud-v2

# Verify environment variables
docker exec modemcheck-cloud-v2 env | grep DATABASE_URL

# Test database connection
docker exec modemcheck-cloud-v2 python -c "from app.core.database import init_db; init_db(); print('OK')"
```

## Operations & Maintenance

### Automated Backups

**Setup daily backups:**
```bash
# Create backup directories
mkdir -p backups/postgres backups/redis logs

# Run manual backup
./backup-all.sh --verify

# Set up cron (see cron-example.txt)
crontab -e
# Add: 0 2 * * * cd /path/to/cloudserver && ./backup-all.sh --verify >> logs/backup.log 2>&1
```

**Restore from backup:**
```bash
# Restore from latest backup
./restore-database.sh --latest

# Restore specific backup
./restore-database.sh backups/postgres/modemcheck_20250117_020000.sql.gz
```

### Audit Log Cleanup

**Automated cleanup (90-day retention):**
```bash
# Set up weekly cleanup
crontab -e
# Add: 0 3 * * 0 cd /path/to/cloudserver && python3 cleanup-audit-logs.py >> logs/cleanup.log 2>&1

# Manual cleanup
python3 cleanup-audit-logs.py --dry-run  # Preview
python3 cleanup-audit-logs.py            # Execute
```

### Session Security Monitoring

**Monitor active sessions:**
```python
from app.core.session_security import get_user_active_sessions, get_session_anomalies

# Get active sessions for user
sessions = await get_user_active_sessions("admin")

# Check for security anomalies
anomalies = await get_session_anomalies("admin", days=7)
```

### Complete Operations Guide

See [OPERATIONS.md](OPERATIONS.md) for comprehensive documentation on:
- Backup and restore procedures
- Audit log management
- Security monitoring
- Performance tuning
- Disaster recovery
- Maintenance checklists

## License

Same as parent project (see repository root).

## Support

See main project CLAUDE.md for detailed implementation notes.

**Additional documentation:**
- [OPERATIONS.md](OPERATIONS.md) - Complete operations guide for backups, monitoring, and maintenance
- [TESTING.md](TESTING.md) - Comprehensive test suite documentation
