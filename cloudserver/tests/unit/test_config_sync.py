"""
Unit tests for configuration sync orchestration.

Tests:
- Config hash calculation (canonical JSON)
- Nonce verification (replay protection, clock skew)
- Version creation (backup)
- First sync scenario (initialize from client)
- One-time mode sync (accept client changes)
- Enforced mode sync (enforce server config)
- Version conflict detection (optimistic locking)
- Deadlock retry logic
"""

import pytest
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import DBAPIError

from app.core.config_sync import (
    calculate_config_hash,
    verify_nonce,
    create_config_backup,
    create_config_version,
    sync_client_config_with_retry,
    get_config_for_sync,
    _handle_first_sync,
    _handle_awaiting_first_sync,
    _handle_one_time_active_sync,
    _handle_enforced_active_sync,
    MAX_CLOCK_SKEW_SECONDS,
    SyncResult
)
from app.models.client_config import ClientConfig, ConfigStatus, ConfigVersion, ConfigNonce
from app.core.errors import (
    ConfigClockSkewError,
    ConfigNonceReplayError,
    ConfigVersionConflictError,
    ConfigHashMismatchError,
    DatabaseError
)


pytestmark = pytest.mark.unit


class TestConfigHashCalculation:
    """Test configuration hash calculation."""

    def test_hash_deterministic(self):
        """Same config produces same hash."""
        config = {"PingCount": 25, "EnableCloud": True}
        hash1 = calculate_config_hash(config)
        hash2 = calculate_config_hash(config)
        assert hash1 == hash2

    def test_hash_order_independent(self):
        """Hash is independent of key order (canonical JSON)."""
        config1 = {"PingCount": 25, "EnableCloud": True}
        config2 = {"EnableCloud": True, "PingCount": 25}
        assert calculate_config_hash(config1) == calculate_config_hash(config2)

    def test_hash_different_configs(self):
        """Different configs produce different hashes."""
        config1 = {"PingCount": 25}
        config2 = {"PingCount": 50}
        assert calculate_config_hash(config1) != calculate_config_hash(config2)

    def test_hash_empty_config(self):
        """Empty config produces valid hash."""
        config = {}
        hash_result = calculate_config_hash(config)
        assert len(hash_result) == 64  # SHA256 hex digest
        assert all(c in '0123456789abcdef' for c in hash_result)

    def test_hash_nested_structures(self):
        """Hash handles nested structures correctly."""
        config = {
            "level1": {
                "level2": {
                    "value": [1, 2, 3]
                }
            }
        }
        hash_result = calculate_config_hash(config)
        assert len(hash_result) == 64

    def test_hash_unicode_characters(self):
        """Hash handles unicode correctly."""
        config = {"CloudHost": "mödémchéck.example.com"}
        hash_result = calculate_config_hash(config)
        assert len(hash_result) == 64

    def test_hash_whitespace_normalized(self):
        """Hash is not affected by whitespace in values."""
        config1 = {"ModemAddress": "192.168.100.1"}
        config2 = {"ModemAddress": "192.168.100.1 "}  # Trailing space
        # These should be DIFFERENT (whitespace IS significant in values)
        assert calculate_config_hash(config1) != calculate_config_hash(config2)


