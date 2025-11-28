"""
End-to-end tests for configuration management system.

Tests complete workflows:
- Client first sync → updates → status changes
- Admin creates/updates config → client syncs → rollback
- Multi-client scenarios
- Cache invalidation flows
- Failover scenarios

Updated for dual-track versioning (v#_client / v#_server format).
"""

import pytest
import hashlib
import hmac
from datetime import datetime, timedelta
from httpx import AsyncClient
from sqlalchemy import select

from app.models.client_config import ClientConfig, ConfigStatus, ConfigVersion
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

        timestamp = datetime.utcnow().isoformat() + "Z"
        nonce = hashlib.sha256(f"nonce_{timestamp}_1".encode()).hexdigest()
        config_hash = calculate_config_hash(initial_config)

        # v2.1: signature format excludes modem_id
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
            "version": None,  # First sync
            "config_hash": config_hash,
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": signature
        }

        response = await http_client.post("/api/config/sync", json=sync_request)
        assert response.status_code == 200
        data = response.json()
        assert data["version"] == "v1_client"  # Dual-track versioning
        assert data["status"] == "unmanaged"  # Default status
        assert data["config_changed"] is True

        # Step 2: Client updates config (unmanaged mode allows this)
        updated_config = {
            "PingCount": 50,  # Changed
            "UpdateChannel": "beta",  # Changed
            "EnableCloud": True
        }

        timestamp2 = datetime.utcnow().isoformat() + "Z"
        nonce2 = hashlib.sha256(f"nonce_{timestamp2}_2".encode()).hexdigest()
        config_hash2 = calculate_config_hash(updated_config)

        # v2.1: signature format excludes modem_id
        message2 = f"{timestamp2}|{nonce2}|{config_hash2}"
        signature2 = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message2.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        sync_request2 = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,  # Optional - for tracking only
            "config": updated_config,
            "version": "v1_client",  # Client has version 1
            "config_hash": config_hash2,
            "timestamp": timestamp2,
            "nonce": nonce2,
            "signature": signature2
        }

        response2 = await http_client.post("/api/config/sync", json=sync_request2)
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["version"] == "v2_client"  # Version incremented
        assert data2["config"]["PingCount"] == 50  # Update accepted
        assert data2["config_changed"] is True

        # Step 3: Admin changes status to enforced_active
        # Note: Primary key is api_key only now (not composite with modem_id)
        result = await db_session.execute(
            select(ClientConfig).where(
                ClientConfig.api_key == active_api_key.api_key
            )
        )
        config_obj = result.scalar_one()
        config_obj.status = ConfigStatus.ENFORCED_ACTIVE
        await db_session.commit()

        # Step 4: Client tries to update (enforced mode rejects)
        attempted_config = {
            "PingCount": 100,  # Client tries to change
            "UpdateChannel": "test",
            "EnableCloud": True
        }

        timestamp3 = datetime.utcnow().isoformat() + "Z"
        nonce3 = hashlib.sha256(f"nonce_{timestamp3}_3".encode()).hexdigest()
        config_hash3 = calculate_config_hash(attempted_config)

        # v2.1: signature format excludes modem_id
        message3 = f"{timestamp3}|{nonce3}|{config_hash3}"
        signature3 = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message3.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        sync_request3 = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,  # Optional - for tracking only
            "config": attempted_config,
            "version": "v2_client",
            "config_hash": config_hash3,
            "timestamp": timestamp3,
            "nonce": nonce3,
            "signature": signature3
        }

        response3 = await http_client.post("/api/config/sync", json=sync_request3)
        assert response3.status_code == 200
        data3 = response3.json()
        assert data3["status"] == "enforced_active"
        assert data3["config"]["PingCount"] == 50  # Server config returned (not client's 100)
        assert data3["config_changed"] is True  # Enforced mode always signals config


