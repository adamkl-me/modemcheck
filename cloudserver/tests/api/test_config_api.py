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

Updated for dual-track versioning (v#_client / v#_server format).
"""

import pytest
import hashlib
import hmac
from datetime import datetime, timedelta
from httpx import AsyncClient
from sqlalchemy import select

from app.models import User, APIKey
from app.models.client_config import ClientConfig, ConfigStatus, ConfigVersion
from app.core.config_sync import calculate_config_hash


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

        timestamp = datetime.utcnow().isoformat() + "Z"
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
            "version": None,  # First sync
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

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["version"] == "v1_client"  # Dual-track versioning
        assert data["status"] == "unmanaged"  # Default status
        assert data["config_changed"] is True
        assert "config" in data
        assert "config_hash" in data
        assert data["active_track"] == "client"
        assert data["client_version"] == 1
        assert data["server_version"] == 0

    @pytest.mark.asyncio
    async def test_sync_with_invalid_signature_fails(self, http_client: AsyncClient, active_api_key):
        """Sync with invalid HMAC signature fails."""
        config = {"PingCount": 25}
        timestamp = datetime.utcnow().isoformat() + "Z"
        modem_id = "ARRIS-TEST001"
        nonce = hashlib.sha256(f"nonce_{timestamp}".encode()).hexdigest()
        config_hash = calculate_config_hash(config)

        sync_request = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "config": config,
            "version": "v1_client",  # String version
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
        timestamp = datetime.utcnow().isoformat() + "Z"
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
            "version": None,
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
        timestamp = (datetime.utcnow() - timedelta(minutes=10)).isoformat() + "Z"
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
            "version": None,
            "config_hash": config_hash,
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": signature
        }

        response = await http_client.post("/api/config/sync", json=sync_request)

        assert response.status_code in [400, 401]
        data = response.json()
        assert "clock" in data["error"]["message"].lower() or "timestamp" in data["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_sync_with_invalid_config_fails(self, http_client: AsyncClient, active_api_key):
        """Sync with invalid configuration fails validation."""
        # Invalid config (PingCount too high)
        config = {"PingCount": 150}  # Above maximum of 100
        timestamp = datetime.utcnow().isoformat() + "Z"
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
            "version": None,
            "config_hash": config_hash,
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": signature
        }

        response = await http_client.post("/api/config/sync", json=sync_request)

        assert response.status_code == 400
        data = response.json()
        assert "validation" in data["error"]["message"].lower()


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
            status=ConfigStatus.ONE_TIME_ACTIVE,
            client_version=1,
            server_version=0,
            active_track="client",
            encryption_salt=salt,
            created_at=datetime.utcnow(),
            created_by="system",
            updated_at=datetime.utcnow(),
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
            status=ConfigStatus.ENFORCED_ACTIVE,
            client_version=0,
            server_version=1,
            active_track="server",
            encryption_salt=salt,
            created_at=datetime.utcnow(),
            created_by="system",
            updated_at=datetime.utcnow(),
            updated_by="system"
        )
        db_session.add(enforced_config)
        await db_session.commit()

        # Filter by enforced_active status
        response = await admin_client_with_token.get(
            "/api/admin/configs?status=enforced_active"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["configs"]) >= 1
        assert all(c["status"] == "enforced_active" for c in data["configs"])

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
            status=ConfigStatus.ONE_TIME_ACTIVE,
            client_version=5,
            server_version=0,
            active_track="client",
            encryption_salt=salt,
            created_at=datetime.utcnow(),
            created_by="system",
            updated_at=datetime.utcnow(),
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
        assert data["version"] == "v5_client"
        assert data["status"] == "one_time_active"
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
            "mode": "one_time",
            "check_reachability": False
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
            status=ConfigStatus.ONE_TIME_ACTIVE,
            client_version=1,
            server_version=0,
            active_track="client",
            encryption_salt=salt,
            created_at=datetime.utcnow(),
            created_by="system",
            updated_at=datetime.utcnow(),
            updated_by="system"
        )
        db_session.add(client_config)
        await db_session.commit()

        # Update config
        new_config = {"PingCount": 50}
        update_request = {
            "config": new_config,
            "mode": "enforced",
            "check_reachability": False
        }

        response = await admin_client_with_token.put(
            f"/api/admin/configs/{active_api_key.api_key}",
            json=update_request,
            headers={"X-CSRF-Token": csrf_token}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["version"] == "v1_server"  # Server track version
        assert data["backup_created"] is True

        # Verify version history was created
        result = await db_session.execute(
            select(ConfigVersion).where(
                ConfigVersion.api_key == active_api_key.api_key,
                ConfigVersion.modem_id_at_creation == "VERSION-001",
                ConfigVersion.version_number == 1,
                ConfigVersion.version_track == "server"
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
            status=ConfigStatus.ONE_TIME_ACTIVE,
            client_version=1,
            server_version=0,
            active_track="client",
            encryption_salt=salt,
            created_at=datetime.utcnow(),
            created_by="system",
            updated_at=datetime.utcnow(),
            updated_by="system"
        )
        db_session.add(client_config)
        await db_session.commit()

        # Try to update with invalid config
        invalid_config = {"PingCount": 150}  # Above maximum
        update_request = {
            "config": invalid_config,
            "mode": "one_time",
            "check_reachability": False
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
            f"/api/admin/configs/{active_api_key.api_key}/rollback/v1_client",
            json=rollback_request
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_rollback_config_restores_version(self, http_client: AsyncClient, db_session, admin_client_with_token: AsyncClient, active_api_key, csrf_token):
        """Rollback restores config from version history."""
        # Create config with version v2_client
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
            status=ConfigStatus.ONE_TIME_ACTIVE,
            client_version=2,
            server_version=0,
            active_track="client",
            encryption_salt=salt,
            created_at=datetime.utcnow(),
            created_by="system",
            updated_at=datetime.utcnow(),
            updated_by="system"
        )
        db_session.add(client_config)

        # Create version history entry for v1_client
        old_hash = calculate_config_hash(old_config)
        old_encrypted, old_salt = await encrypt_config(old_config)

        version_entry = ConfigVersion(
            api_key=active_api_key.api_key,
            modem_id_at_creation="ROLLBACK-001",
            version_number=1,
            version_track="client",
            version_display="v1_client",
            config_plaintext=old_config,
            config_encrypted=old_encrypted,
            config_hash=old_hash,
            status_at_creation=ConfigStatus.ONE_TIME_ACTIVE,
            encryption_salt=old_salt,
            created_at=datetime.utcnow(),
            created_by="system",
            creation_reason="initial_sync"
        )
        db_session.add(version_entry)
        await db_session.commit()

        # Rollback to version v1_client
        rollback_request = {"reason": "Revert changes"}

        response = await admin_client_with_token.post(
            f"/api/admin/configs/{active_api_key.api_key}/rollback/v1_client",
            json=rollback_request,
            headers={"X-CSRF-Token": csrf_token}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["rolled_back_to"] == "v1_client"
        assert "_server" in data["version"]  # New server version created
        assert data["config"]["PingCount"] == 25  # Restored old value

    @pytest.mark.asyncio
    async def test_rollback_nonexistent_version_fails(self, http_client: AsyncClient, admin_client_with_token: AsyncClient, active_api_key, csrf_token):
        """Rolling back to nonexistent version fails."""
        rollback_request = {"reason": "Test"}

        response = await admin_client_with_token.post(
            f"/api/admin/configs/nonexistent_key/rollback/v999_client",
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
                version_number=version_num,
                version_track="client",
                version_display=f"v{version_num}_client",
                config_plaintext=config,
                config_encrypted=encrypted,
                config_hash=config_hash,
                status_at_creation=ConfigStatus.ONE_TIME_ACTIVE,
                encryption_salt=salt,
                created_at=datetime.utcnow() - timedelta(days=version_num),
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
        version_displays = [v["version_display"] for v in data["versions"]]
        assert version_displays == ["v1_client", "v2_client", "v3_client"]

    @pytest.mark.asyncio
    async def test_get_history_filter_by_track(self, http_client: AsyncClient, db_session, admin_client_with_token: AsyncClient, active_api_key):
        """History can be filtered by track."""
        from app.core.config_encryption import encrypt_config

        # Create client and server versions
        for track in ["client", "server"]:
            config = {"PingCount": 25}
            config_hash = calculate_config_hash(config)
            encrypted, salt = await encrypt_config(config)

            version_entry = ConfigVersion(
                api_key=active_api_key.api_key,
                modem_id_at_creation="HISTORY-TRACK-001",
                version_number=1,
                version_track=track,
                version_display=f"v1_{track}",
                config_plaintext=config,
                config_encrypted=encrypted,
                config_hash=config_hash,
                status_at_creation=ConfigStatus.ONE_TIME_ACTIVE,
                encryption_salt=salt,
                created_at=datetime.utcnow(),
                created_by="system",
                creation_reason="client_sync" if track == "client" else "admin_update"
            )
            db_session.add(version_entry)

        await db_session.commit()

        # Filter by server track
        response = await admin_client_with_token.get(
            f"/api/admin/configs/{active_api_key.api_key}/history?track=server"
        )

        assert response.status_code == 200
        data = response.json()
        assert all(v["version_track"] == "server" for v in data["versions"])

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

        # Create modem change audit entry
        audit_entry = ConfigAuditLog(
            timestamp=datetime.utcnow(),
            username=None,
            ip_address="192.168.1.100",
            api_key=active_api_key.api_key,
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

        # Create modem change audit entry
        audit_entry = ConfigAuditLog(
            timestamp=datetime.utcnow(),
            username=None,
            ip_address="192.168.1.100",
            api_key=active_api_key.api_key,
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
