# Modem Check Cloud Server - Docker Setup

This directory contains everything needed to run the Modem Check Cloud Server in a Docker container. The cloud server provides:
- **Upload API** for uploading modem check results (port 22557)
- **Web Viewer** for visualizing collected data (port 23890)
- **Admin Dashboard** for managing API keys and users (port 23891)

## Quick Start

### 1. Create Docker Volumes

```bash
# Create volumes for database and configuration
docker volume create modemcheck-cloud_db
docker volume create modemcheck-cloud_config
```

### 2. Build and Start the Container

```bash
cd cloudserver
docker compose up -d
```

This will:
- Build the Alpine Linux container with nginx, Python, and fcgiwrap
- Create persistent volumes for SQLite database and configuration storage
- Expose port 22557 for data uploads (direct to database)
- Expose port 23890 for web viewer
- Expose port 23891 for admin dashboard

### 3. Verify the Container is Running

```bash
docker ps | grep modemcheck-cloud
```

### 4. Create Your First API Key and Configuration

**Option A: Manual Creation (Quick)**

1. Open the admin dashboard in your browser:
   ```
   http://localhost:23891
   ```

2. Navigate to the API Keys tab

3. Enter a descriptive name (e.g., "Home Router", "Office Modem")

4. Click "Create API Key"

5. **Copy the key immediately** - you won't be able to see it again!

**Option B: Using Config Generator (Recommended)**

1. Open the admin dashboard at `http://localhost:23891`

2. Navigate to the "Config Generator" tab

3. (Optional) Click the "Defaults" sub-tab to set default values for common settings

4. Return to the "Generator" sub-tab (pre-filled with defaults)

5. Fill in or adjust modem settings as needed

6. Click "Generate Key" or "Select Existing" to choose an API key

7. Download the complete `config.json` file

### 5. Update Your modem-check Configuration

If you created the API key manually, create or update your `config.json`:

```json
{
  "ModemAddress": "autodetect",
  "EnableCloud": true,
  "CloudHost": "localhost",
  "CloudPort": "22557",
  "CloudAPIKey": "paste-your-api-key-here"
}
```

### 6. Test the Setup

Run modem-check with your config:

```bash
./modem-check -config config.json
```

Check the logs for successful upload, then view your data at:
```
http://localhost:23890
```

## Architecture

### Port Layout
- **Port 22557**:
  - Data upload API (`/cgi-bin/upload.py`) - inserts directly to database
- **Port 23890**:
  - Data viewer web interface
  - Database API (`/cgi-bin/db-api.py`)
- **Port 23891**:
  - Admin dashboard for user management
  - Admin API (`/cgi-bin/admin-api.py`)

### File Structure
```
/modemcheck-cloud/
├── data/                     # SQLite database (persistent volume)
│   ├── modemcheck.db        # Main database with all modem data
│   └── audit.db             # Audit log database
├── config/                   # Configuration (persistent volume)
│   ├── users.db             # User accounts database
│   ├── sessions/            # Session files
│   └── config_defaults.json # Config Generator default values
├── cgi-bin/
│   ├── db-api.py            # Data viewer API
│   ├── upload.py            # Data upload handler (inserts to database)
│   ├── db_schema.py         # Database schema and utilities
│   ├── admin-api.py         # API key management
│   └── auth.py              # Authentication handler
├── db-viewer.html           # Data viewer interface
├── db-viewer.js             # Data viewer JavaScript
└── admin.html               # Admin dashboard with Config Generator
```

## Container Management

### View Logs

```bash
docker logs modemcheck-cloud
docker logs -f modemcheck-cloud  # Follow logs
```

### Restart Container

```bash
docker compose restart
```

### Stop Container

```bash
docker compose down
```

### Rebuild After Changes

```bash
docker compose down
docker compose build --no-cache
docker compose up -d
```

### Access Container Shell

```bash
docker exec -it modemcheck-cloud /bin/sh
```

