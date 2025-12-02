# CLAUDE.md

ModemCheck: cross-platform cable modem diagnostic tool with cloud storage.

## Quick Reference

```bash
# Build
make                     # Cross-compile + sign all platforms
make build               # Current platform only

# Test (cloudserver/)
./run_all_tests.sh       # Full suite (~700 tests)
./run_all_tests.sh tests/api/  # Specific directory

# Go client tests
cd modemcheck-client && go test -v ./...
```

## Architecture

| Component | Stack | Key Files |
|-----------|-------|-----------|
| **Client** | Go | `main.go`, `cloud_client.go`, `updater.go`, `diagnostics.go` |
| **Server** | FastAPI + PostgreSQL + Redis + nginx | `app/routers/`, `app/core/`, `app/models/` |

**Client:** Implements `ModemScraper` interface (Login, GetMAC, GetData, ClearFEC, GetModemType). Auto-detects modem at 192.168.100.1, 192.168.0.1, 10.0.0.1, 172.20.0.1.

**Server Flow:** HTTP → FastAPI → Pydantic → PostgreSQL JSONB → JSON response

## Security

| Feature | Implementation |
|---------|----------------|
| **Uploads** | HMAC-SHA256 (`X-Request-Timestamp`, `X-Request-Signature`), API key + Redis cache |
| **Auth** | Argon2id (64MB/3iter), Redis sessions (1hr), device fingerprinting, lockout (5 fails→30min) |
| **RBAC** | basic (view), elevated (+API keys, logs), admin (+users, delete, audit) |
| **Rate limits** | IP: 30/min auth, 60/min upload, 300/sec API; User: 100/hr |
| **Auto-update** | Ed25519/Minisign, atomic rename, auto-rollback. Channels: stable/beta/test |

## Client CLI

`-a` address, `-c` config, `-s` server, `-p` port, `-k` apikey, `-q` quiet, `-l` nologs, `-x` xfinitypassword, `-n` nospeedtest, `--version`

**Config:** `SpeedTestInterval` (N=every Nth check), upload queue at `.upload_queue.json` (max 100, FIFO, 14-day expiry)

**IP Detection (diagnostics.go):** ip-api.com → ipapi.co → ipify.org (3-tier fallback)

## Config Management (v7.0+)

Server-side client config with encryption. Modes: `one_time` (client can modify), `locked` (server enforces).

Files: Client `config_sync.go`, `config_state.go` | Server `app/routers/config.py`, `app/core/config_*.py`

API: `GET/PUT /api/admin/configs/{api_key}/{modem_id}`, `/rollback/{version}`, `/history`

## Testing

**Environment:** Ports 22560/23894 (test) vs 22557/23890 (prod), DB `modemcheck_test`, `TESTING=true` disables rate limiting

**Coverage:** `./run_unit_coverage.sh`, `./run_e2e_coverage.sh`, `./run_combined_coverage.sh`

## Database Schema

| Table | Key Columns |
|-------|-------------|
| `modem_checks` | id, modem_id, check_time, filename, full_data (JSONB), 40+ extracted metrics |
| `users` | username, password_hash, role, created_at, last_login |
| `api_keys` | key_hash, name, created_at, expires_at, is_active |
| `audit_logs` | user_id, action, resource, details, ip_address, timestamp |

## Key Files

**Security-critical:** `.signing-keys/minisign.key` (BACKUP!), `cloudserver/.env` (chmod 600)

**Server:** `app/core/errors.py`, `app/core/auth.py`, `app/core/security.py`, `app/routers/upload.py`

**Client:** `diagnostics.go`, `cloud_client.go`, `updater.go`

**Ops:** `backup-all.sh`, `restore-database.sh`, `update-db-password.sh`

## Cron Jobs (Production)

```
0 2 1 * *       create_audit_partition.sh      # Monthly
0 3 1 1,4,7,10 * cleanup_old_partitions.sh    # Quarterly
15 * * * *      cleanup_nonces.py              # Hourly
```

## Troubleshooting

**Redis:** Critical (no fallback). DB 0: sessions/CSRF/logins, DB 1: rate limiting

**Signing:** `sign-all.sh` removes old `.minisig` before re-signing

**Version:** Makefile `VERSION` → `-ldflags "-X main.Version=$(VERSION)"`

## Docker Resources

API: 2 CPU/2GB | Postgres: 2 CPU/2GB | Redis: 0.5 CPU/512MB