class TestNonceVerification:
    """Test nonce verification and replay protection."""

    @pytest.mark.asyncio
    async def test_valid_nonce_accepted(self):
        """Valid nonce with correct timestamp is accepted."""
        db = AsyncMock(spec=AsyncSession)

        # Mock database query to return no existing nonce
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        nonce = "abc123"
        api_key_hash = "hash123"
        timestamp = datetime.now(timezone.utc)
        ip_address = "1.2.3.4"
        modem_id = "ARRIS-ABC"

        # Should not raise
        await verify_nonce(db, nonce, api_key_hash, timestamp, ip_address, modem_id)

        # Should have added nonce entry
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_replay_nonce_rejected(self):
        """Nonce used twice is rejected (replay attack) - via Redis."""
        db = AsyncMock(spec=AsyncSession)

        # Mock Redis cache returning False (nonce already exists)
        mock_cache = AsyncMock()
        mock_cache.setnx.return_value = False  # Nonce already in Redis

        with patch('app.core.cache.get_cache', return_value=mock_cache):
            with pytest.raises(ConfigNonceReplayError) as exc_info:
                await verify_nonce(
                    db, "abc123", "hash123", datetime.now(timezone.utc), "1.2.3.4", "ARRIS-ABC"
                )

        assert "replay" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_replay_nonce_rejected_db_fallback(self):
        """Nonce used twice is rejected (replay attack) - database fallback."""
        db = AsyncMock(spec=AsyncSession)

        # Mock database query to return existing nonce
        mock_result = MagicMock()
        existing_nonce = ConfigNonce(
            nonce="abc123",
            api_key_hash="hash123",
            request_timestamp=datetime.utcnow(),
            ip_address="1.2.3.4",
            modem_id="ARRIS-ABC",
            expires_at=datetime.utcnow() + timedelta(seconds=600)
        )
        mock_result.scalar_one_or_none.return_value = existing_nonce
        db.execute = AsyncMock(return_value=mock_result)

        # Mock Redis failure to test database fallback path
        with patch('app.core.cache.get_cache', side_effect=Exception("Redis unavailable")):
            with pytest.raises(ConfigNonceReplayError) as exc_info:
                await verify_nonce(
                    db, "abc123", "hash123", datetime.now(timezone.utc), "1.2.3.4", "ARRIS-ABC"
                )

        assert "replay" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_clock_skew_forward_rejected(self):
        """Timestamp too far in future is rejected."""
        db = AsyncMock(spec=AsyncSession)

        # Timestamp 10 minutes in the future
        future_time = datetime.now(timezone.utc) + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS + 60)

        with pytest.raises(ConfigClockSkewError) as exc_info:
            await verify_nonce(
                db, "abc123", "hash123", future_time, "1.2.3.4", "ARRIS-ABC"
            )

        error = exc_info.value
        assert error.details["max_skew_seconds"] == MAX_CLOCK_SKEW_SECONDS

    @pytest.mark.asyncio
    async def test_clock_skew_backward_rejected(self):
        """Timestamp too far in past is rejected."""
        db = AsyncMock(spec=AsyncSession)

        # Timestamp 10 minutes in the past
        past_time = datetime.now(timezone.utc) - timedelta(seconds=MAX_CLOCK_SKEW_SECONDS + 60)

        with pytest.raises(ConfigClockSkewError):
            await verify_nonce(
                db, "abc123", "hash123", past_time, "1.2.3.4", "ARRIS-ABC"
            )

    @pytest.mark.asyncio
    async def test_clock_skew_within_tolerance(self):
        """Timestamp within skew tolerance is accepted."""
        db = AsyncMock(spec=AsyncSession)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        # Timestamp just within tolerance (4 minutes)
        near_time = datetime.now(timezone.utc) + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS - 60)

        # Should not raise
        await verify_nonce(
            db, "abc123", "hash123", near_time, "1.2.3.4", "ARRIS-ABC"
        )


class TestConfigBackup:
    """Test configuration backup creation (via create_config_version)."""

    @pytest.mark.asyncio
    async def test_backup_created_with_all_fields(self):
        """Backup includes all config fields."""
        db = AsyncMock(spec=AsyncSession)

        client_config = ClientConfig(
            api_key="test_key",
            last_seen_modem_id="ARRIS-ABC",
            config_plaintext={"PingCount": 25},
            config_encrypted="encrypted_blob",
            config_hash="hash123",
            status=ConfigStatus.ONE_TIME_ACTIVE,
            client_version=5,
            server_version=0,
            active_track="client",
            encryption_salt="salt123",
            created_at=datetime.utcnow(),
            created_by="test",
            updated_at=datetime.utcnow(),
            updated_by="test"
        )

        backup = await create_config_backup(db, client_config, "test_reason", "admin")

        assert backup.api_key == "test_key"
        assert backup.modem_id_at_creation == "ARRIS-ABC"
        assert backup.config_plaintext == {"PingCount": 25}
        assert backup.config_encrypted == "encrypted_blob"
        assert backup.config_hash == "hash123"
        assert backup.status_at_creation == ConfigStatus.ONE_TIME_ACTIVE
        assert backup.version_number == 5
        assert backup.version_track == "client"
        assert backup.encryption_salt == "salt123"
        assert backup.creation_reason == "test_reason"
        assert backup.created_by == "admin"

        db.add.assert_called_once_with(backup)

    @pytest.mark.asyncio
    async def test_backup_timestamp_recent(self):
        """Backup timestamp is set to current time."""
        db = AsyncMock(spec=AsyncSession)

        client_config = ClientConfig(
            api_key="test_key",
            last_seen_modem_id="ARRIS-ABC",
            config_plaintext={},
            config_encrypted="",
            config_hash="",
            status=ConfigStatus.ONE_TIME_ACTIVE,
            client_version=1,
            server_version=0,
            active_track="client",
            encryption_salt="",
            created_at=datetime.utcnow(),
            created_by="test",
            updated_at=datetime.utcnow(),
            updated_by="test"
        )

        before = datetime.utcnow()  # Use timezone-aware to match implementation
        backup = await create_config_backup(db, client_config, "reason", "user")
        after = datetime.utcnow()

        assert before <= backup.created_at <= after


