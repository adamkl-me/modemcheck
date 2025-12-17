# ModemCheck Cloud Server - Operations Guide

Complete guide for operating and maintaining the ModemCheck cloud server in production.

## Table of Contents

1. [Backup and Restore](#backup-and-restore)
2. [Audit Log Management](#audit-log-management)
3. [Security Monitoring](#security-monitoring)
4. [Performance Tuning](#performance-tuning)
5. [Troubleshooting](#troubleshooting)
6. [Disaster Recovery](#disaster-recovery)

---

## Backup and Restore

### Automated Daily Backups

**Setup:**
```bash
# Create backup directories
mkdir -p backups/postgres backups/redis logs

# Set up cron (see cron-example.txt)
crontab -e

# Add this line for daily backups at 2 AM:
0 2 * * * cd /path/to/cloudserver && ./backup-all.sh --verify >> logs/backup.log 2>&1
```

**Backup scripts:**
- `backup-all.sh` - Complete backup (PostgreSQL + Redis)
- `backup-database.sh` - PostgreSQL only
- `backup-redis.sh` - Redis only

**Manual backup:**
```bash
# Full backup with verification
./backup-all.sh --verify

# PostgreSQL only (with custom retention)
./backup-database.sh --retention 60 --verify

# Redis only
./backup-redis.sh --retention 60
```

**Backup retention:**
- Default: 30 days
- Configurable via `--retention` flag
- Automatic cleanup of old backups

### Restore Procedures

**Restore from most recent backup:**
```bash
# Automatic (finds latest backup)
./restore-database.sh --latest

# Manual (specify backup file)
./restore-database.sh backups/postgres/modemcheck_20250117_020000.sql.gz
```

**Safety features:**
- Creates pre-restore backup automatically
- Requires confirmation (use `--force` for automation)
- Verifies table count after restore

**Disaster recovery:**
```bash
# 1. Restore PostgreSQL database
./restore-database.sh --latest

# 2. Restart containers to pick up new database
docker compose restart

# 3. Verify services are healthy
curl http://localhost:22557/health

# 4. Check logs for errors
docker logs modemcheck-cloud-v2
```

---

## Audit Log Management

### Retention Policy

**Default retention:** 90 days for both user activity and client submission logs

**Automated cleanup:**
```bash
# Add to cron (weekly on Sunday at 3 AM)
0 3 * * 0 cd /path/to/cloudserver && python3 cleanup-audit-logs.py >> logs/cleanup.log 2>&1
```

**Manual cleanup:**
```bash
# Use default 90-day retention
python3 cleanup-audit-logs.py

# Custom retention periods
python3 cleanup-audit-logs.py --user-retention 60 --client-retention 120

# Dry run (show what would be deleted)
python3 cleanup-audit-logs.py --dry-run

# Statistics only (no deletion)
python3 cleanup-audit-logs.py --stats-only
```

**Output example:**
```
======================================================================
ModemCheck Audit Log Cleanup
======================================================================
Current Audit Log Statistics:

User Activity Logs:
  Total count: 15,432
  Oldest entry: 2024-10-15T10:23:45
  Newest entry: 2025-01-17T14:32:10
  Age: 94 days

Cleanup Progress:
User Activity Logs:
  Total before: 15,432
  Deleted: 2,341
  Retained: 13,091

Total deleted: 2,341
✅ Cleanup successful
```

---

## Security Monitoring

### Enhanced Security Features

**Per-user rate limiting:**
- Prevents abuse across multiple IPs
- Default: 100 requests/hour per user
- Implemented in `app/core/enhanced_limiter.py`

**Session security:**
- Device fingerprinting (user-agent + IP tracking)
- Concurrent session limits (max 5 per user)
- Session anomaly detection
- Automatic termination of oldest sessions

**Monitoring session activity:**
```python
# Via Python console or admin endpoint
from app.core.session_security import get_user_active_sessions

sessions = await get_user_active_sessions("admin")
# Returns list of active sessions with IP, user-agent, timestamps
```

**Checking for anomalies:**
```python
from app.core.session_security import get_session_anomalies

anomalies = await get_session_anomalies("admin", days=7)
# Returns list of security events (IP changes, user-agent mismatches, etc.)
```

### Security Headers

All responses include comprehensive security headers:
- **HSTS**: Enforces HTTPS for 1 year
- **CSP**: Content Security Policy (XSS protection)
- **X-Frame-Options**: Prevents clickjacking
- **X-Content-Type-Options**: Prevents MIME sniffing

**Verify headers:**
```bash
curl -I https://api.modemcheck.cloud/health
```

### Pre-commit Secret Detection

**Install hooks:**
```bash
pip install pre-commit
pre-commit install
```

**Run manually:**
```bash
# Check all files
pre-commit run --all-files

# Update secret baseline
detect-secrets scan > .secrets.baseline
```

### Dependency Scanning

**GitHub Actions:** Runs automatically on push, PR, and weekly schedule

**Manual scan:**
```bash
cd cloudserver
./scan-dependencies.sh
```

**Review reports:**
- `pip-audit-report.json` - Vulnerability details
- `safety-report.json` - Security advisories
- `bandit-report.json` - Code security issues

---

## Performance Tuning

### Database Optimization

**Connection pooling:**
```python
# In app/core/database.py
engine = create_async_engine(
    DATABASE_URL,
    pool_size=20,        # Concurrent connections
    max_overflow=10,     # Additional connections when needed
    pool_pre_ping=True,  # Verify connections before use
)
```

**Scaling guidelines:**
- **Low traffic (< 50 concurrent users):** pool_size=10, max_overflow=5
- **Medium traffic (50-200 users):** pool_size=20, max_overflow=10 (default)
- **High traffic (200-1000 users):** pool_size=50, max_overflow=25
- **Very high traffic (> 1000 users):** Consider read replicas and connection pooler (PgBouncer)

**Monitoring pool exhaustion:**
```bash
# Check active connections
docker exec modemcheck-postgres psql -U modemcheck -c "SELECT count(*) FROM pg_stat_activity WHERE datname='modemcheck'"

# Check for waiting connections
docker exec modemcheck-postgres psql -U modemcheck -c "SELECT wait_event_type, count(*) FROM pg_stat_activity WHERE datname='modemcheck' GROUP BY wait_event_type"
```

**Query optimization:**
- Use indexes on frequently queried columns
- Monitor slow queries with `EXPLAIN ANALYZE`
- Use JSONB indexes for modem_checks queries

### Redis Configuration

**Memory management:**
- Max memory: 512MB (configurable in docker-compose.yml)
- Eviction policy: allkeys-lru (least recently used)
- Session TTL: 1 hour (configurable in .env)

**Failback behavior:**
When Redis is unavailable, the system falls back to an in-memory cache. Be aware of these limitations:

- **Session loss:** Sessions are NOT migrated to in-memory cache. All active user sessions will be lost when Redis fails, requiring users to log in again.
- **Per-worker isolation:** In-memory cache is NOT shared across workers. Each worker process has its own cache, which can cause inconsistent behavior (e.g., a user logged in on worker A won't be authenticated on worker B).
- **Memory limits:** Default 10,000 keys with LRU eviction. Under high load, sessions may be evicted unexpectedly.
- **Recovery:** When Redis recovers, users must log in again (their in-memory sessions won't automatically migrate back to Redis).

**Recommendation:** Monitor Redis health closely and configure alerts for Redis connection failures.

**Monitor Redis:**
```bash
# Check memory usage
docker exec modemcheck-redis-v2 redis-cli INFO memory

# Check key count
docker exec modemcheck-redis-v2 redis-cli DBSIZE

# Monitor commands in real-time
docker exec modemcheck-redis-v2 redis-cli MONITOR
```

### Resource Limits

**Current limits (docker-compose.yml):**
- **modemcheck-api**: 2 CPU / 4GB RAM
- **postgres**: 2 CPU / 2GB RAM
- **redis**: 0.5 CPU / 512MB RAM

**Adjust for your workload:**
```yaml
deploy:
  resources:
    limits:
      cpus: '4.0'      # Increase for high traffic
      memory: 8G
    reservations:
      cpus: '2.0'
      memory: 2G
```

---

## Troubleshooting

### Common Issues

**1. Sessions not persisting**
```bash
# Check Redis connection
docker exec modemcheck-redis-v2 redis-cli PING
# Expected: PONG

# Check session keys
docker exec modemcheck-redis-v2 redis-cli KEYS "session:*"

# Restart Redis if needed
docker compose restart modemcheck-redis-v2
```

**2. Database connection errors**
```bash
# Check PostgreSQL status
docker exec modemcheck-postgres pg_isready
# Expected: accepting connections

# Check database credentials
docker exec modemcheck-postgres psql -U modemcheck -d modemcheck -c "SELECT 1"

# Review logs
docker logs modemcheck-postgres
```

**3. High memory usage**
```bash
# Check container memory usage
docker stats --no-stream

# PostgreSQL memory
docker exec modemcheck-postgres psql -U modemcheck -c "SELECT pg_size_pretty(pg_database_size('modemcheck'))"

# Redis memory
docker exec modemcheck-redis-v2 redis-cli INFO memory | grep used_memory_human
```

**4. Slow API responses**
```bash
# Check application logs for slow queries
docker logs modemcheck-cloud-v2 | grep "slow query"

# Monitor database queries
docker exec modemcheck-postgres psql -U modemcheck -d modemcheck -c "SELECT query, calls, mean_exec_time FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10"

# Check rate limiting
docker exec modemcheck-redis-v2 redis-cli --scan --pattern "user_rate_limit:*"
```

### Health Checks

**API health:**
```bash
curl http://localhost:22557/health
# Expected: {"status":"healthy"}
```

**Database health:**
```bash
docker exec modemcheck-postgres pg_isready
docker exec modemcheck-postgres psql -U modemcheck -d modemcheck -c "SELECT COUNT(*) FROM modem_checks"
```

**Redis health:**
```bash
docker exec modemcheck-redis-v2 redis-cli PING
docker exec modemcheck-redis-v2 redis-cli DBSIZE
```

---

## Disaster Recovery

### Recovery Scenarios

**1. Complete system failure**
```bash
# Stop all containers
docker compose down

# Restore from latest backup
./restore-database.sh --latest

# Start containers
docker compose up -d

# Verify health
curl http://localhost:22557/health
```

**2. Database corruption**
```bash
# Create emergency backup
docker exec modemcheck-postgres pg_dump -U modemcheck modemcheck | gzip > emergency_backup.sql.gz

# Restore from last known good backup
./restore-database.sh backups/postgres/modemcheck_20250116_020000.sql.gz

# Restart services
docker compose restart
```

**3. Lost secrets/credentials**
```bash
# Regenerate secrets
python3 -c "import secrets; print(secrets.token_urlsafe(48))"

# Update .env file
nano .env

# Restart containers (invalidates all sessions)
docker compose down
docker compose up -d

# Force all users to log in again
# Admin must change password on first login
```

**4. Redis data loss**
```bash
# Sessions lost - users must re-login (non-critical)
# Restore Redis from backup if needed
docker cp backups/redis/redis_20250117_020000.rdb modemcheck-redis-v2:/data/dump.rdb
docker compose restart modemcheck-redis-v2
```

### Recovery Time Objectives (RTO)

| Scenario | RTO Target | Notes |
|----------|------------|-------|
| Database restore | < 10 minutes | From latest backup |
| Redis restore | < 2 minutes | Sessions lost, users re-login |
| Complete system rebuild | < 30 minutes | With backups available |
| Secret rotation | < 5 minutes | Invalidates sessions |

### Backup Verification

**Test restore monthly:**
```bash
# 1. Restore to test environment
cd cloudserver
POSTGRES_CONTAINER=test-postgres ./restore-database.sh --latest --force

# 2. Verify table count
docker exec test-postgres psql -U modemcheck -d modemcheck -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'"

# 3. Verify data integrity
docker exec test-postgres psql -U modemcheck -d modemcheck -c "SELECT COUNT(*) FROM modem_checks"
```

---

## Maintenance Checklist

### Daily
- [ ] Check backup success in logs/backup.log
- [ ] Monitor application logs for errors
- [ ] Review failed login attempts

### Weekly
- [ ] Review GitHub Actions security scan results
- [ ] Check audit log cleanup results
- [ ] Monitor disk space usage
- [ ] Review session anomalies

### Monthly
- [ ] Test database restore procedure
- [ ] Update dependencies (security patches)
- [ ] Review and rotate credentials (if needed)
- [ ] Audit user accounts and API keys

### Quarterly
- [ ] Full security audit
- [ ] Performance review and tuning
- [ ] Update all dependencies
- [ ] Credential rotation (90-day policy)
- [ ] Disaster recovery drill

---

## Log Management

### Log File Growth

Application and backup logs can grow significantly in production. Implement log rotation to prevent disk exhaustion.

**Using logrotate (recommended):**
```bash
# Create /etc/logrotate.d/modemcheck
/path/to/cloudserver/logs/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
```

**Docker logging (for container logs):**
```yaml
# In docker-compose.yml
services:
  modemcheck-cloud-v2:
    logging:
      driver: "json-file"
      options:
        max-size: "100m"
        max-file: "5"
```

**Monitoring disk usage:**
```bash
# Check log sizes
du -sh /path/to/cloudserver/logs/

# Watch for disk pressure
df -h /path/to/cloudserver/
```

---

## Client Upload Handling

### Upload Queue Behavior

The Go client maintains an upload queue (`.upload_queue.json`) for failed uploads. Be aware of these performance characteristics:

- **Queue rebuild:** When loading, the entire queue is deserialized (O(n) operation). With maximum 100 entries, this is typically < 100ms.
- **Large queues:** If clients consistently fail to upload, queue processing can slow startup. Maximum queue size is capped at 100 entries (FIFO eviction).
- **Cleanup:** Entries older than 14 days are automatically purged on load.

**Monitoring client queues:**
If users report slow startup, check for large `.upload_queue.json` files (> 100KB indicates issues).

### Binary Size Limits

The upload endpoint enforces file size limits to prevent resource exhaustion:

- **Maximum upload size:** 10MB (configurable via `MAX_UPLOAD_SIZE` in .env)
- **Typical modem check file:** 50-200KB
- **Files exceeding limit:** Return 413 (Request Entity Too Large)

**Adjusting limits:**
```bash
# In .env
MAX_UPLOAD_SIZE=10485760  # 10MB in bytes
```

**Note:** Larger limits increase memory pressure during upload processing. Each upload is fully buffered in memory before validation.

---

## Support

For issues or questions:
- See main project CLAUDE.md for detailed implementation notes
- Review security-scan/ directory for security documentation
- Check GitHub Issues for known problems

**Emergency contacts:**
- Security issues: (configure security contact)
- Escalation: (configure escalation path)
