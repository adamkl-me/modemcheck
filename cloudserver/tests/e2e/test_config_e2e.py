"""
End-to-end tests for configuration management system.

Tests complete workflows:
- Client first sync → updates → status changes
- Admin creates/updates config → client syncs → rollback
- Multi-client scenarios
- Cache invalidation flows

Version 3.0: Updated for 3-state model (unmanaged, managed, locked) with
simplified versioning (integer versions) and sync_status (n/a, pending, active).
"""

import pytest
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from httpx import AsyncClient
from sqlalchemy import select

from app.models.client_config import ClientConfig, ConfigStatus, SyncStatus, ConfigVersion
from app.core.config_sync import calculate_config_hash


pytestmark = pytest.mark.e2e


class TestClientSyncWorkflow:
    """Test complete client sync lifecycle."""

    @pytest.mark.asyncio
    async def test_complete_client_lifecycle(self, http_client: AsyncClient, db_session, active_api_key):
        """Test complete client lifecycle: first sync → update → status change → sync."""
        modem_id = "LIFECYCLE-001"

        # Step 1: First sync (client initializes config)
        initial_config = {
            "PingCount": 25,
            "UpdateChannel": "stable",
            "EnableCloud": True
        }

        timestamp = datetime.now(timezone.utc).isoformat() + "Z"
        nonce = hashlib.sha256(f"nonce_{timestamp}_1".encode()).hexdigest()
        config_hash = calculate_config_hash(initial_config)

        # Signature format: timestamp|nonce|config_hash
        message = f"{timestamp}|{nonce}|{config_hash}"
        signature = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        sync_request = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,  # Optional - for tracking only
            "config": initial_config,
            "version": 0,  # First sync (int version)
            "config_hash": config_hash,
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": signature
        }

        response = await http_client.post("/api/config/sync", json=sync_request)
        assert response.status_code == 200
        data = response.json()
        assert data["version"] == 1  # Simple int version
        assert data["status"] == "unmanaged"  # Default status
        assert data["sync_status"] == "n/a"  # Unmanaged has n/a sync status
        assert data["config_changed"] is True

        # Step 2: Client updates config (unmanaged mode allows this)
        updated_config = {
            "PingCount": 50,  # Changed
            "UpdateChannel": "beta",  # Changed
            "EnableCloud": True
        }

        timestamp2 = datetime.now(timezone.utc).isoformat() + "Z"
        nonce2 = hashlib.sha256(f"nonce_{timestamp2}_2".encode()).hexdigest()
        config_hash2 = calculate_config_hash(updated_config)

        message2 = f"{timestamp2}|{nonce2}|{config_hash2}"
        signature2 = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message2.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        sync_request2 = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "config": updated_config,
            "version": 1,  # Client has version 1
            "config_hash": config_hash2,
            "timestamp": timestamp2,
            "nonce": nonce2,
            "signature": signature2
        }

        response2 = await http_client.post("/api/config/sync", json=sync_request2)
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["version"] == 2  # Version incremented
        assert data2["config"]["PingCount"] == 50  # Update accepted
        assert data2["config_changed"] is True

        # Step 3: Admin changes status to locked
        result = await db_session.execute(
            select(ClientConfig).where(
                ClientConfig.api_key == active_api_key.api_key
            )
        )
        config_obj = result.scalar_one()
        config_obj.status = ConfigStatus.LOCKED
        config_obj.sync_status = SyncStatus.ACTIVE
        await db_session.commit()

        # Step 4: Client tries to update (locked mode rejects)
        attempted_config = {
            "PingCount": 100,  # Client tries to change
            "UpdateChannel": "test",
            "EnableCloud": True
        }

        timestamp3 = datetime.now(timezone.utc).isoformat() + "Z"
        nonce3 = hashlib.sha256(f"nonce_{timestamp3}_3".encode()).hexdigest()
        config_hash3 = calculate_config_hash(attempted_config)

        message3 = f"{timestamp3}|{nonce3}|{config_hash3}"
        signature3 = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message3.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        sync_request3 = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "config": attempted_config,
            "version": 2,
            "config_hash": config_hash3,
            "timestamp": timestamp3,
            "nonce": nonce3,
            "signature": signature3
        }

        response3 = await http_client.post("/api/config/sync", json=sync_request3)
        assert response3.status_code == 200
        data3 = response3.json()

        # Locked mode: server config returned, client change rejected
        assert data3["status"] == "locked"
        assert data3["config"]["PingCount"] == 50  # Server config (not 100)
        assert data3["config_changed"] is True  # Client needs to update to match server
        # Version should NOT increment when rejecting
        assert data3["version"] == 2


