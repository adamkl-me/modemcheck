"""
Admin router for API key management, audit logs, and configuration.
"""
import secrets
from datetime import datetime, timedelta
from typing import List
from fastapi import APIRouter, Depends, Request

from app.core.utils import utc_now
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update, and_, func, Integer, case

from app.core.database import get_db
from app.core.audit import log_user_activity
from app.core.limiter import limiter
from app.core.config import settings
from app.core.errors import InvalidAPIKeyPreviewError, APIKeyNotFoundError
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
    Create a new API key with dual storage (hash + encrypted) for security (v7.1+).

    Security:
    - Generates 256-bit random API key (cryptographically secure)
    - Stores SHA-256 hash for validation (one-way, fast lookup)
    - Stores AES-256-GCM encrypted plaintext for admin reveal
    - Returns plaintext ONLY ONCE (must be saved by user)

    Requires: elevated or admin role
    """
    from app.core.api_key_crypto import encrypt_api_key_for_storage

    # Generate secure random API key (32 bytes = 64 hex chars)
    new_api_key = secrets.token_hex(32)

    # Hash + encrypt for storage (convenience function)
    api_key_hash, encrypted_hex, salt_hex = encrypt_api_key_for_storage(new_api_key)

    # Create API key record with hash-based storage (v8.0+)
    api_key = APIKey(
        api_key_hash=api_key_hash,  # Primary key - SHA-256 hash for validation
        api_key_encrypted=encrypted_hex,  # Encrypted plaintext for admin reveal
        encryption_salt=salt_hex,  # Salt for decryption
        name=key_data.name,
        created_at=utc_now(),
        is_active=True
    )

    db.add(api_key)
    await db.commit()

    # Invalidate API key cache (forces hash-based repopulation)
    from app.core.api_key_cache import APIKeyCache
    await APIKeyCache.invalidate_cache()

    # Log creation (audit trail)
    await log_user_activity(
        db=db,
        username=session_data["username"],
        action_type="create_api_key",
        ip_address=get_client_ip(request),
        success=True,
        user_role=session_data.get("role"),
        action_details={"key_name": key_data.name, "key_hash_prefix": api_key_hash[:16]},
        user_agent=get_user_agent(request)
    )

    return APIKeyCreateResponse(
        success=True,
        message="API key created successfully. Save it now - it cannot be recovered later.",
        api_key=new_api_key,  # ⚠️ ONLY TIME PLAINTEXT IS SHOWN - must be saved!
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

    v8.0+: Decrypts each key to create preview (first4...last4).
    This is secure because previews are computed on-demand, not stored.

    Requires: elevated or admin role
    """
    from app.core.api_key_crypto import decrypt_api_key_from_storage

    result = await db.execute(select(APIKey))
    keys = result.scalars().all()

    key_list = []
    for key in keys:
        # Decrypt to create preview (v8.0+: no plaintext column)
        try:
            plaintext = decrypt_api_key_from_storage(key.api_key_encrypted, key.encryption_salt)
            preview = create_api_key_preview(plaintext)
        except Exception:
            # Fallback if decryption fails (shouldn't happen)
            preview = f"{key.api_key_hash[:4]}...{key.api_key_hash[-4:]}"

        key_list.append(APIKeyResponse(
            api_key_preview=preview,
            name=key.name,
            created_at=key.created_at,
            last_used=key.last_used,
            is_active=key.is_active
        ))

    return APIKeyListResponse(success=True, api_keys=key_list)


async def find_api_key_by_preview(db: AsyncSession, api_key_preview: str) -> tuple[APIKey, str]:
    """
    Find an API key by its preview format (first4...last4).

    v8.0+: Since plaintext is no longer stored, we decrypt each key to match.
    This is O(n) but acceptable for small key counts (<100 keys typical).

    Args:
        db: Database session
        api_key_preview: Preview string in format "xxxx...yyyy"

    Returns:
        Tuple of (APIKey model, decrypted plaintext)

    Raises:
        InvalidAPIKeyPreviewError: If preview format is invalid
        APIKeyNotFoundError: If no matching key found
    """
    from app.core.api_key_crypto import decrypt_api_key_from_storage

    # Validate preview format
    if "..." not in api_key_preview or len(api_key_preview) != 11:
        raise InvalidAPIKeyPreviewError()

    first_part = api_key_preview[:4]
    last_part = api_key_preview[-4:]

    # v8.0+: Decrypt all keys and find matching one
    result = await db.execute(select(APIKey))
    all_keys = result.scalars().all()

    for key in all_keys:
        try:
            plaintext = decrypt_api_key_from_storage(key.api_key_encrypted, key.encryption_salt)
            if plaintext[:4] == first_part and plaintext[-4:] == last_part:
                return key, plaintext
        except Exception:
            # Skip keys that can't be decrypted
            continue

    raise APIKeyNotFoundError()


@router.get("/api_keys/reveal/{api_key_preview}")
@limiter.limit(lambda: settings.api_admin_rate_limit)
async def reveal_api_key(
    api_key_preview: str,
    request: Request,
    session_data: dict = Depends(require_elevated_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Reveal the full API key by decrypting from encrypted storage.

    Security:
    - Decrypts API key on-demand using AES-256-GCM
    - Access logged for audit trail (who revealed which key when)
    - Requires elevated/admin role
    - Used for "Select Existing API Key" workflow in admin UI

    This endpoint is used when a user needs to copy an existing API key.

    Requires: elevated or admin role
    """
    # Find API key by preview (decrypts all keys to match)
    target_key, plaintext_key = await find_api_key_by_preview(db, api_key_preview)

    # Log this access for audit purposes (CRITICAL for security)
    await log_user_activity(
        db=db,
        username=session_data["username"],
        action_type="reveal_api_key",
        ip_address=get_client_ip(request),
        success=True,
        user_role=session_data.get("role"),
        action_details={
            "key_name": target_key.name,
            "key_preview": api_key_preview,
            "key_hash_prefix": target_key.api_key_hash[:16] if target_key.api_key_hash else "none"
        },
        user_agent=get_user_agent(request)
    )

    return {
        "success": True,
        "api_key": plaintext_key,  # ✅ Decrypted on-demand
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
    # Find API key by preview (decrypts all keys to match)
    target_key, _ = await find_api_key_by_preview(db, toggle_data.api_key_preview)

    # Update status using hash-based primary key
    await db.execute(
        update(APIKey)
        .where(APIKey.api_key_hash == target_key.api_key_hash)
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
    # Find API key by preview (decrypts all keys to match)
    target_key, _ = await find_api_key_by_preview(db, delete_data.api_key_preview)

    # Delete key using hash-based primary key
    await db.execute(
        delete(APIKey).where(APIKey.api_key_hash == target_key.api_key_hash)
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
    # Use CASE expression instead of bitwise NOT (~) which doesn't work with PostgreSQL boolean columns
    stats_query = select(
        func.count(UserActivityLog.id).label('total_actions'),
        func.sum(case((UserActivityLog.success == False, 1), else_=0)).label('failed_actions'),
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
