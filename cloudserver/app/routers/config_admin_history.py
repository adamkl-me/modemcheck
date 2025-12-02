"""
Admin config version history and rollback operations.

Provides:
- GET /api/admin/configs/{api_key}/history - Version history + modem events
- POST /api/admin/configs/{api_key}/rollback/{version} - Rollback to version

Requires: elevated or admin role.
"""
import logging

from fastapi import APIRouter, Depends, Request, Body, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.config import settings
from app.core.limiter import limiter
from app.core.utils import utc_now
from app.middleware.auth import require_elevated_or_admin, get_client_ip
from app.middleware.csrf import verify_csrf
from app.models import ClientConfig, ConfigVersion
from app.models.client_config import ConfigStatus, SyncStatus
from app.schemas.config import (
    ConfigRollbackRequest,
    ConfigRollbackResponse,
    ConfigHistoryResponse,
    ConfigVersionItem,
)
from app.core.config_sync import create_config_version
from app.core.config_audit import log_config_rollback
from app.core.config_cache import invalidate_config_cache
from app.core.errors import (
    ModemCheckError,
    ConfigNotFoundError,
    ConfigBackupNotFoundError,
    DatabaseError,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Config Management"])


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
        current_config.updated_at = utc_now()
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

    try:
        # Query versions using ORM (handles enum conversion automatically)
        versions_result = await db.execute(
            select(ConfigVersion)
            .where(ConfigVersion.api_key == api_key)
            .order_by(ConfigVersion.created_at.desc())
            .limit(limit)
        )
        versions = versions_result.scalars().all()

        # Get total count (separate query for accuracy)
        total_result = await db.execute(
            select(func.count(ConfigVersion.id))
            .where(ConfigVersion.api_key == api_key)
        )
        total = total_result.scalar() or 0

        # Get current config metadata
        current_result = await db.execute(
            select(ClientConfig.last_seen_modem_id, ClientConfig.version)
            .where(ClientConfig.api_key == api_key)
        )
        current_row = current_result.first()
        current_modem_id = current_row.last_seen_modem_id if current_row else None
        current_version = current_row.version if current_row else 0

        # Build version items (ORM objects have proper enum attributes)
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

    except ModemCheckError:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch config history for {api_key[:8]}...: {e}")
        raise DatabaseError(f"Failed to retrieve config history: {type(e).__name__}")
