# ModemCheck Performance Analysis Report

This document details discovered performance issues, their impact, and suggested optimizations.

## Summary

The ModemCheck codebase is well-architected overall with good async patterns and most database queries optimized. However, several optimization opportunities exist across database operations, resource management, and network efficiency.

---

## Critical Issues (High Impact)

### 1. **Duplicate Database Queries in Pagination Endpoints**

**Location:** `/home/adamkl/projects/modemcheck/cloudserver/app/routers/db_api.py:116-124`

**Issue:** The `/api/db/list_checks` endpoint executes two separate queries to get the same data:
1. First query (lines 104-110): Fetches all checks with `limit=1000`
2. Second query (lines 116-122): Counts total checks (identical WHERE clause)

**Performance Impact:**
- Executing nearly identical queries twice increases database load
- On large datasets (10,000+ records), this doubles execution time for pagination
- Estimated performance loss: 50-100% slower pagination for large datasets

**Suggested Optimization:**
Use a single query with `SELECT ... WITH COUNT(*) OVER()` window function to fetch data and count in one operation:

```python
# Combine data fetch and total count in single query
query = select(
    ModemCheck,
    func.count().over().label('total_count')
).where(
    and_(
        ModemCheck.modem_id == modem_id,
        ModemCheck.check_time >= start_dt,
        ModemCheck.check_time <= end_dt
    )
).order_by(ModemCheck.check_time.desc()).limit(limit)

result = await db.execute(query)
rows = result.all()
total_count = rows[0][1] if rows else 0  # Get total from window function
checks = [row[0] for row in rows]
```

**Estimated Improvement:** 50-70% faster pagination queries (single DB round-trip)

---

### 2. **Similar Duplicate Counting in `get_all_checks` Endpoint**

**Location:** `/home/adamkl/projects/modemcheck/cloudserver/app/routers/db_api.py:209-219`

**Issue:** Same as issue #1 - separate data fetch and count queries

**Performance Impact:**
- Doubles database round trips for bulk download operations
- Estimated performance loss: 50-100% slower bulk operations

**Suggested Optimization:** Apply same window function approach as Issue #1

**Estimated Improvement:** 50-70% faster bulk query operations

---

### 3. **Inefficient Bulk Upload: Missing N+1 Query Prevention**

**Location:** `/home/adamkl/projects/modemcheck/cloudserver/app/routers/data_mgmt.py:204-215`

**Issue:** The bulk upload endpoint checks for duplicates in a loop:
```python
for file in files:  # ~50 files typical
    # ...
    existing = await db.execute(
        select(ModemCheck).where(...)
    )
```

**Performance Impact:**
- For 50 files, this executes 50 duplicate-check queries
- Each query scans the entire database for matching records
- Estimated performance loss: Bulk upload takes 50 sequential DB queries instead of 1

**Suggested Optimization:**
Batch the duplicate checks into a single query before processing files:

```python
# Load all filenames to check in single query
filenames_to_check = [f.filename for f in files]
existing_query = select(ModemCheck.filename).where(
    ModemCheck.filename.in_(filenames_to_check)
)
result = await db.execute(existing_query)
existing_files = {row[0] for row in result}

# Then check duplicates in memory (O(1) lookup)
for file in files:
    if file.filename in existing_files:
        results["failed"] += 1
        continue
```

**Estimated Improvement:** 95%+ faster bulk uploads (from 50 queries to 1)

---

## High-Priority Issues

### 4. **Unbounded Query Result Set in List Operations**

**Location:** `/home/adamkl/projects/modemcheck/cloudserver/app/routers/db_api.py:43-70` (list_modems)

**Issue:** The `list_modems` endpoint retrieves ALL modems without pagination:
```python
query = select(
    ModemCheck.modem_id,
    ...
).group_by(ModemCheck.modem_id, ModemCheck.modem_type)
# No limit() applied
```

**Performance Impact:**
- With 100,000+ modem checks from 1,000+ modems, this loads entire dataset to memory
- Memory spike of 1-10MB per request at scale
- Can cause OOM crashes if dataset grows significantly
- Slow JSON serialization of massive response payload

**Suggested Optimization:**
Add pagination to list_modems:

```python
@router.get("/list_modems", response_model=ModemListResponse)
async def list_modems(
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, le=1000),
    session_data: dict = Depends(require_authenticated_user),
    db: AsyncSession = Depends(get_db)
):
    query = select(...).group_by(...).offset(offset).limit(limit)
    # Add total count query for pagination metadata
```

**Estimated Improvement:** Constant memory usage regardless of dataset size; 10-100x faster response times

---

### 5. **Admin API: Inefficient Key Lookup (Already Fixed But Verify)**

**Location:** `/home/adamkl/projects/modemcheck/cloudserver/app/routers/admin.py:154-162`

