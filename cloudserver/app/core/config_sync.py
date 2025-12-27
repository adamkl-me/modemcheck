"""
Configuration sync orchestration with simplified 3-state model.

This module coordinates the entire config sync workflow:
1. Validate client request (nonce, HMAC, clock skew)
2. Check cache or fetch from database
3. Handle sync based on status (3 states):
   - UNMANAGED: Client-controlled, server just stores
   - MANAGED: Server pushed config once, client can modify after receiving
   - LOCKED: Server enforces config, client cannot modify
4. Update database
5. Create version history entries (single-track versioning)
6. Log audit trail
7. Invalidate cache

Single-Track Versioning:
- Simple incrementing versions (v1, v2, v3...)
- created_by field indicates origin ("client" or admin username)

Implements deadlock retry with exponential backoff.
"""

import asyncio
import hashlib
import json
import logging
import random
from dataclasses import dataclass
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from app.core.utils import utc_now
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.models.client_config import (
    ClientConfig, ConfigStatus, SyncStatus, ConfigVersion, ConfigNonce
)
from app.core.config_encryption import encrypt_config, decrypt_config, generate_salt
from app.core.config_validation import validate_config
from app.core.config_audit import log_config_sync, log_config_update, log_status_change, create_config_summary
from app.core.config_cache import (
    get_cached_config,
    set_cached_config,
    get_or_fetch_config
)
# Note: invalidate_config_cache is now called in router after db.commit()
from app.core.errors import (
    ConfigVersionConflictError,
    ConfigNonceReplayError,
    ConfigClockSkewError,
    ConfigHashMismatchError,
    ConfigLockedError,
    ConfigNotFoundError,
    DatabaseError
)


@dataclass
class SyncResult:
    """Result of a config sync operation."""
    config: Dict[str, Any]
    version: int
    status: str
    sync_status: str
    config_changed: bool


logger = logging.getLogger(__name__)