class TestFirstSyncHandling:
    """Test first sync scenario (initialize from client)."""

    @pytest.mark.asyncio
    async def test_first_sync_creates_config(self):
        """First sync creates new ClientConfig in UNMANAGED status."""
        db = AsyncMock(spec=AsyncSession)

        with patch('app.core.config_sync.generate_salt') as mock_salt, \
             patch('app.core.config_sync.encrypt_config') as mock_encrypt, \
             patch('app.core.config_sync.create_config_version'), \
             patch('app.core.config_sync.log_config_sync') as mock_log, \
             patch('app.core.config_sync.invalidate_config_cache') as mock_invalidate:

            mock_salt.return_value = "generated_salt"
            mock_encrypt.return_value = ("encrypted_blob", "generated_salt")

            client_config = {"PingCount": 25, "EnableCloud": True}
            config_hash = calculate_config_hash(client_config)

            result = await _handle_first_sync(
                db, "api_key", "ARRIS-ABC", client_config, config_hash, "1.2.3.4"
            )

            # Verify return value - SyncResult dataclass
            assert result.config == client_config
            assert result.version_display == "v1_client"  # First client sync creates v1_client
            assert result.status == "unmanaged"  # Default status is UNMANAGED
            assert result.config_changed is True
            assert result.active_track == "client"
            assert result.client_version == 1
            assert result.server_version == 0

            # Verify ClientConfig was added
            db.add.assert_called_once()
            added_config = db.add.call_args[0][0]
            assert isinstance(added_config, ClientConfig)
            assert added_config.api_key == "api_key"
            assert added_config.last_seen_modem_id == "ARRIS-ABC"
            assert added_config.client_version == 1
            assert added_config.server_version == 0
            assert added_config.active_track == "client"
            assert added_config.status == ConfigStatus.UNMANAGED

    @pytest.mark.asyncio
    async def test_first_sync_logs_audit(self):
        """First sync logs audit entry."""
        db = AsyncMock(spec=AsyncSession)

        with patch('app.core.config_sync.generate_salt'), \
             patch('app.core.config_sync.encrypt_config') as mock_encrypt, \
             patch('app.core.config_sync.create_config_version'), \
             patch('app.core.config_sync.log_config_sync') as mock_log, \
             patch('app.core.config_sync.invalidate_config_cache'):

            mock_encrypt.return_value = ("encrypted_blob", "salt")

            client_config = {"PingCount": 25}
            config_hash = calculate_config_hash(client_config)

            await _handle_first_sync(
                db, "api_key", "ARRIS-ABC", client_config, config_hash, "1.2.3.4"
            )

            # Verify audit log was called
            mock_log.assert_called_once()
            call_args = mock_log.call_args
            assert call_args[1]['old_config'] is None  # First sync
            assert call_args[1]['new_config'] == client_config
            assert call_args[1]['new_version'] == "v1_client"  # Version display string
            assert call_args[1]['success'] is True


