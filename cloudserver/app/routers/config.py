"""
Configuration management router.

Provides endpoints for:
- Client configuration sync (POST /api/config/sync)
- Health check (GET /api/config/health)
- Admin config management (GET/PUT /api/admin/configs/...)
- Config rollback (POST /api/admin/configs/.../rollback)
- Config history (GET /api/admin/configs/.../history)
- SSE updates (GET /api/admin/configs/stream)

Version 2.0: Dual-track versioning with 6 status states.
"""
import time
import json
import asyncio
import hashlib
import hmac
import secrets
from typing import Optional, List
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Request, Body, Path, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.config import settings
from app.core.limiter import limiter
from app.middleware.auth import require_authenticated_user, require_admin, require_elevated_or_admin, get_client_ip
from app.middleware.csrf import verify_csrf
from app.models import User, UserRole, ClientConfig, ConfigVersion, APIKey
from app.models.client_config import ConfigStatus, ConfigMode, ConfigNonce
from app.schemas.config import (
    PreflightRequest,
    PreflightResponse,
    ConfigSyncRequest,
    ConfigSyncResponse,
    ConfigCreateRequest,
    ConfigCreateResponse,
    ConfigUpdateRequest,
    ConfigUpdateResponse,
    ConfigRollbackRequest,
    ConfigRollbackResponse,
    HealthCheckResponse,
    ConfigListResponse,
    ConfigListItem,
    ConfigDetailResponse,
    ConfigHistoryResponse,
    ConfigVersionItem,
    ConfigSSEUpdate,
)
from app.core.config_sync import sync_client_config_with_retry, create_config_version, calculate_config_hash, SyncResult
from app.core.config_encryption import encrypt_config, decrypt_config, generate_salt
from app.core.config_validation import validate_config, test_url_reachability
from app.core.config_audit import log_config_update, log_config_rollback, log_mode_change, create_config_summary
from app.core.config_cache import invalidate_config_cache, get_cache_stats
from app.core.errors import (
    ModemCheckError,
    ConfigNotFoundError,
    ConfigBackupNotFoundError,
    DatabaseError,
)

router = APIRouter(tags=["Config Management"])


# ============================================================================
# CLIENT ENDPOINTS (No authentication, uses HMAC validation)
# ============================================================================

