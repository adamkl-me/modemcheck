# ModemCheck Comprehensive Test Suite

## Overview

This document describes the comprehensive test suite for ModemCheck v2, covering both the Go client and Python FastAPI server components. The test suite has been developed iteratively through multiple phases, ensuring comprehensive coverage of functionality, security, performance, and error handling.

## Test Statistics

### Coverage Summary
- **Go Client**: ~60% coverage (estimated)
- **Python Server**: 88%+ coverage (target: 80%+)
- **Total Tests**: 450+ test cases across all categories
- **API Tests**: 77+ tests (all endpoints, validation, edge cases, metric extraction, audit retention)
- **Security Tests**: 100+ test cases (SQL injection, XSS, CSRF, authentication bypass, rate limiting, session security)
- **Integration Tests**: 80+ test cases (complete workflows, concurrent operations)
- **Performance Tests**: 20+ test cases (load testing, throughput benchmarks)
- **RBAC Tests**: 20+ tests (role permissions for all endpoints)
- **UI Tests**: 10+ tests (Playwright browser automation)

### Test Results (Latest Run)
- **Passing**: 435+ tests (96%)
- **Skipped**: 5 tests (4%)
  - `test_login_rate_limiting` - Rate limiting disabled in test environment
  - `test_external_api_unavailable` - Requires network isolation
  - `test_database_connection_failure` - Requires database shutdown
  - `test_redis_connection_failure` - Requires Redis shutdown
  - `test_file_system_full` - Requires disk space manipulation

### Test Execution Time
- **Unit Tests**: ~30 seconds
- **Integration Tests**: ~2 minutes
- **Full Suite**: ~5 minutes
- **Performance Tests**: ~2 minutes (marked as slow)
- **Complete Test Run**: ~7-10 minutes including setup/teardown

## Test Organization

### Directory Structure

```
modemcheck/
├── modemcheck-client/
│   ├── main_test.go                          # Core client tests
│   ├── cloud_client_test.go                  # HMAC & upload tests
│   ├── updater_test.go                       # Update system tests
│   ├── diagnostics_comprehensive_test.go     # Network diagnostics
│   └── scraper/
│       ├── scraper_test.go                   # Scraper interface tests
│       └── xfinity_test.go                   # Xfinity-specific tests
│
└── cloudserver/
    ├── tests/
    │   ├── unit/
    │   │   ├── test_database_operations.py   # Database CRUD
    │   │   ├── test_authentication.py        # Auth & password hashing
    │   │   └── test_metric_extraction.py     # Modem check metric extraction (22 tests)
    │   │
    │   ├── security/
    │   │   ├── test_api_key_security.py      # API key security
    │   │   ├── test_hmac_signature_security.py # HMAC validation
    │   │   ├── test_session_hijacking.py     # Session security
    │   │   ├── test_session_security.py      # Device fingerprinting & anomaly detection (20+ tests)
    │   │   └── test_enhanced_rate_limiting.py # Per-user rate limiting (20+ tests)
    │   │
    │   ├── integration/
    │   │   ├── test_upload_flow.py           # Complete upload workflow
    │   │   ├── test_admin_workflow.py        # Admin operations
    │   │   ├── test_error_paths.py           # Error handling
    │   │   └── test_audit_retention.py       # Audit log retention & cleanup (15+ tests)
    │   │
    │   └── performance/
    │       └── test_load.py                  # Load & performance tests
    │
    └── run_tests.sh                          # Test runner script
```

## Running Tests

### Go Client Tests

```bash
# Run all tests
cd modemcheck-client
go test -v ./...

# Run with coverage
go test -v -race -coverprofile=coverage.txt -covermode=atomic ./...

# View coverage report
go tool cover -html=coverage.txt

# Run specific test file
go test -v ./cloud_client_test.go
```

### Python Server Tests

```bash
# Run all tests
cd cloudserver
./run_tests.sh

# Run specific test category
./run_tests.sh tests/unit/
./run_tests.sh tests/security/
./run_tests.sh tests/integration/

# Run with markers
./run_tests.sh -m security    # Security tests only
./run_tests.sh -m rbac        # RBAC tests only
./run_tests.sh -m slow        # Include slow tests

# Keep test environment for debugging
./run_tests.sh --keep-env
```

### CI/CD Pipeline

Tests run automatically via GitHub Actions on:
- Push to `main` or `develop` branches
- Pull requests to `main`

**Workflow**: `.github/workflows/test.yml`

## Test Categories