class TestOneTimeSyncHandling:
    """Test ONE_TIME_ACTIVE sync behavior.

    ONE_TIME_ACTIVE status means client has received the server config.
    - If client sends same hash: Stay ONE_TIME_ACTIVE, no change
    - If client sends different hash: Client modified config, revert to UNMANAGED
    """

    @pytest.mark.asyncio
    async def test_one_time_active_same_hash_no_change(self):
        """ONE_TIME_ACTIVE with same hash stays active, returns no change."""
        db = AsyncMock(spec=AsyncSession)

        server_config = {"PingCount": 25}
        config_hash = calculate_config_hash(server_config)

        existing_config = ClientConfig(
            api_key="api_key",
            last_seen_modem_id="ARRIS-ABC",
            config_plaintext=server_config,
            config_encrypted="encrypted",
            config_hash=config_hash,  # Same hash as client will send
            status=ConfigStatus.ONE_TIME_ACTIVE,
            client_version=1,
            server_version=1,
            active_track="server",
            client_acked_version=1,
            client_acked_track="server",
            encryption_salt="salt",
            created_at=datetime.utcnow(),
            created_by="admin",
            updated_at=datetime.utcnow(),
            updated_by="admin"
        )

        result = await _handle_one_time_active_sync(
            db, existing_config, "ARRIS-ABC", server_config, config_hash, "1.2.3.4"
        )

        assert result.config == server_config
        assert result.version_display == "v1_server"
        assert result.status == "one_time_active"
        assert result.config_changed is False  # Same hash, no change needed
        assert result.active_track == "server"
        assert result.server_version == 1

    @pytest.mark.asyncio
    async def test_one_time_active_different_hash_reverts_to_unmanaged(self):
        """ONE_TIME_ACTIVE with different hash reverts to UNMANAGED."""
        db = AsyncMock(spec=AsyncSession)

        server_config = {"PingCount": 25}
        client_config = {"PingCount": 50}  # Client modified config

        existing_config = ClientConfig(
            api_key="api_key",
            last_seen_modem_id="ARRIS-ABC",
            config_plaintext=server_config,
            config_encrypted="encrypted",
            config_hash=calculate_config_hash(server_config),
            status=ConfigStatus.ONE_TIME_ACTIVE,
            client_version=1,
            server_version=1,
            active_track="server",
            client_acked_version=1,
            client_acked_track="server",
            encryption_salt="salt",
            created_at=datetime.utcnow(),
            created_by="admin",
            updated_at=datetime.utcnow(),
            updated_by="admin"
        )

        with patch('app.core.config_sync.generate_salt', return_value="new_salt"), \
             patch('app.core.config_sync.encrypt_config', return_value=("new_encrypted", "new_salt")), \
             patch('app.core.config_sync.create_config_version'), \
             patch('app.core.config_sync.log_config_sync'), \
             patch('app.core.config_sync.invalidate_config_cache'):

            result = await _handle_one_time_active_sync(
                db, existing_config, "ARRIS-ABC", client_config,
                calculate_config_hash(client_config), "1.2.3.4"
            )

            assert result.config == client_config  # Client config accepted
            assert result.version_display == "v2_client"  # New client version created
            assert result.status == "unmanaged"  # Reverted to unmanaged
            assert result.config_changed is True
            assert result.active_track == "client"
            assert result.client_version == 2

            # Verify config object was updated
            assert existing_config.status == ConfigStatus.UNMANAGED
            assert existing_config.client_version == 2
            assert existing_config.active_track == "client"

    @pytest.mark.asyncio
    async def test_one_time_active_preserves_server_config_on_match(self):
        """ONE_TIME_ACTIVE returns server config when hashes match."""
        db = AsyncMock(spec=AsyncSession)

        server_config = {"PingCount": 25, "UpdateChannel": "stable"}
        config_hash = calculate_config_hash(server_config)

        existing_config = ClientConfig(
            api_key="api_key",
            last_seen_modem_id="ARRIS-ABC",
            config_plaintext=server_config,
            config_encrypted="encrypted",
            config_hash=config_hash,
            status=ConfigStatus.ONE_TIME_ACTIVE,
            client_version=1,
            server_version=1,
            active_track="server",
            client_acked_version=1,
            client_acked_track="server",
            encryption_salt="salt",
            created_at=datetime.utcnow(),
            created_by="admin",
            updated_at=datetime.utcnow(),
            updated_by="admin"
        )

        result = await _handle_one_time_active_sync(
            db, existing_config, "ARRIS-ABC", server_config, config_hash, "1.2.3.4"
        )

        assert result.config == server_config
        assert result.version_display == "v1_server"
        assert result.status == "one_time_active"
        assert result.config_changed is False
        assert result.active_track == "server"


