"""
Unit tests for configuration sync orchestration.

Tests:
- Config hash calculation (canonical JSON)
- Nonce verification (replay protection, clock skew)
- Version creation (backup)
- Handler tests for 3-state model (unmanaged, managed, locked)
- SyncStatus transitions (n/a, pending, active)
- Version conflict detection (optimistic locking)
- Deadlock retry logic

Version 3.0: Updated for 3-state model with simplified versioning.
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
    create_config_version,
    sync_client_config_with_retry,
    _handle_unmanaged_sync,
    _handle_managed_sync,
    _handle_locked_sync,
    SyncResult
)
from app.core.security import TIMESTAMP_WINDOW_SECONDS as MAX_CLOCK_SKEW_SECONDS
from app.models.client_config import ClientConfig, ConfigStatus, SyncStatus, ConfigVersion, ConfigNonce
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

    def test_hash_whitespace_in_values(self):
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
    async def test_clock_skew_future_rejected(self):
        """Timestamp too far in future is rejected."""
        db = AsyncMock(spec=AsyncSession)

        future_time = datetime.now(timezone.utc) + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS + 10)

        with pytest.raises(ConfigClockSkewError):
            await verify_nonce(db, "abc123", "hash123", future_time, "1.2.3.4", "ARRIS-ABC")

    @pytest.mark.asyncio
    async def test_clock_skew_past_rejected(self):
        """Timestamp too far in past is rejected."""
        db = AsyncMock(spec=AsyncSession)

        past_time = datetime.now(timezone.utc) - timedelta(seconds=MAX_CLOCK_SKEW_SECONDS + 10)

        with pytest.raises(ConfigClockSkewError):
            await verify_nonce(db, "abc123", "hash123", past_time, "1.2.3.4", "ARRIS-ABC")

    @pytest.mark.asyncio
    async def test_clock_skew_within_tolerance_accepted(self):
        """Timestamp within tolerance is accepted."""
        db = AsyncMock(spec=AsyncSession)

        # Mock database query to return no existing nonce
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        # Just under the limit
        slight_future = datetime.now(timezone.utc) + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS - 5)

        # Should not raise
        await verify_nonce(db, "abc123", "hash123", slight_future, "1.2.3.4", "ARRIS-ABC")


class TestVersionCreation:
    """Test config version creation for history tracking."""

    @pytest.mark.asyncio
    async def test_create_version_stores_config(self):
        """create_config_version stores config data correctly."""
        import hashlib
        db = AsyncMock(spec=AsyncSession)

        config_data = {"PingCount": 25, "EnableCloud": True}
        config_hash = calculate_config_hash(config_data)
        version_number = 1
        api_key = "test-key-123"
        api_key_hash = hashlib.sha256(api_key.encode('utf-8')).hexdigest()
        modem_id = "ARRIS-001"
        actor = "client"

        await create_config_version(
            db=db,
            api_key_hash=api_key_hash,
            modem_id=modem_id,
            version_number=version_number,
            config_plaintext=config_data,
            config_encrypted="encrypted_blob_placeholder",
            config_hash=config_hash,
            encryption_salt="salt_placeholder",
            status=ConfigStatus.UNMANAGED,
            sync_status=SyncStatus.NA,
            created_by=actor,
            reason="test_version_creation",
            ip_address="1.2.3.4"
        )

        # Should have added version entry
        db.add.assert_called_once()
        added_version = db.add.call_args[0][0]
        assert isinstance(added_version, ConfigVersion)
        assert added_version.version_number == 1
        assert added_version.api_key_hash == api_key_hash


class TestSyncResult:
    """Test SyncResult dataclass behavior."""

    def test_sync_result_creation(self):
        """SyncResult holds all expected fields."""
        result = SyncResult(
            config={"PingCount": 25},
            version=1,
            status="unmanaged",
            sync_status="n/a",
            config_changed=True
        )

        assert result.config == {"PingCount": 25}
        assert result.version == 1
        assert result.status == "unmanaged"
        assert result.sync_status == "n/a"
        assert result.config_changed is True


class TestUnmanagedHandler:
    """Test _handle_unmanaged_sync behavior."""

    @pytest.mark.asyncio
    async def test_unmanaged_accepts_client_config(self):
        """Unmanaged mode accepts client configuration changes."""
        import hashlib
        db = AsyncMock(spec=AsyncSession)

        # Create existing config in unmanaged state
        api_key = "test-key"
        api_key_hash = hashlib.sha256(api_key.encode('utf-8')).hexdigest()
        existing_config = MagicMock(spec=ClientConfig)
        existing_config.api_key_hash = api_key_hash
        existing_config.config_plaintext = {"PingCount": 25}
        existing_config.version = 1
        existing_config.status = ConfigStatus.UNMANAGED
        existing_config.sync_status = SyncStatus.NA

        client_config = {"PingCount": 50, "EnableCloud": True}
        client_hash = calculate_config_hash(client_config)

        # Mock the encryption functions (cache invalidation now happens in router)
        with patch('app.core.config_sync.generate_salt', return_value='test_salt'), \
             patch('app.core.config_sync.encrypt_config', new_callable=AsyncMock, return_value=('encrypted_blob', 'iv')), \
             patch('app.core.config_sync.log_config_sync', new_callable=AsyncMock):

            result = await _handle_unmanaged_sync(
                db=db,
                api_key=api_key,
                existing_config=existing_config,
                modem_id="ARRIS-001",
                client_config=client_config,
                config_hash=client_hash,
                ip_address="1.2.3.4"
            )

        assert result.config == client_config
        assert result.version == 2  # Version incremented
        assert result.status == "unmanaged"
        assert result.sync_status == "n/a"
        assert result.config_changed is True

    @pytest.mark.asyncio
    async def test_unmanaged_no_change_if_same_hash(self):
        """Unmanaged mode returns current config if hash matches."""
        import hashlib
        db = AsyncMock(spec=AsyncSession)

        client_config = {"PingCount": 25}
        client_hash = calculate_config_hash(client_config)

        api_key = "test-key"
        api_key_hash = hashlib.sha256(api_key.encode('utf-8')).hexdigest()
        existing_config = MagicMock(spec=ClientConfig)
        existing_config.api_key_hash = api_key_hash
        existing_config.config_plaintext = client_config
        existing_config.version = 1
        existing_config.status = ConfigStatus.UNMANAGED
        existing_config.sync_status = SyncStatus.NA
        existing_config.config_hash = client_hash

        result = await _handle_unmanaged_sync(
            db=db,
            api_key=api_key,
            existing_config=existing_config,
            modem_id="ARRIS-001",
            client_config=client_config,
            config_hash=client_hash,
            ip_address="1.2.3.4"
        )

        assert result.config == client_config
        assert result.version == 1  # Version not changed
        assert result.config_changed is False


class TestManagedHandler:
    """Test _handle_managed_sync behavior."""

    @pytest.mark.asyncio
    async def test_managed_pending_returns_server_config(self):
        """Managed mode with pending status returns server config."""
        import hashlib
        db = AsyncMock(spec=AsyncSession)

        server_config = {"PingCount": 100, "EnableCloud": True}
        server_hash = calculate_config_hash(server_config)

        api_key = "test-key"
        api_key_hash = hashlib.sha256(api_key.encode('utf-8')).hexdigest()
        existing_config = MagicMock(spec=ClientConfig)
        existing_config.api_key_hash = api_key_hash
        existing_config.config_plaintext = server_config
        existing_config.version = 1
        existing_config.status = ConfigStatus.MANAGED
        existing_config.sync_status = SyncStatus.PENDING
        existing_config.config_hash = server_hash

        client_config = {"PingCount": 25}  # Client has different config
        client_hash = calculate_config_hash(client_config)

        # Mock audit logging (cache invalidation now happens in router)
        with patch('app.core.config_sync.log_status_change', new_callable=AsyncMock):

            result = await _handle_managed_sync(
                db=db,
                api_key=api_key,
                existing_config=existing_config,
                modem_id="ARRIS-001",
                client_config=client_config,
                config_hash=client_hash,
                ip_address="1.2.3.4"
            )

        assert result.config == server_config  # Server config returned
        assert result.sync_status == "active"  # Transitioned to active
        assert result.config_changed is True

    @pytest.mark.asyncio
    async def test_managed_active_client_override_transitions_to_unmanaged(self):
        """Managed mode with active status transitions to unmanaged when client modifies config."""
        import hashlib
        db = AsyncMock(spec=AsyncSession)

        server_config = {"PingCount": 100}
        api_key = "test-key"
        api_key_hash = hashlib.sha256(api_key.encode('utf-8')).hexdigest()
        existing_config = MagicMock(spec=ClientConfig)
        existing_config.api_key_hash = api_key_hash
        existing_config.config_plaintext = server_config
        existing_config.version = 1
        existing_config.status = ConfigStatus.MANAGED
        existing_config.sync_status = SyncStatus.ACTIVE
        existing_config.config_hash = calculate_config_hash(server_config)

        client_config = {"PingCount": 150}  # Client changed
        client_hash = calculate_config_hash(client_config)

        # Mock the encryption functions (cache invalidation now happens in router)
        with patch('app.core.config_sync.generate_salt', return_value='test_salt'), \
             patch('app.core.config_sync.encrypt_config', new_callable=AsyncMock, return_value=('encrypted_blob', 'iv')), \
             patch('app.core.config_sync.log_config_sync', new_callable=AsyncMock), \
             patch('app.core.config_sync.log_status_change', new_callable=AsyncMock):

            result = await _handle_managed_sync(
                db=db,
                api_key=api_key,
                existing_config=existing_config,
                modem_id="ARRIS-001",
                client_config=client_config,
                config_hash=client_hash,
                ip_address="1.2.3.4"
            )

        assert result.config == client_config  # Client change accepted
        assert result.version == 2  # Version incremented
        # Per implementation: client override in MANAGED/ACTIVE transitions to UNMANAGED
        assert result.status == "unmanaged"
        assert result.sync_status == "n/a"
        assert result.config_changed is True


class TestLockedHandler:
    """Test _handle_locked_sync behavior."""

    @pytest.mark.asyncio
    async def test_locked_rejects_client_changes(self):
        """Locked mode always returns server config, rejects client changes."""
        import hashlib
        db = AsyncMock(spec=AsyncSession)

        server_config = {"PingCount": 100, "EnableCloud": True}
        server_hash = calculate_config_hash(server_config)

        api_key = "test-key"
        api_key_hash = hashlib.sha256(api_key.encode('utf-8')).hexdigest()
        existing_config = MagicMock(spec=ClientConfig)
        existing_config.api_key_hash = api_key_hash
        existing_config.config_plaintext = server_config
        existing_config.version = 1
        existing_config.status = ConfigStatus.LOCKED
        existing_config.sync_status = SyncStatus.ACTIVE
        existing_config.config_hash = server_hash

        client_config = {"PingCount": 25, "EnableCloud": False}  # Client tries to change
        client_hash = calculate_config_hash(client_config)

        # Cache invalidation now happens in router
        result = await _handle_locked_sync(
            db=db,
            api_key=api_key,
            existing_config=existing_config,
            modem_id="ARRIS-001",
            client_config=client_config,
            config_hash=client_hash,
            ip_address="1.2.3.4"
        )

        assert result.config == server_config  # Server config enforced
        assert result.version == 1  # Version not changed for rejection
        assert result.status == "locked"
        assert result.config_changed is True  # Client needs to update

    @pytest.mark.asyncio
    async def test_locked_no_version_increment_on_reject(self):
        """Locked mode does NOT create new version when rejecting client config."""
        import hashlib
        db = AsyncMock(spec=AsyncSession)

        server_config = {"PingCount": 100}
        api_key = "test-key"
        api_key_hash = hashlib.sha256(api_key.encode('utf-8')).hexdigest()
        existing_config = MagicMock(spec=ClientConfig)
        existing_config.api_key_hash = api_key_hash
        existing_config.config_plaintext = server_config
        existing_config.version = 5
        existing_config.status = ConfigStatus.LOCKED
        existing_config.sync_status = SyncStatus.ACTIVE
        existing_config.config_hash = calculate_config_hash(server_config)

        client_config = {"PingCount": 999}  # Client tries to change
        client_hash = calculate_config_hash(client_config)

        # Cache invalidation now happens in router
        result = await _handle_locked_sync(
            db=db,
            api_key=api_key,
            existing_config=existing_config,
            modem_id="ARRIS-001",
            client_config=client_config,
            config_hash=client_hash,
            ip_address="1.2.3.4"
        )

        # Version should NOT be incremented - we're just returning existing config
        assert result.version == 5
        # db.add should NOT be called for new version
        assert db.add.call_count == 0  # No version created


class TestStatusTransitions:
    """Test sync_status transitions."""

    @pytest.mark.asyncio
    async def test_pending_to_active_on_sync(self):
        """Pending status transitions to active when client syncs."""
        import hashlib
        db = AsyncMock(spec=AsyncSession)

        server_config = {"PingCount": 100}
        api_key = "test-key"
        api_key_hash = hashlib.sha256(api_key.encode('utf-8')).hexdigest()
        existing_config = MagicMock(spec=ClientConfig)
        existing_config.api_key_hash = api_key_hash
        existing_config.config_plaintext = server_config
        existing_config.version = 1
        existing_config.status = ConfigStatus.MANAGED
        existing_config.sync_status = SyncStatus.PENDING
        existing_config.config_hash = calculate_config_hash(server_config)

        client_config = {"PingCount": 25}
        client_hash = calculate_config_hash(client_config)

        # Mock audit logging (cache invalidation now happens in router)
        with patch('app.core.config_sync.log_status_change', new_callable=AsyncMock):

            result = await _handle_managed_sync(
                db=db,
                api_key=api_key,
                existing_config=existing_config,
                modem_id="ARRIS-001",
                client_config=client_config,
                config_hash=client_hash,
                ip_address="1.2.3.4"
            )

        assert result.sync_status == "active"  # Transitioned from pending

    @pytest.mark.asyncio
    async def test_unmanaged_always_na(self):
        """Unmanaged status always has n/a sync_status."""
        import hashlib
        db = AsyncMock(spec=AsyncSession)

        api_key = "test-key"
        api_key_hash = hashlib.sha256(api_key.encode('utf-8')).hexdigest()
        existing_config = MagicMock(spec=ClientConfig)
        existing_config.api_key_hash = api_key_hash
        existing_config.config_plaintext = {"PingCount": 25}
        existing_config.version = 1
        existing_config.status = ConfigStatus.UNMANAGED
        existing_config.sync_status = SyncStatus.NA
        existing_config.config_hash = calculate_config_hash({"PingCount": 25})

        client_config = {"PingCount": 50}
        client_hash = calculate_config_hash(client_config)

        # Mock the encryption functions (cache invalidation now happens in router)
        with patch('app.core.config_sync.generate_salt', return_value='test_salt'), \
             patch('app.core.config_sync.encrypt_config', new_callable=AsyncMock, return_value=('encrypted_blob', 'iv')), \
             patch('app.core.config_sync.log_config_sync', new_callable=AsyncMock):

            result = await _handle_unmanaged_sync(
                db=db,
                api_key=api_key,
                existing_config=existing_config,
                modem_id="ARRIS-001",
                client_config=client_config,
                config_hash=client_hash,
                ip_address="1.2.3.4"
            )

        assert result.sync_status == "n/a"  # Always n/a for unmanaged