## API Key Management

### Via Web Dashboard (Recommended)

1. Open `http://localhost:23891`
2. Use the interface to:
   - Create new keys with descriptive names
   - View all keys with usage timestamps
   - Edit key names or disable keys
   - Delete keys
   - Copy keys to clipboard
   - Use the Config Generator with Defaults sub-tab to create config.json files with pre-filled values

### Via API (Advanced)

List all keys:
```bash
curl http://localhost:23891/cgi-bin/admin-api.py?action=list
```

Create a new key:
```bash
curl -X POST http://localhost:23891/cgi-bin/admin-api.py \
  -H "Content-Type: application/json" \
  -d '{"action":"create","name":"My New Key"}'
```

Delete a key:
```bash
curl -X POST http://localhost:23891/cgi-bin/admin-api.py \
  -H "Content-Type: application/json" \
  -d '{"action":"delete","key":"key-to-delete"}'
```

## Testing

### Test File Upload

Create a test JSON file:
```bash
echo '{"test":"data"}' > test.json
```

Upload using curl:
```bash
curl -X POST http://localhost:22557/cgi-bin/upload.py \
  -F "api_key=your-api-key" \
  -F "modem_id=TEST-123456" \
  -F "filename=test.json" \
  -F "file=@test.json"
```

### Test Web Viewer

Open in browser:
- **Data Viewer**: http://localhost:23890
- **Admin Dashboard**: http://localhost:23891

### Test Data Access API

```bash
# List all modems
curl http://localhost:23890/cgi-bin/db-api.py?action=list_modems

# List files for a modem
curl "http://localhost:23890/cgi-bin/db-api.py?action=list_files&modem_id=CODA56-xxx"

# Get a specific file
curl "http://localhost:23890/cgi-bin/db-api.py?action=get_file&modem_id=CODA56-xxx&filename=2025-11-05_12-00-00.json"
```

## Config Generator

The admin dashboard includes a Config Generator feature with two sub-tabs:

### Generator Sub-tab
- Point-and-click interface for creating `config.json` files
- Live JSON preview that updates as you type
- Select existing API keys or generate new ones inline
- Download button for instant `config.json` file
- All configuration options available (modem settings, cloud upload, speed tests, etc.)

### Defaults Sub-tab
- Set default values for all configuration fields
- Defaults automatically populate the Generator sub-tab
- Saves time when creating multiple similar configurations
- Changes persist across sessions
- Stored in `/modemcheck-cloud/config/config_defaults.json`

**Usage:**
1. Navigate to the Config Generator tab in the admin dashboard
2. (Optional) Click the "Defaults" sub-tab to set your preferred default values
3. Click "Save Defaults" to persist your settings
4. Return to the "Generator" sub-tab - fields will be pre-filled with your defaults
5. Customize as needed for the specific device
6. Download the generated `config.json` file

This eliminates manual JSON editing and reduces configuration errors.

## Migrating Existing Data

### Architecture Change (v5.0+)

**Important:** Starting with v5.0, the cloud server stores all data directly in an SQLite database instead of JSON files. This provides:
- Immediate data availability (no daemon delay)
- Faster queries and filtering
- Reduced disk usage
- Simpler architecture

### Migrating from Old File-Based System

If you have historical JSON files from the old system, you can import them using the database schema utilities:

```bash
# Option 1: Use Python directly in the container
docker exec -it modemcheck-cloud python3 << 'EOF'
from pathlib import Path
import json
import sys
sys.path.insert(0, '/modemcheck-cloud/cgi-bin')
from db_schema import insert_check

# Import JSON files
for json_file in Path('/path/to/old/files').rglob('*.json'):
    with open(json_file) as f:
        data = json.load(f)
    modem_id = json_file.parent.name  # e.g., "XB8-400FC1F7904C"
    filename = f"{modem_id}/{json_file.name}"
    insert_check(data, filename)
    print(f"Imported: {filename}")
EOF

# Option 2: Copy files and use manual import script
# (Contact for migration assistance if needed)
```

