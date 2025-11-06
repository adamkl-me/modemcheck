# Modem Check Cloud Server - Docker Setup

This directory contains everything needed to run the Modem Check Cloud Server in a Docker container. The cloud server provides:
- **Upload API** for uploading modem check results (port 22557)
- **Web Viewer** for visualizing collected data (port 23890)
- **Admin Dashboard** for managing API keys and users (port 23891)

## Quick Start

### 1. Create Docker Volumes

```bash
# Create volumes for data and configuration
docker volume create modemcheck-cloud_data
docker volume create modemcheck-cloud_config
```

### 2. Build and Start the Container

```bash
cd cloudserver
docker compose up -d
```

This will:
- Build the Alpine Linux container with nginx, Python, and fcgiwrap
- Create persistent volumes for data and configuration storage
- Expose port 22557 for file uploads
- Expose port 23890 for web viewer
- Expose port 23891 for admin dashboard

### 3. Verify the Container is Running

```bash
docker ps | grep modemcheck-cloud
```

### 4. Create Your First API Key

1. Open the admin dashboard in your browser:
   ```
   http://localhost:23891
   ```

2. Enter a descriptive name (e.g., "Home Router", "Office Modem")

3. Click "Create API Key"

4. **Copy the key immediately** - you won't be able to see it again!

### 5. Update Your modem-check Configuration

Create or update your `config.json`:

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
  - File upload API (`/cgi-bin/upload.py`)
- **Port 23890**:
  - Data viewer web interface
  - Database API (`/cgi-bin/db-api.py`)
- **Port 23891**:
  - Admin dashboard for user management
  - Admin API (`/cgi-bin/admin-api.py`)

### File Structure
```
/modemcheck-cloud/
├── datafiles/              # Modem data (persistent volume)
│   ├── CODA56-xxx/
│   ├── DM1000-xxx/
│   └── Xfinity-XB8-xxx/
├── config/                 # API key storage (persistent volume)
│   └── api_keys.json
├── cgi-bin/
│   ├── api.py              # Data viewer API
│   ├── upload.py           # File upload handler
│   └── admin-api.py        # API key management
├── index.html              # Data viewer interface
├── viewer.js               # Data viewer JavaScript
└── admin.html              # Admin dashboard
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
curl http://localhost:23890/cgi-bin/api.py?action=list_modems

# List files for a modem
curl "http://localhost:23890/cgi-bin/api.py?action=list_files&modem_id=CODA56-xxx"

# Get a specific file
curl "http://localhost:23890/cgi-bin/api.py?action=get_file&modem_id=CODA56-xxx&filename=2025-11-05_12-00-00.json"
```

## Migrating Existing Data

### From Local ModemCheck-Results/

```bash
# Copy data preserving structure
docker cp ModemCheck-Results/CODA56-AABBCC112233 \
  modemcheck-cloud:/modemcheck-cloud/datafiles/CODA56-AABBCC112233

docker cp ModemCheck-Results/DM1000-112233445566 \
  modemcheck-cloud:/modemcheck-cloud/datafiles/DM1000-112233445566

# Note: Ensure modem ID format is correct (Type-MAC)
```

### From Previous Installations

If you have data from a previous installation:

```bash
# Extract data from old volume
docker run --rm -v old_modemcheck_volume:/data alpine \
  tar czf - -C /data . > /tmp/old-data.tar.gz

# Import into new volume
docker run --rm -v modemcheck-cloud_data:/data alpine \
  tar xzf - -C /data < /tmp/old-data.tar.gz
```

## Backup and Restore

### Backup Data

```bash
# Backup modem data
docker run --rm \
  -v modemcheck-cloud_data:/data \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/modem-data-$(date +%Y%m%d).tar.gz -C /data .

# Backup API keys
docker run --rm \
  -v modemcheck-cloud_config:/config \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/api-keys-$(date +%Y%m%d).tar.gz -C /config .
```

### Restore Data

```bash
# Restore modem data
docker run --rm \
  -v modemcheck-cloud_data:/data \
  -v $(pwd)/backups:/backup \
  alpine tar xzf /backup/modem-data-20251105.tar.gz -C /data

# Restore API keys
docker run --rm \
  -v modemcheck-cloud_config:/config \
  -v $(pwd)/backups:/backup \
  alpine tar xzf /backup/api-keys-20251105.tar.gz -C /config
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
docker exec modemcheck-cloud /modemcheck-cloud/cgi-bin/api.py
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

## Support

- Main documentation: `../README.md`
- Project docs: `../CLAUDE.md`