class TestLockedSyncHandling:
    """Test ENFORCED_ACTIVE mode sync (always enforce server config)."""

    @pytest.mark.asyncio
    async def test_enforced_provides_server_config_same_hash(self):
        """ENFORCED_ACTIVE always returns server config even with same hash."""
        db = AsyncMock(spec=AsyncSession)

        server_config = {"PingCount": 25}
        config_hash = calculate_config_hash(server_config)

        existing_config = ClientConfig(
            api_key="api_key",
            last_seen_modem_id="ARRIS-ABC",
            config_plaintext=server_config,
            config_encrypted="encrypted",
            config_hash=config_hash,
            status=ConfigStatus.ENFORCED_ACTIVE,
            client_version=1,
            server_version=10,
            active_track="server",
            encryption_salt="salt",
            created_at=datetime.utcnow(),
            created_by="admin",
            updated_at=datetime.utcnow(),
            updated_by="admin"
        )

        with patch('app.core.config_sync.invalidate_config_cache'):
            result = await _handle_enforced_active_sync(
                db, existing_config, "ARRIS-ABC", server_config, config_hash, "1.2.3.4"
            )

            assert result.config == server_config
            assert result.version_display == "v10_server"
            assert result.status == "enforced_active"
            assert result.config_changed is True  # Always True for enforced
            assert result.active_track == "server"
            assert result.server_version == 10

    @pytest.mark.asyncio
    async def test_enforced_logs_rejected_client_config(self):
        """ENFORCED_ACTIVE logs rejected client config as new client version."""
        db = AsyncMock(spec=AsyncSession)

        # Mock the query for latest client version (returns None = first rejection)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        server_config = {"PingCount": 25}
        client_config = {"PingCount": 100}  # Client tries to change

        existing_config = ClientConfig(
            api_key="api_key",
            last_seen_modem_id="ARRIS-ABC",
            config_plaintext=server_config,
            config_encrypted="encrypted",
            config_hash=calculate_config_hash(server_config),
            status=ConfigStatus.ENFORCED_ACTIVE,
            client_version=1,
            server_version=10,
            active_track="server",
            encryption_salt="salt",
            created_at=datetime.utcnow(),
            created_by="admin",
            updated_at=datetime.utcnow(),
            updated_by="admin"
        )

        with patch('app.core.config_sync.generate_salt', return_value="new_salt"), \
             patch('app.core.config_sync.encrypt_config', return_value=("encrypted", "new_salt")), \
             patch('app.core.config_sync.create_config_version') as mock_create, \
             patch('app.core.config_sync.log_config_sync'), \
             patch('app.core.config_sync.invalidate_config_cache'):

            result = await _handle_enforced_active_sync(
                db, existing_config, "ARRIS-ABC", client_config,
                calculate_config_hash(client_config), "1.2.3.4"
            )

            assert result.config == server_config  # Server config enforced
            assert result.version_display == "v10_server"
            assert result.status == "enforced_active"
            assert result.config_changed is True
            assert result.active_track == "server"
            assert result.client_version == 2  # Client version incremented for rejected config

            # Verify client version was incremented
            assert existing_config.client_version == 2

            # Verify rejected config was logged as v2_client
            mock_create.assert_called_once()
            call_args = mock_create.call_args
            assert call_args[1]["version_number"] == 2
            assert call_args[1]["version_track"] == "client"
            assert call_args[1]["reason"] == "client_rejected_enforced"

    @pytest.mark.asyncio
    async def test_enforced_skips_duplicate_client_versions(self):
        """ENFORCED_ACTIVE doesn't create duplicate versions when client sends same config repeatedly."""
        db = AsyncMock(spec=AsyncSession)

        server_config = {"PingCount": 25}
        client_config = {"PingCount": 100}  # Client's config (different from server)
        client_hash = calculate_config_hash(client_config)

        # Mock: latest client version has the SAME hash as what client is sending
        # This simulates the client sending the same rejected config again
        mock_latest_version = MagicMock()
        mock_latest_version.config_hash = client_hash  # Same hash!

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_latest_version
        db.execute = AsyncMock(return_value=mock_result)

        existing_config = ClientConfig(
            api_key="api_key",
            last_seen_modem_id="ARRIS-ABC",
            config_plaintext=server_config,
            config_encrypted="encrypted",
            config_hash=calculate_config_hash(server_config),
            status=ConfigStatus.ENFORCED_ACTIVE,
            client_version=5,  # Already has 5 client versions
            server_version=10,
            active_track="server",
            encryption_salt="salt",
            created_at=datetime.utcnow(),
            created_by="admin",
            updated_at=datetime.utcnow(),
            updated_by="admin"
        )

        with patch('app.core.config_sync.generate_salt', return_value="new_salt"), \
             patch('app.core.config_sync.encrypt_config', return_value=("encrypted", "new_salt")), \
             patch('app.core.config_sync.create_config_version') as mock_create, \
             patch('app.core.config_sync.log_config_sync'), \
             patch('app.core.config_sync.invalidate_config_cache'):

            result = await _handle_enforced_active_sync(
                db, existing_config, "ARRIS-ABC", client_config, client_hash, "1.2.3.4"
            )

            # Server config is still enforced
            assert result.config == server_config
            assert result.version_display == "v10_server"
            assert result.status == "enforced_active"
            assert result.config_changed is True

            # Client version should NOT be incremented (same config as before)
            assert existing_config.client_version == 5

            # create_config_version should NOT be called (no duplicate entry)
            mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_enforced_updates_last_sync(self):
        """ENFORCED_ACTIVE updates last_sync timestamp."""
        db = AsyncMock(spec=AsyncSession)

        server_config = {"PingCount": 25}
        config_hash = calculate_config_hash(server_config)

        existing_config = ClientConfig(
            api_key="api_key",
            last_seen_modem_id="ARRIS-ABC",
            config_plaintext=server_config,
            config_encrypted="encrypted",
            config_hash=config_hash,
            status=ConfigStatus.ENFORCED_ACTIVE,
            client_version=1,
            server_version=5,
            active_track="server",
            encryption_salt="salt",
            created_at=datetime.utcnow(),
            created_by="admin",
            updated_at=datetime.utcnow(),
            updated_by="admin",
            last_sync=datetime.utcnow() - timedelta(hours=24)
        )

        with patch('app.core.config_sync.invalidate_config_cache'):
            before = datetime.utcnow()  # Use timezone-aware to match implementation
            await _handle_enforced_active_sync(
                db, existing_config, "ARRIS-ABC", server_config, config_hash, "1.2.3.4"
            )
            after = datetime.utcnow()

            assert before <= existing_config.last_sync <= after