### 1. Security Tests (100+ tests)

#### API Key Security (`test_api_key_security.py`)
- ✅ Brute force prevention
- ✅ Timing attack resistance
- ✅ Key enumeration prevention
- ✅ Key rotation security
- ✅ Cache invalidation
- ✅ Complexity and entropy

**Example:**
```python
async def test_api_key_timing_attack_resistance(http_client, active_api_key):
    """Verify constant-time comparison prevents timing attacks."""
    # Test partial vs complete mismatch timing
    # Should have < 10ms difference
```

#### HMAC Signature Security (`test_hmac_signature_security.py`)
- ✅ Signature tampering detection
- ✅ Replay attack prevention
- ✅ Timestamp validation
- ✅ Message integrity
- ✅ Malformed signature handling

#### Session Security (`test_session_hijacking.py`)
- ✅ Session fixation prevention
- ✅ Token stealing prevention
- ✅ IP address binding
- ✅ User agent validation
- ✅ Concurrent session detection
- ✅ Anomaly detection

#### Authentication (`test_authentication.py`)
- ✅ Argon2id password hashing
- ✅ PBKDF2 legacy support
- ✅ Password strength validation
- ✅ Hash migration (PBKDF2 → Argon2)
- ✅ Timing-safe verification
- ✅ Account lockout (5 attempts, 30 min)

### 2. Enhanced Security Tests (Additional 77+ tests)

These tests were added as part of security hardening initiatives:

#### Metric Extraction (`test_metric_extraction.py` - 22 tests)
- ✅ Extract 40+ individual fields from modem check JSON
- ✅ System metrics (firmware, uptime, client version/OS/arch)
- ✅ Signal quality (downstream/upstream power, SNR, errors)
- ✅ Speed tests (iperf3, speedtest.net with latency/jitter/packet loss)
- ✅ Ping tests (Google and Cloudflare avg/loss/jitter/max)
- ✅ Network info (public IP, ASN, ISP, city, country)
- ✅ Safe type conversions (handles missing/invalid data)
- ✅ Database storage validation

**Benefits:**
- 10-100x faster queries on specific metrics (no JSONB parsing)
- Enables metric-specific filtering and aggregation
- Maintains backwards compatibility (full JSON still in `full_data`)

#### Session Security (`test_session_security.py` - 20+ tests)
- ✅ Device fingerprinting (SHA256 of user-agent + IP)
- ✅ Fingerprint verification (strict and lenient modes)
- ✅ Concurrent session limits (max 5 per user)
- ✅ Automatic termination of oldest sessions
- ✅ Session anomaly detection (IP changes, user-agent mismatches)
- ✅ Anomaly logging with 30-day retention
- ✅ Session lifecycle management

**Example:**
```python
async def test_fingerprint_mismatch_detection(session_security):
    # Create session with fingerprint
    fingerprint = generate_device_fingerprint("User-Agent-1", "192.168.1.1")
    await create_session_with_fingerprint(session_id, username, fingerprint)

    # Attempt access from different device
    result = await verify_session_fingerprint(
        session_id, "Different-Agent", "192.168.1.1"
    )

    # Should detect anomaly
    assert result["anomaly_detected"] is True
    assert "user_agent_mismatch" in result["anomaly_type"]
```

#### Enhanced Rate Limiting (`test_enhanced_rate_limiting.py` - 20+ tests)
- ✅ Per-user rate limits (100 requests/hour across all IPs)
- ✅ Per-endpoint per-user limits (customizable)
- ✅ Dual-layer protection (IP-based + user-based)
- ✅ Request statistics tracking
- ✅ Admin reset functionality
- ✅ Prevents multi-IP abuse

**Implementation:**
- IP-based (SlowAPI): 30/min (auth), 60/min (upload), 300/sec (API)
- User-based (custom): 100/hour global, endpoint-specific available
- Redis storage: `user_rate_limit:<username>`, `endpoint_rate_limit:<username>:<endpoint>`

#### Audit Retention (`test_audit_retention.py` - 15+ tests)
- ✅ 90-day retention for user activity logs
- ✅ 90-day retention for client submission logs
- ✅ Separate policies per log type
- ✅ Dry-run support for preview
- ✅ Statistics (counts, age, oldest/newest timestamps)
- ✅ Automated cleanup with cron scheduling

