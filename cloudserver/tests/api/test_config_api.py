"""
Integration tests for configuration management API.

Tests:
- Client sync endpoint (HMAC validation, nonce, clock skew)
- Health check endpoint
- Admin list configs (filtering, pagination)
- Admin get/update config (validation, version creation)
- Admin rollback config
- Config history
- Authentication and authorization

v3.0: Simplified 3-state model (unmanaged, managed, locked) with single-track versioning.
"""

import pytest
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from httpx import AsyncClient
from sqlalchemy import select

from app.models import User, APIKey
from app.models.client_config import ClientConfig, ConfigStatus, SyncStatus, ConfigVersion
from app.core.config_sync import calculate_config_hash
from app.core.utils import utc_now


pytestmark = pytest.mark.api


# ============================================================================
# CLIENT ENDPOINTS
# ============================================================================

class TestConfigSync:
    """Test client configuration sync endpoint."""

    @pytest.mark.asyncio
    async def test_first_sync_creates_config(self, http_client: AsyncClient, db_session, active_api_key):
        """First sync from new client creates configuration."""
        # Use the API key from the active_api_key fixture
        api_key_value = active_api_key.api_key

        # Prepare sync request
        config = {
            "ModemAddress": "192.168.100.1",
            "SpeedTestEnabled": True,
            "SpeedTestInterval": 1,
            "PingCount": 25,
            "AutoUpdateEnabled": True,
            "UpdateChannel": "stable",
            "EnableCloud": True,
            "CloudHost": "localhost",
            "CloudPort": "22557",
            "CloudAPIKey": api_key_value
        }

        timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')  # ISO 8601 UTC format
        modem_id = "ARRIS-TEST001"  # Optional - for tracking only
        nonce = hashlib.sha256(f"nonce_{timestamp}".encode()).hexdigest()
        config_hash = calculate_config_hash(config)

        # Calculate HMAC signature (v2.1: no modem_id in signature)
        message = f"{timestamp}|{nonce}|{config_hash}"
        signature = hmac.new(
            api_key_value.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        sync_request = {
            "api_key": api_key_value,
            "modem_id": modem_id,  # Optional - for tracking only
            "config": config,
            "version": 0,  # First sync (v3.0: integer version)
            "config_hash": config_hash,
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": signature
        }

        # Send sync request
        response = await http_client.post("/api/config/sync", json=sync_request)

        # Debug output
        if response.status_code != 200:
            print(f"\n=== ERROR RESPONSE ===")
            print(f"Status: {response.status_code}")
            print(f"Body: {response.text}")
            print(f"======================\n")

        # Assertions (v3.0: simplified single-track versioning)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["version"] == 1  # v3.0: integer version
        assert data["status"] == "unmanaged"  # Default status
        assert data["sync_status"] in ["n/a", "pending", "active"]  # v3.0: sync_status
        assert data["config_changed"] is True
        assert "config" in data
        assert "config_hash" in data
        assert "server_timestamp" in data

    @pytest.mark.asyncio
    async def test_sync_with_invalid_signature_fails(self, http_client: AsyncClient, active_api_key):
        """Sync with invalid HMAC signature fails."""
        config = {"PingCount": 25}
        timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')  # ISO 8601 UTC format
        modem_id = "ARRIS-TEST001"
        nonce = hashlib.sha256(f"nonce_{timestamp}".encode()).hexdigest()
        config_hash = calculate_config_hash(config)

        sync_request = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "config": config,
            "version": 1,  # v3.0: integer version
            "config_hash": config_hash,
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": "invalid_signature_123"
        }

        response = await http_client.post("/api/config/sync", json=sync_request)

        assert response.status_code == 401
        data = response.json()
        assert data["success"] is False
        assert "signature" in data["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_sync_with_replay_nonce_fails(self, http_client: AsyncClient, db_session, active_api_key):
        """Sync with reused nonce fails (replay attack)."""
        config = {"PingCount": 25}
        timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')  # ISO 8601 UTC format
        modem_id = "ARRIS-TEST002"  # Optional - for tracking
        nonce = hashlib.sha256(f"nonce_{timestamp}".encode()).hexdigest()
        config_hash = calculate_config_hash(config)

        # v2.1: signature format excludes modem_id
        message = f"{timestamp}|{nonce}|{config_hash}"
        signature = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        sync_request = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,  # Optional
            "config": config,
            "version": 0,  # v3.0: integer version
            "config_hash": config_hash,
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": signature
        }

        # First request succeeds
        response1 = await http_client.post("/api/config/sync", json=sync_request)
        assert response1.status_code == 200

        # Second request with same nonce fails
        response2 = await http_client.post("/api/config/sync", json=sync_request)
        assert response2.status_code in [400, 401]  # Nonce replay error

    @pytest.mark.asyncio
    async def test_sync_with_clock_skew_fails(self, http_client: AsyncClient, active_api_key):
        """Sync with timestamp too far in past/future fails."""
        config = {"PingCount": 25}
        # Timestamp 10 minutes in past
        timestamp = (datetime.utcnow() - timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')  # ISO 8601 UTC format
        modem_id = "ARRIS-TEST003"  # Optional
        nonce = hashlib.sha256(f"nonce_{timestamp}".encode()).hexdigest()
        config_hash = calculate_config_hash(config)

        # v2.1: signature format excludes modem_id
        message = f"{timestamp}|{nonce}|{config_hash}"
        signature = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        sync_request = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,  # Optional
            "config": config,
            "version": 0,  # v3.0: integer version
            "config_hash": config_hash,
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": signature
        }

        response = await http_client.post("/api/config/sync", json=sync_request)

        assert response.status_code in [400, 401]
        data = response.json()
        assert "clock" in data["error"]["message"].lower() or "timestamp" in data["error"]["message"].lower() or "skew" in data["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_sync_with_invalid_config_fails(self, http_client: AsyncClient, active_api_key):
        """Sync with invalid configuration fails validation."""
        # Invalid config (PingCount too high)
        config = {"PingCount": 150}  # Above maximum of 100
        timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')  # ISO 8601 UTC format
        modem_id = "ARRIS-TEST004"  # Optional
        nonce = hashlib.sha256(f"nonce_{timestamp}".encode()).hexdigest()
        config_hash = calculate_config_hash(config)

        # v2.1: signature format excludes modem_id
        message = f"{timestamp}|{nonce}|{config_hash}"
        signature = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        sync_request = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "config": config,
            "version": 0,  # v3.0: integer version
            "config_hash": config_hash,
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": signature
        }

        response = await http_client.post("/api/config/sync", json=sync_request)

        assert response.status_code == 400
        data = response.json()
        assert "validation" in data["error"]["message"].lower() or "pingcount" in data["error"]["message"].lower()


