# Architecture Review - Action Checklist

## Quick Reference

| Issue ID | Category | Severity | Issue | Status |
|----------|----------|----------|-------|--------|
| 1.1 | Layering | MEDIUM | Circular dependency in core modules | Not Started |
| 1.2 | Layering | MEDIUM | Security module overload (11+ functions) | Not Started |
| 1.3 | Layering | LOW | Middleware imports router functions | Not Started |
| 1.4 | Layering | MEDIUM | Test DB shares schema with production | Not Started |
| 2.1 | Configuration | MEDIUM | Multiple config sources without priority | Not Started |
| 2.2 | Configuration | LOW | Hardcoded values in code | Not Started |
| 3.1 | Abstraction | MEDIUM | No interface for configuration | Not Started |
| 3.2 | Abstraction | MEDIUM | No repository pattern for data access | Not Started |
| 3.3 | Abstraction | LOW | No interface for audit logging | Not Started |
| 4.1 | Global State | **HIGH** | Redis singleton with global state | Not Started |
| 4.2 | Global State | LOW | HTTP client lifecycle not explicit | Not Started |
| 5.1 | Scalability | MEDIUM | Single Redis database (no separation) | Not Started |
| 5.2 | Scalability | MEDIUM | Database pool exhaustion risk | Not Started |
| 5.3 | Scalability | LOW | No query optimization metrics | Not Started |
| 6.1 | Resilience | **HIGH** | Redis required for authentication | Not Started |
| 6.2 | Resilience | **HIGH** | No database replication | Not Started |
| 6.3 | Resilience | MEDIUM | Update mechanism single source | Not Started |
| 7.1 | Deployment | LOW | Docker build without multi-stage | Not Started |
| 7.2 | Deployment | MEDIUM | Minimal health checks | Not Started |
| 7.3 | Deployment | MEDIUM | Missing deployment documentation | Not Started |
| 8.1 | Configuration | MEDIUM | No environment validation at startup | Not Started |
| 8.2 | Configuration | **HIGH** | Credentials in Docker logs | Not Started |
| 9.1 | Observability | MEDIUM | No distributed tracing | Not Started |
| 9.2 | Observability | LOW | No structured logging | Not Started |

---

## Phase 1: Critical Issues (Week 1-2)

These are production blockers and security issues.

### ✅ 8.2 - Fix Credentials in Docker Logs (1-2 hours)
**Status:** Not Started
**Risk:** HIGH - Active security issue
**Impact:** Credentials visible in container logs

**Tasks:**
- [ ] Create `app/core/logging_utils.py`
- [ ] Add `mask_password()` and `mask_database_url()` functions
- [ ] Update `app/main.py` startup logs
- [ ] Update `cloudserver/Dockerfile` to not log sensitive values
- [ ] Verify credentials masked in docker logs
- [ ] Update operations documentation

**Files to create/modify:**
- `cloudserver/app/core/logging_utils.py` (NEW)
- `cloudserver/app/main.py` (MODIFY)
- `cloudserver/Dockerfile` (VERIFY)

**Testing:**
```bash
docker-compose up 2>&1 | grep -i "password\|secret\|api"  # Should find no actual values
```

---

### ✅ 8.1 - Add Startup Configuration Validation (1-2 hours)
**Status:** Not Started
**Risk:** MEDIUM - Fail-late instead of fail-fast
**Impact:** Configuration errors discovered at runtime instead of startup