class TestAdminWorkflow:
    """Test complete admin management workflow."""

    @pytest.mark.asyncio
    async def test_admin_manages_client_config(self, http_client: AsyncClient, db_session, admin_client_with_token: AsyncClient, active_api_key, csrf_token):
        """Test admin creates config → updates → client syncs → admin rollback."""
        modem_id = "ADMIN-MANAGED-001"

        # Step 1: Client does first sync
        initial_config = {"PingCount": 25, "UpdateChannel": "stable"}
        timestamp = datetime.utcnow().isoformat() + "Z"
        nonce = hashlib.sha256(f"nonce_{timestamp}_1".encode()).hexdigest()
        config_hash = calculate_config_hash(initial_config)

        # v2.1: signature format excludes modem_id
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
            "version": None,
            "config_hash": config_hash,
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": signature
        }

        response = await http_client.post("/api/config/sync", json=sync_request)
        assert response.status_code == 200

        # Step 2: Admin updates config to enforced mode
        new_config = {"PingCount": 50, "UpdateChannel": "stable"}  # Admin enforces new settings

        update_request = {
            "config": new_config,
            "mode": "enforced",  # Enforce config
            "check_reachability": False
        }

        # Note: Admin endpoints now use api_key only (not api_key/modem_id)
        response2 = await admin_client_with_token.put(
            f"/api/admin/configs/{active_api_key.api_key}",
            json=update_request,
            headers={"X-CSRF-Token": csrf_token}
        )

        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["version"] == "v1_server"  # Server version created
        assert "enforced" in data2["status"]
        assert data2["backup_created"] is True

        # Step 3: Client syncs and gets new enforced config
        timestamp2 = datetime.utcnow().isoformat() + "Z"
        nonce2 = hashlib.sha256(f"nonce_{timestamp2}_2".encode()).hexdigest()

        # Client still has old config but will get new one
        old_config_hash = calculate_config_hash(initial_config)
        # v2.1: signature format excludes modem_id
        message2 = f"{timestamp2}|{nonce2}|{old_config_hash}"
        signature2 = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message2.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        sync_request2 = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,  # Optional - for tracking only
            "config": initial_config,  # Client's old config
            "version": "v1_client",
            "config_hash": old_config_hash,
            "timestamp": timestamp2,
            "nonce": nonce2,
            "signature": signature2
        }

        response3 = await http_client.post("/api/config/sync", json=sync_request2)
        assert response3.status_code == 200
        data3 = response3.json()
        assert "enforced" in data3["status"]
        assert data3["config"]["PingCount"] == 50  # New server config
        assert "_server" in data3["version"]

        # Step 4: Admin realizes mistake and rolls back
        # Note: Need fresh CSRF token (one-time use)
        session_resp = await admin_client_with_token.get("/api/auth/session_check")
        csrf_token2 = session_resp.json()["csrf_token"]

        rollback_request = {"reason": "Revert to original settings"}

        response4 = await admin_client_with_token.post(
            f"/api/admin/configs/{active_api_key.api_key}/rollback/v1_client",
            json=rollback_request,
            headers={"X-CSRF-Token": csrf_token2}
        )

        assert response4.status_code == 200
        data4 = response4.json()
        assert data4["rolled_back_to"] == "v1_client"
        assert "_server" in data4["version"]  # New server version created by rollback
        assert data4["config"]["PingCount"] == 25  # Back to original

        # Step 5: Verify history shows all changes
        response5 = await admin_client_with_token.get(
            f"/api/admin/configs/{active_api_key.api_key}/history",
        )

        assert response5.status_code == 200
        data5 = response5.json()
        assert len(data5["versions"]) >= 2  # At least 2 versions


