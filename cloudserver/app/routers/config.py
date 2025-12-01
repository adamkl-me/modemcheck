"""
Configuration management router.

Provides endpoints for:
- Client configuration sync (POST /api/config/sync)
- Health check (GET /api/config/health)
- Admin config management (GET/PUT /api/admin/configs/...)
- Config rollback (POST /api/admin/configs/.../rollback)
- Config history (GET /api/admin/configs/.../history)
- SSE updates (GET /api/admin/configs/stream)

Version 3.0: Simplified 3-state model (UNMANAGED, MANAGED, LOCKED) with single-track versioning.
"""
import time
import json
import asyncio
import hashlib
import hmac
import logging
import secrets
from typing import Optional, List
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
from fastapi import APIRouter, Depends, Request, Body, Path, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import load_only

from app.core.database import get_db
from app.core.config import settings
from app.core.limiter import limiter
from app.middleware.auth import require_authenticated_user, require_admin, require_elevated_or_admin, get_client_ip
from app.middleware.csrf import verify_csrf
from app.models import User, UserRole, ClientConfig, ConfigVersion, APIKey
from app.models.client_config import ConfigStatus, SyncStatus, ConfigNonce
from app.schemas.config import (
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
from app.core.config_audit import log_config_update, log_config_rollback, log_status_change, create_config_summary
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

@router.post("/api/config/sync", response_model=ConfigSyncResponse)
@limiter.limit(lambda: settings.config_sync_rate_limit)
async def sync_config(
    request: Request,
    sync_request: ConfigSyncRequest = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Client configuration sync endpoint.

    Single endpoint for all config sync scenarios (replaces preflight + sync).
    Clients send their current config and receive the authoritative config.

    Supports three modes:
    1. UNMANAGED: Client controls config, server stores it
    2. MANAGED: Server pushes config once, client can modify after
    3. LOCKED: Server enforces config, client cannot modify

    Rate limited (configurable via CONFIG_SYNC_RATE_LIMIT, default: 5/hour).

    Security:
    - HMAC-SHA256 signature validation
    - Nonce-based replay protection
    - Clock skew detection (±5 minutes)
    - Hash integrity verification
    """
    client_ip = get_client_ip(request)

    try:
        # Validate HMAC signature
        # Message format: {timestamp}|{nonce}|{config_hash}
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

        # Parse timestamp (strip timezone for naive UTC)
        try:
            request_timestamp = datetime.fromisoformat(sync_request.timestamp.replace('Z', '+00:00')).replace(tzinfo=None)
        except ValueError:
            raise ModemCheckError(
                error_code="VALIDATION_ERROR",
                message="Invalid timestamp format",
                status_code=400,
                details={"timestamp": sync_request.timestamp, "expected_format": "ISO 8601"}
            )

        # Verify API key exists and is active
        api_key_result = await db.execute(
            select(APIKey).where(APIKey.api_key == sync_request.api_key)
        )
        api_key_record = api_key_result.scalar_one_or_none()

        if not api_key_record:
            await asyncio.sleep(secrets.randbelow(100) / 1000 + 0.05)
            raise ModemCheckError(
                error_code="AUTHENTICATION_ERROR",
                message="Invalid or unknown API key",
                status_code=401,
                details={"hint": "API key must be created by an admin before client can sync"}
            )

        if not api_key_record.is_active:
            await asyncio.sleep(secrets.randbelow(100) / 1000 + 0.05)
            raise ModemCheckError(
                error_code="AUTHENTICATION_ERROR",
                message="API key is disabled",
                status_code=401,
                details={"hint": "Contact administrator to re-enable this API key"}
            )

        # Update last_used timestamp
        api_key_record.update_last_used()

        # Perform sync (with deadlock retry)
        sync_result: SyncResult = await sync_client_config_with_retry(
            db=db,
            api_key=sync_request.api_key,
            modem_id=sync_request.modem_id,
            client_config=sync_request.config,
            client_version=sync_request.version,
            client_hash=sync_request.config_hash,
            ip_address=client_ip,
            nonce=sync_request.nonce,
            request_timestamp=request_timestamp
        )

        await db.commit()

        # Invalidate cache AFTER commit to avoid race condition
        await invalidate_config_cache(sync_request.api_key)

        config_hash = calculate_config_hash(sync_result.config)

        return ConfigSyncResponse(
            success=True,
            config=sync_result.config,
            version=sync_result.version,
            status=sync_result.status,
            sync_status=sync_result.sync_status,
            config_hash=config_hash,
            server_timestamp=datetime.now(timezone.utc).isoformat(),
            config_changed=sync_result.config_changed
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
    """
    database_status = "ok"
    cache_status = "ok"
    overall_healthy = True

    try:
        await db.execute(select(1))
    except Exception:
        database_status = "error"
        overall_healthy = False

    try:
        cache_stats = await get_cache_stats()
        if not cache_stats.get("redis_available", False):
            cache_status = "degraded"
    except Exception:
        cache_status = "error"

    return HealthCheckResponse(
        healthy=overall_healthy,
        timestamp=datetime.now(timezone.utc).isoformat(),
        database=database_status,
        cache=cache_status
    )


# ============================================================================
# ADMIN ENDPOINTS (Require admin role + session authentication)
# ============================================================================

@router.get("/api/admin/configs", response_model=ConfigListResponse)
@limiter.limit(lambda: settings.api_admin_rate_limit)
async def list_configs(
    request: Request,
    status: Optional[str] = Query(None, description="Filter by status (unmanaged, managed, locked)"),
    sync_status: Optional[str] = Query(None, description="Filter by sync status (n/a, pending, active)"),
    stale_hours: Optional[int] = Query(None, description="Filter by stale sync (hours since last sync)"),
    limit: int = Query(100, ge=1, le=1000, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    session_data: dict = Depends(require_elevated_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    List all client configurations (admin and elevated users).

    Supports filtering by:
    - Status (unmanaged, managed, locked)
    - Sync status (n/a, pending, active)
    - Staleness (configs not synced in N hours)
    """
    query = select(ClientConfig)

    if status:
        try:
            status_enum = ConfigStatus(status)
            query = query.where(ClientConfig.status == status_enum)
        except ValueError:
            pass

    if sync_status:
        try:
            sync_status_enum = SyncStatus(sync_status)
            query = query.where(ClientConfig.sync_status == sync_status_enum)
        except ValueError:
            pass

    if stale_hours:
        stale_threshold = datetime.now(timezone.utc) - timedelta(hours=stale_hours)
        query = query.where(ClientConfig.last_sync < stale_threshold)

    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(ClientConfig.updated_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    configs = result.scalars().all()

    config_items = [
        ConfigListItem(
            api_key=f"{c.api_key[:8]}...",
            api_key_full=c.api_key,
            last_seen_modem_id=c.last_seen_modem_id,
            status=c.status.value,
            sync_status=c.sync_status.value,
            version=c.version,
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
@limiter.limit(lambda: settings.api_admin_rate_limit)
async def create_config(
    request: Request,
    create_request: ConfigCreateRequest = Body(...),
    session_data: dict = Depends(require_elevated_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new client configuration (admin and elevated users).

    Creates config with initial version (v1).
    - mode='unmanaged': Config stored, client controls it
    - mode='managed': Config pushed once, client can modify after
    - mode='locked': Config enforced, client cannot modify

    Returns the config for download as config.json.
    """
    client_ip = get_client_ip(request)

    try:
        await validate_config(
            create_request.config,
            check_reachability=False,
            strict_security=True
        )

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

        config_hash = calculate_config_hash(create_request.config)
        salt = generate_salt()
        encrypted_blob, _ = await encrypt_config(create_request.config, salt)

        username = session_data.get("username", "unknown")

        # Determine status and sync_status based on mode
        if create_request.mode == "unmanaged":
            status = ConfigStatus.UNMANAGED
            sync_status_val = SyncStatus.NA
        elif create_request.mode == "managed":
            status = ConfigStatus.MANAGED
            sync_status_val = SyncStatus.PENDING
        else:  # locked
            status = ConfigStatus.LOCKED
            sync_status_val = SyncStatus.PENDING

        new_config = ClientConfig(
            api_key=create_request.api_key,
            last_seen_modem_id=None,
            config_plaintext=create_request.config,
            config_encrypted=encrypted_blob,
            config_hash=config_hash,
            status=status,
            sync_status=sync_status_val,
            version=1,
            encryption_salt=salt,
            last_sync=None,
            created_at=datetime.now(timezone.utc),
            created_by=username,
            updated_at=datetime.now(timezone.utc),
            updated_by=username
        )

        db.add(new_config)

        await create_config_version(
            db=db,
            api_key=create_request.api_key,
            modem_id=None,
            version_number=1,
            config_plaintext=create_request.config,
            config_encrypted=encrypted_blob,
            config_hash=config_hash,
            encryption_salt=salt,
            status=status,
            sync_status=sync_status_val,
            created_by=username,
            reason="admin_create",
            ip_address=client_ip
        )

        await log_config_update(
            db=db,
            username=username,
            api_key=create_request.api_key,
            modem_id=None,
            ip_address=client_ip,
            old_config=None,
            new_config=create_request.config,
            old_version=None,
            new_version=1,
            old_status=None,
            new_status=status,
            old_sync_status=None,
            new_sync_status=sync_status_val,
            success=True
        )

        await db.commit()

        return ConfigCreateResponse(
            success=True,
            api_key=f"{create_request.api_key[:8]}...",
            version=1,
            status=status.value,
            sync_status=sync_status_val.value,
            config=create_request.config
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


# ============================================================================
# SSE STREAMING ENDPOINT (Real-time updates for admin dashboard)
# ============================================================================
# NOTE: This endpoint MUST be defined BEFORE /{api_key} routes to avoid
# "stream" being captured as an api_key value by FastAPI's route matching.

@router.get("/api/admin/configs/stream")
@limiter.limit(lambda: settings.config_sse_rate_limit)
async def stream_config_updates(
    request: Request,
    session_data: dict = Depends(require_elevated_or_admin)
):
    """
    Server-Sent Events endpoint for real-time config updates.

    Streams config changes to the admin dashboard.

    PERFORMANCE FIX: Creates new DB session per poll to avoid tying up
    a connection for the entire 30-minute stream duration.
    """
    from app.core.database import get_async_session

    async def event_generator():
        last_check = datetime.now(timezone.utc)
        connection_start = datetime.now(timezone.utc)
        max_connection_time = timedelta(minutes=30)  # Close idle connections after 30 min

        yield f"event: connected\ndata: {json.dumps({'timestamp': last_check.isoformat()})}\n\n"

        while True:
            # Check for client disconnect
            if await request.is_disconnected():
                logger.info("SSE client disconnected")
                break

            # Check for maximum connection time (prevents zombie connections)
            if datetime.now(timezone.utc) - connection_start > max_connection_time:
                logger.info("SSE connection timeout after 30 minutes")
                yield f"event: timeout\ndata: {json.dumps({'message': 'Connection timeout, please reconnect'})}\n\n"
                break

            try:
                # Create new DB session per poll to avoid connection leak
                async with get_async_session() as db:
                    # Use load_only to avoid loading large config fields (config_plaintext, config_encrypted)
                    # Only load columns needed for SSE updates to enable index-only scan
                    result = await db.execute(
                        select(ClientConfig)
                        .where(ClientConfig.updated_at > last_check)
                        .order_by(ClientConfig.updated_at.asc())
                        .limit(100)
                        .options(load_only(
                            ClientConfig.api_key,
                            ClientConfig.last_seen_modem_id,
                            ClientConfig.status,
                            ClientConfig.sync_status,
                            ClientConfig.version,
                            ClientConfig.last_sync,
                            ClientConfig.updated_at
                        ))
                    )
                    updated_configs = result.scalars().all()

                    for config in updated_configs:
                        update_event = ConfigSSEUpdate(
                            api_key=f"{config.api_key[:8]}..." if config.api_key else "unknown",
                            last_seen_modem_id=config.last_seen_modem_id,
                            status=config.status.value if config.status else "unknown",
                            sync_status=config.sync_status.value if config.sync_status else "n/a",
                            version=config.version or 0,
                            last_sync=config.last_sync.isoformat() if config.last_sync else None,
                            updated_at=config.updated_at.isoformat() if config.updated_at else None
                        )
                        yield f"event: config_update\ndata: {update_event.model_dump_json()}\n\n"

                    if updated_configs:
                        last_check = updated_configs[-1].updated_at
                # Session automatically closed when exiting context manager

            except asyncio.CancelledError:
                logger.info("SSE connection cancelled")
                break
            except Exception as e:
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

            await asyncio.sleep(5)
            yield f"event: keepalive\ndata: {json.dumps({'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/api/admin/configs/{api_key}", response_model=ConfigDetailResponse)
@limiter.limit(lambda: settings.api_admin_rate_limit)
async def get_config(
    request: Request,
    api_key: str = Path(..., description="Client API key"),
    session_data: dict = Depends(require_elevated_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Get detailed configuration (admin and elevated users).

    Returns full config with metadata.
    """
    result = await db.execute(
        select(ClientConfig).where(ClientConfig.api_key == api_key)
    )
    config = result.scalar_one_or_none()

    if not config:
        raise ConfigNotFoundError(api_key=api_key)

    return ConfigDetailResponse(
        api_key=config.api_key,
        last_seen_modem_id=config.last_seen_modem_id,
        config=config.config_plaintext,
        status=config.status.value,
        sync_status=config.sync_status.value,
        version=config.version,
        last_sync=config.last_sync,
        created_at=config.created_at,
        created_by=config.created_by,
        updated_at=config.updated_at,
        updated_by=config.updated_by
    )


@router.put("/api/admin/configs/{api_key}", response_model=ConfigUpdateResponse, dependencies=[Depends(verify_csrf)])
@limiter.limit(lambda: settings.api_admin_rate_limit)
async def update_config(
    request: Request,
    api_key: str = Path(..., description="Client API key"),
    update_request: ConfigUpdateRequest = Body(...),
    session_data: dict = Depends(require_elevated_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Update client configuration (admin and elevated users).

    Creates new version and sets sync_status to PENDING for managed/locked modes.
    """
    client_ip = get_client_ip(request)

    try:
        await validate_config(
            update_request.config,
            check_reachability=False,
            strict_security=True
        )

        result = await db.execute(
            select(ClientConfig)
            .where(ClientConfig.api_key == api_key)
            .with_for_update()
        )
        existing_config = result.scalar_one_or_none()

        if not existing_config:
            raise ConfigNotFoundError(api_key=api_key)

        username = session_data.get("username", "unknown")

        new_hash = calculate_config_hash(update_request.config)
        new_salt = generate_salt()
        encrypted_blob, _ = await encrypt_config(update_request.config, new_salt)

        old_config = existing_config.config_plaintext
        old_version = existing_config.version
        old_status = existing_config.status
        old_sync_status = existing_config.sync_status
        old_modem_id = existing_config.last_seen_modem_id  # Capture for audit consistency

        # Check if config actually changed
        version_created = (new_hash != existing_config.config_hash)

        if version_created:
            existing_config.version += 1

        new_version = existing_config.version

        existing_config.config_plaintext = update_request.config
        existing_config.config_encrypted = encrypted_blob
        existing_config.config_hash = new_hash
        existing_config.encryption_salt = new_salt
        existing_config.updated_at = datetime.now(timezone.utc)
        existing_config.updated_by = username

        # Handle mode change if specified
        if update_request.mode:
            if update_request.mode == "unmanaged":
                existing_config.status = ConfigStatus.UNMANAGED
                existing_config.sync_status = SyncStatus.NA
            elif update_request.mode == "managed":
                existing_config.status = ConfigStatus.MANAGED
                existing_config.sync_status = SyncStatus.PENDING
            else:  # locked
                existing_config.status = ConfigStatus.LOCKED
                existing_config.sync_status = SyncStatus.PENDING
        elif existing_config.status in (ConfigStatus.MANAGED, ConfigStatus.LOCKED):
            # Config changed, set to PENDING so client picks up new config
            existing_config.sync_status = SyncStatus.PENDING

        if version_created:
            await create_config_version(
                db=db,
                api_key=api_key,
                modem_id=old_modem_id,
                version_number=new_version,
                config_plaintext=update_request.config,
                config_encrypted=encrypted_blob,
                config_hash=new_hash,
                encryption_salt=new_salt,
                status=existing_config.status,
                sync_status=existing_config.sync_status,
                created_by=username,
                reason="admin_update",
                ip_address=client_ip
            )

        await log_config_update(
            db=db,
            username=username,
            api_key=api_key,
            modem_id=old_modem_id,
            ip_address=client_ip,
            old_config=old_config,
            new_config=update_request.config,
            old_version=old_version,
            new_version=new_version,
            old_status=old_status,
            new_status=existing_config.status,
            old_sync_status=old_sync_status,
            new_sync_status=existing_config.sync_status,
            success=True
        )

        await db.commit()
        # Invalidate cache AFTER commit to avoid race condition
        await invalidate_config_cache(api_key)

        return ConfigUpdateResponse(
            success=True,
            version=new_version,
            status=existing_config.status.value,
            sync_status=existing_config.sync_status.value,
            version_created=version_created
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


@router.post("/api/admin/configs/{api_key}/rollback/{version}", response_model=ConfigRollbackResponse, dependencies=[Depends(verify_csrf)])
@limiter.limit(lambda: settings.api_admin_rate_limit)
async def rollback_config(
    request: Request,
    api_key: str = Path(..., description="Client API key"),
    version: int = Path(..., description="Target version number to rollback to"),
    rollback_request: ConfigRollbackRequest = Body(...),
    session_data: dict = Depends(require_elevated_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Rollback configuration to previous version (admin and elevated users).

    Restores config from a previous version in history.
    Creates new version with the restored config.
    """
    client_ip = get_client_ip(request)

    try:
        # Fetch target version from history
        result = await db.execute(
            select(ConfigVersion)
            .where(
                ConfigVersion.api_key == api_key,
                ConfigVersion.version_number == version
            )
        )
        target_version = result.scalar_one_or_none()

        if not target_version:
            raise ConfigBackupNotFoundError(api_key=api_key, version=str(version))

        result = await db.execute(
            select(ClientConfig)
            .where(ClientConfig.api_key == api_key)
            .with_for_update()
        )
        current_config = result.scalar_one_or_none()

        if not current_config:
            raise ConfigNotFoundError(api_key=api_key)

        username = session_data.get("username", "unknown")
        old_version = current_config.version
        old_modem_id = current_config.last_seen_modem_id  # Capture for audit consistency

        current_config.version += 1
        new_version = current_config.version

        current_config.config_plaintext = target_version.config_plaintext
        current_config.config_encrypted = target_version.config_encrypted
        current_config.config_hash = target_version.config_hash
        current_config.encryption_salt = target_version.encryption_salt
        current_config.updated_at = datetime.now(timezone.utc)
        current_config.updated_by = username

        # Set to PENDING if managed/locked so client picks up rollback
        if current_config.status in (ConfigStatus.MANAGED, ConfigStatus.LOCKED):
            current_config.sync_status = SyncStatus.PENDING

        await create_config_version(
            db=db,
            api_key=api_key,
            modem_id=old_modem_id,
            version_number=new_version,
            config_plaintext=target_version.config_plaintext,
            config_encrypted=target_version.config_encrypted,
            config_hash=target_version.config_hash,
            encryption_salt=target_version.encryption_salt,
            status=current_config.status,
            sync_status=current_config.sync_status,
            created_by=username,
            reason=f"rollback_from_v{version}",
            ip_address=client_ip
        )

        await log_config_rollback(
            db=db,
            username=username,
            api_key=api_key,
            modem_id=old_modem_id,
            ip_address=client_ip,
            target_version=version,
            current_version=old_version,
            new_version=new_version,
            success=True
        )

        await db.commit()
        # Invalidate cache AFTER commit to avoid race condition
        await invalidate_config_cache(api_key)

        return ConfigRollbackResponse(
            success=True,
            version=new_version,
            rolled_back_to=version,
            config=current_config.config_plaintext
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
@limiter.limit(lambda: settings.api_admin_rate_limit)
async def get_config_history(
    request: Request,
    api_key: str = Path(..., description="Client API key"),
    include_modem_events: bool = Query(True, description="Include modem change events"),
    limit: int = Query(50, ge=1, le=100, description="Max versions to return"),
    session_data: dict = Depends(require_elevated_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Get configuration version history with modem events (admin and elevated users).

    Returns list of versions and modem events for unified timeline display.
    """
    from app.core.config_audit import get_modem_events_for_history
    from app.schemas.config import ModemEventItem

    # Optimized query: Combine version fetch + count using window function + current config using CTE
    # This reduces 3 separate queries to 1 combined query
    from sqlalchemy import text

    # Use raw SQL with CTE for optimal performance
    query_text = text("""
        WITH version_data AS (
            SELECT
                id, version_number, config_plaintext, status_at_creation,
                sync_status_at_creation, modem_id_at_creation, created_at,
                created_by, creation_reason, ip_address,
                COUNT(*) OVER() AS total_count
            FROM config_versions
            WHERE api_key = :api_key
            ORDER BY created_at DESC
            LIMIT :limit
        ),
        current_config_data AS (
            SELECT
                last_seen_modem_id, version
            FROM client_configs
            WHERE api_key = :api_key
        )
        SELECT
            v.id, v.version_number, v.config_plaintext, v.status_at_creation,
            v.sync_status_at_creation, v.modem_id_at_creation, v.created_at,
            v.created_by, v.creation_reason, v.ip_address, v.total_count,
            c.last_seen_modem_id, c.version as current_version
        FROM version_data v
        LEFT JOIN current_config_data c ON true
    """)

    result = await db.execute(
        query_text,
        {"api_key": api_key, "limit": limit}
    )
    rows = result.fetchall()

    # Extract data from combined query result
    total = rows[0].total_count if rows else 0
    current_modem_id = rows[0].last_seen_modem_id if rows else None
    current_version = rows[0].current_version if rows else 0

    # Build version list from rows
    versions = []
    for row in rows:
        # Convert status strings back to enum values for schema validation
        version_obj = type('ConfigVersion', (), {
            'id': row.id,
            'version_number': row.version_number,
            'config_plaintext': row.config_plaintext,
            'status_at_creation': ConfigStatus(row.status_at_creation),
            'sync_status_at_creation': SyncStatus(row.sync_status_at_creation) if row.sync_status_at_creation else None,
            'modem_id_at_creation': row.modem_id_at_creation,
            'created_at': row.created_at,
            'created_by': row.created_by,
            'creation_reason': row.creation_reason,
            'ip_address': row.ip_address
        })()
        versions.append(version_obj)

    version_items = [
        ConfigVersionItem(
            id=v.id,
            version_number=v.version_number,
            config=v.config_plaintext,
            status_at_creation=v.status_at_creation.value,
            sync_status_at_creation=v.sync_status_at_creation.value if v.sync_status_at_creation else None,
            modem_id_at_creation=v.modem_id_at_creation,
            created_at=v.created_at,
            created_by=v.created_by,
            creation_reason=v.creation_reason,
            ip_address=v.ip_address
        )
        for v in versions
    ]

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
        last_seen_modem_id=current_modem_id,
        versions=version_items,
        modem_events=modem_events,
        total=total,
        total_modem_events=total_modem_events,
        current_version=current_version
    )