**Note:** This appears to be already optimized with SQL substring functions, but verify:

The `reveal_api_key` endpoint uses:
```python
func.substring(APIKey.api_key, 1, 4) == first_part,
func.right(APIKey.api_key, 4) == last_part
```

**Potential Issue:** If no index exists on API key columns, these pattern matches will require full table scans on large key sets (thousands of keys).

**Suggested Verification:**
Check that these columns have indexes or that API key count is small (<1000). If needed, add index:

```python
Index('idx_api_key_pattern', APIKey.api_key)
```

---

### 6. **Synchronous File I/O in Async Context (Go Client)**

**Location:** `/home/adamkl/projects/modemcheck/modemcheck-client/cloud_client.go:158-169`

**Issue:** The upload function reads the entire file into memory at once:
```go
fileContents, err := io.ReadAll(file)  // Reads entire file to memory
```

**Performance Impact:**
- For 10MB file uploads, allocates 10MB in memory
- With concurrent uploads (future enhancement), memory usage multiplies
- No streaming/chunking for large files
- Slow network will block memory allocation during slow reads

**Suggested Optimization:**
For large files (>1MB), implement streaming:

```go
// Add streaming multipart writer
pr, pw := io.Pipe()
go func() {
    defer pw.Close()
    io.Copy(pw, file)  // Stream instead of Read
}()

// Then write pr to multipart form
```

**Estimated Improvement:** Constant memory usage regardless of file size; 20-40% faster upload for large files

---

## Medium-Priority Issues

### 7. **JSON Unmarshaling in Upload Handler**

**Location:** `/home/adamkl/projects/modemcheck/cloudserver/app/routers/upload.py:282-300`

**Issue:** Full JSON parsing happens even for basic validation:
```python
json_data = json.loads(file_data.decode('utf-8'))  # Lines 283-300
```

Then extraction happens after database insert would fail anyway.

**Performance Impact:**
- Full JSON decode before any validation (modem_id, filename)
- If JSON is invalid, wasted CPU cycles on earlier validation steps
- Estimated 10-20ms per upload on average-sized JSON

**Suggested Optimization:**
Validate input fields BEFORE parsing full JSON:

```python
# Move this earlier (before json.loads):
if not modem_id or not filename:
    raise HTTPException(...)

# Then parse JSON
json_data = json.loads(file_data.decode('utf-8'))
```

**Estimated Improvement:** 10-20% faster bad-request rejection

---

### 8. **Inefficient API Key Validation in Upload**

**Location:** `/home/adamkl/projects/modemcheck/cloudserver/app/routers/upload.py:71-108`

**Issue:** The `validate_and_get_api_key` function has suboptimal error tracking:
```python
if is_valid:
    if await APIKeyCache.get_cached_keys() is not None:
        api_key_cache_stats.record_hit()
    else:
        api_key_cache_stats.record_miss()
```

This queries cache AGAIN after validation to determine hit/miss status.

**Performance Impact:**
- Double Redis query: one for validation, one for stats tracking
- On high-frequency uploads (1000/min), this wastes 20-30ms/sec
- Estimated 2-5% performance loss

**Suggested Optimization:**
Have cache validation function return hit/miss status:

```python
@staticmethod
async def validate_api_key_cached(
    api_key: str,
    db_fallback_func
) -> Tuple[bool, Optional[str], bool]:  # Added cache_hit return
    cached_keys = await APIKeyCache.get_cached_keys()
    if cached_keys is not None:
        # ... validation ...
        return is_valid, key_name, True  # cache_hit=True
    # ... db fallback ...
    return is_valid, key_name, False  # cache_hit=False
```

**Estimated Improvement:** 2-5% faster API validation

---

### 9. **Excessive Session Fingerprinting Checks on Every Request**

**Location:** `/home/adamkl/projects/modemcheck/cloudserver/app/core/session_security.py`

**Issue:** Session fingerprinting (device fingerprinting verification) is checked on EVERY authenticated request. This includes:
- SHA256 hash computation of user-agent + IP
- Redis lookup for stored fingerprint
- Comparison and logging of mismatches

**Performance Impact:**
- 5-10ms overhead per authenticated request
- On database viewer with 100 API calls per session, adds 0.5-1s latency
- Scales poorly with concurrent users

**Suggested Optimization:**
Cache fingerprint verification results per session:

```python
# Store verification result in session with short TTL
session_data['fingerprint_verified_at'] = now
session_data['fingerprint_verified_ttl'] = 300  # 5 minutes

# Only reverify if TTL expired
if time.time() - session_data.get('fingerprint_verified_at', 0) < 300:
    return  # Skip verification
```

**Estimated Improvement:** 5-10ms saved per request (especially on bulk operations)

---