class TestMultiClientScenarios:
    """Test scenarios with multiple clients.

    Note: With v2.1 architecture (one API key = one config), multiple modems
    using the same API key share the same configuration. The last_seen_modem_id
    tracks which modem last synced.
    """

    @pytest.mark.asyncio
    async def test_multiple_modems_share_config(self, http_client: AsyncClient, db_session, active_api_key):
        """Multiple modems with same API key share the same configuration."""
        # With v2.1, all modems using same API key share one config
        # Each sync updates last_seen_modem_id

        last_config = None
        for i in range(3):
            modem_id = f"MULTI-{i:03d}"
            config = {"PingCount": 20 + (i * 10), "UpdateChannel": "stable"}

            timestamp = datetime.utcnow().isoformat() + "Z"
            nonce = hashlib.sha256(f"nonce_{timestamp}_{i}".encode()).hexdigest()
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
                "modem_id": modem_id,  # Optional - for tracking only
                "config": config,
                "version": None if i == 0 else last_config["version"],  # Use version from prev sync
                "config_hash": config_hash,
                "timestamp": timestamp,
                "nonce": nonce,
                "signature": signature
            }

            response = await http_client.post("/api/config/sync", json=sync_request)
            assert response.status_code == 200
            last_config = response.json()

        # Verify only ONE config exists for this API key (not 3)
        result = await db_session.execute(
            select(ClientConfig).where(
                ClientConfig.api_key == active_api_key.api_key
            )
        )
        configs = result.scalars().all()
        assert len(configs) == 1

        # Verify last_seen_modem_id tracks the last modem that synced
        config_obj = configs[0]
        assert config_obj.last_seen_modem_id == "MULTI-002"  # Last modem to sync

    @pytest.mark.asyncio
    async def test_enforced_config_affects_all_modems(self, http_client: AsyncClient, db_session, admin_client_with_token: AsyncClient, active_api_key, csrf_token):
        """Admin enforces config and it affects all modems using this API key."""
        # First modem syncs and creates config
        modem_id = "ENFORCE-001"
        config = {"PingCount": 25}
        timestamp = datetime.utcnow().isoformat() + "Z"
        nonce = hashlib.sha256(f"nonce_{timestamp}_1".encode()).hexdigest()
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
            "modem_id": modem_id,  # Optional - for tracking only
            "config": config,
            "version": None,
            "config_hash": config_hash,
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": signature
        }

        await http_client.post("/api/config/sync", json=sync_request)

        # Admin enforces config with new value
        update_request = {
            "config": {"PingCount": 30},  # New enforced value
            "mode": "enforced",
            "check_reachability": False
        }

        response = await admin_client_with_token.put(
            f"/api/admin/configs/{active_api_key.api_key}",
            json=update_request,
            headers={"X-CSRF-Token": csrf_token}
        )

        assert response.status_code == 200

        # DIFFERENT modem syncs with same API key and gets enforced config
        modem_id2 = "ENFORCE-002"
        config2 = {"PingCount": 50}  # Client tries different value
        timestamp2 = datetime.utcnow().isoformat() + "Z"
        nonce2 = hashlib.sha256(f"nonce_{timestamp2}_2".encode()).hexdigest()
        config_hash2 = calculate_config_hash(config2)

        message2 = f"{timestamp2}|{nonce2}|{config_hash2}"
        signature2 = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message2.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        sync_request2 = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id2,  # Different modem
            "config": config2,
            "version": None,  # New modem, doesn't know version
            "config_hash": config_hash2,
            "timestamp": timestamp2,
            "nonce": nonce2,
            "signature": signature2
        }

        response2 = await http_client.post("/api/config/sync", json=sync_request2)
        assert response2.status_code == 200
        data = response2.json()

        # Different modem gets enforced config, not its own
        assert data["config"]["PingCount"] == 30  # Server's enforced value
        assert "enforced" in data["status"]

        # Verify last_seen_modem_id was updated
        result = await db_session.execute(
            select(ClientConfig).where(ClientConfig.api_key == active_api_key.api_key)
        )
        config_obj = result.scalar_one()
        assert config_obj.last_seen_modem_id == "ENFORCE-002"  # Updated to last modem