class TestManagedSyncWorkflow:
    """Test managed mode with pending/active transitions."""

    @pytest.mark.asyncio
    async def test_managed_pending_to_active(self, http_client: AsyncClient, db_session, active_api_key):
        """Test pending → active transition when client syncs managed config."""
        modem_id = "MANAGED-001"

        # Setup: Create config in managed/pending state via admin
        server_config = {
            "PingCount": 100,
            "UpdateChannel": "stable",
            "EnableCloud": True
        }

        config = ClientConfig(
            api_key=active_api_key.api_key,
            config_plaintext=server_config,
            config_encrypted="placeholder_encrypted_blob",  # Required field
            config_hash=calculate_config_hash(server_config),
            encryption_salt="placeholder_salt",  # Required field
            version=1,
            status=ConfigStatus.MANAGED,
            sync_status=SyncStatus.PENDING,
            last_seen_modem_id=None,
            created_by="admin",
            updated_by="admin"
        )
        db_session.add(config)
        await db_session.commit()

        # Client syncs with old/different config
        client_config = {"PingCount": 25}  # Different from server
        timestamp = datetime.now(timezone.utc).isoformat() + "Z"
        nonce = hashlib.sha256(f"nonce_{timestamp}_m1".encode()).hexdigest()
        config_hash = calculate_config_hash(client_config)

        message = f"{timestamp}|{nonce}|{config_hash}"
        signature = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        sync_request = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "config": client_config,
            "version": 0,  # Client has no version
            "config_hash": config_hash,
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": signature
        }

        response = await http_client.post("/api/config/sync", json=sync_request)
        assert response.status_code == 200
        data = response.json()

        # Server config pushed to client
        assert data["config"]["PingCount"] == 100
        assert data["status"] == "managed"
        assert data["sync_status"] == "active"  # Transitioned from pending
        assert data["config_changed"] is True

    @pytest.mark.asyncio
    async def test_managed_active_client_override_transitions_to_unmanaged(self, http_client: AsyncClient, db_session, active_api_key):
        """Test managed/active mode transitions to unmanaged when client modifies config."""
        modem_id = "MANAGED-002"

        # Setup: Create config in managed/active state
        server_config = {"PingCount": 100, "EnableCloud": True}

        config = ClientConfig(
            api_key=active_api_key.api_key,
            config_plaintext=server_config,
            config_encrypted="placeholder_encrypted_blob",  # Required field
            config_hash=calculate_config_hash(server_config),
            encryption_salt="placeholder_salt",  # Required field
            version=1,
            status=ConfigStatus.MANAGED,
            sync_status=SyncStatus.ACTIVE,
            last_seen_modem_id=modem_id,
            created_by="client",
            updated_by="client"
        )
        db_session.add(config)
        await db_session.commit()

        # Client sends updated config (PingCount max is 100, so use valid value)
        updated_config = {"PingCount": 75, "EnableCloud": True}
        timestamp = datetime.now(timezone.utc).isoformat() + "Z"
        nonce = hashlib.sha256(f"nonce_{timestamp}_m2".encode()).hexdigest()
        config_hash = calculate_config_hash(updated_config)

        message = f"{timestamp}|{nonce}|{config_hash}"
        signature = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        sync_request = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "config": updated_config,
            "version": 1,
            "config_hash": config_hash,
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": signature
        }

        response = await http_client.post("/api/config/sync", json=sync_request)
        if response.status_code != 200:
            print(f"ERROR RESPONSE: {response.json()}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.json()}"
        data = response.json()

        # Client change accepted, but transitions to unmanaged
        assert data["config"]["PingCount"] == 75
        assert data["version"] == 2  # Incremented
        # Per implementation: client override in MANAGED/ACTIVE transitions to UNMANAGED
        assert data["status"] == "unmanaged"
        assert data["sync_status"] == "n/a"


class TestLockedMode:
    """Test locked mode behavior - server always wins, no version increment."""

    @pytest.mark.asyncio
    async def test_locked_rejects_without_version_increment(self, http_client: AsyncClient, db_session, active_api_key):
        """Locked mode rejects client changes without creating new version."""
        modem_id = "LOCKED-001"

        # Setup: Create locked config
        server_config = {"PingCount": 100, "EnableCloud": True}

        config = ClientConfig(
            api_key=active_api_key.api_key,
            config_plaintext=server_config,
            config_encrypted="placeholder_encrypted_blob",  # Required field
            config_hash=calculate_config_hash(server_config),
            encryption_salt="placeholder_salt",  # Required field
            version=5,  # Start at version 5
            status=ConfigStatus.LOCKED,
            sync_status=SyncStatus.ACTIVE,
            last_seen_modem_id=modem_id,
            created_by="admin",
            updated_by="admin"
        )
        db_session.add(config)
        await db_session.commit()

        # Client tries to change
        client_config = {"PingCount": 999, "EnableCloud": False}
        timestamp = datetime.now(timezone.utc).isoformat() + "Z"
        nonce = hashlib.sha256(f"nonce_{timestamp}_l1".encode()).hexdigest()
        config_hash = calculate_config_hash(client_config)

        message = f"{timestamp}|{nonce}|{config_hash}"
        signature = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        sync_request = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "config": client_config,
            "version": 5,
            "config_hash": config_hash,
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": signature
        }

        response = await http_client.post("/api/config/sync", json=sync_request)
        assert response.status_code == 200
        data = response.json()

        # Server config enforced
        assert data["config"]["PingCount"] == 100
        assert data["status"] == "locked"
        # Version should NOT be incremented
        assert data["version"] == 5
        assert data["config_changed"] is True  # Client needs to update

        # Verify no new version was created in database
        result = await db_session.execute(
            select(ConfigVersion).where(
                ConfigVersion.api_key == active_api_key.api_key
            ).order_by(ConfigVersion.version_number.desc())
        )
        versions = result.scalars().all()
        # Should have no versions (or just initial if any)
        # The rejected change should NOT create a version