### 10. **Bulk Download Creates Large In-Memory ZIP**

**Location:** `/home/adamkl/projects/modemcheck/cloudserver/app/routers/data_mgmt.py:309-318`

**Issue:** The bulk download endpoint builds entire ZIP in memory before sending:
```python
zip_buffer = BytesIO()  # In-memory buffer
with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
    for check in checks:  # Up to 10,000 records
        json_content = json.dumps(check.full_data, indent=2)
        zip_file.writestr(filename, json_content)
```

**Performance Impact:**
- For 10,000 records with 100KB each = 1GB in memory
- Can cause OOM crash on systems with 2GB limit (Docker compose)
- Entire ZIP held in memory before streaming starts
- No backpressure control

**Suggested Optimization:**
Stream ZIP to response instead:

```python
async def streaming_generator():
    with zipfile.ZipFile(...) as zip_file:
        for check in checks:
            json_content = json.dumps(check.full_data)
            zip_file.writestr(filename, json_content)
            # Yield chunks as they're created

return StreamingResponse(streaming_generator(), media_type="application/zip")
```

**Estimated Improvement:** Memory usage scales with buffer size (~5MB) instead of total data size; prevents OOM crashes

---

## Low-Priority Issues (Optimization Opportunities)

### 11. **Redis Database Separation Can Be Optimized**

**Location:** `/home/adamkl/projects/modemcheck/cloudserver/docker-compose.yml:7`

**Issue:** Current configuration uses single Redis instance for sessions (DB 0) and rate limiting (DB 1).

**Current State:** Single 256MB Redis instance
- Sessions + rate limiting share memory
- No separate monitoring per feature
- Memory pressure from one feature affects the other

**Suggested Optimization (Optional):**
For deployments with >1000 concurrent users:
- Use separate Redis instances for sessions (persistent) and rate limiting (ephemeral)
- Allows independent resource tuning
- Can evict rate limiting data without affecting sessions

**Estimated Improvement:** More predictable memory behavior; better isolation under load

---

### 12. **HTTP Response Body Reading Inefficiency in IP Detection**

**Location:** `/home/adamkl/projects/modemcheck/modemcheck-client/diagnostics.go:603`

**Issue:** Multiple IP detection services create HTTP clients with different settings:
- ipapi.co uses `https://` (line 530)
- ip-api.com uses `http://` (line 560)
- ipify uses `https://` (line 585)

While there's a shared `ipDetectionHTTPClient`, each service makes separate requests in sequence (not parallel).

**Performance Impact:**
- Sequential calls: 3-5 seconds for full IP detection fallback chain
- Could be parallelized with goroutines
- Estimated: 5-10 seconds serial vs 2-3 seconds parallel

**Suggested Optimization:**
Parallelize IP service calls with goroutines:

```go
func (m *ModemCheck) GetPublicIPInfo(data *scraper.ModemData) {
    resultChan := make(chan ipResult, 3)

    go func() {
        if m.tryIPAPI(data) {
            resultChan <- ipResult{success: true, ...}
        }
    }()
    // Similar for other services

    // Wait for first success
    for i := 0; i < 3; i++ {
        result := <-resultChan
        if result.success { break }
    }
}
```

**Estimated Improvement:** 50-70% faster IP detection (2-3 seconds vs 5-10 seconds)

---

### 13. **Metric Extraction: Redundant List Iterations**

**Location:** `/home/adamkl/projects/modemcheck/cloudserver/app/core/metric_extraction.py:63-76`

**Issue:** The metric extraction iterates through downstream channels multiple times:
```python
# First iteration for downstream power
powers = [safe_float(ch.get('power')) for ch in downstream['channels'] ...]

# Second iteration for SNR
snrs = [safe_float(ch.get('snr')) for ch in downstream['channels'] ...]

# Third iteration for errors
for ch in downstream['channels']:
    total_corrected += safe_int(ch.get('correcteds')) or 0
```

For 32 downstream channels (typical DOCSIS 3.1), this is 3+ iterations instead of 1.

**Performance Impact:**
- Estimated 1-2ms per upload (marginal at small scale)
- At 1000 uploads/min, adds 16-32ms/sec

**Suggested Optimization:**
Single-pass extraction:

```python
powers = []
snrs = []
total_corrected = 0
total_uncorrected = 0

for ch in downstream['channels']:
    powers.append(safe_float(ch.get('power')))
    snrs.append(safe_float(ch.get('snr')))
    total_corrected += safe_int(ch.get('correcteds')) or 0
    total_uncorrected += safe_int(ch.get('uncorrectables')) or 0
```

**Estimated Improvement:** 2-5% faster metric extraction

---

### 14. **Database Connection Pool May Be Undersized**

**Location:** `/home/adamkl/projects/modemcheck/cloudserver/app/core/database.py:50-52`