class TestCacheInvalidationFlow:
    """Test cache invalidation during config updates."""

    @pytest.mark.asyncio
    async def test_update_invalidates_cache(self, http_client: AsyncClient, db_session, admin_client_with_token: AsyncClient, active_api_key, csrf_token):
        """Updating config invalidates cache."""
        modem_id = "CACHE-001"

        # Create initial config
        config = {"PingCount": 25}
        timestamp = datetime.utcnow().isoformat() + "Z"
        nonce = hashlib.sha256(f"nonce_{timestamp}_1".encode()).hexdigest()
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
            "modem_id": modem_id,  # Optional - for tracking only
            "config": config,
            "version": None,
            "config_hash": config_hash,
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": signature
        }

        response = await http_client.post("/api/config/sync", json=sync_request)
        assert response.status_code == 200

        # Admin updates config
        new_config = {"PingCount": 50}
        update_request = {
            "config": new_config,
            "mode": "one_time",
            "check_reachability": False
        }

        response2 = await admin_client_with_token.put(
            f"/api/admin/configs/{active_api_key.api_key}",
            json=update_request,
            headers={"X-CSRF-Token": csrf_token}
        )

        assert response2.status_code == 200

        # Next sync gets updated value (cache was invalidated)
        timestamp2 = datetime.utcnow().isoformat() + "Z"
        nonce2 = hashlib.sha256(f"nonce_{timestamp2}_2".encode()).hexdigest()
        config_hash2 = calculate_config_hash(config)  # Client still has old hash

        # v2.1: signature format excludes modem_id
        message2 = f"{timestamp2}|{nonce2}|{config_hash2}"
        signature2 = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message2.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        sync_request2 = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,  # Optional - for tracking only
            "config": config,  # Old config
            "version": "v1_server",  # Admin updated to v1_server
            "config_hash": config_hash2,
            "timestamp": timestamp2,
            "nonce": nonce2,
            "signature": signature2
        }

        response3 = await http_client.post("/api/config/sync", json=sync_request2)
        assert response3.status_code == 200
        data = response3.json()

        # Validate cache was invalidated - client gets updated value
        assert data["config"]["PingCount"] == 50, "Cache should be invalidated, new value returned"
        assert data["config_changed"] is True, "Config should be marked as changed"
        assert "version" in data, "Response must include version"


class TestVersionConflictResolution:
    """Test handling of version conflicts.

    In UNMANAGED mode, the server accepts client updates regardless of version mismatch.
    This is by design - version conflicts are only enforced in ENFORCED mode.
    """

    @pytest.mark.asyncio
    async def test_unmanaged_mode_accepts_stale_version_updates(self, http_client: AsyncClient, db_session, active_api_key):
        """In unmanaged mode, client updates are accepted even with stale versions.

        This test documents that version conflict resolution is NOT enforced in unmanaged mode.
        The client's update always wins, allowing maximum flexibility for client-side control.
        """
        modem_id = "CONFLICT-001"

        # Initial sync (creates v1_client)
        config = {"PingCount": 25}
        timestamp = datetime.utcnow().isoformat() + "Z"
        nonce = hashlib.sha256(f"nonce_{timestamp}_1".encode()).hexdigest()
        config_hash = calculate_config_hash(config)

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

        response1 = await http_client.post("/api/config/sync", json=sync_request)
        assert response1.status_code == 200
        assert response1.json()["version"] == "v1_client"

        # Update to version 2 (creates v2_client)
        config2 = {"PingCount": 30}
        timestamp2 = datetime.utcnow().isoformat() + "Z"
        nonce2 = hashlib.sha256(f"nonce_{timestamp2}_2".encode()).hexdigest()
        config_hash2 = calculate_config_hash(config2)

        message2 = f"{timestamp2}|{nonce2}|{config_hash2}"
        signature2 = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message2.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        sync_request2 = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "config": config2,
            "version": "v1_client",
            "config_hash": config_hash2,
            "timestamp": timestamp2,
            "nonce": nonce2,
            "signature": signature2
        }

        response2 = await http_client.post("/api/config/sync", json=sync_request2)
        assert response2.status_code == 200
        assert response2.json()["version"] == "v2_client"

        # Try to update with stale v1_client version (server is at v2_client)
        # In UNMANAGED mode, this should be ACCEPTED (client wins)
        config3 = {"PingCount": 40}
        timestamp3 = datetime.utcnow().isoformat() + "Z"
        nonce3 = hashlib.sha256(f"nonce_{timestamp3}_3".encode()).hexdigest()
        config_hash3 = calculate_config_hash(config3)

        message3 = f"{timestamp3}|{nonce3}|{config_hash3}"
        signature3 = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message3.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        sync_request3 = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "config": config3,
            "version": "v1_client",  # Stale version
            "config_hash": config_hash3,
            "timestamp": timestamp3,
            "nonce": nonce3,
            "signature": signature3
        }

        response3 = await http_client.post("/api/config/sync", json=sync_request3)
        data = response3.json()

        # In unmanaged mode, the update is accepted (client always wins)
        assert response3.status_code == 200, f"Unmanaged mode should accept updates: {data}"
        assert data["config"]["PingCount"] == 40, \
            "In unmanaged mode, client's update should be accepted"
        # Version increments despite stale version being sent
        assert "client" in data["version"], "Should create new client version"