# Sync configuration
# Note: Uses TIMESTAMP_WINDOW_SECONDS from app.core.security for consistency
MAX_VERSION = 2_000_000_000  # PostgreSQL INTEGER max is 2,147,483,647, leaving headroom
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
    1. Redis cache (fast path)
    2. PostgreSQL (fallback for durability)

    Raises:
        ConfigNonceReplayError: If nonce was already used
        ConfigClockSkewError: If timestamp too far from server time
    """
    from app.core.cache import get_cache
    from app.core.security import validate_request_timestamp_datetime, TIMESTAMP_WINDOW_SECONDS

    # Check clock skew first using shared validation (fast, no I/O)
    is_valid, error_msg, server_time = validate_request_timestamp_datetime(request_timestamp)

    if not is_valid:
        raise ConfigClockSkewError(
            client_time=request_timestamp.isoformat() + "Z",
            server_time=server_time.isoformat() + "Z",
            max_skew_seconds=TIMESTAMP_WINDOW_SECONDS
        )

    # Try Redis first (fast path)
    redis_key = f"nonce:{nonce}"
    nonce_ttl = TIMESTAMP_WINDOW_SECONDS * 2  # 10 minutes

    try:
        cache = await get_cache()
        is_new = await cache.setnx(redis_key, "used", ttl=nonce_ttl)

        if not is_new:
            raise ConfigNonceReplayError(nonce=nonce)

    except ConfigNonceReplayError:
        raise
    except Exception as e:
        # Redis unavailable - fall back to database-only checking
        logger.warning(f"Redis unavailable for nonce check, using database fallback: {e}")

        existing_nonce = await db.execute(
            select(ConfigNonce).where(ConfigNonce.nonce == nonce)
        )
        if existing_nonce.scalar_one_or_none() is not None:
            raise ConfigNonceReplayError(nonce=nonce)

    # Store nonce in database for durability
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
    api_key_hash: str,
    modem_id: Optional[str],
    version_number: int,
    config_plaintext: Dict[str, Any],
    config_encrypted: str,
    config_hash: str,
    encryption_salt: str,
    status: ConfigStatus,
    sync_status: SyncStatus,
    created_by: str,
    reason: str,
    ip_address: Optional[str] = None
) -> ConfigVersion:
    """
    Create a version history entry for a configuration.

    Args:
        db: Database session
        api_key_hash: SHA-256 hash of API key (v8.0+: no plaintext stored)
        modem_id: Modem ID at time of creation (for tracking)
        version_number: Version number (1, 2, 3...)
        config_plaintext: Configuration data
        config_encrypted: Encrypted configuration
        config_hash: SHA256 hash
        encryption_salt: Encryption salt
        status: Config status when version was created
        sync_status: Sync status when version was created
        created_by: Username or "client"
        reason: Reason for creating version
        ip_address: Client IP address

    Returns:
        Created ConfigVersion instance
    """
    version_entry = ConfigVersion(
        api_key_hash=api_key_hash,
        modem_id_at_creation=modem_id,
        version_number=version_number,
        config_plaintext=config_plaintext,
        config_encrypted=config_encrypted,
        config_hash=config_hash,
        encryption_salt=encryption_salt,
        status_at_creation=status,
        sync_status_at_creation=sync_status,
        created_at=utc_now(),
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
    client_version: int,
    client_hash: str,
    ip_address: str,
    nonce: str,
    request_timestamp: datetime
) -> SyncResult:
    """
    Sync client configuration with deadlock retry logic.

    Args:
        db: Database session
        api_key: Client API key
        modem_id: Optional modem ID for tracking (metadata only)
        client_config: Client's current configuration
        client_version: Client's current version number (0 if first sync)
        client_hash: SHA256 hash of client config
        ip_address: Client IP address
        nonce: Request nonce for replay protection
        request_timestamp: Request timestamp

    Returns:
        SyncResult with config, version, status, sync_status, and config_changed flag
    """
    for attempt in range(DEADLOCK_RETRY_ATTEMPTS):
        try:
            return await _sync_client_config_impl(
                db, api_key, modem_id, client_config, client_version,
                client_hash, ip_address, nonce, request_timestamp
            )

        except DBAPIError as e:
            if "deadlock detected" in str(e).lower() and attempt < DEADLOCK_RETRY_ATTEMPTS - 1:
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
    client_version: int,
    client_hash: str,
    ip_address: str,
    nonce: str,
    request_timestamp: datetime
) -> SyncResult:
    """
    Internal implementation of sync logic.

    Returns:
        SyncResult with config, version, status, sync_status, and config_changed flag
    """
    # SECURITY FIX: Validate cheap operations BEFORE consuming nonce
    # This prevents invalid requests from wasting nonces in replay attacks

    # Calculate hash of client config (for integrity check) - cheap operation, no side effects
    calculated_hash = calculate_config_hash(client_config)
    if calculated_hash != client_hash:
        raise ConfigHashMismatchError(
            expected_hash=client_hash,
            actual_hash=calculated_hash
        )

    # Hash API key for database lookups (v8.0+: only hash stored in DB)
    api_key_hash = hashlib.sha256(api_key.encode('utf-8')).hexdigest()

    # Fetch existing config by API key hash (with row-level lock for update)
    result = await db.execute(
        select(ClientConfig)
        .where(ClientConfig.api_key_hash == api_key_hash)
        .with_for_update()
    )
    existing_config = result.scalar_one_or_none()

    # Determine if we need to validate the client config
    # Skip validation if server will push its own config anyway
    should_validate_client_config = True
    if existing_config is not None:
        if existing_config.status == ConfigStatus.LOCKED:
            # LOCKED always pushes server config - skip client validation
            should_validate_client_config = False
        elif existing_config.status == ConfigStatus.MANAGED and existing_config.sync_status == SyncStatus.PENDING:
            # MANAGED with PENDING pushes server config - skip client validation
            should_validate_client_config = False

    # Validate client config BEFORE consuming nonce (prevents nonce waste on invalid requests)
    if should_validate_client_config:
        await validate_config(client_config, check_reachability=False, strict_security=True)

    # NOW verify nonce (replay protection) - only after validation passes
    # Note: api_key_hash was computed above for database lookup
    await verify_nonce(db, nonce, api_key_hash, request_timestamp, ip_address, modem_id)

    # SCENARIO 1: First sync (no existing config)
    if existing_config is None:
        return await _handle_first_sync(
            db, api_key, api_key_hash, modem_id, client_config, calculated_hash, ip_address
        )

    # Track modem ID changes (explicit None check to distinguish "not provided" from "changed")
    if modem_id is not None and existing_config.last_seen_modem_id != modem_id:
        await _log_modem_change(
            db, api_key_hash, existing_config.last_seen_modem_id, modem_id, ip_address
        )
        existing_config.last_seen_modem_id = modem_id

    # Dispatch based on status
    if existing_config.status == ConfigStatus.UNMANAGED:
        return await _handle_unmanaged_sync(
            db, api_key, existing_config, modem_id, client_config, calculated_hash, ip_address
        )
    elif existing_config.status == ConfigStatus.MANAGED:
        return await _handle_managed_sync(
            db, api_key, existing_config, modem_id, client_config, calculated_hash, ip_address
        )
    elif existing_config.status == ConfigStatus.LOCKED:
        return await _handle_locked_sync(
            db, api_key, existing_config, modem_id, client_config, calculated_hash, ip_address
        )
    else:
        # All ConfigStatus enum values should be handled above.
        # If we get here, a new status was added without a handler.
        raise ValueError(f"Unknown config status: {existing_config.status}")


async def _log_modem_change(
    db: AsyncSession,
    api_key_hash: str,
    old_modem_id: Optional[str],
    new_modem_id: str,
    ip_address: str
) -> None:
    """Log a modem ID change event to the audit log."""
    from app.models.client_config import ConfigAuditLog

    audit_entry = ConfigAuditLog(
        timestamp=utc_now(),
        username=None,  # Client-initiated
        api_key_hash=api_key_hash,
        ip_address=ip_address,
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
        old_sync_status=None,
        new_sync_status=None,
        success=True,
        failure_reason=None
    )
    db.add(audit_entry)


async def _handle_first_sync(
    db: AsyncSession,
    api_key: str,
    api_key_hash: str,
    modem_id: Optional[str],
    client_config: Dict[str, Any],
    config_hash: str,
    ip_address: str
) -> SyncResult:
    """
    Handle first sync: Create new config from client.

    Creates v1 and sets status to UNMANAGED with sync_status N/A.
    """
    salt = generate_salt()
    encrypted_blob, _ = await encrypt_config(client_config, salt)

    new_config = ClientConfig(
        api_key_hash=api_key_hash,
        last_seen_modem_id=modem_id,
        config_plaintext=client_config,
        config_encrypted=encrypted_blob,
        config_hash=config_hash,
        status=ConfigStatus.UNMANAGED,
        sync_status=SyncStatus.NA,
        version=1,
        encryption_salt=salt,
        last_sync=utc_now(),
        created_at=utc_now(),
        created_by="client",
        updated_at=utc_now(),
        updated_by="client"
    )

    db.add(new_config)

    # Create version history entry
    await create_config_version(
        db, api_key_hash, modem_id,
        version_number=1,
        config_plaintext=client_config,
        config_encrypted=encrypted_blob,
        config_hash=config_hash,
        encryption_salt=salt,
        status=ConfigStatus.UNMANAGED,
        sync_status=SyncStatus.NA,
        created_by="client",
        reason="first_sync",
        ip_address=ip_address
    )

    # Log audit entry (uses plaintext api_key which it hashes internally)
    await log_config_sync(
        db, api_key, modem_id, ip_address,
        old_config=None,
        new_config=client_config,
        old_version=None,
        new_version=1,
        success=True
    )

    # Cache invalidation moved to router (after db.commit) to avoid race condition

    return SyncResult(
        config=client_config,
        version=1,
        status=ConfigStatus.UNMANAGED.value,
        sync_status=SyncStatus.NA.value,
        config_changed=True
    )


async def _handle_unmanaged_sync(
    db: AsyncSession,
    api_key: str,
    existing_config: ClientConfig,
    modem_id: Optional[str],
    client_config: Dict[str, Any],
    config_hash: str,
    ip_address: str
) -> SyncResult:
    """
    Handle UNMANAGED sync: Accept client config updates.

    - Same config: No version change
    - Different config: Create new version
    """
    existing_config.last_sync = utc_now()

    # Check if config actually changed
    # Use stored hash directly to avoid Go/Python JSON serialization differences
    stored_hash = existing_config.config_hash
    if config_hash == stored_hash:
        # No change - just update last_sync
        return SyncResult(
            config=existing_config.config_plaintext,
            version=existing_config.version,
            status=ConfigStatus.UNMANAGED.value,
            sync_status=SyncStatus.NA.value,
            config_changed=False
        )

    # Config changed - create new version
    # Check for version overflow (PostgreSQL INTEGER limit protection)
    # Use > to allow version MAX_VERSION to be created, reject only when exceeding it
    if existing_config.version > MAX_VERSION:
        raise DatabaseError(
            message=f"Version number overflow: current version {existing_config.version} exceeds maximum limit",
            details={"current_version": existing_config.version, "max_version": MAX_VERSION}
        )
    new_version = existing_config.version + 1
    salt = generate_salt()
    encrypted_blob, _ = await encrypt_config(client_config, salt)

    old_version = existing_config.version
    old_config_plaintext = existing_config.config_plaintext  # Capture BEFORE mutation

    existing_config.config_plaintext = client_config
    existing_config.config_encrypted = encrypted_blob
    existing_config.config_hash = config_hash
    existing_config.encryption_salt = salt
    existing_config.version = new_version
    existing_config.updated_at = utc_now()
    existing_config.updated_by = "client"

    # Create version history
    await create_config_version(
        db, existing_config.api_key_hash, modem_id,
        version_number=new_version,
        config_plaintext=client_config,
        config_encrypted=encrypted_blob,
        config_hash=config_hash,
        encryption_salt=salt,
        status=ConfigStatus.UNMANAGED,
        sync_status=SyncStatus.NA,
        created_by="client",
        reason="client_sync",
        ip_address=ip_address
    )

    # Log audit entry (uses plaintext api_key which it hashes internally)
    await log_config_sync(
        db, api_key, modem_id, ip_address,
        old_config=old_config_plaintext,  # Use captured value, not mutated object
        new_config=client_config,
        old_version=old_version,
        new_version=new_version,
        success=True
    )

    # Cache invalidation moved to router (after db.commit) to avoid race condition

    return SyncResult(
        config=client_config,
        version=new_version,
        status=ConfigStatus.UNMANAGED.value,
        sync_status=SyncStatus.NA.value,
        config_changed=True
    )


async def _handle_managed_sync(
    db: AsyncSession,
    api_key: str,
    existing_config: ClientConfig,
    modem_id: Optional[str],
    client_config: Dict[str, Any],
    config_hash: str,
    ip_address: str
) -> SyncResult:
    """
    Handle MANAGED sync: One-time config push.

    - PENDING: Push server config, transition to ACTIVE
    - ACTIVE + same config: Stay MANAGED/ACTIVE
    - ACTIVE + different config: Client modified, transition to UNMANAGED
    """
    existing_config.last_sync = utc_now()

    if existing_config.sync_status == SyncStatus.PENDING:
        # Push server config to client, transition to ACTIVE
        old_sync_status = existing_config.sync_status
        existing_config.sync_status = SyncStatus.ACTIVE

        # Log status change (uses plaintext api_key which it hashes internally)
        await log_status_change(
            db=db,
            username="client",
            api_key=api_key,
            modem_id=modem_id,
            ip_address=ip_address,
            old_status=existing_config.status,
            new_status=existing_config.status,
            old_sync_status=old_sync_status,
            new_sync_status=SyncStatus.ACTIVE,
            version=existing_config.version,
            success=True
        )

        # Cache invalidation moved to router (after db.commit) to avoid race condition

        return SyncResult(
            config=existing_config.config_plaintext,
            version=existing_config.version,
            status=ConfigStatus.MANAGED.value,
            sync_status=SyncStatus.ACTIVE.value,
            config_changed=True
        )

    # ACTIVE state - check if client modified config
    # Normalize client config to only include fields present in server's stored config
    # This handles cases where client sends extra fields (e.g., IgnitePassword, EnableCloud)
    server_fields = set(existing_config.config_plaintext.keys())
    client_fields = set(client_config.keys())
    dropped_fields = client_fields - server_fields
    if dropped_fields:
        logger.debug(
            f"MANAGED config normalization: dropping client fields not tracked by server "
            f"for api_key_hash={existing_config.api_key_hash[:16]}..., "
            f"modem_id={modem_id}, dropped_fields={sorted(dropped_fields)}"
        )
    normalized_client_config = {k: v for k, v in client_config.items() if k in server_fields}
    normalized_client_hash = calculate_config_hash(normalized_client_config)

    if normalized_client_hash == existing_config.config_hash:
        # Client still using server config (for the fields server tracks)
        return SyncResult(
            config=existing_config.config_plaintext,
            version=existing_config.version,
            status=ConfigStatus.MANAGED.value,
            sync_status=SyncStatus.ACTIVE.value,
            config_changed=False
        )

    # Client modified config - transition to UNMANAGED
    # Check for version overflow (PostgreSQL INTEGER limit protection)
    # Use > to allow version MAX_VERSION to be created, reject only when exceeding it
    if existing_config.version > MAX_VERSION:
        raise DatabaseError(
            message=f"Version number overflow: current version {existing_config.version} exceeds maximum limit",
            details={"current_version": existing_config.version, "max_version": MAX_VERSION}
        )
    new_version = existing_config.version + 1
    salt = generate_salt()
    encrypted_blob, _ = await encrypt_config(client_config, salt)

    old_version = existing_config.version
    old_status = existing_config.status
    old_sync_status = existing_config.sync_status
    old_config_plaintext = existing_config.config_plaintext  # Capture BEFORE mutation

    existing_config.config_plaintext = client_config
    existing_config.config_encrypted = encrypted_blob
    existing_config.config_hash = config_hash
    existing_config.encryption_salt = salt
    existing_config.version = new_version
    existing_config.status = ConfigStatus.UNMANAGED
    existing_config.sync_status = SyncStatus.NA
    existing_config.updated_at = utc_now()
    existing_config.updated_by = "client"

    await create_config_version(
        db, existing_config.api_key_hash, modem_id,
        version_number=new_version,
        config_plaintext=client_config,
        config_encrypted=encrypted_blob,
        config_hash=config_hash,
        encryption_salt=salt,
        status=ConfigStatus.UNMANAGED,
        sync_status=SyncStatus.NA,
        created_by="client",
        reason="client_override_managed",
        ip_address=ip_address
    )

    # Log audit entries (uses plaintext api_key which it hashes internally)
    await log_config_sync(
        db, api_key, modem_id, ip_address,
        old_config=old_config_plaintext,  # Use captured value, not mutated object
        new_config=client_config,
        old_version=old_version,
        new_version=new_version,
        success=True
    )

    await log_status_change(
        db=db,
        username="client",
        api_key=api_key,
        modem_id=modem_id,
        ip_address=ip_address,
        old_status=old_status,
        new_status=ConfigStatus.UNMANAGED,
        old_sync_status=old_sync_status,
        new_sync_status=SyncStatus.NA,
        version=new_version,
        success=True
    )

    # Cache invalidation moved to router (after db.commit) to avoid race condition

    return SyncResult(
        config=client_config,
        version=new_version,
        status=ConfigStatus.UNMANAGED.value,
        sync_status=SyncStatus.NA.value,
        config_changed=True
    )


async def _handle_locked_sync(
    db: AsyncSession,
    api_key: str,
    existing_config: ClientConfig,
    modem_id: Optional[str],
    client_config: Dict[str, Any],
    config_hash: str,
    ip_address: str
) -> SyncResult:
    """
    Handle LOCKED sync: Always enforce server config.

    - PENDING: Push server config, transition to ACTIVE
    - ACTIVE: Always return server config, ignore client changes

    Client config changes are NOT recorded as new versions (per requirements).
    """
    existing_config.last_sync = utc_now()

    if existing_config.sync_status == SyncStatus.PENDING:
        # Push server config to client, transition to ACTIVE
        old_sync_status = existing_config.sync_status
        existing_config.sync_status = SyncStatus.ACTIVE

        # Log status change (uses plaintext api_key which it hashes internally)
        await log_status_change(
            db=db,
            username="client",
            api_key=api_key,
            modem_id=modem_id,
            ip_address=ip_address,
            old_status=existing_config.status,
            new_status=existing_config.status,
            old_sync_status=old_sync_status,
            new_sync_status=SyncStatus.ACTIVE,
            version=existing_config.version,
            success=True
        )

        # Cache invalidation moved to router (after db.commit) to avoid race condition

        return SyncResult(
            config=existing_config.config_plaintext,
            version=existing_config.version,
            status=ConfigStatus.LOCKED.value,
            sync_status=SyncStatus.ACTIVE.value,
            config_changed=True
        )

    # ACTIVE state - always return server config
    # Do NOT record rejected client configs as new versions
    # Cache invalidation moved to router (after db.commit) to avoid race condition

    # Log attempted config changes for audit trail (security monitoring)
    if config_hash != existing_config.config_hash:
        logger.info(
            f"LOCKED config rejection: client attempted config change for api_key_hash={existing_config.api_key_hash[:16]}..., "
            f"modem_id={modem_id}, client_hash={config_hash[:16]}..., server_hash={existing_config.config_hash[:16]}..."
        )
        # Log to audit for security visibility
        from app.models.client_config import ConfigAuditLog
        audit_entry = ConfigAuditLog(
            timestamp=utc_now(),
            username=None,  # Client-initiated
            api_key_hash=existing_config.api_key_hash,
            ip_address=ip_address,
            modem_id=modem_id,
            action="locked_config_rejected",
            config_summary={
                "reason": "client_attempted_modify_locked_config",
                "client_hash": config_hash[:16] + "...",
                "server_hash": existing_config.config_hash[:16] + "..."
            },
            old_version=existing_config.version,
            new_version=existing_config.version,
            old_status=ConfigStatus.LOCKED,
            new_status=ConfigStatus.LOCKED,
            old_sync_status=SyncStatus.ACTIVE,
            new_sync_status=SyncStatus.ACTIVE,
            success=True,
            failure_reason=None
        )
        db.add(audit_entry)

    return SyncResult(
        config=existing_config.config_plaintext,
        version=existing_config.version,
        status=ConfigStatus.LOCKED.value,
        sync_status=SyncStatus.ACTIVE.value,
        config_changed=(config_hash != existing_config.config_hash)
    )


async def get_config_for_sync(
    db: AsyncSession,
    api_key: str
) -> Optional[Dict[str, Any]]:
    """
    Fetch configuration for sync (used by cache).

    Returns:
        Config dict with encrypted_blob, salt, hash, status, sync_status, version
        None if config doesn't exist
    """
    # Hash API key for database lookup (v8.0+: only hash stored in DB)
    api_key_hash = hashlib.sha256(api_key.encode('utf-8')).hexdigest()

    result = await db.execute(
        select(ClientConfig)
        .where(ClientConfig.api_key_hash == api_key_hash)
    )
    config = result.scalar_one_or_none()

    if config is None:
        return None

    return {
        "encrypted_blob": config.config_encrypted,
        "salt": config.encryption_salt,
        "hash": config.config_hash,
        "status": config.status.value,
        "sync_status": config.sync_status.value,
        "version": config.version
    }
