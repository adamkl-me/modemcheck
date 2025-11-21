"""
Authentication router for login, logout, session management, and password changes.
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response, Cookie
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.database import get_db
from app.core.limiter import limiter
from app.core.enhanced_limiter import check_user_rate_limit
from app.core.session_security import create_session_with_fingerprint, enforce_concurrent_session_limit, terminate_oldest_sessions
from app.core.security import (
    verify_password,
    hash_password,
    validate_password,
    create_session,
    delete_session,
    generate_csrf_token,
    check_account_locked,
    record_failed_login,
    clear_failed_logins,
)
from app.core.audit import log_user_activity
from app.core.config import settings
from app.models import User
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    SessionCheckResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
)
from app.middleware.auth import (
    get_current_user_from_session,
    require_authenticated_user,
    require_authenticated_user_bypass_password_check,
    get_client_ip,
    get_user_agent,
    get_user_from_db,
)
from sqlalchemy import select, update

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/login", response_model=LoginResponse)
@limiter.limit(lambda: settings.auth_rate_limit)
async def login(
    login_data: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db)
):
    """
    Authenticate user and create session.

    Security features:
    - Account lockout after 5 failed attempts (30 minutes)
    - Argon2id password hashing with PBKDF2 backward compatibility
    - Redis session storage with 1-hour sliding window
    - Comprehensive audit logging
    """
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)

    # Check account lockout (skip in test environment)
    if not settings.is_test():
        is_locked, remaining_seconds = await check_account_locked(login_data.username)
        if is_locked:
            minutes_remaining = (remaining_seconds + 59) // 60  # Round up
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Account locked due to too many failed login attempts. Try again in {minutes_remaining} minutes."
            )

    # Get user from database
    user = await get_user_from_db(login_data.username, db)
    if not user:
        # Record failed login (user not found)
        await record_failed_login(login_data.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )

    # Verify password
    is_valid, needs_upgrade = verify_password(login_data.password, user.password_hash)
    if not is_valid:
        # Record failed login (wrong password)
        await record_failed_login(login_data.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )

    # Check per-user rate limit (100 requests/hour across all IPs)
    allowed, current_count, remaining = await check_user_rate_limit(
        username=login_data.username,
        limit=100,
        window_seconds=3600
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many requests from this account. {remaining} requests remaining."
        )

    # All validation passed - clear failed login attempts
    await clear_failed_logins(login_data.username)

    # Upgrade password hash if needed (PBKDF2 → Argon2id)
    if needs_upgrade:
        new_hash = hash_password(login_data.password)
        await db.execute(
            update(User)
            .where(User.username == login_data.username)
            .values(password_hash=new_hash)
        )
        await db.commit()

    # Update last login info
    await db.execute(
        update(User)
        .where(User.username == login_data.username)
        .values(last_login=datetime.utcnow(), last_login_ip=ip_address)
    )
    await db.commit()

    # Check concurrent session limit (max 5 active sessions per user)
    can_create_session = await enforce_concurrent_session_limit(
        username=login_data.username,
        max_sessions=5
    )

    if not can_create_session:
        # Automatically terminate oldest sessions to make room
        terminated = await terminate_oldest_sessions(
            username=login_data.username,
            keep_count=3  # Keep 3 most recent, terminate older ones
        )
        await log_user_activity(
            db=db,
            username=login_data.username,
            action_type="session_cleanup",
            ip_address=ip_address,
            success=True,
            user_role=user.role.value,
            user_agent=user_agent,
            action_details={"message": f"Terminated {terminated} old sessions due to concurrent session limit"}
        )

    # Create session
    session_id = await create_session(login_data.username, user.role.value)

    # Store device fingerprint with session for security tracking
    await create_session_with_fingerprint(session_id, login_data.username, request)

    # Set secure cookie
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_id,
        max_age=settings.session_ttl,
        httponly=settings.session_cookie_httponly,
        samesite=settings.session_cookie_samesite,
        secure=request.headers.get("X-Forwarded-Proto") == "https",  # Secure if behind HTTPS proxy
        path="/"
    )

    # Log successful login
    await log_user_activity(
        db=db,
        username=login_data.username,
        action_type="login",
        ip_address=ip_address,
        success=True,
        user_role=user.role.value,
        user_agent=user_agent,
        session_id=session_id
    )

    return LoginResponse(
        success=True,
        message="Login successful",
        username=login_data.username,
        role=user.role.value,
        must_change_password=user.must_change_password
    )


@router.post("/logout", response_model=LogoutResponse)
@limiter.limit(lambda: settings.auth_rate_limit)
async def logout(
    request: Request,
    response: Response,
    modemcheck_session: Optional[str] = Cookie(None),
    session_data: dict = Depends(require_authenticated_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Logout user and destroy session.
    """
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)

    # Delete session from Redis
    if modemcheck_session:
        await delete_session(modemcheck_session)

    # Clear cookie
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/"
    )

    # Log logout
    await log_user_activity(
        db=db,
        username=session_data["username"],
        action_type="logout",
        ip_address=ip_address,
        success=True,
        user_role=session_data.get("role"),
        user_agent=user_agent,
        session_id=modemcheck_session
    )

    return LogoutResponse(
        success=True,
        message="Logout successful"
    )


