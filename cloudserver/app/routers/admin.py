"""
Admin router for API key management, audit logs, and configuration.
"""
import secrets
from typing import List
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update, and_, func, Integer

from app.core.database import get_db
from app.core.audit import log_user_activity
from app.core.limiter import limiter
from app.core.config import settings
from app.models import APIKey, UserActivityLog, ClientSubmissionLog, ConfigDefaults
from app.schemas.api_key import (
    APIKeyCreate,
    APIKeyCreateResponse,
    APIKeyResponse,
    APIKeyListResponse,
    APIKeyToggleRequest,
    APIKeyDeleteRequest,
)
from app.schemas.common import SuccessResponse
from app.middleware.auth import (
    require_admin,
    require_elevated_or_admin,
    get_client_ip,
    get_user_agent,
)
from app.middleware.csrf import verify_csrf

router = APIRouter(prefix="/api/admin", tags=["Admin"], dependencies=[Depends(verify_csrf)])


def create_api_key_preview(api_key: str) -> str:
    """Create preview of API key (first 4 + last 4 chars)."""
    if len(api_key) <= 8:
        return api_key
    return f"{api_key[:4]}...{api_key[-4:]}"


@router.post("/api_keys", response_model=APIKeyCreateResponse)
@limiter.limit(lambda: settings.api_admin_rate_limit)
async def create_api_key(
    key_data: APIKeyCreate,
    request: Request,
    session_data: dict = Depends(require_elevated_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new API key for client authentication.

    Requires: elevated or admin role
    """
    # Generate secure random API key (32 bytes = 64 hex chars)
    new_api_key = secrets.token_hex(32)

    # Create API key record
    api_key = APIKey(
        api_key=new_api_key,
        name=key_data.name,
        created_at=datetime.now(timezone.utc),
        is_active=True
    )

    db.add(api_key)
    await db.commit()

    # Invalidate API key cache
    from app.core.api_key_cache import APIKeyCache
    await APIKeyCache.invalidate_cache()

    # Log creation
    await log_user_activity(
        db=db,
        username=session_data["username"],
        action_type="create_api_key",
        ip_address=get_client_ip(request),
        success=True,
        user_role=session_data.get("role"),
        action_details={"key_name": key_data.name},
        user_agent=get_user_agent(request)
    )

    return APIKeyCreateResponse(
        success=True,
        message="API key created successfully",
        api_key=new_api_key,  # Only shown once!
        name=key_data.name
    )


@router.get("/api_keys", response_model=APIKeyListResponse)
@limiter.limit(lambda: settings.api_admin_rate_limit)
async def list_api_keys(
    request: Request,
    session_data: dict = Depends(require_elevated_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    List all API keys (without exposing the actual keys).

    Requires: elevated or admin role
    """
    result = await db.execute(select(APIKey))
    keys = result.scalars().all()

    key_list = [
        APIKeyResponse(
            api_key_preview=create_api_key_preview(key.api_key),
            name=key.name,
            created_at=key.created_at,
            last_used=key.last_used,
            is_active=key.is_active
        )
        for key in keys
    ]

    return APIKeyListResponse(success=True, api_keys=key_list)


@router.get("/api_keys/reveal/{api_key_preview}")
@limiter.limit(lambda: settings.api_admin_rate_limit)
async def reveal_api_key(
    api_key_preview: str,
    request: Request,
    session_data: dict = Depends(require_elevated_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Reveal the full API key given its preview.

    This endpoint is used when a user needs to copy an existing API key.
    Access is logged for security audit purposes.

    Requires: elevated or admin role
    """
    # Find API key by preview - extract the pattern from preview
    # Preview format is "first4...last4", so we need to extract these parts
    if "..." not in api_key_preview or len(api_key_preview) != 11:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid API key preview format"
        )

    first_part = api_key_preview[:4]
    last_part = api_key_preview[-4:]

    # Query database for keys matching this pattern
    # Using SQL functions to match first 4 and last 4 characters
    from sqlalchemy import and_, func

    query = select(APIKey).where(
        and_(
            func.substring(APIKey.api_key, 1, 4) == first_part,
            func.right(APIKey.api_key, 4) == last_part
        )
    )

    result = await db.execute(query)
    target_key = result.scalar_one_or_none()

    if not target_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )

    # Log this access for audit purposes
    await log_user_activity(
        db=db,
        username=session_data["username"],
        action_type="reveal_api_key",
        ip_address=get_client_ip(request),
        success=True,
        user_role=session_data.get("role"),
        action_details={"key_name": target_key.name, "key_preview": api_key_preview},
        user_agent=get_user_agent(request)
    )

    return {
        "success": True,
        "api_key": target_key.api_key,
        "name": target_key.name
    }


@router.put("/api_keys/toggle", response_model=SuccessResponse)
@limiter.limit(lambda: settings.api_admin_rate_limit)
async def toggle_api_key(
    toggle_data: APIKeyToggleRequest,
    request: Request,
    session_data: dict = Depends(require_elevated_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Toggle API key active status.

    Requires: elevated or admin role
    """
    # Find API key by preview - extract the pattern from preview
    if "..." not in toggle_data.api_key_preview or len(toggle_data.api_key_preview) != 11:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid API key preview format"
        )

    first_part = toggle_data.api_key_preview[:4]
    last_part = toggle_data.api_key_preview[-4:]

    # Query database for keys matching this pattern
    from sqlalchemy import and_, func

    query = select(APIKey).where(
        and_(
            func.substring(APIKey.api_key, 1, 4) == first_part,
            func.right(APIKey.api_key, 4) == last_part
        )
    )

    result = await db.execute(query)
    target_key = result.scalar_one_or_none()

    if not target_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )

    # Update status
    await db.execute(
        update(APIKey)
        .where(APIKey.api_key == target_key.api_key)
        .values(is_active=toggle_data.is_active)
    )
    await db.commit()

    # Invalidate API key cache
    from app.core.api_key_cache import APIKeyCache
    await APIKeyCache.invalidate_cache()

    # Log action
    await log_user_activity(
        db=db,
        username=session_data["username"],
        action_type="toggle_api_key",
        ip_address=get_client_ip(request),
        success=True,
        user_role=session_data.get("role"),
        action_details={"key_name": target_key.name, "new_status": toggle_data.is_active},
        user_agent=get_user_agent(request)
    )

    return SuccessResponse(
        success=True,
        message=f"API key {'activated' if toggle_data.is_active else 'deactivated'}"
    )


@router.delete("/api_keys", response_model=SuccessResponse)
@limiter.limit(lambda: settings.api_admin_rate_limit)
async def delete_api_key(
    delete_data: APIKeyDeleteRequest,
    request: Request,
    session_data: dict = Depends(require_elevated_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete an API key.

    Requires: elevated or admin role
    """
    # Find API key by preview - extract the pattern from preview
    if "..." not in delete_data.api_key_preview or len(delete_data.api_key_preview) != 11:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid API key preview format"
        )

    first_part = delete_data.api_key_preview[:4]
    last_part = delete_data.api_key_preview[-4:]

    # Query database for keys matching this pattern
    from sqlalchemy import and_, func

    query = select(APIKey).where(
        and_(
            func.substring(APIKey.api_key, 1, 4) == first_part,
            func.right(APIKey.api_key, 4) == last_part
        )
    )

    result = await db.execute(query)
    target_key = result.scalar_one_or_none()

    if not target_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )

    # Delete key
    await db.execute(
        delete(APIKey).where(APIKey.api_key == target_key.api_key)
    )
    await db.commit()

    # Invalidate API key cache
    from app.core.api_key_cache import APIKeyCache
    await APIKeyCache.invalidate_cache()

    # Log deletion
    await log_user_activity(
        db=db,
        username=session_data["username"],
        action_type="delete_api_key",
        ip_address=get_client_ip(request),
        success=True,
        user_role=session_data.get("role"),
        action_details={"key_name": target_key.name},
        user_agent=get_user_agent(request)
    )

    return SuccessResponse(
        success=True,
        message="API key deleted successfully"
    )


@router.get("/logs/user_activity")
@limiter.limit(lambda: settings.api_admin_rate_limit)
async def get_user_activity_logs(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    username: str = None,
    action_type: str = None,
    start_date: str = None,
    end_date: str = None,
    session_data: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Get user activity logs with optional filters.

    Requires: admin role

    Query parameters:
    - username: Filter by username
    - action_type: Filter by action type
    - start_date: Filter by start date (YYYY-MM-DD)
    - end_date: Filter by end date (YYYY-MM-DD)
    """
    # Build filter conditions
    conditions = []
    if username:
        conditions.append(UserActivityLog.username.ilike(f"%{username}%"))
    if action_type:
        conditions.append(UserActivityLog.action_type == action_type)
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date)
            conditions.append(UserActivityLog.timestamp >= start_dt)
        except ValueError:
            pass
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date)
            # Add one day to include the entire end date
            from datetime import timedelta
            end_dt = end_dt + timedelta(days=1)
            conditions.append(UserActivityLog.timestamp < end_dt)
        except ValueError:
            pass

    # Build query with filters
    query = select(UserActivityLog)
    if conditions:
        query = query.where(and_(*conditions))

    # Get total count
    count_query = select(func.count()).select_from(UserActivityLog)
    if conditions:
        count_query = count_query.where(and_(*conditions))
    count_result = await db.execute(count_query)
    total_count = count_result.scalar()

    # Calculate statistics
    stats_query = select(
        func.count(UserActivityLog.id).label('total_actions'),
        func.sum(func.cast(~UserActivityLog.success, Integer)).label('failed_actions'),
        func.count(func.distinct(UserActivityLog.username)).label('unique_users')
    )
    if conditions:
        stats_query = stats_query.where(and_(*conditions))
    stats_result = await db.execute(stats_query)
    stats_row = stats_result.first()

    # Get logs with pagination
    result = await db.execute(
        query
        .order_by(UserActivityLog.timestamp.desc())
        .limit(limit)
        .offset(offset)
    )
    logs = result.scalars().all()

    return {
        "success": True,
        "count": total_count,
        "stats": {
            "total_actions": stats_row.total_actions or 0,
            "failed_actions": stats_row.failed_actions or 0,
            "unique_users": stats_row.unique_users or 0
        },
        "logs": [
            {
                "id": log.id,
                "timestamp": log.timestamp.isoformat(),
                "username": log.username,
                "user_role": log.user_role,
                "action_type": log.action_type,
                "action_details": log.action_details,
                "ip_address": log.ip_address,
                "success": log.success,
                "failure_reason": log.failure_reason
            }
            for log in logs
        ]
    }


@router.get("/logs/client_submissions")
@limiter.limit(lambda: settings.api_admin_rate_limit)
async def get_client_submission_logs(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    modem_id: str = None,
    ip_address: str = None,
    start_date: str = None,
    end_date: str = None,
    session_data: dict = Depends(require_elevated_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Get client submission logs with optional filters.

    Requires: elevated or admin role

    Query parameters:
    - modem_id: Filter by modem ID
    - ip_address: Filter by IP address
    - start_date: Filter by start date (YYYY-MM-DD)
    - end_date: Filter by end date (YYYY-MM-DD)
    """
    # Build filter conditions
    conditions = []
    if modem_id:
        conditions.append(ClientSubmissionLog.modem_id.ilike(f"%{modem_id}%"))
    if ip_address:
        conditions.append(ClientSubmissionLog.ip_address.ilike(f"%{ip_address}%"))
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date)
            conditions.append(ClientSubmissionLog.timestamp >= start_dt)
        except ValueError:
            pass
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date)
            # Add one day to include the entire end date
            from datetime import timedelta
            end_dt = end_dt + timedelta(days=1)
            conditions.append(ClientSubmissionLog.timestamp < end_dt)
        except ValueError:
            pass

    # Build query with filters
    query = select(ClientSubmissionLog)
    if conditions:
        query = query.where(and_(*conditions))

    # Get total count
    count_query = select(func.count()).select_from(ClientSubmissionLog)
    if conditions:
        count_query = count_query.where(and_(*conditions))
    count_result = await db.execute(count_query)
    total_count = count_result.scalar()

    # Calculate statistics
    stats_query = select(
        func.count(ClientSubmissionLog.id).label('total_submissions'),
        func.sum(func.cast(~ClientSubmissionLog.success, Integer)).label('failed_submissions'),
        func.count(func.distinct(ClientSubmissionLog.modem_id)).label('unique_modems'),
        func.count(func.distinct(ClientSubmissionLog.api_key_hash)).label('unique_api_keys')
    )
    if conditions:
        stats_query = stats_query.where(and_(*conditions))
    stats_result = await db.execute(stats_query)
    stats_row = stats_result.first()

    # Get logs with pagination
    result = await db.execute(
        query
        .order_by(ClientSubmissionLog.timestamp.desc())
        .limit(limit)
        .offset(offset)
    )
    logs = result.scalars().all()

    return {
        "success": True,
        "count": total_count,
        "stats": {
            "total_submissions": stats_row.total_submissions or 0,
            "failed_submissions": stats_row.failed_submissions or 0,
            "unique_modems": stats_row.unique_modems or 0,
            "unique_api_keys": stats_row.unique_api_keys or 0
        },
        "logs": [
            {
                "id": log.id,
                "timestamp": log.timestamp.isoformat(),
                "modem_id": log.modem_id,
                "modem_type": log.modem_type,
                "filename": log.filename,
                "file_size": log.file_size,
                "api_key_name": log.api_key_name,
                "api_key_hash": log.api_key_hash,
                "ip_address": log.ip_address,
                "success": log.success,
                "failure_reason": log.failure_reason,
                "processing_time_ms": log.processing_time_ms
            }
            for log in logs
        ]
    }

# ============================================================================
# Config Defaults Endpoints
# ============================================================================

@router.get("/config_defaults")
@limiter.limit(lambda: settings.api_admin_rate_limit)
async def get_config_defaults(
    request: Request,
    session_data: dict = Depends(require_elevated_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the stored configuration defaults.

    Accessible to elevated and admin users.
    Returns the default configuration values for the config generator.
    """
    result = await db.execute(select(ConfigDefaults).limit(1))
    defaults_row = result.scalar_one_or_none()

    if defaults_row:
        return {
            "success": True,
            "defaults": defaults_row.defaults
        }
    else:
        # Return empty defaults if none are stored
        return {
            "success": True,
            "defaults": {}
        }


@router.post("/config_defaults")
@limiter.limit(lambda: settings.api_admin_rate_limit)
async def save_config_defaults(
    defaults_data: dict,
    request: Request,
    session_data: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Save configuration defaults.

    Admin only. Saves the default configuration values for the config generator.
    These defaults will be available to all users.
    """
    # Get existing defaults row or create new one
    result = await db.execute(select(ConfigDefaults).limit(1))
    defaults_row = result.scalar_one_or_none()

    if defaults_row:
        # Update existing defaults
        defaults_row.defaults = defaults_data
    else:
        # Create new defaults row
        defaults_row = ConfigDefaults(defaults=defaults_data)
        db.add(defaults_row)

    await db.commit()

    # Log the activity
    await log_user_activity(
        db=db,
        username=session_data["username"],
        action_type="update_config_defaults",
        ip_address=get_client_ip(request),
        success=True,
        action_details={"defaults_updated": True}
    )

    return {
        "success": True,
        "message": "Configuration defaults saved successfully"
    }