**Example:**
```python
async def test_cleanup_old_audit_logs():
    # Create logs of various ages
    old_log = create_log(90 days ago)
    new_log = create_log(30 days ago)

    # Run cleanup (90-day retention)
    result = await cleanup_all_audit_logs(dry_run=False)

    # Verify old logs deleted, new logs retained
    assert result["user_activity"]["deleted"] == 1
    assert result["client_submissions"]["deleted"] == 1
```

### 3. Core Functionality Tests (150+ tests)

#### Go Client Tests

**Main Functionality** (`main_test.go`)
- ✅ Configuration loading & validation
- ✅ Results directory creation
- ✅ JSON output formatting
- ✅ Log file management (30-day cleanup)
- ✅ Cloud upload with HMAC
- ✅ Upload queue (FIFO, 100 max)
- ✅ Private network detection
- ✅ Version comparison
- ✅ Concurrent operations

**Network Diagnostics** (`diagnostics_comprehensive_test.go`)
- ✅ 3-tier IP detection fallback
- ✅ Ping tests (Google, Cloudflare)
- ✅ Speed test interval logic
- ✅ iperf3 integration
- ✅ speedtest.net integration
- ✅ HTTP client connection pooling
- ✅ Goroutine panic recovery

**Modem Scrapers** (`scraper/scraper_test.go`, `scraper/xfinity_test.go`)
- ✅ Auto-detection (4 IPs)
- ✅ State file persistence
- ✅ MAC address extraction
- ✅ Channel data parsing
- ✅ FEC error extraction
- ✅ Session management
- ✅ Response body closure (18 leaks fixed)

**Update System** (`updater_test.go`)
- ✅ Signature verification (Ed25519)
- ✅ Download integrity (SHA256)
- ✅ Update rollback
- ✅ Channel selection (stable/beta/test)
- ✅ Network resilience
- ✅ Permission handling

#### Python Server Tests

**Database Operations** (`test_database_operations.py`)
- ✅ Connection pooling
- ✅ CRUD operations (ModemCheck, User, APIKey)
- ✅ Transaction handling & rollback
- ✅ Foreign key constraints
- ✅ Concurrent connections
- ✅ Query optimization

### 3. Integration Tests (80+ tests)

#### Upload Workflow (`test_upload_flow.py`)
- ✅ Complete upload with authentication
- ✅ Metric extraction (40+ fields)
- ✅ Signature validation
- ✅ Audit logging
- ✅ Checksum verification
- ✅ Timestamp validation
- ✅ Malformed JSON rejection
- ✅ Oversized upload rejection (10MB limit)
- ✅ Concurrent uploads (same modem)
- ✅ Concurrent uploads (different modems)

**Example Flow:**
```
Client → HMAC Signature → API Key Validation →
JSON Validation → Checksum Verification →
Metric Extraction → Database Storage → Audit Log
```

#### Admin Workflow (`test_admin_workflow.py`)
- ✅ User creation → login verification
- ✅ Role updates (basic → elevated → admin)
- ✅ User deletion
- ✅ API key lifecycle (create → use → rotate → delete)
- ✅ Data management (query, filter, delete)
- ✅ RBAC enforcement

#### Error Paths (`test_error_paths.py`)
- ✅ Network errors (timeout, connection failure)
- ✅ Database errors (duplicate key, foreign key)
- ✅ Transaction rollback recovery
- ✅ Concurrent edge cases
- ✅ Input validation (XSS, null bytes, unicode)
- ✅ Resource limits (max upload size, connections)
- ✅ Error recovery (invalid JSON → valid request)

### 4. Performance Tests (20+ tests)

#### Load Testing (`test_load.py`)

**Upload Performance:**
- Target: < 1s average latency
- Concurrent: 20 uploads, < 2s average
- Throughput: ≥ 5 req/s

**Query Performance:**
- Target: < 500ms for 100 records
- API key cache: 10-100x speedup

**Database Performance:**
- Bulk insert: ≥ 20 records/s
- Indexed queries: < 100ms

**Stress Testing:**
- Sustained load: 30 seconds
- Target: ≥ 100 successful uploads
- Error rate: < 10%

## Test Fixtures

### Go Client Fixtures
- Temporary directories
- Mock HTTP servers
- Test configurations
- Sample modem data

### Python Server Fixtures

**Database Fixtures** (`conftest.py`)
```python
@pytest.fixture
async def db_session():
    """Async database session."""

@pytest.fixture
async def admin_user(db_session):
    """Admin user with TestPass123!"""

@pytest.fixture
async def active_api_key(admin_user, db_session):
    """Active API key for uploads."""
```