@router.get("/session_check", response_model=SessionCheckResponse, response_model_exclude_none=True)
async def session_check(
    session_data: Optional[dict] = Depends(get_current_user_from_session),
    modemcheck_session: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Check if user has valid session.

    Returns session info and CSRF token if authenticated.
    """
    if not session_data:
        return SessionCheckResponse(authenticated=False)

    # Generate CSRF token for subsequent requests
    csrf_token = await generate_csrf_token(modemcheck_session)

    # Get must_change_password flag from database
    user = await get_user_from_db(session_data["username"], db)
    must_change_password = user.must_change_password if user else False

    return SessionCheckResponse(
        authenticated=True,
        username=session_data["username"],
        role=session_data["role"],
        csrf_token=csrf_token,
        must_change_password=must_change_password
    )


@router.post("/change_password", response_model=ChangePasswordResponse)
@limiter.limit(lambda: settings.auth_rate_limit)
async def change_password(
    password_data: ChangePasswordRequest,
    request: Request,
    session_data: dict = Depends(require_authenticated_user_bypass_password_check),
    db: AsyncSession = Depends(get_db)
):
    """
    Change user's password.

    Requires:
    - Current password verification
    - New password must meet policy requirements
    """
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    username = session_data["username"]

    # Get user from database
    user = await get_user_from_db(username, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Verify current password
    is_valid, _ = verify_password(password_data.current_password, user.password_hash)
    if not is_valid:
        await log_user_activity(
            db=db,
            username=username,
            action_type="change_password",
            ip_address=ip_address,
            success=False,
            user_role=session_data.get("role"),
            user_agent=user_agent,
            failure_reason="Invalid current password"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect"
        )

    # Validate new password
    is_valid_password, error_message = validate_password(password_data.new_password)
    if not is_valid_password:
        await log_user_activity(
            db=db,
            username=username,
            action_type="change_password",
            ip_address=ip_address,
            success=False,
            user_role=session_data.get("role"),
            user_agent=user_agent,
            failure_reason=f"Password policy violation: {error_message}"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_message
        )

    # Hash new password
    new_hash = hash_password(password_data.new_password)

    # Update password in database
    await db.execute(
        update(User)
        .where(User.username == username)
        .values(password_hash=new_hash, must_change_password=False)
    )
    await db.commit()

    # Log successful password change
    await log_user_activity(
        db=db,
        username=username,
        action_type="change_password",
        ip_address=ip_address,
        success=True,
        user_role=session_data.get("role"),
        user_agent=user_agent
    )

    return ChangePasswordResponse(
        success=True,
        message="Password changed successfully"
    )


@router.post("/change_own_password", response_model=ChangePasswordResponse)
@limiter.limit(lambda: settings.auth_rate_limit)
async def change_own_password(
    password_data: dict,
    request: Request,
    session_data: dict = Depends(require_authenticated_user_bypass_password_check),
    db: AsyncSession = Depends(get_db)
):
    """
    Change user's own password (for forced password changes after login).

    Only requires new_password - no current password verification.
    This matches the v1 CGI 'change_own_password' action.
    """
    from app.core.security import hash_password, validate_password
    from sqlalchemy import update

    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    username = session_data["username"]

    # Get new password from request
    new_password = password_data.get("new_password", "")

    # Get user from database
    user = await get_user_from_db(username, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Validate new password
    is_valid_password, error_message = validate_password(new_password)
    if not is_valid_password:
        await log_user_activity(
            db=db,
            username=username,
            action_type="change_own_password",
            ip_address=ip_address,
            success=False,
            user_role=session_data.get("role"),
            user_agent=user_agent,
            failure_reason=error_message
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_message
        )

    # Hash new password
    new_hash = hash_password(new_password)

    # Update password and clear must_change_password flag
    await db.execute(
        update(User)
        .where(User.username == username)
        .values(password_hash=new_hash, must_change_password=False)
    )
    await db.commit()

    # Log success
    await log_user_activity(
        db=db,
        username=username,
        action_type="change_own_password",
        ip_address=ip_address,
        success=True,
        user_role=session_data.get("role"),
        user_agent=user_agent
    )

    return ChangePasswordResponse(
        success=True,
        message="Password changed successfully"
    )
