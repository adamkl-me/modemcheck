# Docker Secrets for Enhanced Security

This guide shows how to use Docker Secrets to securely manage sensitive environment variables in production.

## Overview

**Problem:** Environment variables in `docker-compose.yml` can be exposed through:
- `docker inspect` commands
- Process listings (`ps aux`)
- Docker API queries
- Container environment exports

**Solution:** Use Docker Secrets (Docker Swarm feature) to inject secrets as files instead of environment variables.

## Prerequisites

- Docker Swarm mode enabled (even for single-node deployments)
- Production environment only (overkill for development/testing)

## Quick Start

### 1. Initialize Docker Swarm

```bash
# Enable Swarm mode (safe for single-node setups)
docker swarm init

# Verify Swarm is active
docker info | grep Swarm
```

### 2. Create Secrets

```bash
# Generate secure passwords
DB_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
CSRF_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
REDIS_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

# Create Docker secrets
echo "$DB_PASSWORD" | docker secret create postgres_password -
echo "$SECRET_KEY" | docker secret create app_secret_key -
echo "$CSRF_SECRET" | docker secret create csrf_secret_key -
echo "$REDIS_PASSWORD" | docker secret create redis_password -

# Verify secrets were created
docker secret ls
```

### 3. Update Docker Compose for Secrets

Create `docker-compose.secrets.yml`:

```yaml
version: '3.8'

services:
  postgres:
    secrets:
      - postgres_password
    environment:
      # Read password from secret file instead of env var
      POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password

  modemcheck-api:
    secrets:
      - postgres_password
      - app_secret_key
      - csrf_secret_key
      - redis_password
    environment:
      # Use secret files instead of direct env vars
      DATABASE_PASSWORD_FILE: /run/secrets/postgres_password
      SECRET_KEY_FILE: /run/secrets/app_secret_key
      CSRF_SECRET_KEY_FILE: /run/secrets/csrf_secret_key
      REDIS_PASSWORD_FILE: /run/secrets/redis_password

  redis:
    secrets:
      - redis_password
    command: >
      sh -c 'redis-server
      --requirepass $$(cat /run/secrets/redis_password)
      --appendonly yes
      --maxmemory 256mb
      --maxmemory-policy allkeys-lru'

secrets:
  postgres_password:
    external: true
  app_secret_key:
    external: true
  csrf_secret_key:
    external: true
  redis_password:
    external: true
```

### 4. Update Application Code

Modify `app/core/config.py` to support `_FILE` suffix environment variables:

```python
import os
from pathlib import Path

def read_secret_file(env_var: str, fallback_var: str = None) -> Optional[str]:
    """
    Read secret from file if _FILE env var exists, otherwise use direct env var.

    Args:
        env_var: Name of _FILE environment variable (e.g., 'SECRET_KEY_FILE')
        fallback_var: Name of direct environment variable (e.g., 'SECRET_KEY')

    Returns:
        Secret value from file or environment variable
    """
    # Check for _FILE variant first
    secret_file = os.getenv(env_var)
    if secret_file and Path(secret_file).exists():
        return Path(secret_file).read_text().strip()

    # Fall back to direct environment variable
    if fallback_var:
        return os.getenv(fallback_var)

    return None

class Settings(BaseSettings):
    # ... existing fields ...

    def __init__(self, **kwargs):
        # Read secrets from files if _FILE env vars are set
        if not kwargs.get('secret_key'):
            secret_key = read_secret_file('SECRET_KEY_FILE', 'SECRET_KEY')
            if secret_key:
                kwargs['secret_key'] = secret_key

        if not kwargs.get('csrf_secret_key'):
            csrf_key = read_secret_file('CSRF_SECRET_KEY_FILE', 'CSRF_SECRET_KEY')
            if csrf_key:
                kwargs['csrf_secret_key'] = csrf_key

        if not kwargs.get('redis_password'):
            redis_pass = read_secret_file('REDIS_PASSWORD_FILE', 'REDIS_PASSWORD')
            if redis_pass:
                kwargs['redis_password'] = redis_pass

        # Update database URL to use password from file
        db_password_file = os.getenv('DATABASE_PASSWORD_FILE')
        if db_password_file and Path(db_password_file).exists():
            db_password = Path(db_password_file).read_text().strip()
            # Inject password into database URL
            if kwargs.get('database_url'):
                kwargs['database_url'] = kwargs['database_url'].replace(
                    '${POSTGRES_PASSWORD}',
                    db_password
                )

        super().__init__(**kwargs)
```