**Issue:** Current settings (default from SQLAlchemy):
- `pool_size=5` (connections in pool)
- `max_overflow=10` (additional connections allowed)

For 4 Gunicorn workers with 100+ concurrent requests, this may be insufficient.

**Current Configuration:**
- 5 base connections + 10 overflow = 15 total
- 4 workers × 100 requests/sec = 400 concurrent requests
- Only 15 connections available → connection wait/timeout

**Performance Impact:**
- Under high load, requests queue waiting for database connections
- Can cause 429 (Too Many Requests) or timeout errors
- Difficult to debug as it appears as slow response time

**Suggested Optimization:**
Increase pool size for production deployments:

```python
pool_size=20,           # Increase to 20
max_overflow=30,        # Increase to 30
pool_timeout=30,        # Increase timeout
```

**Estimated Improvement:** Reduced connection wait times under peak load; more consistent response times

---

## Resource Limit Recommendations

### Docker Compose Resource Configuration

**Current Limits** (from docker-compose.yml):
- API container: 2.0 CPU, 2GB RAM
- PostgreSQL: 2.0 CPU, 2GB RAM
- Redis: 0.5 CPU, 512MB RAM

**Observations:**
1. API container has 2GB limit but may need 2-4GB under sustained 1000 req/min load
2. PostgreSQL 2GB is reasonable for typical datasets (<100GB)
3. Redis 256MB maxmemory with LRU eviction is good baseline

**Recommendation for Scaling:**
- Keep API at 2GB-4GB depending on batch sizes
- Monitor for OOM: `docker stats modemcheck-cloud`
- If OOM occurs, increase memory and add bulk operation streaming (Issue #10)

---

## Caching Opportunities

### 1. **Modem Type Distribution Caching**

The `list_modems` endpoint recalculates GROUP BY aggregates on every request. With 100K records, this is expensive.

**Suggested:** Cache results for 5-10 minutes:

```python
# Check cache first
cached = await redis.get("modems:summary")
if cached:
    return json.loads(cached)

# Fetch and cache for 10 minutes
result = await db.execute(query)
await redis.setex("modems:summary", 600, json.dumps(result))
```

**Estimated Improvement:** 100-500x faster responses for frequently accessed list

---

### 2. **Signal Quality Summary Caching**

Dashboard queries for average SNR, power levels across all modems.

**Suggested:** Pre-compute and cache metrics:
```python
# Weekly background job to cache aggregated metrics
cached_metrics = {
    "avg_downstream_snr": db.query(avg(avg_downstream_snr)),
    "avg_downstream_power": db.query(avg(avg_downstream_power)),
    # ... etc
}
await redis.setex("metrics:summary", 3600, json.dumps(cached_metrics))
```

---

## Summary of Estimated Performance Improvements

| Issue | Current | After Optimization | Improvement |
|-------|---------|-------------------|------------|
| Duplicate pagination queries | 2 DB queries | 1 query | 50-70% faster |
| Bulk upload N+1 | 50 queries | 1 query | 95% faster |
| Unbounded list_modems | OOM risk | Paginated | Constant memory |
| Bulk download in-memory ZIP | 1GB RAM | 5MB streaming | OOM prevention |
| Session fingerprint check | 5-10ms/req | Cached (5min) | 5-10ms saved per req |
| IP detection serial calls | 5-10s | Parallelized | 50-70% faster |
| API key validation | 2 Redis calls | 1 call + return hint | 2-5% faster |
| **Total for typical workflow** | - | - | **30-50% faster** |

---

## Implementation Priority

### Phase 1 (Immediate - High Impact)
1. Fix duplicate pagination queries (Issues #1, #2)
2. Fix bulk upload N+1 (Issue #3)
3. Add pagination to list_modems (Issue #4)

### Phase 2 (Short-term - Stability)
4. Stream bulk downloads (Issue #10)
5. Parallelize IP detection (Issue #12)
6. Tune database connection pool (Issue #14)

### Phase 3 (Medium-term - Polish)
7. Cache session fingerprint verification (Issue #9)
8. Optimize metric extraction (Issue #13)
9. Implement Redis caching for modem summaries

---

## Testing Recommendations

After implementing optimizations, run load tests:

```bash
# Install locust for load testing
pip install locust

# Run 100 concurrent users for 5 minutes
locust -f locustfile.py -u 100 -r 10 -t 5m
```

Monitor:
- Response times (target: <100ms for API calls)
- Database connection pool usage
- Redis memory usage
- CPU utilization
- Memory usage

---

## Notes

- This analysis is based on code inspection and does not include actual profiling data
- Actual improvements will vary based on dataset size and access patterns
- All suggested changes maintain backward compatibility
- Implement changes incrementally and measure impact with load testing
