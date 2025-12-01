"""
Authentication and authorization dependencies for FastAPI routes.
"""
from typing import Optional
from fastapi import Depends, HTTPException, status, Request, Cookie
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import verify_session
from app.models import User, UserRole
from sqlalchemy import select


async def get_current_user_from_session(
    request: Request,
    modemcheck_session: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db)
) -> Optional[dict]:
    """
    Get current user from session cookie.

    Returns session data or None if not authenticated.
    Does NOT raise exception - use for optional authentication.
    """
    if not modemcheck_session:
        return None

    session_data = await verify_session(modemcheck_session)
    if not session_data:
        return None

    return session_data


async def require_authenticated_user(
    session_data: Optional[dict] = Depends(get_current_user_from_session),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """
    Require authenticated user.

    Raises 401 if not authenticated.
    Raises 403 if user must change password before continuing.
    """
    if not session_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )

    # Check if user must change password (for default admin accounts)
    username = session_data.get("username")
    if username:
        user = await get_user_from_db(username, db)
        if user and user.must_change_password:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Password change required. You must change your password before accessing other features.",
                headers={"X-Password-Change-Required": "true"}
            )

    return session_data


async def require_role(
    required_roles: list[UserRole],
    session_data: dict = Depends(require_authenticated_user)
) -> dict:
    """
    Require user to have one of the specified roles.

    Args:
        required_roles: List of allowed roles
        session_data: Current user session data

    Raises:
        403 if user doesn't have required role
    """
    user_role = session_data.get("role")

    if user_role not in [role.value for role in required_roles]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires one of: {', '.join([r.value for r in required_roles])}"
        )

    return session_data


async def require_admin(
    session_data: dict = Depends(require_authenticated_user)
) -> dict:
    """Require admin role."""
    return await require_role([UserRole.ADMIN], session_data)


async def require_elevated_or_admin(
    session_data: dict = Depends(require_authenticated_user)
) -> dict:
    """Require elevated or admin role."""
    return await require_role([UserRole.ADMIN, UserRole.ELEVATED], session_data)


def get_client_ip(request: Request) -> str:
    """
    Extract client IP address from request.

    SECURITY: Only trusts X-Forwarded-For header when the request comes from
    a trusted proxy (configured via TRUSTED_PROXIES setting). This prevents
    IP spoofing attacks where malicious clients set X-Forwarded-For directly.

    When running behind nginx/Docker, nginx sets X-Forwarded-For and requests
    come from Docker internal network (172.x.x.x), which is trusted by default.
    """
    from app.core.config import settings

    # Get the direct client IP (the IP that actually connected to us)
    direct_ip = request.client.host if request.client else "unknown"

    # Only trust X-Forwarded-For from trusted proxies
    if direct_ip != "unknown" and settings.is_trusted_proxy(direct_ip):
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # X-Forwarded-For can contain multiple IPs: client, proxy1, proxy2
            # The first IP is the original client (set by first proxy)
            return forwarded_for.split(",")[0].strip()

    return direct_ip


def get_user_agent(request: Request) -> str:
    """Extract User-Agent from request headers."""
    return request.headers.get("User-Agent", "unknown")


async def require_authenticated_user_bypass_password_check(
    session_data: Optional[dict] = Depends(get_current_user_from_session)
) -> dict:
    """
    Require authenticated user but bypass password change check.

    Used for password change endpoints to prevent lockout.
    Raises 401 if not authenticated.
    """
    if not session_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )

    return session_data


async def get_user_from_db(
    username: str,
    db: AsyncSession
) -> Optional[User]:
    """
    Get user from database by username.

    Args:
        username: Username to lookup
        db: Database session

    Returns:
        User object or None if not found
    """
    result = await db.execute(
        select(User).where(User.username == username)
    )
    return result.scalars().first()
