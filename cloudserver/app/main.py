"""
ModemCheck Cloud API v2 - FastAPI application.

Main application entry point.
"""
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Request, status, Form, File, UploadFile, Header, Depends
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.database import init_db, create_tables, close_db, get_db
from app.core.security import close_redis, get_redis
from app.core.cache_provider import init_cache, close_cache
from app.core.init_data import create_default_admin
from app.core.limiter import limiter
from app.core.errors import ModemCheckError
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.routers import auth, upload, db_api, admin, users, data_mgmt


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events.
    """
    # Startup
    print(f"Starting {settings.app_name}...")
    print(f"Environment: {settings.app_env}")
    print(f"Database: {settings.database_url.split('@')[1] if '@' in settings.database_url else 'configured'}")
    print(f"Redis: {settings.redis_host}:{settings.redis_port}")

    # Initialize database
    init_db()
    print("Database initialized")

    # Create tables if they don't exist
    await create_tables()
    print("Database tables created")

    # Create default admin user if needed
    await create_default_admin()

    # Initialize cache with Redis fallback support
    redis_client = await get_redis()
    await init_cache(redis_client, enable_fallback=True)
    print("Cache initialized with fallback support")

    yield

    # Shutdown
    print("Shutting down...")
    await close_cache()
    await close_db()
    await close_redis()
    print("Cleanup complete")


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    description="ModemCheck Cloud Storage API - FastAPI version with PostgreSQL",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,  # Disable docs in production
    redoc_url="/redoc" if settings.debug else None,
)

# Configure rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# Security headers middleware (must be added before CORS)
app.add_middleware(SecurityHeadersMiddleware)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_origins_list(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(ModemCheckError)
async def modemcheck_error_handler(request: Request, exc: ModemCheckError):
    """
    Handle all ModemCheckError exceptions with standardized response format.

    Returns JSON with:
    - success: false
    - error.code: Machine-readable error code
    - error.message: Human-readable message
    - error.error_id: Unique correlation ID for tracking
    - error.timestamp: When the error occurred
    - error.details: Additional context (optional)
    """
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict()
    )


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """Custom 404 handler."""
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"success": False, "error": "Endpoint not found"}
    )


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    """Custom 500 handler."""
    # Log the error (in production, use proper logging)
    if settings.debug:
        import traceback
        print(f"Internal error: {exc}")
        traceback.print_exc()

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"success": False, "error": "Internal server error"}
    )


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint for Docker/K8s."""
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": "2.0.0",
        "environment": settings.app_env
    }


@app.get("/health/db")
async def database_health():
    """
    Database connection pool health check.

    Returns pool statistics including:
    - Pool size and overflow settings
    - Current connections (checked out, in pool)
    - Connection utilization percentage
    """
    from app.core.database import engine

    if not engine:
        return {
            "status": "error",
            "error": "Database engine not initialized"
        }

    pool = engine.pool

    # Calculate pool statistics
    pool_size = pool.size()
    checked_out = pool.checkedout()
    overflow = pool.overflow()
    checkedin = pool.checkedin()

    # Calculate total capacity and utilization
    total_capacity = settings.db_pool_size + settings.db_max_overflow
    current_connections = checked_out + checkedin
    utilization = (checked_out / total_capacity * 100) if total_capacity > 0 else 0

    return {
        "status": "healthy",
        "pool": {
            "size": pool_size,
            "max_overflow": settings.db_max_overflow,
            "total_capacity": total_capacity,
            "checked_out": checked_out,
            "checked_in": checkedin,
            "overflow": overflow,
            "current_connections": current_connections,
            "utilization_percent": round(utilization, 2)
        },
        "config": {
            "pool_size_per_worker": settings.db_pool_size,
            "max_overflow_per_worker": settings.db_max_overflow,
            "workers": settings.workers,
            "total_app_capacity": total_capacity * settings.workers,
            "postgres_max_connections": 200
        }
    }


