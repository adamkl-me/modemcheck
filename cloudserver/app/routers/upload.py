"""
Upload router for client data uploads with HMAC signature validation.

This router handles HTTP concerns (authentication, rate limiting, error handling)
and delegates business logic to the service layer for better testability.
"""
import logging
import time
import hashlib
import hmac
import secrets
import asyncio
from typing import Optional

logger = logging.getLogger(__name__)
from fastapi import APIRouter, Depends, HTTPException, status, Request, Form, File, UploadFile, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.audit import log_client_submission
from app.core.config import settings
from app.core.limiter import limiter
from app.models import APIKey
from app.models.client_config import ClientConfig
from app.schemas.modem_check import ModemCheckUploadResponse
from app.middleware.auth import get_client_ip, get_user_agent
from app.services.upload_service import UploadService, UploadValidationError

router = APIRouter(prefix="/api/upload", tags=["Upload"])


def validate_request_signature(
    api_key: str,
    timestamp: str,
    modem_id: str,
    filename: str,
    checksum: str,
    provided_signature: str
) -> tuple[bool, str]:
    """
    Validate HMAC-SHA256 request signature to prevent replay attacks.

    Returns:
        (is_valid, error_message)
    """
    from app.core.security import validate_request_timestamp

    if not timestamp:
        logger.warning("HMAC validation failed: missing timestamp")
        return False, "Missing request timestamp"

    # Use shared timestamp validation
    is_valid_ts, ts_error = validate_request_timestamp(timestamp)
    if not is_valid_ts:
        logger.warning(f"HMAC validation failed: {ts_error}")
        return False, ts_error

    # Compute expected signature using HMAC-SHA256 (matches Go client)
    message = f"{timestamp}|{modem_id}|{filename}|{checksum}"
    expected_signature = hmac.new(
        api_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    # Timing-safe comparison
    if not secrets.compare_digest(provided_signature, expected_signature):
        return False, "Invalid request signature"

    return True, ""


async def validate_and_get_api_key(
    api_key: str,
    db: AsyncSession
) -> tuple[bool, Optional[str]]:
    """
    Validate API key and return key name if valid.

    Uses Redis cache for performance optimization.

    Returns:
        (is_valid, key_name)
    """
    from app.core.api_key_cache import APIKeyCache, api_key_cache_stats

    # Database fallback function
    async def get_active_keys_from_db():
        result = await db.execute(
            select(APIKey).where(APIKey.is_active == True)
        )
        return result.scalars().all()

    # Validate using cache with DB fallback
    is_valid, key_name = await APIKeyCache.validate_api_key_cached(
        api_key,
        get_active_keys_from_db
    )

    if is_valid:
        # Update cache statistics
        if await APIKeyCache.get_cached_keys() is not None:
            api_key_cache_stats.record_hit()
        else:
            api_key_cache_stats.record_miss()

        # Update last_used timestamp in background (non-blocking)
        # Performance: Avoids 10-50ms latency from waiting for DB commit
        # Note: Creates its own DB session to avoid session lifecycle conflicts
        asyncio.create_task(APIKeyCache.update_last_used(api_key))

    return is_valid, key_name


@router.post("", response_model=ModemCheckUploadResponse)
@limiter.limit(lambda: settings.upload_rate_limit)
async def upload_check(
    request: Request,
    api_key: str = Form(...),
    modem_id: str = Form(...),
    filename: str = Form(...),
    checksum: str = Form(...),
    file: UploadFile = File(...),
    x_request_timestamp: Optional[str] = Header(None),
    x_request_signature: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Upload modem check data from Go clients.

    This endpoint handles HTTP-level concerns (authentication, rate limiting)
    and delegates business logic to the service layer for better testability.

    Security features:
    - API key validation (timing-safe)
    - HMAC-SHA256 signature verification
    - Replay attack prevention (5-minute window)
    - SHA-256 checksum validation
    - 10MB file size limit
    - Input format validation
    """
    start_time = time.time()
    client_ip = get_client_ip(request)
    user_agent = get_user_agent(request)

    # Create API key hash for logging
    api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16] if api_key else 'none'

    # Step 1: Validate HMAC signature BEFORE any database operations
    # This rejects invalid requests early without expensive DB queries
    if not x_request_timestamp or not x_request_signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing HMAC signature headers (X-Request-Timestamp and X-Request-Signature required)"
        )

    # Validate the signature (no DB needed)
    is_valid_sig, sig_error = validate_request_signature(
        api_key, x_request_timestamp, modem_id, filename, checksum, x_request_signature
    )
    if not is_valid_sig:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Signature validation failed: {sig_error}"
        )

    # Step 2: API key brute force protection (Redis only, no DB)
    from app.core.security import check_api_key_lockout, record_failed_api_key, clear_failed_api_keys

    is_locked, remaining_seconds = await check_api_key_lockout(client_ip)
    if is_locked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed API key attempts. Try again in {remaining_seconds} seconds."
        )

    # Step 3: Validate API key (FIRST DATABASE OPERATION - only after signature validated)
    is_valid, key_name = await validate_and_get_api_key(api_key, db)
    if not is_valid:
        # Record failed attempt in Redis (even in test mode, for brute force tests to verify)
        await record_failed_api_key(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key"
        )

    # Step 4: Read file data (before service layer processing)
    file_data = await file.read(settings.max_upload_size + 1)

    # Step 5: Process upload using service layer
    upload_service = UploadService()
    try:
        saved_check, modem_type, modem_mac, original_filename, check_time_str = await upload_service.process_upload(
            modem_id=modem_id,
            filename=filename,
            checksum=checksum,
            file_data=file_data,
            max_file_size=settings.max_upload_size,
            db=db
        )
    except UploadValidationError as e:
        # Convert service layer errors to HTTP exceptions
        raise HTTPException(
            status_code=e.status_code,
            detail=e.message
        )

    # All validation passed - clear failed API key attempts
    await clear_failed_api_keys(client_ip)

    # Update last_seen_modem_id in ClientConfig if it exists for this API key
    # This populates the "Modem ID" column in the Client Configurations table
    # Also logs modem changes to audit log for history timeline
    try:
        config_result = await db.execute(
            select(ClientConfig).where(ClientConfig.api_key == api_key)
        )
        client_config = config_result.scalar_one_or_none()
        if client_config and client_config.last_seen_modem_id != modem_id:
            # Log modem change to audit log before updating
            from app.core.config_sync import _log_modem_change
            await _log_modem_change(
                db=db,
                api_key=api_key,
                old_modem_id=client_config.last_seen_modem_id,
                new_modem_id=modem_id,
                ip_address=client_ip
            )
            client_config.last_seen_modem_id = modem_id
            await db.commit()
    except Exception as e:
        # Non-critical - don't fail upload if config update fails
        logger.warning(f"Failed to update client config last_seen_modem_id: {type(e).__name__}: {e}")

    # Step 6: Log successful submission
    processing_time_ms = int((time.time() - start_time) * 1000)
    await log_client_submission(
        db=db,
        ip_address=client_ip,
        api_key_hash=api_key_hash,
        api_key_name=key_name,
        modem_id=modem_id,
        modem_type=modem_type,
        modem_mac=modem_mac,
        filename=original_filename,
        file_size=len(file_data),
        check_time=saved_check.check_time,
        user_agent=user_agent,
        success=True,
        processing_time_ms=processing_time_ms
    )

    return ModemCheckUploadResponse(
        success=True,
        message="Check uploaded successfully",
        database_id=saved_check.id,
        modem_id=modem_id,
        check_time=check_time_str
    )
