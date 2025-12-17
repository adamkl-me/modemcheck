"""
Server-Sent Events (SSE) streaming for real-time config updates.

Provides:
- GET /api/admin/configs/stream - Real-time update stream

Features: Connection pooling, idle timeout, keepalive heartbeat.
Must be registered BEFORE /{api_key} routes to avoid route capture.
"""
import json
import asyncio
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import load_only

from app.core.config import settings
from app.core.limiter import limiter
from app.core.utils import utc_now
from app.middleware.auth import require_elevated_or_admin
from app.models import ClientConfig
from app.schemas.config import ConfigSSEUpdate
from datetime import timedelta

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Config Management"])


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
    from app.core.database import get_db_context

    async def event_generator():
        last_check = utc_now()
        connection_start = utc_now()
        max_connection_time = timedelta(minutes=30)  # Close idle connections after 30 min

        yield f"event: connected\ndata: {json.dumps({'timestamp': last_check.isoformat()})}\n\n"

        while True:
            # Check for client disconnect
            if await request.is_disconnected():
                logger.info("SSE client disconnected")
                break

            # Check for maximum connection time (prevents zombie connections)
            if utc_now() - connection_start > max_connection_time:
                logger.info("SSE connection timeout after 30 minutes")
                yield f"event: timeout\ndata: {json.dumps({'message': 'Connection timeout, please reconnect'})}\n\n"
                break

            try:
                # Create new DB session per poll to avoid connection leak
                async with get_db_context() as db:
                    # Use load_only to avoid loading large config fields (config_plaintext, config_encrypted)
                    # Only load columns needed for SSE updates to enable index-only scan
                    result = await db.execute(
                        select(ClientConfig)
                        .where(ClientConfig.updated_at > last_check)
                        .order_by(ClientConfig.updated_at.asc())
                        .limit(100)
                        .options(load_only(
                            ClientConfig.api_key_hash,
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
                            api_key=f"{config.api_key_hash[:8]}..." if config.api_key_hash else "unknown",
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
            yield f"event: keepalive\ndata: {json.dumps({'timestamp': utc_now().isoformat()})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