### 5. Deploy with Docker Stack

```bash
# Deploy as a stack (uses Swarm)
docker stack deploy -c docker-compose.yml -c docker-compose.secrets.yml modemcheck

# Verify deployment
docker stack services modemcheck

# Check secrets are mounted
docker exec $(docker ps -q -f name=modemcheck_api) ls -la /run/secrets/
```

## Security Benefits

✅ **Secrets not visible in:**
- `docker inspect` output
- Process environment listings
- Docker API responses
- Container environment dumps

✅ **Secrets are:**
- Encrypted at rest (Swarm Raft log)
- Encrypted in transit (TLS between nodes)
- Only accessible to services that explicitly declare them
- Mounted as read-only files at `/run/secrets/`

✅ **Access control:**
- Only root and container user can read secret files
- Secrets are never written to disk unencrypted
- Secrets are removed when container stops

## Alternative: SOPS (Simpler, No Swarm Required)

If you don't want to use Docker Swarm, consider Mozilla SOPS:

```bash
# Install SOPS
wget https://github.com/mozilla/sops/releases/latest/download/sops-v3.8.1.linux.amd64
sudo mv sops-v3.8.1.linux.amd64 /usr/local/bin/sops
sudo chmod +x /usr/local/bin/sops

# Configure age key
age-keygen -o ~/.config/sops/age/keys.txt

# Encrypt .env file
sops --age $(age-keygen -y ~/.config/sops/age/keys.txt) \
     --encrypt .env > .env.encrypted

# Decrypt at runtime
sops --decrypt .env.encrypted > .env
docker-compose up -d
rm .env  # Clean up
```

## Rollback

To revert to regular environment variables:

```bash
# Stop stack
docker stack rm modemcheck

# Remove secrets
docker secret rm postgres_password app_secret_key csrf_secret_key redis_password

# Leave Swarm mode (optional)
docker swarm leave --force

# Use regular docker-compose
docker-compose up -d
```

## Production Checklist

- [ ] Docker Swarm initialized
- [ ] All secrets created and verified (`docker secret ls`)
- [ ] Application code updated to read from secret files
- [ ] Tested in staging environment
- [ ] Secrets backed up securely (encrypted, offline storage)
- [ ] `.env` file removed from production server
- [ ] Docker Compose files updated to use secrets
- [ ] Deployment tested with `docker stack deploy`
- [ ] Secret file permissions verified in running containers

## Maintenance

### Rotating Secrets

```bash
# Create new secret with version suffix
echo "$NEW_PASSWORD" | docker secret create postgres_password_v2 -

# Update service to use new secret
docker service update --secret-rm postgres_password \
                       --secret-add postgres_password_v2 \
                       modemcheck_postgres

# Remove old secret after verification
docker secret rm postgres_password
```

### Backup Secrets

```bash
# Secrets cannot be read after creation!
# Save the secret values during initial creation:

cat > secrets_backup.txt.gpg <<EOF
postgres_password: $(docker secret inspect postgres_password --format '{{.ID}}')
app_secret_key: $(docker secret inspect app_secret_key --format '{{.ID}}')
# Note: IDs only, not values!
EOF

# Store original values encrypted separately
gpg --symmetric --cipher-algo AES256 secrets_backup.txt
rm secrets_backup.txt

# Store encrypted file in secure location (KeePass, 1Password, etc.)
```

## When to Use Docker Secrets

**Use Docker Secrets when:**
- ✅ Running in production environment
- ✅ Multiple services need shared secrets
- ✅ Compliance requires secrets management
- ✅ Multi-node Docker Swarm cluster

**Skip Docker Secrets when:**
- ❌ Development/testing environment
- ❌ Single-container setup
- ❌ Secrets already managed by vault/AWS Secrets Manager
- ❌ Using Kubernetes (use K8s Secrets instead)

## References

- [Docker Secrets Documentation](https://docs.docker.com/engine/swarm/secrets/)
- [Mozilla SOPS](https://github.com/mozilla/sops)
- [Docker Swarm Security Best Practices](https://docs.docker.com/engine/swarm/swarm_manager_locking/)