**HTTP Client Fixtures**
```python
@pytest.fixture
async def http_client():
    """HTTP client for API testing."""

@pytest.fixture
async def admin_client_with_token(http_client, admin_user):
    """Authenticated admin client."""

@pytest.fixture
async def csrf_token(admin_client_with_token):
    """CSRF token for state-changing operations."""
```

## Test Markers

```python
@pytest.mark.unit          # Fast unit tests
@pytest.mark.integration   # Integration tests
@pytest.mark.security      # Security-focused tests
@pytest.mark.rbac          # RBAC permission tests
@pytest.mark.performance   # Performance benchmarks
@pytest.mark.slow          # Long-running tests
@pytest.mark.asyncio       # Async test support
```

## Coverage Requirements

### Minimum Coverage Targets
- **Critical Security Functions**: 95%+
- **Core Business Logic**: 90%+
- **API Endpoints**: 85%+
- **Overall**: 80%+

### Coverage Reports

**Go Client:**
```bash
go test -coverprofile=coverage.txt ./...
go tool cover -func=coverage.txt
```

**Python Server:**
```bash
pytest --cov=app --cov-report=html --cov-report=term
open htmlcov/index.html
```

## Known Test Limitations

### Skipped Tests (5 total)

1. **test_login_rate_limiting** - Rate limiting disabled in test environment
2. **test_external_api_unavailable** - Requires network isolation
3. **test_database_connection_failure** - Requires database shutdown
4. **test_redis_connection_failure** - Requires Redis shutdown
5. **test_file_system_full** - Requires disk space manipulation

### Test Environment Differences

**Production vs Test:**
- **Ports**:
  - Production: 22557 (API), 23890 (UI)
  - Test: 22560 (API), 23894 (UI)
- **Databases**:
  - Production: `modemcheck` (PostgreSQL)
  - Test: `modemcheck_test` (PostgreSQL)
- **Docker Networks**:
  - Production: `172.25.0.0/16`
  - Test: `172.26.0.0/16` (isolated)
- **Environment**: `TESTING=true` variable set
- **Rate Limiting**: Disabled in test environment to prevent fixture failures
- **Docker Services**:
  - Test uses separate containers: `postgres-test`, `redis-test`, `modemcheck-api-test`, `nginx-test`
  - Separate volumes: `postgres-test-data`, `redis-test-data` (ephemeral)
  - No resource limits in test environment (vs production 2 CPU / 4GB RAM limits)

## Test Data Management

### Test Database
- Automatically initialized with schema
- Populated with fixtures (users, API keys)
- Cleaned up after each test
- Isolated from production

### Test Credentials
```python
# Admin
username: admin
password: TestPass123!

# Elevated
username: test_elevated
password: TestPass123!

# Basic
username: test_basic
password: TestPass123!
```

## Continuous Integration

### GitHub Actions Workflow

**Workflow File:** `.github/workflows/test.yml`

**Triggers:**
- Push to `main` or `develop` branches
- Pull requests to `main`

**Jobs:**

1. **Go Client Tests** (ubuntu-latest, Go 1.21)
   - Download dependencies (`go mod download`)
   - Run tests with race detection (`go test -race`)
   - Generate coverage report (`-coverprofile=coverage.txt -covermode=atomic`)
   - Check coverage threshold (95%+)
   - Upload to Codecov for tracking

2. **Python Server Tests** (ubuntu-latest, Python 3.11)
   - Services: PostgreSQL 16, Redis 7
   - Install dependencies from `requirements.txt`
   - Install Playwright browsers
   - Run pytest with coverage (`pytest --cov --cov-report=xml`)
   - Check coverage threshold (95%+)
   - Upload coverage to Codecov

3. **Security Tests** (runs after unit tests pass)
   - **Bandit** (Python): Scans for security issues in Python code
   - **gosec** (Go): Detects security issues in Go code
   - Upload security reports as artifacts
   - Fail build on high-severity findings

4. **Integration Tests** (Docker Compose)
   - Start test environment (`docker compose -f docker-compose.test.yml up -d`)
   - Health checks: Wait for PostgreSQL, Redis, FastAPI
   - Run end-to-end tests
   - Upload test artifacts (screenshots, traces for failures)
   - Cleanup containers (`docker compose down -v`)

5. **Build Verification**
   - Build Go client binary for linux-amd64
   - Verify binary executes (`./modem-check --version`)
   - Build Docker image (`docker build cloudserver/`)
   - Verify image starts successfully

