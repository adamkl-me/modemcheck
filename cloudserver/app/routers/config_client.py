"""
Client-facing configuration synchronization endpoints.

Provides:
- POST /api/config/sync - HMAC-validated config sync
- GET /api/config/health - Public health check

No session authentication required (HMAC signature validation instead).
"""
import asyncio
import hashlib
import hmac
import logging
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.config import settings
from app.core.limiter import limiter
from app.core.utils import utc_now
from app.middleware.auth import get_client_ip
from app.models import APIKey
from app.schemas.config import (
    ConfigSyncRequest,
    ConfigSyncResponse,
    HealthCheckResponse,
)
from app.core.config_sync import sync_client_config_with_retry, calculate_config_hash, SyncResult
from app.core.config_cache import invalidate_config_cache, get_cache_stats
from app.core.errors import ModemCheckError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Config Management"])


@router.post("/api/config/sync", response_model=ConfigSyncResponse)
@limiter.limit(lambda: f"{settings.config_sync_burst_limit}; {settings.config_sync_hourly_limit}")
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

    Rate limited with two-tier limits:
    - Burst: CONFIG_SYNC_BURST_LIMIT (default: 10/5minutes)
    - Sustained: CONFIG_SYNC_HOURLY_LIMIT (default: 100/hour)

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
            server_timestamp=utc_now().isoformat(),
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
        timestamp=utc_now().isoformat(),
        database=database_status,
        cache=cache_status
    )