### From Previous Database

If upgrading from an older version with a database:

```bash
# Backup old database
docker run --rm \
  -v old_modemcheck_db:/data \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/old-db.tar.gz -C /data .

# Restore to new volume
docker run --rm \
  -v modemcheck-cloud_db:/data \
  -v $(pwd)/backups:/backup \
  alpine tar xzf /backup/old-db.tar.gz -C /data
```

## User Role Management

### Permission Levels

The admin dashboard supports three user roles with different permission levels:

| Role | Permissions |
|------|------------|
| **admin** | Full system access including User Management, User Activity audit logs, Config Defaults, API Keys, and all other features |
| **elevated** | Limited admin access to API Keys, Config Generator (Generator sub-tab only), and Client Submissions |
| **basic** | View-only access to check data |

### First-Time Setup

After building the container for the first time, you'll need to fix the database role constraint to support the new permission levels:

```bash
# Fix the database constraint to allow 'admin', 'elevated', and 'basic' roles
docker exec -it modemcheck-cloud python3 /modemcheck-cloud/fix_role_constraint.py
```

**Note:** The default admin account is created with username `admin` and password `changeme`. You'll be prompted to change this on first login.

### Migrating from Old Role Hierarchy

If you're upgrading from a previous version that used different role names (superadmin/admin), run the migration script:

```bash
# Migrate old role names to new hierarchy
docker exec -it modemcheck-cloud python3 /modemcheck-cloud/migrate_roles.py
```

This will:
- Convert `superadmin` → `admin` (full access)
- Convert old `admin` → `elevated` (limited admin)
- Keep `basic` unchanged

### Upgrading Users to Admin

To give a user full admin access:

```bash
# Upgrade a user to admin role
docker exec -it modemcheck-cloud python3 /modemcheck-cloud/upgrade_to_admin.py username
```

### Managing Users via Dashboard

Users with **admin** role can:
- Access the admin dashboard with full visibility
- Create new users with any role (basic, elevated, or admin)
- Change user roles via dropdown
- Reset user passwords
- Delete users
- View user activity logs
- Manage API keys
- Use Config Generator (all tabs including Defaults)
- View client submission logs

Users with **elevated** role can:
- Access the admin dashboard with reduced visibility
- Manage API keys
- Use Config Generator (Generator tab only - Defaults tab is hidden)
- View client submission logs
- **Cannot** access User Management tab
- **Cannot** view User Activity audit logs
- **Cannot** modify Config Defaults

Users with **basic** role:
- Cannot access the admin dashboard
- View-only access to check data via the viewer

## Backup and Restore

### Backup Data

```bash
# Backup SQLite database (contains all modem data)
docker run --rm \
  -v modemcheck-cloud_db:/data \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/database-$(date +%Y%m%d).tar.gz -C /data .

# Backup configuration (users and API keys)
docker run --rm \
  -v modemcheck-cloud_config:/config \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/config-$(date +%Y%m%d).tar.gz -C /config .
```

### Restore Data

```bash
# Restore database
docker run --rm \
  -v modemcheck-cloud_db:/data \
  -v $(pwd)/backups:/backup \
  alpine tar xzf /backup/database-20251105.tar.gz -C /data

# Restore configuration
docker run --rm \
  -v modemcheck-cloud_config:/config \
  -v $(pwd)/backups:/backup \
  alpine tar xzf /backup/config-20251105.tar.gz -C /config
```

## Production Deployment

### Reverse Proxy with HTTPS

The container serves plain HTTP. For production, use a reverse proxy with HTTPS:

