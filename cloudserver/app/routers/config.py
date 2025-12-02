"""
Configuration management router (composition layer).

This module provides a unified entry point for all config management endpoints
by composing four specialized sub-routers:

- config_client: Client-facing endpoints (sync, health)
- config_admin_crud: Admin CRUD operations (list, create, get, update)
- config_admin_history: Version history and rollback
- config_admin_streaming: SSE real-time updates

Endpoints:
- POST /api/config/sync - Client config sync (HMAC authenticated)
- GET /api/config/health - Health check
- GET /api/admin/configs - List all configs
- POST /api/admin/configs - Create new config
- GET /api/admin/configs/stream - SSE updates (must be before /{api_key})
- GET /api/admin/configs/{api_key} - Get config details
- PUT /api/admin/configs/{api_key} - Update config
- POST /api/admin/configs/{api_key}/rollback/{version} - Rollback to version
- GET /api/admin/configs/{api_key}/history - Version history

Version 3.0: Simplified 3-state model (UNMANAGED, MANAGED, LOCKED) with single-track versioning.
"""
from fastapi import APIRouter

from app.routers.config_client import router as client_router
from app.routers.config_admin_crud import router as crud_router
from app.routers.config_admin_streaming import router as streaming_router
from app.routers.config_admin_history import router as history_router

router = APIRouter(tags=["Config Management"])

# Include sub-routers in specific order:
# 1. Client endpoints (no auth prefix, HMAC validation)
router.include_router(client_router)

# 2. Streaming endpoint MUST come before CRUD to avoid "stream" matching as api_key
router.include_router(streaming_router)

# 3. Admin CRUD operations (list, create, get, update)
router.include_router(crud_router)

# 4. Admin history and rollback operations
router.include_router(history_router)