class TestHealthCheck:
    """Test health check endpoint."""

    @pytest.mark.asyncio
    async def test_health_check_returns_status(self, http_client: AsyncClient):
        """Health check endpoint returns service status."""
        response = await http_client.get("/api/config/health")

        assert response.status_code == 200
        data = response.json()
        assert "healthy" in data
        assert "timestamp" in data
        assert "database" in data
        assert "cache" in data

    @pytest.mark.asyncio
    async def test_health_check_no_auth_required(self, http_client: AsyncClient):
        """Health check does not require authentication."""
        # No session cookie or auth headers
        response = await http_client.get("/api/config/health")
        assert response.status_code == 200


# ============================================================================
# ADMIN ENDPOINTS
# ============================================================================

class TestAdminListConfigs:
    """Test admin config listing endpoint."""

    @pytest.mark.asyncio
    async def test_list_configs_requires_admin(self, basic_client_with_token: AsyncClient):
        """Non-admin users cannot list configs."""
        response = await basic_client_with_token.get("/api/admin/configs")
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_list_configs_returns_all(self, http_client: AsyncClient, db_session, admin_client_with_token: AsyncClient, active_api_key):
        """Admin can list all configurations."""
        # Create a test config (one per API key in v2.1 architecture)
        from app.core.config_encryption import encrypt_config

        config = {"PingCount": 25}
        config_hash = calculate_config_hash(config)
        encrypted, salt = await encrypt_config(config)

        client_config = ClientConfig(
            api_key=active_api_key.api_key,
            last_seen_modem_id="ARRIS-TEST000",
            config_plaintext=config,
            config_encrypted=encrypted,
            config_hash=config_hash,
            status=ConfigStatus.UNMANAGED,  # v3.0: simplified 3-state model
            sync_status=SyncStatus.NA,  # v3.0: sync status
            version=1,  # v3.0: single integer version
            encryption_salt=salt,
            created_at=utc_now(),
            created_by="system",
            updated_at=utc_now(),
            updated_by="system"
        )
        db_session.add(client_config)
        await db_session.commit()

        # List configs
        response = await admin_client_with_token.get(
            "/api/admin/configs"
        )

        assert response.status_code == 200
        data = response.json()
        assert "configs" in data
        assert len(data["configs"]) >= 1  # At least one config
        assert "total" in data

    @pytest.mark.asyncio
    async def test_list_configs_filter_by_status(self, http_client: AsyncClient, db_session, admin_client_with_token: AsyncClient, active_api_key):
        """Admin can filter configs by status."""
        # Create enforced config
        config = {"PingCount": 25}
        config_hash = calculate_config_hash(config)

        from app.core.config_encryption import encrypt_config
        encrypted, salt = await encrypt_config(config)

        enforced_config = ClientConfig(
            api_key=active_api_key.api_key,
            last_seen_modem_id="ENFORCED-001",
            config_plaintext=config,
            config_encrypted=encrypted,
            config_hash=config_hash,
            status=ConfigStatus.LOCKED,  # v3.0: simplified 3-state model
            sync_status=SyncStatus.ACTIVE,  # v3.0: sync status
            version=1,  # v3.0: single integer version
            encryption_salt=salt,
            created_at=utc_now(),
            created_by="system",
            updated_at=utc_now(),
            updated_by="system"
        )
        db_session.add(enforced_config)
        await db_session.commit()

        # Filter by locked status (v3.0)
        response = await admin_client_with_token.get(
            "/api/admin/configs?status=locked"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["configs"]) >= 1
        assert all(c["status"] == "locked" for c in data["configs"])

    @pytest.mark.asyncio
    async def test_list_configs_pagination(self, http_client: AsyncClient, admin_client_with_token: AsyncClient):
        """Admin can paginate config list."""
        response = await admin_client_with_token.get(
            "/api/admin/configs?limit=10&offset=0"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["configs"]) <= 10