@router.post("/api/config/preflight", response_model=PreflightResponse)
@limiter.limit(lambda: settings.config_preflight_rate_limit)
async def preflight_check(
    request: Request,
    preflight_request: PreflightRequest = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Pre-flight API key validation endpoint.

    Called BEFORE modem login to:
    1. Validate API key exists and is active
    2. Return existing config if any (for enforced mode)
    3. Allow client to fail fast if API key is invalid

    HMAC signature format: {timestamp}|{nonce} (no modem_id - not known yet)

    Rate limited (configurable via CONFIG_PREFLIGHT_RATE_LIMIT, default: 10/hour).
    """
    client_ip = get_client_ip(request)

    try:
        # Validate HMAC signature (no modem_id in preflight)
        message = f"{preflight_request.timestamp}|{preflight_request.nonce}"
        expected_signature = hmac.new(
            preflight_request.api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        # Timing-safe comparison
        if not secrets.compare_digest(preflight_request.signature, expected_signature):
            return PreflightResponse(
                success=True,
                api_key_valid=False,
                has_existing_config=False,
                status=None,
                config=None,
                server_timestamp=datetime.utcnow().isoformat()
            )

        # Fetch API key and config in a single query using outerjoin
        # This reduces database round-trips from 2 to 1
        result = await db.execute(
            select(APIKey, ClientConfig)
            .outerjoin(ClientConfig, APIKey.api_key == ClientConfig.api_key)
            .where(APIKey.api_key == preflight_request.api_key)
        )
        row = result.first()

        # Extract API key and config from join result
        api_key_record = row[0] if row else None
        existing_config = row[1] if row else None

        if not api_key_record or not api_key_record.is_active:
            # Add random jitter to prevent API key enumeration via timing attacks
            # Jitter between 50-150ms to confuse timing analysis
            await asyncio.sleep(secrets.randbelow(100) / 1000 + 0.05)
            return PreflightResponse(
                success=True,
                api_key_valid=False,
                has_existing_config=False,
                status=None,
                config=None,
                server_timestamp=datetime.utcnow().isoformat()
            )

        # Update last_used timestamp
        api_key_record.update_last_used()

        if not existing_config:
            await db.commit()
            return PreflightResponse(
                success=True,
                api_key_valid=True,
                has_existing_config=False,
                status=None,
                config=None,
                server_timestamp=datetime.utcnow().isoformat()
            )

        # Return config if enforced mode (client needs to apply it)
        config_to_return = None
        if existing_config.status in (ConfigStatus.ENFORCED_READY, ConfigStatus.ENFORCED_ACTIVE):
            config_to_return = existing_config.config_plaintext

        await db.commit()

        return PreflightResponse(
            success=True,
            api_key_valid=True,
            has_existing_config=True,
            status=existing_config.status.value,
            config=config_to_return,
            server_timestamp=datetime.utcnow().isoformat()
        )

    except Exception as e:
        await db.rollback()
        raise ModemCheckError(
            error_code="INTERNAL_SERVER_ERROR",
            message=f"Preflight check failed: {str(e)}",
            status_code=500,
            details={"error_type": type(e).__name__}
        )


@router.post("/api/config/sync", response_model=ConfigSyncResponse)
@limiter.limit(lambda: settings.config_sync_rate_limit)
async def sync_config(
    request: Request,
    sync_request: ConfigSyncRequest = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Client configuration sync endpoint.

    Clients send their current config and receive the authoritative config.
    Config is keyed by API key only - modem_id is optional metadata for tracking.

    Supports three modes:
    1. First sync: Initialize config from client
    2. One-time mode: Client can update config (server accepts changes)
    3. Enforced mode: Server enforces config (client must accept server config)

    Rate limited (configurable via CONFIG_SYNC_RATE_LIMIT, default: 5/hour).

    Security:
    - HMAC-SHA256 signature validation (no modem_id in signature)
    - Nonce-based replay protection
    - Clock skew detection (±5 minutes)
    - Hash integrity verification
    """
    start_time = time.time()
    client_ip = get_client_ip(request)

    try:
        # Validate HMAC signature
        # Message format: {timestamp}|{nonce}|{config_hash} (no modem_id)
        message = f"{sync_request.timestamp}|{sync_request.nonce}|{sync_request.config_hash}"
        expected_signature = hmac.new(
            sync_request.api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        # Timing-safe comparison
        if not secrets.compare_digest(sync_request.signature, expected_signature):
            raise ModemCheckError(
                error_code="AUTHENTICATION_ERROR",
                message="Invalid request signature",
                status_code=401,
                details={"hint": "Check HMAC signature calculation"}
            )

        # Parse timestamp
        try:
            request_timestamp = datetime.fromisoformat(sync_request.timestamp.replace('Z', '+00:00'))
        except ValueError:
            raise ModemCheckError(
                error_code="VALIDATION_ERROR",
                message="Invalid timestamp format",
                status_code=400,
                details={"timestamp": sync_request.timestamp, "expected_format": "ISO 8601"}
            )

        # Verify API key exists and is active in the database
        api_key_result = await db.execute(
            select(APIKey).where(APIKey.api_key == sync_request.api_key)
        )
        api_key_record = api_key_result.scalar_one_or_none()

        if not api_key_record:
            # Add random jitter to prevent API key enumeration via timing attacks
            await asyncio.sleep(secrets.randbelow(100) / 1000 + 0.05)
            raise ModemCheckError(
                error_code="AUTHENTICATION_ERROR",
                message="Invalid or unknown API key",
                status_code=401,
                details={"hint": "API key must be created by an admin before client can sync"}
            )

        if not api_key_record.is_active:
            # Add random jitter to prevent API key enumeration via timing attacks
            await asyncio.sleep(secrets.randbelow(100) / 1000 + 0.05)
            raise ModemCheckError(
                error_code="AUTHENTICATION_ERROR",
                message="API key is disabled",
                status_code=401,
                details={"hint": "Contact administrator to re-enable this API key"}
            )

        # Update last_used timestamp for the API key
        api_key_record.update_last_used()

        # Perform sync (with deadlock retry) - modem_id is optional for tracking
        sync_result: SyncResult = await sync_client_config_with_retry(
            db=db,
            api_key=sync_request.api_key,
            modem_id=sync_request.modem_id,  # Optional, for tracking only
            client_config=sync_request.config,
            client_version=sync_request.version,
            client_hash=sync_request.config_hash,
            ip_address=client_ip,
            nonce=sync_request.nonce,
            request_timestamp=request_timestamp
        )

        # Commit transaction
        await db.commit()

        # Calculate new hash from sync result
        config_hash = calculate_config_hash(sync_result.config)

        # Return response with dual-track versioning info from SyncResult
        # (eliminates redundant database query)
        return ConfigSyncResponse(
            success=True,
            config=sync_result.config,
            version=sync_result.version_display,
            status=sync_result.status,
            config_hash=config_hash,
            server_timestamp=datetime.utcnow().isoformat(),
            config_changed=sync_result.config_changed,
            active_track=sync_result.active_track,
            client_version=sync_result.client_version,
            server_version=sync_result.server_version
        )

    except ModemCheckError:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise ModemCheckError(
            error_code="INTERNAL_SERVER_ERROR",
            message=f"Sync failed: {str(e)}",
            status_code=500,
            details={"error_type": type(e).__name__}
        )


@router.get("/api/config/health", response_model=HealthCheckResponse)
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    Health check endpoint for client failover.

    Returns service health status without authentication.
    Clients use this to detect server availability.

    Checks:
    - Database connectivity
    - Cache availability
    - Nonce table size (for monitoring cleanup cron)
    """
    database_status = "ok"
    cache_status = "ok"
    overall_healthy = True
    nonce_count = None

    # Check database
    try:
        await db.execute(select(1))
    except Exception:
        database_status = "error"
        overall_healthy = False

    # Check cache
    try:
        cache_stats = await get_cache_stats()
        if not cache_stats.get("redis_available", False):
            cache_status = "degraded"
            # Don't mark unhealthy for degraded cache (in-memory fallback works)
    except Exception:
        cache_status = "error"
        # Don't mark unhealthy for cache errors (graceful degradation)

    # Get nonce count for monitoring (only if database is healthy)
    if database_status == "ok":
        try:
            result = await db.execute(select(func.count()).select_from(ConfigNonce))
            nonce_count = result.scalar_one()
        except Exception:
            pass  # Non-critical, just for monitoring

    return HealthCheckResponse(
        healthy=overall_healthy,
        timestamp=datetime.utcnow().isoformat(),
        database=database_status,
        cache=cache_status,
        nonce_count=nonce_count
    )


# ============================================================================
# ADMIN ENDPOINTS (Require admin role + session authentication)
# ============================================================================

@router.get("/api/admin/configs", response_model=ConfigListResponse)
async def list_configs(
    request: Request,
    status: Optional[str] = Query(None, description="Filter by status (6 states)"),
    stale_hours: Optional[int] = Query(None, description="Filter by stale sync (hours since last sync)"),
    limit: int = Query(100, ge=1, le=1000, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    session_data: dict = Depends(require_elevated_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    List all client configurations (admin and elevated users).

    Supports filtering by:
    - Status (6 states: unmanaged, one_time_ready, one_time_active, enforced_ready, enforced_active, awaiting_first_sync)
    - Staleness (configs not synced in N hours)

    Returns paginated list with sync status.
    """
    # Build query
    query = select(ClientConfig)

    # Apply status filter
    if status:
        try:
            status_enum = ConfigStatus(status)
            query = query.where(ClientConfig.status == status_enum)
        except ValueError:
            pass  # Invalid status, ignore filter

    if stale_hours:
        stale_threshold = datetime.utcnow() - timedelta(hours=stale_hours)
        query = query.where(ClientConfig.last_sync < stale_threshold)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Get paginated results
    query = query.order_by(ClientConfig.updated_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    configs = result.scalars().all()

    # Convert to response format with dual-track versioning
    config_items = [
        ConfigListItem(
            api_key=f"{c.api_key[:8]}...",  # Truncate for display
            api_key_full=c.api_key,  # Full key for API calls
            last_seen_modem_id=c.last_seen_modem_id,  # Tracking metadata only
            status=c.status.value,
            version=c.active_version_display,
            client_version=c.client_version,
            server_version=c.server_version,
            active_track=c.active_track,
            last_sync=c.last_sync,
            updated_at=c.updated_at,
            updated_by=c.updated_by
        )
        for c in configs
    ]

    return ConfigListResponse(
        configs=config_items,
        total=total,
        filtered=len(config_items)
    )


@router.post("/api/admin/configs", response_model=ConfigCreateResponse, dependencies=[Depends(verify_csrf)])
async def create_config(
    request: Request,
    create_request: ConfigCreateRequest = Body(...),
    session_data: dict = Depends(require_elevated_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new client configuration (admin and elevated users).

    Pre-create a config for a client before they sync. Sets status to
    AWAITING_FIRST_SYNC with the target_mode specified. When the client
    syncs for the first time, the config will transition based on target_mode.

    Config is keyed by API key only - no modem_id required.
    Use this to push configurations to new clients.
    """
    client_ip = get_client_ip(request)

    try:
        # Validate the config
        await validate_config(
            create_request.config,
            check_reachability=False,
            strict_security=True
        )

        # Verify API key exists and is active
        api_key_result = await db.execute(
            select(APIKey).where(APIKey.api_key == create_request.api_key)
        )
        api_key_record = api_key_result.scalar_one_or_none()

        if not api_key_record:
            raise ModemCheckError(
                error_code="VALIDATION_ERROR",
                message="API key not found",
                status_code=400,
                details={"hint": "API key must exist before creating a config"}
            )

        if not api_key_record.is_active:
            raise ModemCheckError(
                error_code="VALIDATION_ERROR",
                message="API key is disabled",
                status_code=400,
                details={"hint": "API key must be active"}
            )

        # Check if config already exists for this API key
        existing_result = await db.execute(
            select(ClientConfig).where(ClientConfig.api_key == create_request.api_key)
        )
        if existing_result.scalar_one_or_none():
            raise ModemCheckError(
                error_code="CONFLICT",
                message="Configuration already exists for this API key",
                status_code=409,
                details={
                    "api_key": f"{create_request.api_key[:8]}...",
                    "hint": "Use PUT to update existing config"
                }
            )

        # Calculate hash
        config_hash = calculate_config_hash(create_request.config)

        # Generate encryption salt and encrypt config
        salt = generate_salt()
        encrypted_blob, _ = await encrypt_config(create_request.config, salt)

        # Create config with AWAITING_FIRST_SYNC status
        username = session_data.get("username", "unknown")
        new_config = ClientConfig(
            api_key=create_request.api_key,
            last_seen_modem_id=None,  # Will be set when client syncs
            config_plaintext=create_request.config,
            config_encrypted=encrypted_blob,
            config_hash=config_hash,
            status=ConfigStatus.AWAITING_FIRST_SYNC,
            target_mode=create_request.mode,  # What mode to become after first sync
            client_version=0,
            server_version=1,  # v1_server
            active_track="server",
            client_acked_version=None,
            client_acked_track=None,
            encryption_salt=salt,
            last_sync=None,
            created_at=datetime.utcnow(),
            created_by=username,
            updated_at=datetime.utcnow(),
            updated_by=username
        )

        db.add(new_config)

        # Create version history entry (no modem_id at creation)
        await create_config_version(
            db=db,
            api_key=create_request.api_key,
            modem_id=None,  # Not known yet
            version_number=1,
            version_track="server",
            config_plaintext=create_request.config,
            config_encrypted=encrypted_blob,
            config_hash=config_hash,
            encryption_salt=salt,
            status=ConfigStatus.AWAITING_FIRST_SYNC,
            created_by=username,
            reason="admin_create",
            ip_address=client_ip
        )

        # Log audit entry
        await log_config_update(
            db=db,
            username=username,
            api_key=create_request.api_key,
            modem_id=None,  # Not known yet
            ip_address=client_ip,
            old_config=None,
            new_config=create_request.config,
            old_version=None,
            new_version="v1_server",
            old_mode=None,
            new_mode=ConfigStatus.AWAITING_FIRST_SYNC,
            success=True
        )

        # Commit
        await db.commit()

        return ConfigCreateResponse(
            success=True,
            api_key=f"{create_request.api_key[:8]}...",
            version="v1_server",
            status=ConfigStatus.AWAITING_FIRST_SYNC.value,
            target_mode=create_request.mode
        )

    except ModemCheckError:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise ModemCheckError(
            error_code="INTERNAL_SERVER_ERROR",
            message=f"Config creation failed: {str(e)}",
            status_code=500,
            details={"error_type": type(e).__name__}
        )


@router.get("/api/admin/configs/{api_key}", response_model=ConfigDetailResponse)
async def get_config(
    request: Request,
    api_key: str = Path(..., description="Client API key"),
    session_data: dict = Depends(require_elevated_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Get detailed configuration (admin and elevated users).

    Returns full config with metadata including dual-track versioning.
    Config is shown in plaintext (no redaction) for admin editing.
    """
    # Fetch config by api_key only
    result = await db.execute(
        select(ClientConfig).where(ClientConfig.api_key == api_key)
    )
    config = result.scalar_one_or_none()

    if not config:
        raise ConfigNotFoundError(api_key=api_key)

    # Return full config without redaction for admin editing
    return ConfigDetailResponse(
        api_key=config.api_key,
        last_seen_modem_id=config.last_seen_modem_id,
        config=config.config_plaintext,  # No redaction - plaintext for editing
        status=config.status.value,
        version=config.active_version_display,
        client_version=config.client_version,
        server_version=config.server_version,
        active_track=config.active_track,
        client_acked_version=config.client_acked_version,
        client_acked_track=config.client_acked_track,
        last_sync=config.last_sync,
        created_at=config.created_at,
        created_by=config.created_by,
        updated_at=config.updated_at,
        updated_by=config.updated_by
    )


@router.put("/api/admin/configs/{api_key}", response_model=ConfigUpdateResponse, dependencies=[Depends(verify_csrf)])
async def update_config(
    request: Request,
    api_key: str = Path(..., description="Client API key"),
    update_request: ConfigUpdateRequest = Body(...),
    session_data: dict = Depends(require_elevated_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Update client configuration (admin and elevated users).

    Updates config with dual-track versioning:
    - Creates new v#_server version
    - Transitions status to *_READY state for client to pick up

    Status transitions on admin update:
    - UNMANAGED → ONE_TIME_READY or ENFORCED_READY (based on mode)
    - ONE_TIME_ACTIVE → ONE_TIME_READY (new config ready for client)
    - ENFORCED_ACTIVE → ENFORCED_READY (new config ready to enforce)
    - AWAITING_FIRST_SYNC → stays AWAITING_FIRST_SYNC (updates pending config)

    Optional URL reachability test (if check_reachability=true).
    """
    client_ip = get_client_ip(request)

    try:
        # Validate new config
        await validate_config(
            update_request.config,
            check_reachability=update_request.check_reachability,
            strict_security=True
        )

        # Optional reachability test
        reachability_result = None
        if update_request.check_reachability:
            reachability_result = await test_url_reachability(update_request.config)
            if not reachability_result.get("reachable"):
                raise ModemCheckError(
                    error_code="VALIDATION_ERROR",
                    message=f"CloudHost unreachable: {reachability_result.get('error')}",
                    status_code=400,
                    details=reachability_result
                )

        # Fetch existing config (with lock) by api_key only
        result = await db.execute(
            select(ClientConfig)
            .where(ClientConfig.api_key == api_key)
            .with_for_update()
        )
        existing_config = result.scalar_one_or_none()

        if not existing_config:
            raise ConfigNotFoundError(api_key=api_key)

        username = session_data.get("username", "unknown")

        # Calculate new hash
        new_hash = calculate_config_hash(update_request.config)

        # Encrypt new config
        new_salt = generate_salt()
        encrypted_blob, _ = await encrypt_config(update_request.config, new_salt)

        # Store old values for audit
        old_config = existing_config.config_plaintext
        old_version_display = existing_config.active_version_display
        old_status = existing_config.status

        # Increment server version (always creates new v#_server)
        existing_config.server_version += 1
        new_version_number = existing_config.server_version

        # Update config data
        existing_config.config_plaintext = update_request.config
        existing_config.config_encrypted = encrypted_blob
        existing_config.config_hash = new_hash
        existing_config.encryption_salt = new_salt
        existing_config.active_track = "server"
        existing_config.updated_at = datetime.utcnow()
        existing_config.updated_by = username

        # Determine new status based on current status and requested mode
        requested_mode = update_request.mode
        new_status = existing_config.status

        if existing_config.status == ConfigStatus.AWAITING_FIRST_SYNC:
            # Pre-create: update target_mode if specified, keep status
            if requested_mode:
                existing_config.target_mode = requested_mode
        elif existing_config.status == ConfigStatus.UNMANAGED:
            # Unmanaged: transition to READY state based on mode
            if requested_mode == "enforced":
                new_status = ConfigStatus.ENFORCED_READY
            else:
                new_status = ConfigStatus.ONE_TIME_READY
            existing_config.status = new_status
        elif existing_config.status in (ConfigStatus.ONE_TIME_READY, ConfigStatus.ONE_TIME_ACTIVE):
            # One-time: go back to READY (new config ready for client)
            if requested_mode == "enforced":
                new_status = ConfigStatus.ENFORCED_READY
            else:
                new_status = ConfigStatus.ONE_TIME_READY
            existing_config.status = new_status
        elif existing_config.status in (ConfigStatus.ENFORCED_READY, ConfigStatus.ENFORCED_ACTIVE):
            # Enforced: go back to READY (new config to enforce)
            if requested_mode == "one_time":
                new_status = ConfigStatus.ONE_TIME_READY
            else:
                new_status = ConfigStatus.ENFORCED_READY
            existing_config.status = new_status

        new_version_display = f"v{new_version_number}_server"

        # Create version history entry (use last_seen_modem_id for tracking)
        await create_config_version(
            db=db,
            api_key=api_key,
            modem_id=existing_config.last_seen_modem_id,  # Tracking metadata
            version_number=new_version_number,
            version_track="server",
            config_plaintext=update_request.config,
            config_encrypted=encrypted_blob,
            config_hash=new_hash,
            encryption_salt=new_salt,
            status=existing_config.status,
            created_by=username,
            reason="admin_update",
            ip_address=client_ip
        )

        # Log audit entry
        await log_config_update(
            db=db,
            username=username,
            api_key=api_key,
            modem_id=existing_config.last_seen_modem_id,  # Tracking metadata
            ip_address=client_ip,
            old_config=old_config,
            new_config=update_request.config,
            old_version=old_version_display,
            new_version=new_version_display,
            old_mode=old_status,
            new_mode=existing_config.status,
            success=True
        )

        # Invalidate cache
        await invalidate_config_cache(api_key)

        # Commit
        await db.commit()

        return ConfigUpdateResponse(
            success=True,
            version=new_version_display,
            status=existing_config.status.value,
            backup_created=True,
            reachability_test=reachability_result
        )

    except ModemCheckError:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise ModemCheckError(
            error_code="INTERNAL_SERVER_ERROR",
            message=f"Config update failed: {str(e)}",
            status_code=500,
            details={"error_type": type(e).__name__}
        )


@router.post("/api/admin/configs/{api_key}/rollback/{version_display}", response_model=ConfigRollbackResponse, dependencies=[Depends(verify_csrf)])
async def rollback_config(
    request: Request,
    api_key: str = Path(..., description="Client API key"),
    version_display: str = Path(..., description="Target version (e.g., 'v2_server' or 'v3_client')"),
    rollback_request: ConfigRollbackRequest = Body(...),
    session_data: dict = Depends(require_elevated_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Rollback configuration to previous version (admin and elevated users).

    Restores config from a previous version in history.
    Creates new v#_server version with the restored config.

    Version format: 'v{number}_{track}' (e.g., 'v2_server' or 'v3_client')
    """
    client_ip = get_client_ip(request)

    try:
        # Parse version_display to extract number and track
        import re
        match = re.match(r'^v(\d+)_(client|server)$', version_display)
        if not match:
            raise ModemCheckError(
                error_code="VALIDATION_ERROR",
                message="Invalid version format",
                status_code=400,
                details={
                    "version": version_display,
                    "expected_format": "v{number}_{track} (e.g., v2_server or v3_client)"
                }
            )

        target_version_number = int(match.group(1))
        target_version_track = match.group(2)

        # Fetch target version from history (by api_key only)
        result = await db.execute(
            select(ConfigVersion)
            .where(
                ConfigVersion.api_key == api_key,
                ConfigVersion.version_number == target_version_number,
                ConfigVersion.version_track == target_version_track
            )
        )
        target_version = result.scalar_one_or_none()

        if not target_version:
            raise ConfigBackupNotFoundError(api_key=api_key, version=version_display)

        # Fetch current config (with lock) by api_key only
        result = await db.execute(
            select(ClientConfig)
            .where(ClientConfig.api_key == api_key)
            .with_for_update()
        )
        current_config = result.scalar_one_or_none()

        if not current_config:
            raise ConfigNotFoundError(api_key=api_key)

        username = session_data.get("username", "unknown")
        old_version_display = current_config.active_version_display
        old_status = current_config.status

        # Increment server version for the rollback
        current_config.server_version += 1
        new_version_number = current_config.server_version
        new_version_display = f"v{new_version_number}_server"

        # Restore config from target version
        current_config.config_plaintext = target_version.config_plaintext
        current_config.config_encrypted = target_version.config_encrypted
        current_config.config_hash = target_version.config_hash
        current_config.encryption_salt = target_version.encryption_salt
        current_config.active_track = "server"
        current_config.updated_at = datetime.utcnow()
        current_config.updated_by = username

        # Transition to READY state (admin is pushing a config change)
        if current_config.status in (ConfigStatus.ENFORCED_ACTIVE, ConfigStatus.ENFORCED_READY):
            current_config.status = ConfigStatus.ENFORCED_READY
        elif current_config.status != ConfigStatus.AWAITING_FIRST_SYNC:
            current_config.status = ConfigStatus.ONE_TIME_READY

        # Create version history entry for the rollback (use last_seen_modem_id)
        await create_config_version(
            db=db,
            api_key=api_key,
            modem_id=current_config.last_seen_modem_id,  # Tracking metadata
            version_number=new_version_number,
            version_track="server",
            config_plaintext=target_version.config_plaintext,
            config_encrypted=target_version.config_encrypted,
            config_hash=target_version.config_hash,
            encryption_salt=target_version.encryption_salt,
            status=current_config.status,
            created_by=username,
            reason=f"rollback_from_{version_display}",
            ip_address=client_ip
        )

        # Log rollback
        await log_config_rollback(
            db=db,
            username=username,
            api_key=api_key,
            modem_id=current_config.last_seen_modem_id,  # Tracking metadata
            ip_address=client_ip,
            target_version=version_display,
            current_version=old_version_display,
            new_version=new_version_display,
            success=True
        )

        # Invalidate cache
        await invalidate_config_cache(api_key)

        # Commit
        await db.commit()

        return ConfigRollbackResponse(
            success=True,
            version=new_version_display,
            rolled_back_to=version_display,
            config=current_config.config_plaintext  # No redaction
        )

    except ModemCheckError:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise ModemCheckError(
            error_code="INTERNAL_SERVER_ERROR",
            message=f"Rollback failed: {str(e)}",
            status_code=500,
            details={"error_type": type(e).__name__}
        )


@router.get("/api/admin/configs/{api_key}/history", response_model=ConfigHistoryResponse)
async def get_config_history(
    request: Request,
    api_key: str = Path(..., description="Client API key"),
    track: Optional[str] = Query(None, description="Filter by track: 'client' or 'server'"),
    include_modem_events: bool = Query(True, description="Include modem change events"),
    limit: int = Query(50, ge=1, le=100, description="Max versions to return"),
    session_data: dict = Depends(require_elevated_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Get configuration version history with modem events (admin and elevated users).

    Returns list of versions and modem events for unified timeline display.
    Supports filtering by track (client or server).
    """
    from app.core.config_audit import get_modem_events_for_history
    from app.schemas.config import ModemEventItem

    # Build query (by api_key only)
    query = select(ConfigVersion).where(ConfigVersion.api_key == api_key)

    # Apply track filter
    if track in ("client", "server"):
        query = query.where(ConfigVersion.version_track == track)

    # Order by creation time (newest first)
    query = query.order_by(ConfigVersion.created_at.desc()).limit(limit)

    # Fetch versions
    result = await db.execute(query)
    versions = result.scalars().all()

    # Get total count (for pagination info)
    count_query = select(func.count()).select_from(ConfigVersion).where(
        ConfigVersion.api_key == api_key
    )
    if track in ("client", "server"):
        count_query = count_query.where(ConfigVersion.version_track == track)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Get current config for last_seen_modem_id
    config_result = await db.execute(
        select(ClientConfig).where(ClientConfig.api_key == api_key)
    )
    current_config = config_result.scalar_one_or_none()

    # Convert to response format
    version_items = [
        ConfigVersionItem(
            id=v.id,
            version_display=v.version_display,
            version_number=v.version_number,
            version_track=v.version_track,
            config=v.config_plaintext,  # No redaction
            status_at_creation=v.status_at_creation.value,
            modem_id_at_creation=v.modem_id_at_creation,
            created_at=v.created_at,
            created_by=v.created_by,
            creation_reason=v.creation_reason,
            ip_address=v.ip_address
        )
        for v in versions
    ]

    # Fetch modem events if requested
    modem_events = []
    total_modem_events = 0
    if include_modem_events:
        modem_events_raw = await get_modem_events_for_history(db, api_key, limit)
        modem_events = [
            ModemEventItem(
                id=e['id'],
                event_type=e['event_type'],
                timestamp=e['timestamp'],
                old_modem_id=e['old_modem_id'],
                new_modem_id=e['new_modem_id'],
                ip_address=e['ip_address']
            )
            for e in modem_events_raw
        ]
        total_modem_events = len(modem_events)

    return ConfigHistoryResponse(
        api_key=api_key,
        last_seen_modem_id=current_config.last_seen_modem_id if current_config else None,
        versions=version_items,
        modem_events=modem_events,
        total=total,
        total_modem_events=total_modem_events,
        filter_track=track
    )


# ============================================================================
# SSE STREAMING ENDPOINT (Real-time updates for admin dashboard)
# ============================================================================

@router.get("/api/admin/configs/stream")
async def stream_config_updates(
    request: Request,
    session_data: dict = Depends(require_elevated_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Server-Sent Events endpoint for real-time config updates.

    Streams config changes to the admin dashboard. Events are sent when:
    - Config is synced (client update)
    - Config is updated (admin update)
    - Config status changes

    Event format:
    ```
    event: config_update
    data: {"api_key": "abc...", "modem_id": "...", "status": "...", ...}
    ```
    """
    async def event_generator():
        """Generate SSE events for config changes."""
        last_check = datetime.utcnow()

        # Send initial keepalive
        yield f"event: connected\ndata: {json.dumps({'timestamp': last_check.isoformat()})}\n\n"

        while True:
            # Check for new client disconnection
            if await request.is_disconnected():
                break

            # Query for configs updated since last check (with limit to prevent OOM)
            try:
                result = await db.execute(
                    select(ClientConfig)
                    .where(ClientConfig.updated_at > last_check)
                    .order_by(ClientConfig.updated_at.asc())
                    .limit(100)  # Prevent unbounded queries that could cause OOM
                )
                updated_configs = result.scalars().all()

                for config in updated_configs:
                    # Safely handle potential null values
                    update_event = ConfigSSEUpdate(
                        api_key=f"{config.api_key[:8]}..." if config.api_key else "unknown",
                        last_seen_modem_id=config.last_seen_modem_id or "unknown",
                        status=config.status.value if config.status else "unknown",
                        version=config.active_version_display or "unknown",
                        client_version=config.client_version or 0,
                        server_version=config.server_version or 0,
                        active_track=config.active_track or "client",
                        last_sync=config.last_sync.isoformat() if config.last_sync else None,
                        updated_at=config.updated_at.isoformat() if config.updated_at else None
                    )
                    yield f"event: config_update\ndata: {update_event.model_dump_json()}\n\n"

                if updated_configs:
                    last_check = updated_configs[-1].updated_at

            except Exception as e:
                # Log error but keep connection alive
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

            # Send keepalive every 30 seconds
            await asyncio.sleep(5)  # Check every 5 seconds
            yield f"event: keepalive\ndata: {json.dumps({'timestamp': datetime.utcnow().isoformat()})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )
