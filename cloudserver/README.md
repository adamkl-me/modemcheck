# Modem Check Cloud Server

Docker-based cloud server for centralized modem diagnostic data storage and visualization.

**Ports:**
- **22557** - Upload API (HTTPS)
- **23890** - Web Viewer
- **23891** - Admin Dashboard

## Table of Contents
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Admin Dashboard](#admin-dashboard)
- [User Roles & Permissions](#user-roles--permissions)
- [Container Management](#container-management)
- [API Reference](#api-reference)
- [Production Deployment](#production-deployment)
- [Backup & Restore](#backup--restore)
- [Troubleshooting](#troubleshooting)
- [Updating](#updating)

## Quick Start

### 1. Create Volumes and Start

```bash
docker volume create modemcheck-cloud_db
docker volume create modemcheck-cloud_config
docker volume create modemcheck-cloud_redis
cd cloudserver
docker compose up -d
```

This starts two containers:
- `modemcheck-cloud`: nginx + Python CGI application
- `redis`: Session storage for authentication

### 2. Create API Key

Open admin dashboard at `http://localhost:23891` (login: `admin` / `changeme`)

**Using Config Generator (Recommended):**
1. Navigate to "Config Generator" tab
2. Fill in modem settings or configure defaults in "Defaults" sub-tab
3. Click "Generate Key" or select existing API key
4. Download complete `config.json` file

**Manual Creation:**
1. Navigate to "API Keys" tab
2. Enter descriptive name → Click "Create API Key"
3. Copy key immediately (not shown again)

### 3. Test Upload

```bash
./modem-check -config config.json
```

Check the web viewer at `http://localhost:23890` to verify data appeared.

## Architecture

### Components

| Component | Technology | Purpose |
|-----------|------------|---------|
| Web Server | nginx | Serves static files and proxies CGI requests |
| Application | Python 3 CGI | Handles API endpoints and database operations (10 fcgiwrap workers) |
| Database | SQLite (WAL mode) | Stores modem data, users, API keys, audit logs |
| Session Store | Redis | Manages user sessions (12-hour TTL, 256MB max memory) |
| Container | Alpine Linux | Minimal base image with fcgiwrap for CGI |

### Directory Structure

```
/modemcheck-cloud/
├── db-viewer.html          # Web viewer interface
├── db-viewer.js            # Viewer JavaScript
├── admin.html              # Admin dashboard
├── login.html              # Viewer login page
├── admin-login.html        # Admin login page
├── cgi-bin/
│   ├── upload.py           # Upload API endpoint
│   ├── db-api.py           # Database query API
│   ├── auth.py             # Authentication/sessions
│   ├── admin-api.py        # Admin operations
│   ├── user-management.py  # User CRUD operations
│   ├── data-management-api.py # Bulk upload/download/delete
│   ├── db_schema.py        # Main database schema
│   └── audit_schema.py     # Audit logging schema
```

### Data Storage

- **Database**: Docker volume `modemcheck-cloud_db` → `/modemcheck-cloud/data/`
  - `modemcheck.db` - Main modem check data (SQLite WAL mode)
  - `audit.db` - Users, API keys, and audit logs
- **Redis**: Docker volume `modemcheck-cloud_redis` → Redis `/data` directory
  - Session data (in-memory with persistence)
- **Config**: Docker volume `modemcheck-cloud_config` → `/modemcheck-cloud/config/`

### Stored Data Fields

The database stores comprehensive modem diagnostic data including:

**Modem Information**
- Detection status (success/failed)
- Modem type, MAC address, firmware version
- System time and uptime

**Channel Metrics**
- Downstream/upstream power levels and SNR
- FEC error counts (corrected/uncorrected)
- Channel frequencies and modulation

**Network Performance**
- Speed test results (download/upload/latency/jitter)
- Ping test results (Google and Cloudflare)
- Speed test server information

**Network Information** *(new in v5.7.0)*
- Public IP address
- ASN and ISP name
- Geolocation (city, country)

**Client Information**
- Client version, OS, and architecture

## Web Viewer

Access at `http://localhost:23890` (requires login)

### Features

**Modem Selection**
- Browse all registered modems
- View modem type and last check time
- Filter and search capabilities

**Check Visualization**
- Timeline view of all checks for selected modem
- Date range filtering
- Interactive charts for signal quality trends

**Data Display**
- System information and detection status
- Network information (IP, ISP, location)
- Channel power levels and SNR
- Error rates and event logs
- Speed test and ping results
- All data automatically refreshes when selecting different checks

## Admin Dashboard

Access at `http://localhost:23891` (default: admin/changeme, change on first login)

### Features

**API Key Management**
- Create, view, edit, and delete API keys
- Track last usage time for each key
- Enable/disable keys without deletion
- Required permissions: Admin (create/delete), Elevated (view/toggle)

**Config Generator**
- Point-and-click interface for creating `config.json` files
- **Generator sub-tab**: Create configurations with live JSON preview
- **Defaults sub-tab**: Set default values that auto-populate the generator
- Download complete config files ready to use
- Required permissions: Admin, Elevated

**Data Management**
- **Bulk Upload**: Upload multiple JSON check files at once
- **Bulk Download**: Download checks as ZIP with date/limit filtering
- **Delete Operations**: Remove individual checks or all checks for a modem
- Required permissions: Admin (all), Elevated (upload/download only)

**User Management**
- Create viewer users (basic/elevated/admin roles)
- Promote/demote user roles
- Force password changes on next login
- View user activity and last login times
- Required permissions: Admin only

**Audit Logging**
- Complete tracking of all user actions
- Role changes, API key operations, data deletions
- Searchable by user, action type, and date
- Required permissions: Admin only

## User Roles & Permissions

| Feature | Basic | Elevated | Admin |
|---------|-------|----------|-------|
| View modem data | ✓ | ✓ | ✓ |
| View own API keys | ✓ | ✓ | ✓ |
| List/toggle API keys | ✗ | ✓ | ✓ |
| Delete API keys | ✗ | ✗ | ✓ |
| Config Generator | ✗ | ✓ | ✓ |
| Bulk upload/download | ✗ | ✓ | ✓ |
| Delete checks | ✗ | ✗ | ✓ |
| User management | ✗ | ✗ | ✓ |
| View audit logs | ✗ | ✗ | ✓ |

**Default Credentials:**
- Username: `admin`
- Password: `changeme` (must change on first login)

**Managing Roles:**
1. Login as admin → Navigate to "User Management" tab
2. Select user → Choose new role → Click "Update Role"
3. Changes are logged in audit trail

## Container Management

### Common Commands

| Operation | Command |
|-----------|---------|
| Start | `docker compose up -d` |
| Stop | `docker compose down` |
| Restart | `docker compose restart` |
| View logs | `docker compose logs -f` |
| Shell access | `docker exec -it modemcheck-cloud /bin/sh` |
| Rebuild | `docker compose up -d --build` |

### Viewing Logs

```bash
# All logs
docker compose logs -f

# Nginx only
docker compose logs -f | grep nginx

# Python errors
docker compose logs -f | grep "ERROR\|Traceback"
```

## API Reference

### Upload Endpoint

**POST** `https://your-server:22557/cgi-bin/upload.py`

```bash
curl -X POST https://localhost:22557/cgi-bin/upload.py \
  -F "api_key=your-api-key-here" \
  -F "modem_id=XB8-AABBCCDDEEFF" \
  -F "filename=2025-01-12_10-30-00.json" \
  -F "file=@/path/to/check.json"
```

**Response:**
```json
{
  "success": true,
  "message": "Data uploaded successfully",
  "database_id": 1234
}
```

### Query Endpoint

**GET** `http://localhost:23890/cgi-bin/db-api.py`

```bash
# Get all modems
curl "http://localhost:23890/cgi-bin/db-api.py?action=list_modems"

# Get checks for specific modem
curl "http://localhost:23890/cgi-bin/db-api.py?action=get_checks&modem_id=XB8-AABBCCDDEEFF&start_date=2025-01-01&end_date=2025-01-31"
```

### Authentication

All API requests to port 23890 and 23891 require session cookies obtained via login.

## Production Deployment

### HTTPS Setup

**Option 1: Cloudflare Tunnel (Recommended)**

```bash
# Install cloudflared
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o cloudflared
chmod +x cloudflared

# Create tunnel
./cloudflared tunnel create modemcheck
./cloudflared tunnel route dns modemcheck modemcheck.yourdomain.com

# Configure tunnel (config.yml)
tunnel: <tunnel-id>
credentials-file: /path/to/credentials.json

ingress:
  - hostname: modemcheck.yourdomain.com
    service: http://localhost:22557
  - hostname: viewer.yourdomain.com
    service: http://localhost:23890
  - service: http_status:404

# Run tunnel
./cloudflared tunnel run modemcheck
```

**Option 2: Reverse Proxy (nginx/Caddy)**

See full nginx/Caddy configuration examples in repository wiki.

### Security Checklist

- [ ] Change default admin password
- [ ] Use strong, unique API keys
- [ ] Enable HTTPS for public access
- [ ] Keep admin dashboard on local network only (or behind VPN)
- [ ] Regular backups of database
- [ ] Update container regularly
- [ ] Monitor audit logs for suspicious activity

## Backup & Restore

### Backup

```bash
# Stop container
docker compose down

# Backup database
docker run --rm -v modemcheck-cloud_db:/data -v $(pwd):/backup alpine \
  tar czf /backup/modemcheck-db-$(date +%Y%m%d).tar.gz -C /data .

# Backup config
docker run --rm -v modemcheck-cloud_config:/data -v $(pwd):/backup alpine \
  tar czf /backup/modemcheck-config-$(date +%Y%m%d).tar.gz -C /data .

# Backup Redis (optional - sessions are temporary)
docker run --rm -v modemcheck-cloud_redis:/data -v $(pwd):/backup alpine \
  tar czf /backup/modemcheck-redis-$(date +%Y%m%d).tar.gz -C /data .

# Restart
docker compose up -d
```

**Note:** Redis backup is optional since it only contains temporary session data (12-hour TTL). Users will need to re-login after restore.

### Restore

```bash
# Stop container
docker compose down

# Restore database
docker run --rm -v modemcheck-cloud_db:/data -v $(pwd):/backup alpine \
  sh -c "rm -rf /data/* && tar xzf /backup/modemcheck-db-YYYYMMDD.tar.gz -C /data"

# Restore config
docker run --rm -v modemcheck-cloud_config:/data -v $(pwd):/backup alpine \
  sh -c "rm -rf /data/* && tar xzf /backup/modemcheck-config-YYYYMMDD.tar.gz -C /data"

# Restart
docker compose up -d
```

## Troubleshooting

### Container Won't Start

**Check logs:**
```bash
docker compose logs
```

**Common causes:**
- Port already in use: Check with `netstat -tlnp | grep -E '22557|23890|23891'`
- Volume permissions: Ensure Docker has access to volume paths
- Missing volumes: Recreate with `docker volume create` commands

### Upload Fails

**Symptoms:** `curl` returns error or timeout

**Solutions:**
1. Verify API key is valid in admin dashboard
2. Check modem_id format (e.g., `XB8-AABBCCDDEEFF`)
3. Verify JSON file is valid: `python3 -m json.tool check.json`
4. Check container logs: `docker compose logs -f`

### Web Viewer Shows No Data

**Solutions:**
1. Verify data exists: Check database via admin dashboard
2. Check date range filter (default: last 14 days)
3. Verify modem selection in dropdown
4. Clear browser cache and cookies

### Login Issues

**Reset admin password:**
```bash
docker exec -it modemcheck-cloud python3 -c "
from cgi_bin.auth import hash_password
import sqlite3
conn = sqlite3.connect('/modemcheck-cloud/db/modemcheck.db')
conn.execute('UPDATE users SET password_hash=?, must_change_password=1 WHERE username=?',
             (hash_password('changeme'), 'admin'))
conn.commit()
"
```

### Slow Performance

**Check database size:**
```bash
docker exec modemcheck-cloud du -sh /modemcheck-cloud/db/modemcheck.db
```

**Optimize if large:**
```bash
docker exec modemcheck-cloud sqlite3 /modemcheck-cloud/db/modemcheck.db "VACUUM;"
```

**Consider cleanup:**
- Remove old data via Data Management tab
- Archive and delete checks older than X days

## Updating

### Update Container

```bash
# Pull latest code
git pull

# Rebuild and restart
cd cloudserver
docker compose down
docker compose up -d --build
```

### Database Migrations

Database schema updates are handled automatically on container startup. Check logs for migration messages:

```bash
docker compose logs | grep -i migration
```

## Support

For issues, questions, or feature requests:
- Check this documentation
- Review [main README](../README.md) for client setup
- Check [GitHub Issues](https://github.com/adamkl-me/modemcheck/issues)
