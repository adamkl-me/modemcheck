"""
Admin CRUD operations for client configurations.

Provides:
- GET /api/admin/configs - List with filtering/pagination
- POST /api/admin/configs - Create new config
- GET /api/admin/configs/{api_key} - Get config detail
- PUT /api/admin/configs/{api_key} - Update config

Requires: elevated or admin role.
Handles: Encryption, versioning, audit logging, caching.
"""
import logging
from typing import Optional
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Body, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete

from app.core.database import get_db
from app.core.config import settings
from app.core.limiter import limiter
from app.core.utils import utc_now
from app.middleware.auth import require_elevated_or_admin, get_client_ip
from app.middleware.csrf import verify_csrf
from app.models import ClientConfig, ConfigVersion, APIKey
from app.models.client_config import ConfigStatus, SyncStatus
from app.schemas.config import (
    ConfigCreateRequest,
    ConfigCreateResponse,
    ConfigUpdateRequest,
    ConfigUpdateResponse,
    ConfigListResponse,
    ConfigListItem,
    ConfigDetailResponse,
)
from app.core.config_sync import create_config_version, calculate_config_hash
from app.core.config_encryption import encrypt_config, generate_salt
from app.core.config_validation import validate_config
from app.core.config_audit import log_config_update
from app.core.config_cache import invalidate_config_cache
from app.core.errors import ModemCheckError, ConfigNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Config Management"])


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
        stale_threshold = utc_now() - timedelta(hours=stale_hours)
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
            created_at=utc_now(),
            created_by=username,
            updated_at=utc_now(),
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
        existing_config.updated_at = utc_now()
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


@router.delete("/api/admin/configs/{api_key}", dependencies=[Depends(verify_csrf)])
@limiter.limit(lambda: settings.api_admin_rate_limit)
async def delete_config(
    request: Request,
    api_key: str = Path(..., description="Client API key"),
    session_data: dict = Depends(require_elevated_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a client configuration (admin only).

    Removes the config but keeps the API key active.
    Use this to reset a client to unmanaged state.
    """
    client_ip = get_client_ip(request)
    username = session_data.get("username", "unknown")

    try:
        result = await db.execute(
            select(ClientConfig)
            .where(ClientConfig.api_key == api_key)
            .with_for_update()
        )
        config = result.scalar_one_or_none()

        if not config:
            raise ConfigNotFoundError(api_key=api_key)

        # Log the deletion before removing
        # Note: Pass empty dict for new_config to show all fields as "removed"
        await log_config_update(
            db=db,
            username=username,
            api_key=api_key,
            modem_id=config.last_seen_modem_id,
            ip_address=client_ip,
            old_config=config.config_plaintext,
            new_config={},  # Empty dict - all fields will appear as "removed"
            old_version=config.version,
            new_version=0,  # 0 indicates deletion
            old_status=config.status,
            new_status=ConfigStatus.UNMANAGED,  # Deleted = unmanaged
            old_sync_status=config.sync_status,
            new_sync_status=SyncStatus.NA,  # N/A after deletion
            success=True
        )

        # Delete version history first (no FK cascade)
        await db.execute(
            delete(ConfigVersion).where(ConfigVersion.api_key == api_key)
        )

        await db.delete(config)
        await db.commit()

        # Invalidate cache after commit
        await invalidate_config_cache(api_key)

        return {"success": True, "message": "Configuration deleted"}

    except ModemCheckError:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise ModemCheckError(
            error_code="INTERNAL_SERVER_ERROR",
            message=f"Config deletion failed: {str(e)}",
            status_code=500,
            details={"error_type": type(e).__name__}
        )