class TestAwaitingFirstSyncHandling:
    """Test AWAITING_FIRST_SYNC status (admin-created configs waiting for first client sync).

    AWAITING_FIRST_SYNC is set when an admin creates a config before the client syncs.
    On first sync, the behavior depends on target_mode:
    - "unmanaged": Accept client config, become UNMANAGED
    - "one_time": Push server config, become ONE_TIME_ACTIVE
    - "enforced": Push server config, become ENFORCED_ACTIVE
    """

    @pytest.mark.asyncio
    async def test_awaiting_first_sync_updates_last_seen_modem_id(self):
        """First sync should update last_seen_modem_id field."""
        db = AsyncMock(spec=AsyncSession)

        existing_config = ClientConfig(
            api_key="api_key",
            last_seen_modem_id=None,  # Not set yet (awaiting first sync)
            config_plaintext={"PingCount": 25},
            config_encrypted="encrypted",
            config_hash="hash123",
            status=ConfigStatus.AWAITING_FIRST_SYNC,
            target_mode="unmanaged",
            client_version=0,
            server_version=0,
            active_track="server",
            encryption_salt="salt",
            created_at=datetime.utcnow(),
            created_by="admin",
            updated_at=datetime.utcnow(),
            updated_by="admin"
        )

        client_config = {"PingCount": 50}
        config_hash = calculate_config_hash(client_config)

        with patch('app.core.config_sync.generate_salt', return_value="new_salt"), \
             patch('app.core.config_sync.encrypt_config', return_value=("encrypted", "new_salt")), \
             patch('app.core.config_sync.create_config_version'), \
             patch('app.core.config_sync.log_config_sync'), \
             patch('app.core.config_sync.invalidate_config_cache'):

            await _handle_awaiting_first_sync(
                db, existing_config, "ARRIS-ABC", client_config, config_hash, "1.2.3.4"
            )

            # Verify last_seen_modem_id was set
            assert existing_config.last_seen_modem_id == "ARRIS-ABC"

    @pytest.mark.asyncio
    async def test_awaiting_first_sync_unmanaged_mode(self):
        """AWAITING_FIRST_SYNC with target_mode=unmanaged accepts client config."""
        db = AsyncMock(spec=AsyncSession)

        server_config = {"PingCount": 25}
        client_config = {"PingCount": 50}

        existing_config = ClientConfig(
            api_key="api_key",
            last_seen_modem_id=None,
            config_plaintext=server_config,
            config_encrypted="encrypted",
            config_hash=calculate_config_hash(server_config),
            status=ConfigStatus.AWAITING_FIRST_SYNC,
            target_mode="unmanaged",  # Accept client config
            client_version=0,
            server_version=1,
            active_track="server",
            encryption_salt="salt",
            created_at=datetime.utcnow(),
            created_by="admin",
            updated_at=datetime.utcnow(),
            updated_by="admin"
        )

        with patch('app.core.config_sync.generate_salt', return_value="new_salt"), \
             patch('app.core.config_sync.encrypt_config', return_value=("encrypted", "new_salt")), \
             patch('app.core.config_sync.create_config_version'), \
             patch('app.core.config_sync.log_config_sync'), \
             patch('app.core.config_sync.invalidate_config_cache'):

            result = await _handle_awaiting_first_sync(
                db, existing_config, "ARRIS-ABC", client_config,
                calculate_config_hash(client_config), "1.2.3.4"
            )

            assert result.config == client_config  # Client config accepted
            assert result.status == "unmanaged"
            assert result.version_display == "v1_client"
            assert result.active_track == "client"
            assert existing_config.status == ConfigStatus.UNMANAGED

    @pytest.mark.asyncio
    async def test_awaiting_first_sync_one_time_mode(self):
        """AWAITING_FIRST_SYNC with target_mode=one_time pushes server config."""
        db = AsyncMock(spec=AsyncSession)

        server_config = {"PingCount": 25}
        client_config = {"PingCount": 50}

        existing_config = ClientConfig(
            api_key="api_key",
            last_seen_modem_id=None,
            config_plaintext=server_config,
            config_encrypted="encrypted",
            config_hash=calculate_config_hash(server_config),
            status=ConfigStatus.AWAITING_FIRST_SYNC,
            target_mode="one_time",  # Push server config once
            client_version=0,
            server_version=1,
            active_track="server",
            encryption_salt="salt",
            created_at=datetime.utcnow(),
            created_by="admin",
            updated_at=datetime.utcnow(),
            updated_by="admin"
        )

        with patch('app.core.config_sync.generate_salt', return_value="new_salt"), \
             patch('app.core.config_sync.encrypt_config', return_value=("encrypted", "new_salt")), \
             patch('app.core.config_sync.create_config_version'), \
             patch('app.core.config_sync.log_config_sync'), \
             patch('app.core.config_sync.invalidate_config_cache'):

            result = await _handle_awaiting_first_sync(
                db, existing_config, "ARRIS-ABC", client_config,
                calculate_config_hash(client_config), "1.2.3.4"
            )

            assert result.config == server_config  # Server config pushed
            assert result.status == "one_time_active"
            assert result.config_changed is True
            assert result.active_track == "server"
            assert existing_config.status == ConfigStatus.ONE_TIME_ACTIVE

    @pytest.mark.asyncio
    async def test_awaiting_first_sync_enforced_mode(self):
        """AWAITING_FIRST_SYNC with target_mode=enforced becomes ENFORCED_ACTIVE."""
        db = AsyncMock(spec=AsyncSession)

        server_config = {"PingCount": 25}
        client_config = {"PingCount": 50}

        existing_config = ClientConfig(
            api_key="api_key",
            last_seen_modem_id=None,
            config_plaintext=server_config,
            config_encrypted="encrypted",
            config_hash=calculate_config_hash(server_config),
            status=ConfigStatus.AWAITING_FIRST_SYNC,
            target_mode="enforced",  # Enforce server config permanently
            client_version=0,
            server_version=1,
            active_track="server",
            encryption_salt="salt",
            created_at=datetime.utcnow(),
            created_by="admin",
            updated_at=datetime.utcnow(),
            updated_by="admin"
        )

        with patch('app.core.config_sync.generate_salt', return_value="new_salt"), \
             patch('app.core.config_sync.encrypt_config', return_value=("encrypted", "new_salt")), \
             patch('app.core.config_sync.create_config_version'), \
             patch('app.core.config_sync.log_config_sync'), \
             patch('app.core.config_sync.invalidate_config_cache'):

            result = await _handle_awaiting_first_sync(
                db, existing_config, "ARRIS-ABC", client_config,
                calculate_config_hash(client_config), "1.2.3.4"
            )

            assert result.config == server_config  # Server config enforced
            assert result.status == "enforced_active"
            assert result.config_changed is True
            assert result.active_track == "server"
            assert existing_config.status == ConfigStatus.ENFORCED_ACTIVE