class TestBackupAndRollbackFlow:
    """Test complete backup and rollback workflows."""

    @pytest.mark.asyncio
    async def test_multiple_rollbacks(self, http_client: AsyncClient, db_session, admin_client_with_token: AsyncClient, active_api_key, csrf_token):
        """Test rolling back through multiple versions."""
        modem_id = "ROLLBACK-MULTI-001"

        # Create initial config (v1_client)
        config_v1 = {"PingCount": 25}
        timestamp = datetime.utcnow().isoformat() + "Z"
        nonce = hashlib.sha256(f"nonce_{timestamp}_1".encode()).hexdigest()
        config_hash = calculate_config_hash(config_v1)

        # v2.1: signature format excludes modem_id
        message = f"{timestamp}|{nonce}|{config_hash}"
        signature = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        sync_request = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,  # Optional - for tracking only
            "config": config_v1,
            "version": None,
            "config_hash": config_hash,
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": signature
        }

        await http_client.post("/api/config/sync", json=sync_request)

        # Update to v1_server (need fresh CSRF token for each admin request)
        update_v2 = {
            "config": {"PingCount": 50},
            "mode": "one_time",
            "check_reachability": False
        }
        await admin_client_with_token.put(
            f"/api/admin/configs/{active_api_key.api_key}",
            json=update_v2,
            headers={"X-CSRF-Token": csrf_token}
        )

        # Update to v2_server - get fresh CSRF token (one-time use)
        session_resp = await admin_client_with_token.get("/api/auth/session_check")
        csrf_token2 = session_resp.json()["csrf_token"]

        update_v3 = {
            "config": {"PingCount": 75},
            "mode": "one_time",
            "check_reachability": False
        }
        await admin_client_with_token.put(
            f"/api/admin/configs/{active_api_key.api_key}",
            json=update_v3,
            headers={"X-CSRF-Token": csrf_token2}
        )

        # Rollback to v1_client (original client config) - get fresh CSRF token
        session_resp = await admin_client_with_token.get("/api/auth/session_check")
        csrf_token3 = session_resp.json()["csrf_token"]

        rollback_request = {"reason": "Revert to original"}
        response = await admin_client_with_token.post(
            f"/api/admin/configs/{active_api_key.api_key}/rollback/v1_client",
            json=rollback_request,
            headers={"X-CSRF-Token": csrf_token3}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["config"]["PingCount"] == 25

        # Rollback to v1_server (first admin update) - get fresh CSRF token
        session_resp = await admin_client_with_token.get("/api/auth/session_check")
        csrf_token4 = session_resp.json()["csrf_token"]

        response2 = await admin_client_with_token.post(
            f"/api/admin/configs/{active_api_key.api_key}/rollback/v1_server",
            json=rollback_request,
            headers={"X-CSRF-Token": csrf_token4}
        )

        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["config"]["PingCount"] == 50


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