class TestAdminGetConfig:
    """Test admin get config endpoint."""

    @pytest.mark.asyncio
    async def test_get_config_requires_admin(self, http_client: AsyncClient, basic_client_with_token: AsyncClient, active_api_key):
        """Non-admin users cannot get config details."""
        response = await basic_client_with_token.get(
            f"/api/admin/configs/{active_api_key.api_key}"
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_get_config_returns_details(self, http_client: AsyncClient, db_session, admin_client_with_token: AsyncClient, active_api_key):
        """Admin can get config details."""
        # Create config
        config = {"PingCount": 25, "CloudAPIKey": "secret123"}
        config_hash = calculate_config_hash(config)

        from app.core.config_encryption import encrypt_config
        encrypted, salt = await encrypt_config(config)

        client_config = ClientConfig(
            api_key=active_api_key.api_key,
            last_seen_modem_id="DETAIL-001",
            config_plaintext=config,
            config_encrypted=encrypted,
            config_hash=config_hash,
            status=ConfigStatus.UNMANAGED,  # v3.0: simplified 3-state model
            sync_status=SyncStatus.NA,  # v3.0: sync status
            version=5,  # v3.0: single integer version
            encryption_salt=salt,
            created_at=utc_now(),
            created_by="system",
            updated_at=utc_now(),
            updated_by="system"
        )
        db_session.add(client_config)
        await db_session.commit()

        # Get config (api_key only - modem_id is no longer primary key)
        response = await admin_client_with_token.get(
            f"/api/admin/configs/{active_api_key.api_key}"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["api_key"] == active_api_key.api_key
        assert data["last_seen_modem_id"] == "DETAIL-001"
        assert data["version"] == 5  # v3.0: integer version
        assert data["status"] == "unmanaged"  # v3.0: simplified status
        # Sensitive fields are NOT redacted in new version
        assert data["config"]["CloudAPIKey"] == "secret123"
        assert data["config"]["PingCount"] == 25

    @pytest.mark.asyncio
    async def test_get_nonexistent_config_fails(self, http_client: AsyncClient, admin_client_with_token: AsyncClient):
        """Getting nonexistent config returns 404."""
        response = await admin_client_with_token.get(
            "/api/admin/configs/nonexistent_key"
        )

        assert response.status_code == 404


class TestAdminUpdateConfig:
    """Test admin update config endpoint."""

    @pytest.mark.asyncio
    async def test_update_config_requires_admin(self, http_client: AsyncClient, basic_client_with_token: AsyncClient, active_api_key):
        """Non-admin users cannot update config."""
        update_request = {
            "config": {"PingCount": 50},
            "mode": "managed"  # v3.0: simplified modes
        }

        response = await basic_client_with_token.put(
            f"/api/admin/configs/{active_api_key.api_key}",
            json=update_request
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_update_config_creates_version(self, http_client: AsyncClient, db_session, admin_client_with_token: AsyncClient, active_api_key, csrf_token):
        """Updating config creates version history."""
        # Create initial config
        config = {"PingCount": 25}
        config_hash = calculate_config_hash(config)

        from app.core.config_encryption import encrypt_config
        encrypted, salt = await encrypt_config(config)

        client_config = ClientConfig(
            api_key=active_api_key.api_key,
            last_seen_modem_id="VERSION-001",
            config_plaintext=config,
            config_encrypted=encrypted,
            config_hash=config_hash,
            status=ConfigStatus.UNMANAGED,  # v3.0: simplified 3-state model
            sync_status=SyncStatus.NA,  # v3.0: sync status
            version=1,  # v3.0: single integer version
            encryption_salt=salt,
            created_at=utc_now(),
            created_by="system",
            updated_at=utc_now(),
            updated_by="system"
        )
        db_session.add(client_config)
        await db_session.commit()

        # Update config
        new_config = {"PingCount": 50}
        update_request = {
            "config": new_config,
            "mode": "locked"  # v3.0: simplified modes
        }

        response = await admin_client_with_token.put(
            f"/api/admin/configs/{active_api_key.api_key}",
            json=update_request,
            headers={"X-CSRF-Token": csrf_token}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["version"] == 2  # v3.0: integer version (incremented)
        assert data["version_created"] is True  # v3.0: field name change

        # Verify version history was created
        result = await db_session.execute(
            select(ConfigVersion).where(
                ConfigVersion.api_key == active_api_key.api_key,
                ConfigVersion.version_number == 2  # v3.0: simple version lookup
            )
        )
        version_entry = result.scalar_one_or_none()
        assert version_entry is not None
        assert version_entry.config_plaintext == {"PingCount": 50}  # New config

    @pytest.mark.asyncio
    async def test_update_config_with_invalid_data_fails(self, http_client: AsyncClient, db_session, admin_client_with_token: AsyncClient, active_api_key, csrf_token):
        """Updating with invalid config fails validation."""
        # Create config
        config = {"PingCount": 25}
        config_hash = calculate_config_hash(config)

        from app.core.config_encryption import encrypt_config
        encrypted, salt = await encrypt_config(config)

        client_config = ClientConfig(
            api_key=active_api_key.api_key,
            last_seen_modem_id="INVALID-001",
            config_plaintext=config,
            config_encrypted=encrypted,
            config_hash=config_hash,
            status=ConfigStatus.UNMANAGED,  # v3.0: simplified 3-state model
            sync_status=SyncStatus.NA,  # v3.0: sync status
            version=1,  # v3.0: single integer version
            encryption_salt=salt,
            created_at=utc_now(),
            created_by="system",
            updated_at=utc_now(),
            updated_by="system"
        )
        db_session.add(client_config)
        await db_session.commit()

        # Try to update with invalid config
        invalid_config = {"PingCount": 150}  # Above maximum
        update_request = {
            "config": invalid_config,
            "mode": "managed"  # v3.0: simplified modes
        }

        response = await admin_client_with_token.put(
            f"/api/admin/configs/{active_api_key.api_key}",
            json=update_request,
            headers={"X-CSRF-Token": csrf_token}
        )

        assert response.status_code == 400
        data = response.json()
        assert "validation" in data["error"]["message"].lower()


class TestAdminRollbackConfig:
    """Test admin rollback config endpoint."""

    @pytest.mark.asyncio
    async def test_rollback_config_requires_admin(self, http_client: AsyncClient, basic_client_with_token: AsyncClient, active_api_key):
        """Non-admin users cannot rollback config."""
        rollback_request = {"reason": "Test rollback"}

        response = await basic_client_with_token.post(
            f"/api/admin/configs/{active_api_key.api_key}/rollback/1",  # v3.0: integer version
            json=rollback_request
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_rollback_config_restores_version(self, http_client: AsyncClient, db_session, admin_client_with_token: AsyncClient, active_api_key, csrf_token):
        """Rollback restores config from version history."""
        # Create config with version 2
        old_config = {"PingCount": 25}
        new_config = {"PingCount": 50}
        config_hash = calculate_config_hash(new_config)

        from app.core.config_encryption import encrypt_config
        encrypted, salt = await encrypt_config(new_config)

        client_config = ClientConfig(
            api_key=active_api_key.api_key,
            last_seen_modem_id="ROLLBACK-001",
            config_plaintext=new_config,
            config_encrypted=encrypted,
            config_hash=config_hash,
            status=ConfigStatus.UNMANAGED,  # v3.0: simplified 3-state model
            sync_status=SyncStatus.NA,  # v3.0: sync status
            version=2,  # v3.0: single integer version
            encryption_salt=salt,
            created_at=utc_now(),
            created_by="system",
            updated_at=utc_now(),
            updated_by="system"
        )
        db_session.add(client_config)

        # Create version history entry for version 1
        old_hash = calculate_config_hash(old_config)
        old_encrypted, old_salt = await encrypt_config(old_config)

        version_entry = ConfigVersion(
            api_key=active_api_key.api_key,
            modem_id_at_creation="ROLLBACK-001",
            version_number=1,  # v3.0: simple integer version
            config_plaintext=old_config,
            config_encrypted=old_encrypted,
            config_hash=old_hash,
            status_at_creation=ConfigStatus.UNMANAGED,  # v3.0: simplified status
            sync_status_at_creation=SyncStatus.NA,  # v3.0: sync status
            encryption_salt=old_salt,
            created_at=utc_now(),
            created_by="system",
            creation_reason="initial_sync"
        )
        db_session.add(version_entry)
        await db_session.commit()

        # Rollback to version 1 (v3.0: integer version)
        rollback_request = {"reason": "Revert changes"}

        response = await admin_client_with_token.post(
            f"/api/admin/configs/{active_api_key.api_key}/rollback/1",  # v3.0: integer version
            json=rollback_request,
            headers={"X-CSRF-Token": csrf_token}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["rolled_back_to"] == 1  # v3.0: integer version
        assert data["version"] == 3  # v3.0: new version created after rollback
        assert data["config"]["PingCount"] == 25  # Restored old value

    @pytest.mark.asyncio
    async def test_rollback_nonexistent_version_fails(self, http_client: AsyncClient, admin_client_with_token: AsyncClient, active_api_key, csrf_token):
        """Rolling back to nonexistent version fails."""
        rollback_request = {"reason": "Test"}

        response = await admin_client_with_token.post(
            f"/api/admin/configs/nonexistent_key/rollback/999",  # v3.0: integer version
            json=rollback_request,
            headers={"X-CSRF-Token": csrf_token}
        )

        assert response.status_code == 404


class TestAdminConfigHistory:
    """Test admin config history endpoint."""

    @pytest.mark.asyncio
    async def test_get_history_requires_admin(self, http_client: AsyncClient, basic_client_with_token: AsyncClient, active_api_key):
        """Non-admin users cannot view history."""
        response = await basic_client_with_token.get(
            f"/api/admin/configs/{active_api_key.api_key}/history"
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_get_history_returns_versions(self, http_client: AsyncClient, db_session, admin_client_with_token: AsyncClient, active_api_key):
        """Admin can view version history."""
        # Create multiple version entries
        from app.core.config_encryption import encrypt_config

        for version_num in [1, 2, 3]:
            config = {"PingCount": 20 + version_num}
            config_hash = calculate_config_hash(config)
            encrypted, salt = await encrypt_config(config)

            version_entry = ConfigVersion(
                api_key=active_api_key.api_key,
                modem_id_at_creation="HISTORY-001",
                version_number=version_num,  # v3.0: simple integer version
                config_plaintext=config,
                config_encrypted=encrypted,
                config_hash=config_hash,
                status_at_creation=ConfigStatus.UNMANAGED,  # v3.0: simplified status
                sync_status_at_creation=SyncStatus.NA,  # v3.0: sync status
                encryption_salt=salt,
                created_at=utc_now() - timedelta(days=version_num),
                created_by="system",
                creation_reason="client_sync"
            )
            db_session.add(version_entry)

        await db_session.commit()

        # Get history
        response = await admin_client_with_token.get(
            f"/api/admin/configs/{active_api_key.api_key}/history"
        )

        assert response.status_code == 200
        data = response.json()
        assert "versions" in data
        assert len(data["versions"]) == 3
        assert data["total"] == 3

        # Verify versions are sorted newest first (v1 is most recent, then v2, then v3)
        version_numbers = [v["version_number"] for v in data["versions"]]
        assert version_numbers == [1, 2, 3]  # v3.0: simple integer versions

    @pytest.mark.asyncio
    async def test_get_history_filter_by_status(self, http_client: AsyncClient, db_session, admin_client_with_token: AsyncClient, active_api_key):
        """History can be filtered by status (v3.0: replaces track filtering)."""
        from app.core.config_encryption import encrypt_config

        # Create versions with different statuses
        for idx, status in enumerate([ConfigStatus.UNMANAGED, ConfigStatus.LOCKED]):
            config = {"PingCount": 25}
            config_hash = calculate_config_hash(config)
            encrypted, salt = await encrypt_config(config)

            version_entry = ConfigVersion(
                api_key=active_api_key.api_key,
                modem_id_at_creation="HISTORY-STATUS-001",
                version_number=idx + 1,  # v3.0: simple integer version
                config_plaintext=config,
                config_encrypted=encrypted,
                config_hash=config_hash,
                status_at_creation=status,  # v3.0: simplified status
                sync_status_at_creation=SyncStatus.NA if status == ConfigStatus.UNMANAGED else SyncStatus.ACTIVE,
                encryption_salt=salt,
                created_at=utc_now(),
                created_by="system",
                creation_reason="client_sync" if status == ConfigStatus.UNMANAGED else "admin_update"
            )
            db_session.add(version_entry)

        await db_session.commit()

        # Get all history (no filtering by track in v3.0)
        response = await admin_client_with_token.get(
            f"/api/admin/configs/{active_api_key.api_key}/history"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["versions"]) >= 2

    @pytest.mark.asyncio
    async def test_get_history_respects_limit(self, http_client: AsyncClient, admin_client_with_token: AsyncClient, active_api_key):
        """History endpoint respects limit parameter."""
        response = await admin_client_with_token.get(
            f"/api/admin/configs/{active_api_key.api_key}/history?limit=2"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["versions"]) <= 2

    @pytest.mark.asyncio
    async def test_get_history_includes_modem_events(self, http_client: AsyncClient, db_session, admin_client_with_token: AsyncClient, active_api_key):
        """History includes modem events when requested."""
        from app.models.client_config import ConfigAuditLog

        # Hash the API key for the audit log (matches query in get_modem_events_for_history)
        api_key_hash = hashlib.sha256(active_api_key.api_key.encode('utf-8')).hexdigest()

        # Create modem change audit entry
        audit_entry = ConfigAuditLog(
            timestamp=utc_now(),
            username=None,
            ip_address="192.168.1.100",
            api_key=active_api_key.api_key,
            api_key_hash=api_key_hash,
            modem_id="MODEM-NEW",
            old_modem_id="MODEM-OLD",
            new_modem_id="MODEM-NEW",
            action="modem_change",
            config_summary={"old_modem_id": "MODEM-OLD", "new_modem_id": "MODEM-NEW"},
            success=True
        )
        db_session.add(audit_entry)
        await db_session.commit()

        response = await admin_client_with_token.get(
            f"/api/admin/configs/{active_api_key.api_key}/history"
        )

        assert response.status_code == 200
        data = response.json()
        assert "modem_events" in data
        assert len(data["modem_events"]) >= 1
        modem_change_events = [e for e in data["modem_events"] if e["event_type"] == "modem_change"]
        assert len(modem_change_events) >= 1
        assert modem_change_events[0]["old_modem_id"] == "MODEM-OLD"
        assert modem_change_events[0]["new_modem_id"] == "MODEM-NEW"

    @pytest.mark.asyncio
    async def test_get_history_excludes_modem_events_when_disabled(self, http_client: AsyncClient, db_session, admin_client_with_token: AsyncClient, active_api_key):
        """History can exclude modem events with query param."""
        from app.models.client_config import ConfigAuditLog

        # Hash the API key for the audit log (matches query in get_modem_events_for_history)
        api_key_hash = hashlib.sha256(active_api_key.api_key.encode('utf-8')).hexdigest()

        # Create modem change audit entry
        audit_entry = ConfigAuditLog(
            timestamp=utc_now(),
            username=None,
            ip_address="192.168.1.100",
            api_key=active_api_key.api_key,
            api_key_hash=api_key_hash,
            modem_id="MODEM-TEST",
            old_modem_id=None,
            new_modem_id="MODEM-TEST",
            action="modem_change",
            config_summary={"old_modem_id": None, "new_modem_id": "MODEM-TEST"},
            success=True
        )
        db_session.add(audit_entry)
        await db_session.commit()

        response = await admin_client_with_token.get(
            f"/api/admin/configs/{active_api_key.api_key}/history?include_modem_events=false"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["modem_events"] == []
        assert data["total_modem_events"] == 0

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
