"""
Configuration sync orchestration with dual-track versioning and 6 status states.

This module coordinates the entire config sync workflow:
1. Validate client request (nonce, HMAC, clock skew)
2. Check cache or fetch from database
3. Handle sync based on status (6 states):
   - AWAITING_FIRST_SYNC: Admin pre-created config, waiting for client
   - UNMANAGED: Client-controlled, server just stores
   - ONE_TIME_READY: Server has config ready to push
   - ONE_TIME_ACTIVE: Client received and using server config
   - ENFORCED_READY: Server has config ready to enforce
   - ENFORCED_ACTIVE: Client using enforced config
4. Update database with optimistic locking
5. Create version history entries
6. Log audit trail
7. Invalidate cache

Dual-Track Versioning:
- Client versions (v#_client): Configs originating from client
- Server versions (v#_server): Configs set by admin
- Only one track is "active" at a time

Implements deadlock retry with exponential backoff.
"""

import asyncio
import hashlib
import json
import logging
import random
import warnings
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone, timedelta


@dataclass
class SyncResult:
    """Result of a config sync operation with all version info."""
    config: Dict[str, Any]
    version_display: str
    status: str
    config_changed: bool
    active_track: str
    client_version: int
    server_version: int

logger = logging.getLogger(__name__)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.models.client_config import (
    ClientConfig, ConfigStatus, ConfigVersion, ConfigNonce,
    ConfigMode  # Backward compatibility alias
)
from app.core.config_encryption import encrypt_config, decrypt_config, generate_salt
from app.core.config_validation import validate_config
from app.core.config_audit import log_config_sync, log_config_update, log_mode_change, create_config_summary
from app.core.config_cache import (
    get_cached_config,
    set_cached_config,
    invalidate_config_cache,
    get_or_fetch_config
)
from app.core.errors import (
    ConfigVersionConflictError,
    ConfigNonceReplayError,
    ConfigClockSkewError,
    ConfigHashMismatchError,
    ConfigLockedError,
    ConfigNotFoundError,
    DatabaseError
)


# Sync configuration
MAX_CLOCK_SKEW_SECONDS = 300  # 5 minutes
DEADLOCK_RETRY_ATTEMPTS = 5
DEADLOCK_RETRY_BASE_DELAY = 0.1  # 100ms base delay
DEADLOCK_RETRY_MAX_DELAY = 2.0  # 2 second max delay
DEADLOCK_JITTER_FACTOR = 0.5  # Add up to 50% jitter