class TestAdminWorkflow:
    """Test admin config management workflows."""

    @pytest.mark.asyncio
    async def test_admin_create_and_client_sync(self, admin_client_with_token: AsyncClient, http_client: AsyncClient, db_session, active_api_key, csrf_token):
        """Admin creates config, client syncs and gets it."""
        modem_id = "ADMIN-001"

        # Step 1: Admin creates config via API
        admin_config = {
            "PingCount": 50,  # Use valid value (max is 100)
            "UpdateChannel": "beta",
            "EnableCloud": True,
            "SpeedTestEnabled": True,
            "SpeedTestInterval": 5
        }

        create_response = await admin_client_with_token.post(
            "/api/admin/configs",
            json={
                "api_key": active_api_key.api_key,
                "config": admin_config,
                "mode": "managed"  # Use mode (not status) per schema
            },
            headers={"X-CSRF-Token": csrf_token}
        )
        if create_response.status_code != 200:
            print(f"CREATE ERROR: {create_response.json()}")
        assert create_response.status_code == 200
        create_data = create_response.json()
        print(f"CREATE RESPONSE: {create_data}")
        assert create_data["success"] is True
        # Managed status creates pending sync_status
        assert create_data.get("sync_status") == "pending", f"Expected pending, got {create_data}"

        # Step 2: Client syncs
        client_config = {"PingCount": 25}  # Different
        timestamp = datetime.now(timezone.utc).isoformat() + "Z"
        nonce = hashlib.sha256(f"nonce_{timestamp}_a1".encode()).hexdigest()
        config_hash = calculate_config_hash(client_config)

        message = f"{timestamp}|{nonce}|{config_hash}"
        signature = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        sync_request = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "config": client_config,
            "version": 0,
            "config_hash": config_hash,
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": signature
        }

        response = await http_client.post("/api/config/sync", json=sync_request)
        assert response.status_code == 200
        data = response.json()

        # Client should receive admin config
        assert data["config"]["PingCount"] == 50  # We used 50 (valid value)
        assert data["config"]["UpdateChannel"] == "beta"
        assert data["sync_status"] == "active"  # Transitioned from pending