**Tasks:**
- [ ] Add validators to `app/core/config.py` for:
  - SECRET_KEY length >= 32 chars
  - DATABASE_URL format (postgresql://)
  - CSRF_SECRET_KEY length >= 32 chars
  - ALLOWED_ORIGINS not wildcard in production
  - Port numbers valid
- [ ] Add database connectivity check in `app/main.py` lifespan
- [ ] Add Redis connectivity check in `app/main.py` lifespan
- [ ] Update error messages to be actionable
- [ ] Test with missing/invalid environment variables

**Files to create/modify:**
- `cloudserver/app/core/config.py` (MODIFY)
- `cloudserver/app/main.py` (MODIFY)

**Testing:**
```bash
# Test missing SECRET_KEY
unset SECRET_KEY
docker-compose up 2>&1 | grep -i "secret_key"  # Should show validation error immediately

# Test invalid DATABASE_URL
DATABASE_URL=mysql://... docker-compose up  # Should fail at startup
```

---

### ✅ 4.1 - Extract Redis Client Module (2-3 hours)
**Status:** Not Started
**Risk:** HIGH - Global state affects testing
**Impact:** Tests fail due to event loop issues, difficult to mock Redis

**Tasks:**
- [ ] Create `app/core/redis_client.py`
- [ ] Extract `_redis_client` global and lifecycle management
- [ ] Create `RedisConnectionPool` class with explicit `connect()`/`disconnect()`
- [ ] Update `app/core/security.py` to remove Redis management
- [ ] Update `app/core/enhanced_limiter.py` imports
- [ ] Update `app/core/session_security.py` imports
- [ ] Fix `app/core/api_key_cache.py` import (currently broken)
- [ ] Update `app/main.py` lifespan to call `connect_redis()`
- [ ] Verify tests pass without event loop issues

**Files to create/modify:**
- `cloudserver/app/core/redis_client.py` (NEW)
- `cloudserver/app/core/security.py` (MODIFY)
- `cloudserver/app/core/enhanced_limiter.py` (MODIFY)
- `cloudserver/app/core/session_security.py` (MODIFY)
- `cloudserver/app/core/api_key_cache.py` (MODIFY)
- `cloudserver/app/main.py` (MODIFY)

**Testing:**
```bash
cd cloudserver
./run_tests.sh tests/api/test_auth.py  # Should pass without event loop issues
./run_tests.sh -m redis  # New tests for Redis connection
```

---

### ✅ 6.1 - Add PostgreSQL Fallback for Sessions (3-4 hours)
**Status:** Not Started
**Risk:** HIGH - Redis is SPOF for authentication
**Impact:** If Redis down, no users can log in

**Tasks:**
- [ ] Create `app/models/session.py` with SessionRecord model
- [ ] Create `app/core/sessions/hybrid_storage.py` with HybridSessionStore
- [ ] Update `app/core/security.py` to use HybridSessionStore
- [ ] Add migration: create sessions table
- [ ] Add tests for Redis failure recovery
- [ ] Test with Redis down: should still authenticate from database
- [ ] Document fallback behavior in OPERATIONS.md

**Files to create/modify:**
- `cloudserver/app/models/session.py` (NEW)
- `cloudserver/app/core/sessions/__init__.py` (NEW)
- `cloudserver/app/core/sessions/hybrid_storage.py` (NEW)
- `cloudserver/app/core/security.py` (MODIFY)
- `cloudserver/tests/api/test_auth.py` (ADD tests for Redis failure)
- `cloudserver/OPERATIONS.md` (DOCUMENT fallback)

**Testing:**
```bash
# Start with Redis running
curl -X POST http://localhost:22560/api/auth/login -d "username=admin&password=admin"
# Session should work

# Stop Redis
docker-compose stop redis

# Login should still work from PostgreSQL
curl -X POST http://localhost:22560/api/auth/login -d "username=admin&password=admin"
# Should succeed via PostgreSQL fallback

# Restart Redis
docker-compose start redis
```

---

## Phase 2: High Priority Issues (Week 3-4)

### ✅ 3.2 - Repository Pattern for Data Access (4-5 hours)
**Status:** Not Started
**Risk:** MEDIUM - Difficult to test, tight coupling to SQLAlchemy
**Impact:** Hard to swap database backends, mock in tests

**Tasks:**
- [ ] Create `app/core/repositories/base.py` with BaseRepository interface
- [ ] Create `app/core/repositories/modem_check.py` with ModemCheckRepository
- [ ] Create `app/core/repositories/user.py` with UserRepository
- [ ] Create `app/core/repositories/api_key.py` with APIKeyRepository
- [ ] Update `app/routers/upload.py` to use ModemCheckRepository
- [ ] Update `app/routers/db_api.py` to use ModemCheckRepository
- [ ] Update `app/routers/admin.py` to use repositories
- [ ] Create mock repositories for testing
- [ ] Update tests to use mock repositories

**Files to create/modify:**
- `cloudserver/app/core/repositories/__init__.py` (NEW)
- `cloudserver/app/core/repositories/base.py` (NEW)
- `cloudserver/app/core/repositories/modem_check.py` (NEW)
- `cloudserver/app/core/repositories/user.py` (NEW)
- `cloudserver/app/core/repositories/api_key.py` (NEW)
- `cloudserver/app/routers/upload.py` (MODIFY)
- `cloudserver/app/routers/db_api.py` (MODIFY)
- `cloudserver/tests/test_repositories.py` (NEW)

**Testing:**
```bash
cd cloudserver
./run_tests.sh tests/test_repositories.py
./run_tests.sh tests/api/test_upload.py  # Should still work with repositories
```

---

### ✅ 1.2 - Decompose Security Module (3-4 hours)
**Status:** Not Started
**Risk:** MEDIUM - Difficult to test, maintain, understand
**Impact:** Single 600+ line module with 11+ functions

**Tasks:**
- [ ] Create `app/core/passwords/hashing.py` (hash_password, verify_password)
- [ ] Create `app/core/passwords/validation.py` (validate_password, is_common_password)
- [ ] Create `app/core/csrf/tokens.py` (generate_csrf_token, validate_csrf_token)
- [ ] Create `app/core/auth/lockout.py` (check_account_locked, record_failed_login)
- [ ] Refactor session management out of security.py
- [ ] Update all imports across application
- [ ] Verify tests still pass

**Files to create/modify:**
- `cloudserver/app/core/passwords/__init__.py` (NEW)
- `cloudserver/app/core/passwords/hashing.py` (NEW)
- `cloudserver/app/core/passwords/validation.py` (NEW)
- `cloudserver/app/core/csrf/__init__.py` (NEW)
- `cloudserver/app/core/csrf/tokens.py` (NEW)
- `cloudserver/app/core/auth/__init__.py` (NEW)
- `cloudserver/app/core/auth/lockout.py` (NEW)
- `cloudserver/app/core/security.py` (REFACTOR - remove decomposed functions)
- All importing modules (MODIFY imports)

**Testing:**
```bash
cd cloudserver
./run_tests.sh tests/security/  # All security tests should pass
```

---

### ✅ 6.2 - Add Database Replication (2-3 hours planning, variable implementation)
**Status:** Not Started
**Risk:** HIGH - No disaster recovery for database
**Impact:** Data loss if primary database fails

**Tasks:**
- [ ] Research PostgreSQL replication options:
  - [ ] Streaming replication (built-in)
  - [ ] pgBouncer for connection pooling + failover
  - [ ] Patroni for automatic failover
- [ ] Update docker-compose with replica service
- [ ] Update application connection string to use pgBouncer
- [ ] Test failover scenario (stop primary, verify replica takes over)
- [ ] Document recovery procedures in OPERATIONS.md
- [ ] Add monitoring/alerting for replication lag

**Files to create/modify:**
- `cloudserver/docker-compose.yml` (MODIFY - add postgres-replica)
- `cloudserver/pgbouncer.ini` (NEW - if using pgBouncer)
- `cloudserver/.env.example` (UPDATE - mention replica config)
- `cloudserver/OPERATIONS.md` (DOCUMENT - replication setup)

**Testing:**
```bash
docker-compose up
# Write data to primary
curl -X POST http://localhost:22557/api/upload ...

# Check replica has the data
docker-compose exec postgres-replica psql -U modemcheck -c "SELECT COUNT(*) FROM modem_checks"

# Stop primary
docker-compose stop postgres

# Verify replica becomes primary (via pgBouncer)
curl -X POST http://localhost:22557/api/upload ...  # Should work via replica
```

---

### ✅ 7.2 - Enhance Health Checks (1-2 hours)
**Status:** Not Started
**Risk:** MEDIUM - Minimal health checks miss cascading failures
**Impact:** Service appears healthy but is actually degraded

**Tasks:**
- [ ] Update PostgreSQL health check to verify connectivity
- [ ] Update Redis health check to verify PING
- [ ] Update API health check to:
  - [ ] Connect to database
  - [ ] Connect to Redis
  - [ ] Verify required tables exist
- [ ] Add liveness probe (quick check)
- [ ] Add readiness probe (full check)
- [ ] Document health check endpoints

**Files to create/modify:**
- `cloudserver/docker-compose.yml` (MODIFY - enhance healthchecks)
- `cloudserver/app/main.py` (MODIFY - add /health and /ready endpoints)
- `cloudserver/OPERATIONS.md` (DOCUMENT - health checks)

**Testing:**
```bash
docker-compose up

# Test liveness
curl http://localhost:22557/health
# Response: {status: "healthy"}

# Test readiness
curl http://localhost:22557/ready
# Response: {ready: true, database: ok, redis: ok}

# Stop Redis
docker-compose stop redis

# Readiness should now fail
curl http://localhost:22557/ready
# Response: {ready: false, database: ok, redis: failed}
```

---

### ✅ 7.3 - Create Production Deployment Guide (1-2 hours)
**Status:** Not Started
**Risk:** MEDIUM - Operators lack clear deployment procedure
**Impact:** Incorrect deployment, security misconfigurations

**Tasks:**
- [ ] Create `DEPLOYMENT.md` with:
  - [ ] System requirements
  - [ ] Pre-deployment checklist
  - [ ] Step-by-step deployment procedure
  - [ ] Post-deployment verification
  - [ ] Security hardening checklist
  - [ ] Performance tuning guidance
  - [ ] Backup/restore procedures
  - [ ] Monitoring setup
  - [ ] Troubleshooting guide
- [ ] Create `.env.example` with all required variables
- [ ] Create `docker-compose.prod.yml` with production settings
- [ ] Create health check monitoring script

**Files to create/modify:**
- `cloudserver/DEPLOYMENT.md` (NEW)
- `cloudserver/.env.example` (CREATE if missing, or ENHANCE)
- `cloudserver/docker-compose.prod.yml` (NEW - production config)
- `cloudserver/monitoring/health-check.sh` (NEW - monitoring script)

**Testing:**
```bash
# Dry run: follow DEPLOYMENT.md on clean server
# Verify all steps are clear and achievable
# Verify post-deployment verification passes
```

---

## Phase 3: Medium Priority Issues (Month 2)

### ✅ 1.1 - Fix Circular Dependencies (2-3 hours)
**Status:** Not Started
**Risk:** MEDIUM - Code quality, maintainability
**Impact:** Difficult to understand dependency flow, hard to refactor

**Tasks:**
- [ ] Map current dependency graph
- [ ] Identify circular dependencies
- [ ] Refactor to eliminate cycles
- [ ] Document dependency rules in ARCHITECTURE.md

---

### ✅ 5.1 - Separate Redis Databases (1-2 hours)
**Status:** Not Started
**Risk:** LOW - Operational clarity
**Impact:** Difficult to manage different data types

**Tasks:**
- [ ] Create `app/core/redis_databases.py`
- [ ] Separate databases:
  - DB 0: Sessions (critical, replicated)
  - DB 1: Rate limiting (transient)
  - DB 2: Caches (transient)
  - DB 3: Anomaly logs (persistent)
- [ ] Update code to use appropriate database
- [ ] Document database separation

---

### ✅ 9.1 - Add Distributed Tracing (2-3 hours)
**Status:** Not Started
**Risk:** LOW - Debugging capability
**Impact:** Difficult to trace requests across client-server

**Tasks:**
- [ ] Add request ID to Go client requests
- [ ] Add request ID to FastAPI logging
- [ ] Correlate logs across client/server
- [ ] Add X-Trace-ID header

---

## Phase 4: Low Priority Issues (Month 2+)

### 1.3, 1.4, 2.2, 3.1, 3.3, 4.2, 5.2, 5.3, 6.3, 7.1, 9.2

These are quality improvements that don't block functionality.

---

## Testing Strategy

### Unit Tests
- Repository tests (mock database)
- Configuration validation tests
- Password hashing tests
- Session storage tests

### Integration Tests
- Redis connectivity failure scenarios
- Database fallback scenarios
- Session creation and verification
- Authentication flow

### End-to-End Tests
- Full upload flow with Redis available
- Full upload flow with Redis down (fallback)
- Login flow with Redis available
- Login flow with Redis down (fallback)

### Deployment Tests
- Health checks succeed in clean deployment
- Health checks catch connection failures
- Backup/restore procedures work
- Replication failover works

---

## Success Criteria

### After Phase 1 (Week 1-2)
- [ ] Credentials no longer visible in docker logs
- [ ] Configuration validation fails at startup (not runtime)
- [ ] Tests pass without event loop closure errors
- [ ] Login still works when Redis is down

### After Phase 2 (Week 3-4)
- [ ] All data access uses repositories
- [ ] Security module decomposed into focused modules
- [ ] Database replication documented and working
- [ ] Health checks verify all dependencies
- [ ] Deployment guide is comprehensive and tested

### After Phase 3 (Month 2)
- [ ] Dependency graph is acyclic
- [ ] Redis databases are properly separated
- [ ] Requests can be traced from client to server

---

## Timeline Estimate

| Phase | Duration | Issues | Start Date | End Date |
|-------|----------|--------|-----------|----------|
| 1 | 1-2 weeks | 8.2, 8.1, 4.1, 6.1 | Week 1 | Week 2 |
| 2 | 2-3 weeks | 3.2, 1.2, 6.2, 7.2, 7.3 | Week 3 | Week 5 |
| 3 | 2-3 weeks | 1.1, 5.1, 9.1 | Week 6 | Week 8 |
| 4 | As-needed | Low priority items | Week 8+ | Ongoing |

**Total estimated effort:** 30-35 developer hours over 8 weeks

---

## Metrics & Monitoring

### Before
- No structured logging
- No distributed tracing
- Redis downtime = complete outage
- Configuration errors discovered at runtime

### After
- Structured JSON logs for automated analysis
- Request IDs correlate logs across services
- Service continues with PostgreSQL fallback when Redis down
- Configuration validated at startup (fail-fast)
- Replication ensures data durability

---

## Related Documentation

- **ARCHITECTURE_REVIEW.md** - Detailed analysis of each issue
- **ARCHITECTURE_FIXES_GUIDE.md** - Code examples for implementing fixes
- **CLAUDE.md** - Project overview and architecture patterns
- **OPERATIONS.md** - Operational procedures (to be created)
- **DEPLOYMENT.md** - Deployment guide (to be created)

---

## Questions for Team

1. **Database replication:** Will you use streaming replication or managed PostgreSQL?
2. **Monitoring:** Will you use Prometheus, DataDog, or custom monitoring?
3. **Logging aggregation:** Will logs be forwarded to ELK, Datadog, or stored locally?
4. **Timeline:** Can we start Phase 1 this sprint or need to plan for next quarter?
5. **Testing:** Do you have staging environment to test changes before production?

---

## Sign-Off

**Reviewed by:** Architecture Review Process
**Date:** 2025-11-17
**Status:** Ready for Implementation

Once you're ready to start Phase 1, see **ARCHITECTURE_FIXES_GUIDE.md** for detailed implementation steps with code examples.
