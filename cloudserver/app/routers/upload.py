"""
Upload router for client data uploads with HMAC signature validation.
"""
import time
import re
import json
import hashlib
import hmac
import secrets
import asyncio
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, Form, File, UploadFile, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.core.database import get_db
from app.core.audit import log_client_submission
from app.core.config import settings
from app.core.limiter import limiter
from app.core.metric_extraction import extract_metrics
from app.models import APIKey, ModemCheck
from app.schemas.modem_check import ModemCheckUploadResponse
from app.middleware.auth import get_client_ip, get_user_agent

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
    if not timestamp:
        return False, "Missing request timestamp"

    try:
        request_time = int(timestamp)
    except (ValueError, TypeError):
        return False, "Invalid timestamp format"

    # Check timestamp within 5 minutes to prevent replay attacks
    current_time = int(time.time())
    time_diff = abs(current_time - request_time)
    if time_diff > 300:  # 5 minutes
        return False, f"Request timestamp too old (difference: {time_diff}s, max: 300s)"

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
        asyncio.create_task(APIKeyCache.update_last_used(api_key, db))

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

    # API key brute force protection
    from app.core.security import check_api_key_lockout, record_failed_api_key, clear_failed_api_keys

    is_locked, remaining_seconds = await check_api_key_lockout(client_ip)
    if is_locked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed API key attempts. Try again in {remaining_seconds} seconds."
        )

    # Validate API key
    is_valid, key_name = await validate_and_get_api_key(api_key, db)
    if not is_valid:
        # Record failed attempt in Redis (even in test mode, for brute force tests to verify)
        await record_failed_api_key(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key"
        )

    # Validate HMAC signature (MANDATORY - v6.0.0+ clients always send signature)
    if not x_request_timestamp or not x_request_signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing HMAC signature headers (X-Request-Timestamp and X-Request-Signature required)"
        )

    # Validate the signature
    is_valid_sig, sig_error = validate_request_signature(
        api_key, x_request_timestamp, modem_id, filename, checksum, x_request_signature
    )
    if not is_valid_sig:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Signature validation failed: {sig_error}"
        )

    # Validate required fields
    if not modem_id or not filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing modem_id or filename"
        )

    # Validate modem_id format: MODEL-MACADDRESS (e.g., XB8-AA:BB:CC:DD:EE:FF)
    # Model can be alphanumeric with underscores, MAC address uses hex digits and colons
    if not re.match(r'^[a-zA-Z0-9_]+-[A-Fa-f0-9:]+$', modem_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid modem_id format (expected: MODEL-MACADDRESS)"
        )

    # Validate filename format (supports optional UUID suffix for uniqueness)
    # Examples: 2024-01-01_12-00-00.json, 2024-01-01_12-00-00_123.json, 2024-01-01_12-00-00_a1b2c3d4.json

    # Security: Prevent path traversal attacks
    if '..' in filename or '/' in filename or '\\' in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename format (path traversal attempt detected)"
        )

    if not re.match(r'^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(_[a-zA-Z0-9]+)?\.json$', filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename format"
        )

    # Read file data
    file_data = await file.read(settings.max_upload_size + 1)

    if len(file_data) > settings.max_upload_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds {settings.max_upload_size // (1024*1024)}MB limit"
        )

    # Validate checksum
    if not checksum:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing checksum field (upgrade client to v6.0.0+)"
        )

    server_checksum = hashlib.sha256(file_data).hexdigest()
    if not secrets.compare_digest(checksum.lower(), server_checksum.lower()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Checksum validation failed"
        )

    # Parse JSON data
    try:
        json_data = json.loads(file_data.decode('utf-8'))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON data: {str(e)}"
        )

    # Extract sysinfo
    sysinfo = json_data.get('sysinfo', {})
    modem_type = sysinfo.get('modemtype', 'unknown')
    modem_mac = sysinfo.get('modemmac', 'unknown')
    check_time_raw = sysinfo.get('checktime')

    # Parse check_time (handle both Unix timestamp and ISO string formats)
    check_time = None
    check_time_str = None
    if check_time_raw:
        try:
            # If it's a Unix timestamp (integer), convert to datetime and ISO string
            if isinstance(check_time_raw, int):
                check_time = datetime.utcfromtimestamp(check_time_raw)
                check_time_str = check_time.isoformat() + 'Z'
            else:
                # If it's already an ISO string
                check_time_str = str(check_time_raw)
                check_time = datetime.fromisoformat(check_time_str.replace('Z', '+00:00'))
        except Exception:
            check_time = None
            check_time_str = None

    # Extract metrics from JSON data for efficient querying
    extracted_metrics = extract_metrics(json_data)

    # All validation passed - clear failed API key attempts
    await clear_failed_api_keys(client_ip)

    # Insert into database with extracted metrics
    db_filename = f"{modem_id}/{filename}"
    new_check = ModemCheck(
        modem_id=modem_id,
        modem_type=modem_type,
        check_time=check_time or datetime.utcnow(),
        filename=db_filename,
        full_data=json_data,
        created_at=datetime.utcnow(),
        # Extracted metrics for efficient querying
        **extracted_metrics
    )

    try:
        db.add(new_check)
        await db.commit()
        await db.refresh(new_check)
    except Exception as e:
        await db.rollback()
        # Check if duplicate
        if "unique constraint" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Check already exists"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database error"
            )

    # Log successful submission
    processing_time_ms = int((time.time() - start_time) * 1000)
    await log_client_submission(
        db=db,
        ip_address=client_ip,
        api_key_hash=api_key_hash,
        api_key_name=key_name,
        modem_id=modem_id,
        modem_type=modem_type,
        modem_mac=modem_mac,
        filename=filename,
        file_size=len(file_data),
        check_time=check_time,
        user_agent=user_agent,
        success=True,
        processing_time_ms=processing_time_ms
    )

    return ModemCheckUploadResponse(
        success=True,
        message="Check uploaded successfully",
        database_id=new_check.id,
        modem_id=modem_id,
        check_time=check_time_str
    )