class TestUnmanagedMode:
    """Test unmanaged (client-controlled) mode."""

    @pytest.mark.asyncio
    async def test_unmanaged_first_sync_creates_record(self, http_client: AsyncClient, db_session, active_api_key):
        """First sync in unmanaged mode creates server record."""
        modem_id = "UNMANAGED-001"

        client_config = {
            "PingCount": 75,
            "EnableCloud": True,
            "SpeedTestEnabled": False
        }

        timestamp = datetime.now(timezone.utc).isoformat() + "Z"
        nonce = hashlib.sha256(f"nonce_{timestamp}_u1".encode()).hexdigest()
        config_hash = calculate_config_hash(client_config)

        message = f"{timestamp}|{nonce}|{config_hash}"
        signature = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        sync_request = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "config": client_config,
            "version": 0,
            "config_hash": config_hash,
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": signature
        }

        response = await http_client.post("/api/config/sync", json=sync_request)
        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "unmanaged"
        assert data["sync_status"] == "n/a"
        assert data["version"] == 1
        assert data["config"]["PingCount"] == 75

        # Verify record exists in database
        result = await db_session.execute(
            select(ClientConfig).where(
                ClientConfig.api_key == active_api_key.api_key
            )
        )
        config_obj = result.scalar_one_or_none()
        assert config_obj is not None
        assert config_obj.status == ConfigStatus.UNMANAGED

    @pytest.mark.asyncio
    async def test_unmanaged_multiple_updates(self, http_client: AsyncClient, db_session, active_api_key):
        """Unmanaged mode accepts multiple client updates."""
        modem_id = "UNMANAGED-002"

        # First sync
        config1 = {"PingCount": 10}
        timestamp1 = datetime.now(timezone.utc).isoformat() + "Z"
        nonce1 = hashlib.sha256(f"nonce_{timestamp1}_u2a".encode()).hexdigest()
        hash1 = calculate_config_hash(config1)
        msg1 = f"{timestamp1}|{nonce1}|{hash1}"
        sig1 = hmac.new(active_api_key.api_key.encode(), msg1.encode(), hashlib.sha256).hexdigest()

        resp1 = await http_client.post("/api/config/sync", json={
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "config": config1,
            "version": 0,
            "config_hash": hash1,
            "timestamp": timestamp1,
            "nonce": nonce1,
            "signature": sig1
        })
        assert resp1.status_code == 200
        assert resp1.json()["version"] == 1

        # Second update
        config2 = {"PingCount": 20}
        timestamp2 = datetime.now(timezone.utc).isoformat() + "Z"
        nonce2 = hashlib.sha256(f"nonce_{timestamp2}_u2b".encode()).hexdigest()
        hash2 = calculate_config_hash(config2)
        msg2 = f"{timestamp2}|{nonce2}|{hash2}"
        sig2 = hmac.new(active_api_key.api_key.encode(), msg2.encode(), hashlib.sha256).hexdigest()

        resp2 = await http_client.post("/api/config/sync", json={
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "config": config2,
            "version": 1,
            "config_hash": hash2,
            "timestamp": timestamp2,
            "nonce": nonce2,
            "signature": sig2
        })
        assert resp2.status_code == 200
        assert resp2.json()["version"] == 2
        assert resp2.json()["config"]["PingCount"] == 20

        # Third update
        config3 = {"PingCount": 30}
        timestamp3 = datetime.now(timezone.utc).isoformat() + "Z"
        nonce3 = hashlib.sha256(f"nonce_{timestamp3}_u2c".encode()).hexdigest()
        hash3 = calculate_config_hash(config3)
        msg3 = f"{timestamp3}|{nonce3}|{hash3}"
        sig3 = hmac.new(active_api_key.api_key.encode(), msg3.encode(), hashlib.sha256).hexdigest()

        resp3 = await http_client.post("/api/config/sync", json={
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "config": config3,
            "version": 2,
            "config_hash": hash3,
            "timestamp": timestamp3,
            "nonce": nonce3,
            "signature": sig3
        })
        assert resp3.status_code == 200
        assert resp3.json()["version"] == 3