def calculate_config_hash(config_dict: Dict[str, Any]) -> str:
    """
    Calculate SHA256 hash of configuration for integrity checking.

    Uses canonical JSON (sorted keys) to ensure consistent hashing.

    Args:
        config_dict: Configuration dictionary

    Returns:
        SHA256 hex digest
    """
    canonical_json = json.dumps(config_dict, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()


async def verify_nonce(
    db: AsyncSession,
    nonce: str,
    api_key_hash: str,
    request_timestamp: datetime,
    ip_address: str,
    modem_id: Optional[str] = None
) -> None:
    """
    Verify nonce is not a replay attack.

    Uses a two-tier approach:
    1. Redis cache (fast path, 10-100x faster)
    2. PostgreSQL (fallback for durability)

    Args:
        modem_id: Optional modem ID for tracking (may not be known at preflight)

    Raises:
        ConfigNonceReplayError: If nonce was already used
        ConfigClockSkewError: If timestamp too far from server time
    """
    from app.core.cache import get_cache

    # Check clock skew first (fast, no I/O)
    # Use timezone-aware datetime for comparison with request_timestamp
    server_time = datetime.now(timezone.utc)
    time_diff = abs((server_time - request_timestamp).total_seconds())

    if time_diff > MAX_CLOCK_SKEW_SECONDS:
        raise ConfigClockSkewError(
            client_time=request_timestamp.isoformat(),
            server_time=server_time.isoformat(),
            max_skew_seconds=MAX_CLOCK_SKEW_SECONDS
        )

    # Try Redis first (fast path)
    redis_key = f"nonce:{nonce}"
    nonce_ttl = MAX_CLOCK_SKEW_SECONDS * 2  # 10 minutes

    try:
        cache = await get_cache()
        # Use SETNX for atomic check-and-set
        # Returns True if set (nonce not seen), False if already exists (replay)
        is_new = await cache.setnx(redis_key, "used", ttl=nonce_ttl)

        if not is_new:
            # Nonce already in Redis - replay attack
            raise ConfigNonceReplayError(nonce=nonce)

        # Successfully added to Redis - also store in database for durability
    except ConfigNonceReplayError:
        raise  # Re-raise replay errors
    except Exception as e:
        # Redis unavailable - fall back to database-only checking
        logger.warning(f"Redis unavailable for nonce check, using database fallback: {e}")

        # Check if nonce was already used (replay attack) - database only
        existing_nonce = await db.execute(
            select(ConfigNonce).where(ConfigNonce.nonce == nonce)
        )
        if existing_nonce.scalar_one_or_none() is not None:
            raise ConfigNonceReplayError(nonce=nonce)

    # Store nonce in database for durability (regardless of Redis)
    nonce_entry = ConfigNonce.create_with_expiry(
        nonce=nonce,
        api_key_hash=api_key_hash,
        request_timestamp=request_timestamp,
        ip_address=ip_address,
        modem_id=modem_id,
        ttl_seconds=nonce_ttl
    )
    db.add(nonce_entry)


async def create_config_version(
    db: AsyncSession,
    api_key: str,
    modem_id: Optional[str],
    version_number: int,
    version_track: str,
    config_plaintext: Dict[str, Any],
    config_encrypted: str,
    config_hash: str,
    encryption_salt: str,
    status: ConfigStatus,
    created_by: str,
    reason: str,
    ip_address: Optional[str] = None
) -> ConfigVersion:
    """
    Create a version history entry for a configuration.

    Args:
        db: Database session
        api_key: Client API key
        modem_id: Modem ID at time of creation (for tracking, nullable)
        version_number: Version number (1, 2, 3...)
        version_track: "client" or "server"
        config_plaintext: Configuration data
        config_encrypted: Encrypted configuration
        config_hash: SHA256 hash
        encryption_salt: Encryption salt
        status: Current status when version was created
        created_by: Username or "client"
        reason: Reason for creating version
        ip_address: Client IP address

    Returns:
        Created ConfigVersion instance
    """
    version_display = f"v{version_number}_{version_track}"

    version_entry = ConfigVersion(
        api_key=api_key,
        modem_id_at_creation=modem_id,  # Renamed: tracking metadata only
        version_number=version_number,
        version_track=version_track,
        version_display=version_display,
        config_plaintext=config_plaintext,
        config_encrypted=config_encrypted,
        config_hash=config_hash,
        encryption_salt=encryption_salt,
        status_at_creation=status,
        created_at=datetime.utcnow(),
        created_by=created_by,
        creation_reason=reason,
        ip_address=ip_address
    )

    db.add(version_entry)
    return version_entry


async def sync_client_config_with_retry(
    db: AsyncSession,
    api_key: str,
    modem_id: Optional[str],
    client_config: Dict[str, Any],
    client_version: Optional[str],  # Now string: "v2_client"
    client_hash: str,
    ip_address: str,
    nonce: str,
    request_timestamp: datetime
) -> SyncResult:
    """
    Sync client configuration with deadlock retry logic.

    Args:
        modem_id: Optional modem ID for tracking (metadata only, not part of key)

    Returns:
        SyncResult with config, version info, status, and version numbers
    """
    for attempt in range(DEADLOCK_RETRY_ATTEMPTS):
        try:
            return await _sync_client_config_impl(
                db, api_key, modem_id, client_config, client_version,
                client_hash, ip_address, nonce, request_timestamp
            )

        except DBAPIError as e:
            if "deadlock detected" in str(e).lower() and attempt < DEADLOCK_RETRY_ATTEMPTS - 1:
                # Exponential backoff with jitter to prevent thundering herd
                base_delay = min(
                    DEADLOCK_RETRY_BASE_DELAY * (2 ** attempt),
                    DEADLOCK_RETRY_MAX_DELAY
                )
                jitter = base_delay * DEADLOCK_JITTER_FACTOR * random.random()
                delay = base_delay + jitter

                logger.warning(
                    f"Deadlock detected during config sync for api_key={api_key[:8]}..., "
                    f"attempt {attempt + 1}/{DEADLOCK_RETRY_ATTEMPTS}, "
                    f"retrying in {delay:.3f}s"
                )

                await asyncio.sleep(delay)
                await db.rollback()
                continue
            else:
                logger.error(
                    f"Config sync failed after {attempt + 1} attempts for api_key={api_key[:8]}...: {e}"
                )
                raise DatabaseError(operation="config_sync") from e


async def _sync_client_config_impl(
    db: AsyncSession,
    api_key: str,
    modem_id: Optional[str],
    client_config: Dict[str, Any],
    client_version: Optional[str],
    client_hash: str,
    ip_address: str,
    nonce: str,
    request_timestamp: datetime
) -> SyncResult:
    """
    Internal implementation of sync logic.

    Args:
        modem_id: Optional modem ID for tracking (metadata only, not part of lookup key)

    Returns:
        SyncResult with config, version info, status, and version numbers
    """
    # Verify nonce (replay protection)
    api_key_hash = hashlib.sha256(api_key.encode('utf-8')).hexdigest()
    await verify_nonce(db, nonce, api_key_hash, request_timestamp, ip_address, modem_id)

    # Calculate hash of client config (for integrity check, not validation)
    calculated_hash = calculate_config_hash(client_config)
    if calculated_hash != client_hash:
        raise ConfigHashMismatchError(
            expected_hash=client_hash,
            actual_hash=calculated_hash
        )

    # Fetch existing config by API key only (with row-level lock for update)
    result = await db.execute(
        select(ClientConfig)
        .where(ClientConfig.api_key == api_key)
        .with_for_update()
    )
    existing_config = result.scalar_one_or_none()

    # Determine if we need to validate the client config
    # Skip validation if server has a config ready to push (client's config will be ignored)
    should_validate_client_config = True
    if existing_config is not None:
        if existing_config.status == ConfigStatus.AWAITING_FIRST_SYNC:
            # If target_mode is one_time or enforced, we push server config - skip client validation
            target_mode = existing_config.target_mode or "unmanaged"
            if target_mode in ("one_time", "enforced"):
                should_validate_client_config = False
        elif existing_config.status in (ConfigStatus.ENFORCED_READY, ConfigStatus.ENFORCED_ACTIVE):
            # Enforced modes always push server config - skip client validation
            should_validate_client_config = False
        elif existing_config.status == ConfigStatus.ONE_TIME_READY:
            # ONE_TIME_READY pushes server config - skip client validation
            should_validate_client_config = False

    # Validate client config only if we'll actually use it
    if should_validate_client_config:
        await validate_config(client_config, check_reachability=False, strict_security=True)

    # SCENARIO 1: First sync (no existing config)
    if existing_config is None:
        return await _handle_first_sync(
            db, api_key, modem_id, client_config, calculated_hash, ip_address
        )

    # Track modem ID changes (if modem_id provided and different from last seen)
    if modem_id and existing_config.last_seen_modem_id != modem_id:
        await _log_modem_change(
            db, api_key, existing_config.last_seen_modem_id, modem_id, ip_address
        )
        existing_config.last_seen_modem_id = modem_id

    # Dispatch based on status
    handlers = {
        ConfigStatus.AWAITING_FIRST_SYNC: _handle_awaiting_first_sync,
        ConfigStatus.UNMANAGED: _handle_unmanaged_sync,
        ConfigStatus.ONE_TIME_READY: _handle_one_time_ready_sync,
        ConfigStatus.ONE_TIME_ACTIVE: _handle_one_time_active_sync,
        ConfigStatus.ENFORCED_READY: _handle_enforced_ready_sync,
        ConfigStatus.ENFORCED_ACTIVE: _handle_enforced_active_sync,
    }

    handler = handlers.get(existing_config.status, _handle_unmanaged_sync)
    return await handler(
        db, existing_config, modem_id, client_config, calculated_hash, ip_address
    )


async def _log_modem_change(
    db: AsyncSession,
    api_key: str,
    old_modem_id: Optional[str],
    new_modem_id: str,
    ip_address: str
) -> None:
    """
    Log a modem ID change event to the audit log.

    Called when client syncs with a different modem than last seen.
    """
    from app.models.client_config import ConfigAuditLog

    audit_entry = ConfigAuditLog(
        timestamp=datetime.utcnow(),
        username=None,  # Client-initiated
        api_key_hash=None,
        ip_address=ip_address,
        api_key=api_key,
        modem_id=new_modem_id,
        old_modem_id=old_modem_id,
        new_modem_id=new_modem_id,
        action="modem_change",
        config_summary={
            "old_modem_id": old_modem_id,
            "new_modem_id": new_modem_id
        },
        old_version=None,
        new_version=None,
        old_status=None,
        new_status=None,
        success=True,
        failure_reason=None
    )
    db.add(audit_entry)


async def _handle_first_sync(
    db: AsyncSession,
    api_key: str,
    modem_id: Optional[str],
    client_config: Dict[str, Any],
    config_hash: str,
    ip_address: str
) -> SyncResult:
    """
    Handle first sync: Create new config from client.

    Creates v1_client and sets status to UNMANAGED.
    modem_id is stored as last_seen_modem_id (tracking metadata only).
    """
    salt = generate_salt()
    encrypted_blob, _ = await encrypt_config(client_config, salt)

    # Create new config with dual-track versioning
    new_config = ClientConfig(
        api_key=api_key,
        last_seen_modem_id=modem_id,  # Renamed: tracking metadata only
        config_plaintext=client_config,
        config_encrypted=encrypted_blob,
        config_hash=config_hash,
        status=ConfigStatus.UNMANAGED,
        target_mode=None,
        client_version=1,  # v1_client
        server_version=0,  # No server version yet
        active_track="client",
        client_acked_version=1,
        client_acked_track="client",
        encryption_salt=salt,
        last_sync=datetime.utcnow(),
        created_at=datetime.utcnow(),
        created_by="client",
        updated_at=datetime.utcnow(),
        updated_by="client"
    )

    db.add(new_config)

    # Create version history entry
    await create_config_version(
        db, api_key, modem_id,
        version_number=1,
        version_track="client",
        config_plaintext=client_config,
        config_encrypted=encrypted_blob,
        config_hash=config_hash,
        encryption_salt=salt,
        status=ConfigStatus.UNMANAGED,
        created_by="client",
        reason="first_sync",
        ip_address=ip_address
    )

    # Log audit entry
    await log_config_sync(
        db, api_key, modem_id, ip_address,
        old_config=None,
        new_config=client_config,
        old_version=None,
        new_version="v1_client",
        success=True
    )

    await invalidate_config_cache(api_key)

    return SyncResult(
        config=client_config,
        version_display="v1_client",
        status=ConfigStatus.UNMANAGED.value,
        config_changed=True,
        active_track="client",
        client_version=1,
        server_version=0
    )


async def _handle_awaiting_first_sync(
    db: AsyncSession,
    existing_config: ClientConfig,
    modem_id: Optional[str],
    client_config: Dict[str, Any],
    config_hash: str,
    ip_address: str
) -> SyncResult:
    """
    Handle AWAITING_FIRST_SYNC: Admin pre-created config, first client sync.

    Transition based on target_mode:
    - "unmanaged": Accept client config, create v1_client, become UNMANAGED
    - "one_time": Push server config, become ONE_TIME_ACTIVE
    - "enforced": Push server config, become ENFORCED_ACTIVE
    """
    old_status = existing_config.status  # Capture before any changes
    target_mode = existing_config.target_mode or "unmanaged"

    existing_config.last_sync = datetime.utcnow()

    # Update last_seen_modem_id if provided (critical for first sync tracking)
    if modem_id:
        existing_config.last_seen_modem_id = modem_id

    if target_mode == "unmanaged":
        # Accept client config, create v1_client
        salt = generate_salt()
        encrypted_blob, _ = await encrypt_config(client_config, salt)

        existing_config.config_plaintext = client_config
        existing_config.config_encrypted = encrypted_blob
        existing_config.config_hash = config_hash
        existing_config.encryption_salt = salt
        existing_config.client_version = 1
        existing_config.active_track = "client"
        existing_config.client_acked_version = 1
        existing_config.client_acked_track = "client"
        existing_config.status = ConfigStatus.UNMANAGED
        existing_config.target_mode = None
        existing_config.updated_by = "client"

        await create_config_version(
            db, existing_config.api_key, modem_id,
            version_number=1, version_track="client",
            config_plaintext=client_config,
            config_encrypted=encrypted_blob,
            config_hash=config_hash,
            encryption_salt=salt,
            status=ConfigStatus.UNMANAGED,
            created_by="client",
            reason="first_sync_unmanaged",
            ip_address=ip_address
        )

        await log_config_sync(
            db, existing_config.api_key, modem_id, ip_address,
            old_config=None, new_config=client_config,
            old_version=None, new_version="v1_client",
            success=True
        )

        await invalidate_config_cache(existing_config.api_key)
        return SyncResult(
            config=client_config,
            version_display="v1_client",
            status=ConfigStatus.UNMANAGED.value,
            config_changed=True,
            active_track="client",
            client_version=1,
            server_version=existing_config.server_version
        )

    elif target_mode == "one_time":
        # Push server config, become ONE_TIME_ACTIVE
        existing_config.client_acked_version = existing_config.server_version
        existing_config.client_acked_track = "server"
        existing_config.status = ConfigStatus.ONE_TIME_ACTIVE
        existing_config.target_mode = None

        # Also log client config as v1_client for history
        if config_hash != existing_config.config_hash:
            salt = generate_salt()
            encrypted_blob, _ = await encrypt_config(client_config, salt)
            existing_config.client_version = 1
            await create_config_version(
                db, existing_config.api_key, modem_id,
                version_number=1, version_track="client",
                config_plaintext=client_config,
                config_encrypted=encrypted_blob,
                config_hash=config_hash,
                encryption_salt=salt,
                status=ConfigStatus.ONE_TIME_ACTIVE,
                created_by="client",
                reason="first_sync_client_config",
                ip_address=ip_address
            )

        version_display = f"v{existing_config.server_version}_server"
        await log_config_sync(
            db, existing_config.api_key, modem_id, ip_address,
            old_config=client_config, new_config=existing_config.config_plaintext,
            old_version="v1_client", new_version=version_display,
            success=True
        )

        # Log status transition: AWAITING_FIRST_SYNC -> ONE_TIME_ACTIVE
        await log_mode_change(
            db=db,
            username="client",
            api_key=existing_config.api_key,
            modem_id=modem_id,
            ip_address=ip_address,
            old_status=old_status,
            new_status=ConfigStatus.ONE_TIME_ACTIVE,
            version=version_display,
            success=True
        )

        await invalidate_config_cache(existing_config.api_key)
        return SyncResult(
            config=existing_config.config_plaintext,
            version_display=version_display,
            status=ConfigStatus.ONE_TIME_ACTIVE.value,
            config_changed=True,
            active_track=existing_config.active_track,
            client_version=existing_config.client_version,
            server_version=existing_config.server_version
        )

    else:  # enforced
        # Push server config, become ENFORCED_ACTIVE
        existing_config.client_acked_version = existing_config.server_version
        existing_config.client_acked_track = "server"
        existing_config.status = ConfigStatus.ENFORCED_ACTIVE
        existing_config.target_mode = None

        # Log client config as v1_client for history (rejected)
        if config_hash != existing_config.config_hash:
            salt = generate_salt()
            encrypted_blob, _ = await encrypt_config(client_config, salt)
            existing_config.client_version = 1
            await create_config_version(
                db, existing_config.api_key, modem_id,
                version_number=1, version_track="client",
                config_plaintext=client_config,
                config_encrypted=encrypted_blob,
                config_hash=config_hash,
                encryption_salt=salt,
                status=ConfigStatus.ENFORCED_ACTIVE,
                created_by="client",
                reason="first_sync_client_rejected_enforced",
                ip_address=ip_address
            )

        version_display = f"v{existing_config.server_version}_server"
        await log_config_sync(
            db, existing_config.api_key, modem_id, ip_address,
            old_config=client_config, new_config=existing_config.config_plaintext,
            old_version="v1_client", new_version=version_display,
            success=True
        )

        # Log status transition: AWAITING_FIRST_SYNC -> ENFORCED_ACTIVE
        await log_mode_change(
            db=db,
            username="client",
            api_key=existing_config.api_key,
            modem_id=modem_id,
            ip_address=ip_address,
            old_status=old_status,
            new_status=ConfigStatus.ENFORCED_ACTIVE,
            version=version_display,
            success=True
        )

        await invalidate_config_cache(existing_config.api_key)
        return SyncResult(
            config=existing_config.config_plaintext,
            version_display=version_display,
            status=ConfigStatus.ENFORCED_ACTIVE.value,
            config_changed=True,
            active_track=existing_config.active_track,
            client_version=existing_config.client_version,
            server_version=existing_config.server_version
        )


async def _handle_unmanaged_sync(
    db: AsyncSession,
    existing_config: ClientConfig,
    modem_id: Optional[str],
    client_config: Dict[str, Any],
    config_hash: str,
    ip_address: str
) -> SyncResult:
    """
    Handle UNMANAGED sync: Accept client config updates.

    - Same config: No version change, just log
    - Different config: Create new v#_client
    """
    existing_config.last_sync = datetime.utcnow()

    # Check if config actually changed (compare to latest client config hash)
    if config_hash == existing_config.config_hash:
        # No change - just update last_sync
        version_display = existing_config.active_version_display
        return SyncResult(
            config=existing_config.config_plaintext,
            version_display=version_display,
            status=ConfigStatus.UNMANAGED.value,
            config_changed=False,
            active_track=existing_config.active_track,
            client_version=existing_config.client_version,
            server_version=existing_config.server_version
        )

    # Config changed - create new v#_client
    new_client_version = existing_config.client_version + 1
    salt = generate_salt()
    encrypted_blob, _ = await encrypt_config(client_config, salt)

    old_version_display = existing_config.active_version_display

    existing_config.config_plaintext = client_config
    existing_config.config_encrypted = encrypted_blob
    existing_config.config_hash = config_hash
    existing_config.encryption_salt = salt
    existing_config.client_version = new_client_version
    existing_config.active_track = "client"
    existing_config.client_acked_version = new_client_version
    existing_config.client_acked_track = "client"
    existing_config.updated_at = datetime.utcnow()
    existing_config.updated_by = "client"

    version_display = f"v{new_client_version}_client"

    # Create version history
    await create_config_version(
        db, existing_config.api_key, modem_id,
        version_number=new_client_version,
        version_track="client",
        config_plaintext=client_config,
        config_encrypted=encrypted_blob,
        config_hash=config_hash,
        encryption_salt=salt,
        status=ConfigStatus.UNMANAGED,
        created_by="client",
        reason="client_sync",
        ip_address=ip_address
    )

    await log_config_sync(
        db, existing_config.api_key, modem_id, ip_address,
        old_config=existing_config.config_plaintext,
        new_config=client_config,
        old_version=old_version_display,
        new_version=version_display,
        success=True
    )

    await invalidate_config_cache(existing_config.api_key)

    return SyncResult(
        config=client_config,
        version_display=version_display,
        status=ConfigStatus.UNMANAGED.value,
        config_changed=True,
        active_track=existing_config.active_track,
        client_version=existing_config.client_version,
        server_version=existing_config.server_version
    )


async def _handle_one_time_ready_sync(
    db: AsyncSession,
    existing_config: ClientConfig,
    modem_id: Optional[str],
    client_config: Dict[str, Any],
    config_hash: str,
    ip_address: str
) -> SyncResult:
    """
    Handle ONE_TIME_READY sync: Push server config to client.

    Client receives server config, status becomes ONE_TIME_ACTIVE.
    """
    old_status = existing_config.status  # Capture before change

    existing_config.last_sync = datetime.utcnow()
    existing_config.client_acked_version = existing_config.server_version
    existing_config.client_acked_track = "server"
    existing_config.status = ConfigStatus.ONE_TIME_ACTIVE

    version_display = f"v{existing_config.server_version}_server"

    await log_config_sync(
        db, existing_config.api_key, modem_id, ip_address,
        old_config=client_config,
        new_config=existing_config.config_plaintext,
        old_version=f"v{existing_config.client_version}_client",
        new_version=version_display,
        success=True
    )

    # Log status transition: ONE_TIME_READY -> ONE_TIME_ACTIVE
    # This indicates the client has received and acknowledged the server config
    await log_mode_change(
        db=db,
        username="client",
        api_key=existing_config.api_key,
        modem_id=modem_id,
        ip_address=ip_address,
        old_status=old_status,
        new_status=ConfigStatus.ONE_TIME_ACTIVE,
        version=version_display,
        success=True
    )

    await invalidate_config_cache(existing_config.api_key)

    return SyncResult(
        config=existing_config.config_plaintext,
        version_display=version_display,
        status=ConfigStatus.ONE_TIME_ACTIVE.value,
        config_changed=True,
        active_track=existing_config.active_track,
        client_version=existing_config.client_version,
        server_version=existing_config.server_version
    )


async def _handle_one_time_active_sync(
    db: AsyncSession,
    existing_config: ClientConfig,
    modem_id: Optional[str],
    client_config: Dict[str, Any],
    config_hash: str,
    ip_address: str
) -> SyncResult:
    """
    Handle ONE_TIME_ACTIVE sync: Check if client modified config.

    - Same as server config: Stay ONE_TIME_ACTIVE
    - Different (client edited): Revert to UNMANAGED, create new v#_client
    """
    existing_config.last_sync = datetime.utcnow()

    # Check if client is using the server config
    if config_hash == existing_config.config_hash:
        # Client still using server config - stay ONE_TIME_ACTIVE
        version_display = f"v{existing_config.server_version}_server"
        return SyncResult(
            config=existing_config.config_plaintext,
            version_display=version_display,
            status=ConfigStatus.ONE_TIME_ACTIVE.value,
            config_changed=False,
            active_track=existing_config.active_track,
            client_version=existing_config.client_version,
            server_version=existing_config.server_version
        )

    # Client edited config - revert to UNMANAGED
    new_client_version = existing_config.client_version + 1
    salt = generate_salt()
    encrypted_blob, _ = await encrypt_config(client_config, salt)

    old_version_display = f"v{existing_config.server_version}_server"

    existing_config.config_plaintext = client_config
    existing_config.config_encrypted = encrypted_blob
    existing_config.config_hash = config_hash
    existing_config.encryption_salt = salt
    existing_config.client_version = new_client_version
    existing_config.active_track = "client"
    existing_config.client_acked_version = new_client_version
    existing_config.client_acked_track = "client"
    existing_config.status = ConfigStatus.UNMANAGED
    existing_config.updated_at = datetime.utcnow()
    existing_config.updated_by = "client"

    version_display = f"v{new_client_version}_client"

    await create_config_version(
        db, existing_config.api_key, modem_id,
        version_number=new_client_version,
        version_track="client",
        config_plaintext=client_config,
        config_encrypted=encrypted_blob,
        config_hash=config_hash,
        encryption_salt=salt,
        status=ConfigStatus.UNMANAGED,
        created_by="client",
        reason="client_override_one_time",
        ip_address=ip_address
    )

    await log_config_sync(
        db, existing_config.api_key, modem_id, ip_address,
        old_config=existing_config.config_plaintext,
        new_config=client_config,
        old_version=old_version_display,
        new_version=version_display,
        success=True
    )

    await invalidate_config_cache(existing_config.api_key)

    return SyncResult(
        config=client_config,
        version_display=version_display,
        status=ConfigStatus.UNMANAGED.value,
        config_changed=True,
        active_track=existing_config.active_track,
        client_version=existing_config.client_version,
        server_version=existing_config.server_version
    )


async def _handle_enforced_ready_sync(
    db: AsyncSession,
    existing_config: ClientConfig,
    modem_id: Optional[str],
    client_config: Dict[str, Any],
    config_hash: str,
    ip_address: str
) -> SyncResult:
    """
    Handle ENFORCED_READY sync: Push server config to client.

    Client receives server config, status becomes ENFORCED_ACTIVE.
    If client sent different config, log it as rejected v#_client (but only if
    it's actually a new config different from what they sent last time).
    """
    old_status = existing_config.status  # Capture before change

    existing_config.last_sync = datetime.utcnow()
    existing_config.client_acked_version = existing_config.server_version
    existing_config.client_acked_track = "server"
    existing_config.status = ConfigStatus.ENFORCED_ACTIVE

    # If client sent different config, log it as rejected (but check for duplicates)
    if config_hash != existing_config.config_hash:
        # Check if this exact client config was already logged
        latest_client_version_result = await db.execute(
            select(ConfigVersion)
            .where(
                ConfigVersion.api_key == existing_config.api_key,
                ConfigVersion.version_track == "client"
            )
            .order_by(ConfigVersion.version_number.desc())
            .limit(1)
        )
        latest_client_version = latest_client_version_result.scalar_one_or_none()

        # Only create new version if the hash is different from the last client version
        if latest_client_version is None or latest_client_version.config_hash != config_hash:
            new_client_version = existing_config.client_version + 1
            salt = generate_salt()
            encrypted_blob, _ = await encrypt_config(client_config, salt)

            existing_config.client_version = new_client_version

            await create_config_version(
                db, existing_config.api_key, modem_id,
                version_number=new_client_version,
                version_track="client",
                config_plaintext=client_config,
                config_encrypted=encrypted_blob,
                config_hash=config_hash,
                encryption_salt=salt,
                status=ConfigStatus.ENFORCED_ACTIVE,
                created_by="client",
                reason="client_rejected_enforced",
                ip_address=ip_address
            )

    version_display = f"v{existing_config.server_version}_server"

    await log_config_sync(
        db, existing_config.api_key, modem_id, ip_address,
        old_config=client_config,
        new_config=existing_config.config_plaintext,
        old_version=f"v{existing_config.client_version}_client",
        new_version=version_display,
        success=True
    )

    # Log status transition: ENFORCED_READY -> ENFORCED_ACTIVE
    # This indicates the client has received and is now using the enforced config
    await log_mode_change(
        db=db,
        username="client",
        api_key=existing_config.api_key,
        modem_id=modem_id,
        ip_address=ip_address,
        old_status=old_status,
        new_status=ConfigStatus.ENFORCED_ACTIVE,
        version=version_display,
        success=True
    )

    await invalidate_config_cache(existing_config.api_key)

    return SyncResult(
        config=existing_config.config_plaintext,
        version_display=version_display,
        status=ConfigStatus.ENFORCED_ACTIVE.value,
        config_changed=True,
        active_track=existing_config.active_track,
        client_version=existing_config.client_version,
        server_version=existing_config.server_version
    )


async def _handle_enforced_active_sync(
    db: AsyncSession,
    existing_config: ClientConfig,
    modem_id: Optional[str],
    client_config: Dict[str, Any],
    config_hash: str,
    ip_address: str
) -> SyncResult:
    """
    Handle ENFORCED_ACTIVE sync: Always enforce server config.

    Client edits are rejected but logged as new v#_client.
    Server config is always returned.

    Only creates a new version entry if the client's config is actually different
    from what they sent last time (prevents duplicate history entries when client
    repeatedly sends the same non-matching config due to serialization differences).
    """
    existing_config.last_sync = datetime.utcnow()

    # Check if client sent a different config than what the server has
    # AND it's actually a new config (not the same one they sent last sync)
    if config_hash != existing_config.config_hash:
        # Check if this exact client config was already logged in the most recent
        # client version - if so, don't create a duplicate history entry
        latest_client_version_result = await db.execute(
            select(ConfigVersion)
            .where(
                ConfigVersion.api_key == existing_config.api_key,
                ConfigVersion.version_track == "client"
            )
            .order_by(ConfigVersion.version_number.desc())
            .limit(1)
        )
        latest_client_version = latest_client_version_result.scalar_one_or_none()

        # Only create new version if the hash is different from the last client version
        # This prevents duplicate entries when client keeps sending the same config
        if latest_client_version is None or latest_client_version.config_hash != config_hash:
            new_client_version = existing_config.client_version + 1
            salt = generate_salt()
            encrypted_blob, _ = await encrypt_config(client_config, salt)

            existing_config.client_version = new_client_version

            await create_config_version(
                db, existing_config.api_key, modem_id,
                version_number=new_client_version,
                version_track="client",
                config_plaintext=client_config,
                config_encrypted=encrypted_blob,
                config_hash=config_hash,
                encryption_salt=salt,
                status=ConfigStatus.ENFORCED_ACTIVE,
                created_by="client",
                reason="client_rejected_enforced",
                ip_address=ip_address
            )

            await log_config_sync(
                db, existing_config.api_key, modem_id, ip_address,
                old_config=client_config,
                new_config=existing_config.config_plaintext,
                old_version=f"v{new_client_version}_client",
                new_version=f"v{existing_config.server_version}_server",
                success=True
            )

    version_display = f"v{existing_config.server_version}_server"

    await invalidate_config_cache(existing_config.api_key)

    # Always return server config with config_changed=True
    return SyncResult(
        config=existing_config.config_plaintext,
        version_display=version_display,
        status=ConfigStatus.ENFORCED_ACTIVE.value,
        config_changed=True,
        active_track=existing_config.active_track,
        client_version=existing_config.client_version,
        server_version=existing_config.server_version
    )


async def get_config_for_sync(
    db: AsyncSession,
    api_key: str
) -> Optional[Dict[str, Any]]:
    """
    Fetch configuration for sync (used by cache).

    Lookup by api_key only (one config per API key).

    Returns:
        Config dict with encrypted_blob, salt, hash, status, versions
        None if config doesn't exist
    """
    result = await db.execute(
        select(ClientConfig)
        .where(ClientConfig.api_key == api_key)
    )
    config = result.scalar_one_or_none()

    if config is None:
        return None

    return {
        "encrypted_blob": config.config_encrypted,
        "salt": config.encryption_salt,
        "hash": config.config_hash,
        "status": config.status.value,
        "client_version": config.client_version,
        "server_version": config.server_version,
        "active_track": config.active_track,
        "version_display": config.active_version_display
    }


# Backward compatibility function
async def create_config_backup(
    db: AsyncSession,
    client_config: ClientConfig,
    reason: str,
    backed_up_by: str
) -> ConfigVersion:
    """
    Create point-in-time backup of configuration.

    DEPRECATED: Use create_config_version instead.
    This function exists for backward compatibility and will be removed in v8.0.
    """
    warnings.warn(
        "create_config_backup is deprecated, use create_config_version instead. "
        "This function will be removed in v8.0.",
        DeprecationWarning,
        stacklevel=2
    )
    # Determine track based on active_track
    track = client_config.active_track
    version_num = (
        client_config.server_version if track == "server"
        else client_config.client_version
    )

    return await create_config_version(
        db,
        api_key=client_config.api_key,
        modem_id=client_config.last_seen_modem_id,  # Updated: use last_seen_modem_id
        version_number=version_num,
        version_track=track,
        config_plaintext=client_config.config_plaintext,
        config_encrypted=client_config.config_encrypted,
        config_hash=client_config.config_hash,
        encryption_salt=client_config.encryption_salt,
        status=client_config.status,
        created_by=backed_up_by,
        reason=reason,
        ip_address=None
    )