@app.get("/health/cache")
async def cache_health():
    """
    Cache backend health check with automatic fallback status.

    Returns cache statistics including:
    - Backend type (redis or memory)
    - Redis availability status
    - Degraded mode warnings
    - Memory cache statistics (if applicable)
    """
    from app.core.cache_provider import get_cache

    try:
        cache = await get_cache()

        # Check if cache has get_stats method (FallbackCache)
        if hasattr(cache, 'get_stats'):
            stats = cache.get_stats()
        else:
            # Fallback for simpler cache implementations
            is_healthy = await cache.is_healthy()
            stats = {
                "type": "unknown",
                "using_fallback": False
            }

        # Determine status based on fallback state
        using_fallback = stats.get("using_fallback", False)
        cache_type = stats.get("type", "unknown")

        if using_fallback or cache_type == "in_memory":
            status = "degraded"
            message = "Using in-memory cache fallback (Redis unavailable)"
        else:
            status = "healthy"
            message = "Using Redis cache backend"

        return {
            "status": status,
            "message": message,
            "backend": "memory" if using_fallback else "redis",
            "cache_type": cache_type,
            "using_fallback": using_fallback,
            "failure_count": stats.get("failure_count", 0),
            "failover_time": stats.get("failover_time"),
            "failover_duration_seconds": stats.get("failover_duration_seconds"),
            "memory_cache": {
                "size": stats.get("size", 0),
                "max_size": stats.get("max_size", 0),
                "utilization": stats.get("utilization", 0)
            } if using_fallback or cache_type == "in_memory" else None,
            "warning": "⚠️  Sessions and rate limiting not shared across workers in degraded mode" if using_fallback else None
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "message": "Cache health check failed"
        }


# Root endpoint - redirect based on authentication
@app.get("/")
async def root(request: Request):
    """
    Root endpoint - redirects to appropriate page based on authentication.

    - Authenticated users -> /viewer (home page for all users)
    - Unauthenticated users -> /login
    - Upload API port (22560) -> JSON info
    """
    from fastapi.responses import RedirectResponse
    from app.core.security import verify_session

    # Check if this is the upload API port (return JSON for clients)
    referer = request.headers.get("Referer", "")
    if "22560" in referer or request.url.port == 22560:
        return {
            "app": settings.app_name,
            "version": "2.0.0",
            "status": "running",
            "purpose": "Client upload API",
            "endpoint": "/api/upload"
        }

    # Check authentication status
    session_cookie = request.cookies.get("modemcheck_session")
    session_data = None
    if session_cookie:
        session_data = await verify_session(session_cookie)

    # Redirect based on auth status
    if session_data:
        # Authenticated - go to viewer (home page)
        return RedirectResponse(url="/viewer", status_code=302)
    else:
        # Not authenticated - go to login
        return RedirectResponse(url="/login", status_code=302)


# Include routers
app.include_router(auth.router)
app.include_router(upload.router)
app.include_router(db_api.router)
app.include_router(admin.router)
app.include_router(users.router)
app.include_router(data_mgmt.router)

# Root POST endpoint - proxy to upload (allows clients to skip /api/upload path)
@app.post("/")
@limiter.limit("60/minute")  # Upload rate limit: 60 requests per minute
async def root_upload(
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
    Root upload endpoint - same as /api/upload but accessible at /.

    This allows Go clients to upload without specifying a CloudPath.
    """
    from app.routers.upload import upload_check
    return await upload_check(
        request=request,
        api_key=api_key,
        modem_id=modem_id,
        filename=filename,
        checksum=checksum,
        file=file,
        x_request_timestamp=x_request_timestamp,
        x_request_signature=x_request_signature,
        db=db
    )


# Mount static files (HTML/CSS/JS for web UI)
static_path = Path(__file__).parent.parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

    # Serve HTML files at root paths with authentication checks
    @app.get("/viewer")
    async def viewer(request: Request):
        """
        Database viewer interface - accessible to all authenticated users.

        Server-side enforcement: Requires valid session (any role).
        """
        from app.core.security import verify_session

        # Check authentication
        session_cookie = request.cookies.get("modemcheck_session")
        session_data = None
        if session_cookie:
            session_data = await verify_session(session_cookie)

        if not session_data:
            # Not authenticated - redirect to login
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url="/login", status_code=302)

        # Authenticated - serve viewer HTML
        return FileResponse(static_path / "db-viewer.html")

    @app.get("/login")
    async def login_page():
        """User login page - accessible to all."""
        return FileResponse(static_path / "login.html")

    @app.get("/admin")
    async def admin_page(request: Request):
        """
        Admin dashboard - accessible to elevated and admin users only.

        Server-side enforcement: Requires valid session with elevated or admin role.
        """
        from app.core.security import verify_session
        from app.models import UserRole

        # Check authentication
        session_cookie = request.cookies.get("modemcheck_session")
        session_data = None
        if session_cookie:
            session_data = await verify_session(session_cookie)

        if not session_data:
            # Not authenticated - redirect to login
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url="/login", status_code=302)

        # Check role - admin and elevated only
        user_role = session_data.get("role", "").upper()
        if user_role not in ["ADMIN", "ELEVATED"]:
            # Wrong role - show forbidden page
            return FileResponse(static_path / "forbidden.html", status_code=403)

        # Authorized - serve admin HTML
        return FileResponse(static_path / "admin.html")

    @app.get("/forbidden")
    async def forbidden_page():
        """Access denied error page."""
        return FileResponse(static_path / "forbidden.html", status_code=403)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info"
    )