**Nginx example:**
```nginx
server {
    listen 443 ssl;
    server_name modemcheck.example.com;

    ssl_certificate /etc/letsencrypt/live/modemcheck.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/modemcheck.example.com/privkey.pem;

    # Data viewer and upload API
    location / {
        proxy_pass http://localhost:23890;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}

server {
    listen 443 ssl;
    server_name admin.modemcheck.example.com;

    ssl_certificate /etc/letsencrypt/live/modemcheck.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/modemcheck.example.com/privkey.pem;

    # Admin dashboard - consider IP restrictions
    location / {
        proxy_pass http://localhost:23891;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        # Optional: restrict to trusted IPs
        # allow 192.168.1.0/24;
        # deny all;
    }
}
```

**Caddy example:**
```
modemcheck.example.com {
    reverse_proxy localhost:23890
}

admin.modemcheck.example.com {
    reverse_proxy localhost:23891
    # Optional: restrict to trusted IPs
    # @blocked not remote_ip 192.168.1.0/24
    # respond @blocked 403
}
```

### Firewall Configuration

```bash
# Allow HTTPS traffic
sudo ufw allow 443/tcp

# If not using reverse proxy, allow direct access:
sudo ufw allow 22557/tcp  # Upload API
sudo ufw allow 23890/tcp  # Data viewer
sudo ufw allow 23891/tcp  # Admin dashboard (consider restricting)
```

## Troubleshooting

### Container Won't Start

Check logs:
```bash
docker logs modemcheck-cloud
```

Verify volumes exist:
```bash
docker volume ls | grep modemcheck
```

### Upload Fails with "Invalid API key"

1. Verify the API key in your config.json
2. Check that the key exists in the admin dashboard
3. Verify the key is active (not disabled)
4. Check Docker logs for errors: `docker logs modemcheck-cloud`

### Web Interface Not Loading

Check nginx status:
```bash
docker exec modemcheck-cloud ps aux | grep nginx
```

Check fcgiwrap:
```bash
docker exec modemcheck-cloud ps aux | grep fcgiwrap
```

Check nginx logs:
```bash
docker exec modemcheck-cloud cat /var/log/nginx/error.log
```

### API Endpoints Return Errors

Test the API directly:
```bash
docker exec modemcheck-cloud python3 /modemcheck-cloud/cgi-bin/db-api.py
```

Check CGI script permissions:
```bash
docker exec modemcheck-cloud ls -l /modemcheck-cloud/cgi-bin/
```

### Admin Dashboard Not Accessible

Verify port is exposed:
```bash
docker port modemcheck-cloud 23891
```

Check nginx is listening on both ports:
```bash
docker exec modemcheck-cloud netstat -tulpn | grep nginx
```

## Performance

The container uses minimal resources:
- **Memory**: ~30MB (no SSH server!)
- **CPU**: Minimal (only during uploads/queries)
- **Storage**: Depends on data volume
- **Startup Time**: < 2 seconds

## Security Considerations

### API Key Security
- Keys are 32-byte URL-safe random tokens (256 bits of entropy)
- Keys shown only once during creation
- Keys stored in persistent volume as JSON
- Each device can have its own key
- Easy to revoke access by deleting keys

### Network Security
- Use HTTPS in production (reverse proxy)
- Consider restricting admin dashboard to trusted IPs
- Use firewall rules to limit access
- Keep Docker and Alpine packages updated

### Best Practices
- Use separate API keys for each device
- Use descriptive key names
- Regularly review and remove unused keys
- Enable HTTPS for production deployments
- Set appropriate file permissions on config files
- Use TestMode "both" to maintain local backups

## Updating the Container

To update to a new version:

```bash
cd cloudserver
git pull  # Get latest changes
docker compose down
docker compose build --no-cache
docker compose up -d
```

Your data and API keys are preserved in Docker volumes.

**Important:** After updating to a version with new user role features, run the database fix script:

```bash
docker exec -it modemcheck-cloud python3 /modemcheck-cloud/fix_role_constraint.py
```

This updates the database schema to support the new permission levels (admin, elevated, basic).

## Support

- Main documentation: `../README.md`
- Project docs: `../CLAUDE.md`