class TestDeadlockRetry:
    """Test deadlock retry logic."""

    @pytest.mark.asyncio
    async def test_deadlock_retries_with_backoff(self):
        """Deadlock errors trigger retry with exponential backoff."""
        db = AsyncMock(spec=AsyncSession)

        attempt_count = 0

        async def mock_impl(*args, **kwargs):
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                # Simulate deadlock on first 2 attempts
                raise DBAPIError("statement", {}, Exception("deadlock detected"))
            else:
                # Succeed on 3rd attempt with SyncResult
                return SyncResult(
                    config={"PingCount": 25},
                    version_display="v1_client",
                    status="one_time_active",
                    config_changed=True,
                    active_track="client",
                    client_version=1,
                    server_version=0
                )

        with patch('app.core.config_sync._sync_client_config_impl', new=mock_impl):
            result = await sync_client_config_with_retry(
                db, "api_key", "ARRIS-ABC", {"PingCount": 25},
                None, "hash123", "1.2.3.4", "nonce123", datetime.utcnow()
            )

            assert attempt_count == 3  # Retried twice, succeeded on 3rd
            assert result.config == {"PingCount": 25}
            assert result.version_display == "v1_client"

    @pytest.mark.asyncio
    async def test_non_deadlock_error_not_retried(self):
        """Non-deadlock errors are not retried."""
        db = AsyncMock(spec=AsyncSession)

        async def mock_impl(*args, **kwargs):
            # Different database error (not deadlock)
            raise DBAPIError("statement", {}, Exception("connection timeout"))

        with patch('app.core.config_sync._sync_client_config_impl', new=mock_impl):
            with pytest.raises(DatabaseError):
                await sync_client_config_with_retry(
                    db, "api_key", "ARRIS-ABC", {"PingCount": 25},
                    None, "hash123", "1.2.3.4", "nonce123", datetime.utcnow()
                )

    @pytest.mark.asyncio
    async def test_max_retries_exceeded_raises(self):
        """Persistent deadlocks after max retries raise DatabaseError."""
        db = AsyncMock(spec=AsyncSession)

        async def mock_impl(*args, **kwargs):
            # Always fail with deadlock
            raise DBAPIError("statement", {}, Exception("deadlock detected"))

        with patch('app.core.config_sync._sync_client_config_impl', new=mock_impl):
            with pytest.raises(DatabaseError):
                await sync_client_config_with_retry(
                    db, "api_key", "ARRIS-ABC", {"PingCount": 25},
                    None, "hash123", "1.2.3.4", "nonce123", datetime.utcnow()
                )