**Coverage Tracking:**
- Codecov integration with automatic PR comments
- Coverage trends tracked over time
- Pull requests blocked if coverage drops below threshold

**Security Scanning:**
- Weekly automated dependency scanning
- `pip-audit` for Python dependencies
- `govulncheck` for Go dependencies
- Dependency review action blocks PRs with vulnerable dependencies

## Debugging Failed Tests

### Enable Verbose Output
```bash
# Go
go test -v ./...

# Python
pytest -vv tests/

# Python with logs
pytest -vv -s tests/  # Show print statements
```

### Keep Test Environment
```bash
./run_tests.sh --keep-env
# Environment stays running at localhost:22560
```

### Run Single Test
```bash
# Go
go test -v -run TestSpecificFunction

# Python
pytest tests/path/to/test.py::TestClass::test_function
```

### Debug with PDB
```python
import pdb; pdb.set_trace()
```

## Performance Benchmarking

### Baseline Metrics (Reference Hardware)

**Upload Endpoint:**
- Average latency: 50-100ms
- Concurrent (20): 150-250ms
- Throughput: 10-20 req/s

**Query Endpoint:**
- 100 records: 30-50ms
- 1000 records: 100-200ms

**Database:**
- Bulk insert: 50-100 records/s
- Indexed query: 10-30ms

## Security Test Examples

### Timing Attack Test
```python
async def test_api_key_timing_attack_resistance(http_client, active_api_key):
    # Partial key match
    partial_key = active_api_key[:16] + "0" * 48

    # Completely wrong key
    wrong_key = "x" * 64

    # Measure timing for both
    timings_partial = [measure(partial_key) for _ in range(10)]
    timings_wrong = [measure(wrong_key) for _ in range(10)]

    # Difference should be < 10ms
    timing_diff = abs(avg(timings_partial) - avg(timings_wrong))
    assert timing_diff < 0.01
```

### Replay Attack Test
```python
async def test_replay_attack_prevention(http_client, active_api_key):
    # Upload once
    response1 = await upload_check(timestamp, signature)
    assert response1.status_code == 200

    # Try to replay exact same request
    response2 = await upload_check(timestamp, signature)

    # Should be rejected (old timestamp)
    assert response2.status_code == 403
```

## Contributing Tests

### Test Naming Conventions
- Test files: `test_*.py` or `*_test.go`
- Test functions: `test_*` or `Test*`
- Test classes: `Test*`
- Use descriptive names: `test_upload_with_invalid_signature_is_rejected`

### Test Structure (AAA Pattern)
```python
def test_example():
    # Arrange - Set up test data
    user = create_user(username="test")

    # Act - Perform the action
    result = user.login("password")

    # Assert - Verify the outcome
    assert result.success is True
```

### Adding New Tests
1. Create test file in appropriate directory
2. Import necessary fixtures from `conftest.py`
3. Add test markers (`@pytest.mark.integration`)
4. Ensure test is idempotent (can run multiple times)
5. Clean up resources (use fixtures/teardown)
6. Update this documentation if adding new category

## Test Maintenance

### Regular Tasks
- [ ] Review test coverage weekly
- [ ] Update fixtures when models change
- [ ] Keep test data realistic
- [ ] Remove obsolete tests
- [ ] Update documentation

### When to Update Tests
- ✅ New feature added → Add tests
- ✅ Bug fixed → Add regression test
- ✅ API changed → Update integration tests
- ✅ Security vulnerability → Add security test
- ✅ Performance regression → Add performance test

## References

- **Test Framework**: pytest (Python), testing (Go)
- **Coverage**: pytest-cov, go test -cover
- **Async**: pytest-asyncio
- **HTTP**: httpx (async client)
- **Mocking**: unittest.mock, gomock
- **Fixtures**: pytest fixtures, go subtests

## Test Development History

### Phase 1: Initial Test Suite (2024)
The ModemCheck v2 test suite was developed in multiple phases:

**Phase 1: Critical Security Tests**
- HMAC signature validation
- API key brute force prevention
- Timing attack resistance
- Session hijacking prevention
- Update signature verification

**Phase 2: Core Go Client Tests**
- Configuration loading
- Results directory management
- JSON output formatting
- Cloud upload with retry logic
- Network diagnostics (3-tier IP detection)

**Phase 3: Modem Scraper Tests**
- Auto-detection across 4 common IPs
- State file persistence
- MAC address extraction
- Channel data parsing
- Response body closure (fixed 18 file descriptor leaks)

**Phase 4: Python Server Unit Tests**
- Database CRUD operations
- Connection pooling
- Transaction handling
- Authentication system
- Password hashing (Argon2id + PBKDF2 migration)

**Phase 5: Integration Tests**
- Complete upload workflow
- Admin user management
- API key lifecycle
- Data management operations
- RBAC enforcement

**Phase 6: Error Path Tests**
- Network errors and timeouts
- Database errors (duplicate keys, foreign keys)
- Concurrent operation edge cases
- Input validation (XSS, null bytes, unicode)
- Resource limits and recovery

**Phase 7: Performance Tests**
- Upload latency benchmarks (< 1s average)
- Concurrent upload handling (20 simultaneous)
- Query performance (< 500ms for 100 records)
- Database bulk operations (≥ 20 records/s)
- Stress testing (30s sustained load)

**Phase 8: Documentation**
- Comprehensive TESTING.md creation
- Test category organization
- Running instructions
- Coverage requirements
- Contributing guidelines

### Phase 2: Security Hardening Tests (2025)
Additional tests added during security enhancement initiatives:

**Metric Extraction** (22 tests)
- Extract 40+ fields from modem check JSON
- System metrics, signal quality, speed tests, ping results
- Database storage validation
- Safe type conversion

**Session Security** (20+ tests)
- Device fingerprinting (SHA256)
- Concurrent session limits (max 5)
- Session anomaly detection
- IP and user-agent validation

**Enhanced Rate Limiting** (20+ tests)
- Per-user rate limits (100 req/hour)
- Per-endpoint limits
- Dual-layer protection (IP + user)
- Multi-IP abuse prevention

**Audit Retention** (15+ tests)
- 90-day retention policies
- Automated cleanup
- Statistics and dry-run support
- Separate user activity and client submission logs

### Total Test Coverage Evolution
- **Initial (v1)**: ~20% coverage, basic functionality only
- **Phase 1 (v2.0)**: 60% client, 72% server, 350+ tests
- **Phase 2 (v2.1)**: 60% client, 88%+ server, 450+ tests
- **Target**: 95% security, 90% business logic, 85% API, 80%+ overall

## Related Documentation

### Primary Testing Documentation
- **TESTING.md** (this file): Comprehensive test suite documentation (consolidated from all sources)
- **cloudserver/README.md**: Cloud server overview with testing section

### Architecture & Implementation
- **CLAUDE.md**: Complete technical implementation guide
- **cloudserver/OPERATIONS.md**: Operations, backups, monitoring, maintenance
- **SECURITY.md**: Security model and threat protection
- **modemcheck-client/UPDATER.md**: Auto-update security details

### Development & Configuration
- **.github/workflows/test.yml**: CI/CD pipeline configuration
- **cloudserver/run_tests.sh**: Test runner script
- **cloudserver/conftest.py**: pytest fixtures and configuration
- **docker-compose.test.yml**: Isolated test environment

### API Documentation
- **FastAPI Docs** (running server): http://localhost:22557/docs (production) or http://localhost:22560/docs (test)
- **OpenAPI Schema**: Auto-generated from Pydantic models
- **cloudserver/README.md**: API endpoint reference

## Support

For test failures or questions:
1. Check GitHub Actions logs for CI/CD failures
2. Run tests locally with `-vv` flag for verbose output
3. Review this documentation for test organization
4. Check `conftest.py` for fixture details and configuration
5. Examine `docker-compose.test.yml` for environment setup
6. Review individual test files for specific test implementations
7. Open issue at project repository for assistance

### Common Issues

**Tests failing locally but passing in CI:**
- Ensure Docker containers are running (`docker ps`)
- Check environment variables (`.env` file)
- Verify database is initialized (`docker exec modemcheck-postgres-test psql -U modemcheck -d modemcheck_test -c "SELECT 1"`)
- Clear test database (`docker compose -f docker-compose.test.yml down -v`)

**Rate limiting test failures:**
- Ensure `TESTING=true` environment variable is set
- Rate limiting should be automatically disabled in test environment
- Check Redis connection (`docker exec modemcheck-redis-test redis-cli ping`)

**Fixture errors:**
- Clear pytest cache (`rm -rf .pytest_cache`)
- Reinstall dependencies (`pip install -r requirements.txt`)
- Check conftest.py for fixture dependencies

**Slow test execution:**
- Run specific test categories instead of full suite
- Use `-n auto` for parallel execution (pytest-xdist)
- Skip performance tests with `-m "not slow"`