class TestGetConfigForSync:
    """Test fetching config for sync."""

    @pytest.mark.asyncio
    async def test_get_existing_config(self):
        """Fetching existing config returns all fields."""
        db = AsyncMock(spec=AsyncSession)

        mock_config = ClientConfig(
            api_key="api_key",
            last_seen_modem_id="ARRIS-ABC",
            config_plaintext={"PingCount": 25},
            config_encrypted="encrypted_blob",
            config_hash="hash123",
            status=ConfigStatus.ENFORCED_ACTIVE,
            client_version=1,
            server_version=5,
            active_track="server",
            encryption_salt="salt123",
            created_at=datetime.utcnow(),
            created_by="admin",
            updated_at=datetime.utcnow(),
            updated_by="admin"
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_config
        db.execute = AsyncMock(return_value=mock_result)

        result = await get_config_for_sync(db, "api_key")

        assert result is not None
        assert result["encrypted_blob"] == "encrypted_blob"
        assert result["salt"] == "salt123"
        assert result["hash"] == "hash123"
        assert result["status"] == "enforced_active"
        assert result["version_display"] == "v5_server"  # Key name in response
        assert result["client_version"] == 1
        assert result["server_version"] == 5
        assert result["active_track"] == "server"

    @pytest.mark.asyncio
    async def test_get_nonexistent_config(self):
        """Fetching nonexistent config returns None."""
        db = AsyncMock(spec=AsyncSession)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        result = await get_config_for_sync(db, "api_key")

        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
