"""
User management router for admin operations.
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update

from app.core.database import get_db
from app.core.limiter import limiter
from app.core.config import settings
from app.core.security import hash_password, validate_password, delete_user_sessions
from app.core.audit import log_user_activity
from app.models import User
from app.schemas.user import (
    UserCreate,
    UserResponse,
    UserListResponse,
    UserDeleteRequest,
    UserChangeRoleRequest,
    AdminPasswordResetRequest,
    ForceLogoutRequest,
    ForceLogoutResponse,
)
from app.schemas.common import SuccessResponse
from app.middleware.auth import (
    require_admin,
    get_client_ip,
    get_user_agent,
)
from app.middleware.csrf import verify_csrf

router = APIRouter(
    prefix="/api/users",
    tags=["User Management"],
    dependencies=[Depends(verify_csrf), Depends(require_admin)]
)


@router.post("", response_model=SuccessResponse)
@limiter.limit(lambda: settings.api_admin_rate_limit)
async def create_user(
    user_data: UserCreate,
    request: Request,
    session_data: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new user.

    Requires: admin role
    """
    # Check if user already exists
    result = await db.execute(
        select(User).where(User.username == user_data.username)
    )
    existing_user = result.scalars().first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User already exists"
        )

    # Validate password
    is_valid, error_msg = validate_password(user_data.password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )

    # Hash password
    password_hash = hash_password(user_data.password)

    # Create user
    new_user = User(
        username=user_data.username,
        password_hash=password_hash,
        role=user_data.role,
        created_at=datetime.utcnow(),
        must_change_password=user_data.must_change_password
    )

    db.add(new_user)
    await db.commit()

    # Log action
    await log_user_activity(
        db=db,
        username=session_data["username"],
        action_type="create_user",
        ip_address=get_client_ip(request),
        success=True,
        user_role=session_data.get("role"),
        action_details={"new_username": user_data.username, "new_role": user_data.role.value},
        user_agent=get_user_agent(request)
    )

    return SuccessResponse(
        success=True,
        message=f"User '{user_data.username}' created successfully"
    )


@router.get("", response_model=UserListResponse)
@limiter.limit(lambda: settings.api_admin_rate_limit)
async def list_users(
    request: Request,
    session_data: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    List all users.

    Requires: admin role
    """
    result = await db.execute(select(User))
    users = result.scalars().all()

    user_list = [
        UserResponse(
            username=user.username,
            role=user.role.value,
            created_at=user.created_at,
            last_login=user.last_login,
            last_login_ip=user.last_login_ip,
            must_change_password=user.must_change_password
        )
        for user in users
    ]

    return UserListResponse(success=True, users=user_list)


@router.delete("", response_model=SuccessResponse)
@limiter.limit(lambda: settings.api_admin_rate_limit)
async def delete_user(
    delete_data: UserDeleteRequest,
    request: Request,
    session_data: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a user.

    Requires: admin role
    Cannot delete yourself.
    """
    # Prevent self-deletion
    if delete_data.username == session_data["username"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account"
        )

    # Delete user
    result = await db.execute(
        delete(User).where(User.username == delete_data.username)
    )
    await db.commit()

    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Delete all sessions for this user
    await delete_user_sessions(delete_data.username)

    # Log action
    await log_user_activity(
        db=db,
        username=session_data["username"],
        action_type="delete_user",
        ip_address=get_client_ip(request),
        success=True,
        user_role=session_data.get("role"),
        action_details={"deleted_username": delete_data.username},
        user_agent=get_user_agent(request)
    )

    return SuccessResponse(
        success=True,
        message=f"User '{delete_data.username}' deleted successfully"
    )


@router.put("/change_role", response_model=SuccessResponse)
@limiter.limit(lambda: settings.api_admin_rate_limit)
async def change_user_role(
    role_data: UserChangeRoleRequest,
    request: Request,
    session_data: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Change a user's role.

    Requires: admin role
    """
    # Update role
    result = await db.execute(
        update(User)
        .where(User.username == role_data.username)
        .values(role=role_data.new_role)
    )
    await db.commit()

    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Log action
    await log_user_activity(
        db=db,
        username=session_data["username"],
        action_type="change_user_role",
        ip_address=get_client_ip(request),
        success=True,
        user_role=session_data.get("role"),
        action_details={"target_username": role_data.username, "new_role": role_data.new_role.value},
        user_agent=get_user_agent(request)
    )

    return SuccessResponse(
        success=True,
        message=f"User role changed to '{role_data.new_role.value}'"
    )


@router.put("/reset_password", response_model=SuccessResponse)
@limiter.limit(lambda: settings.api_admin_rate_limit)
async def admin_reset_password(
    reset_data: AdminPasswordResetRequest,
    request: Request,
    session_data: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Admin password reset (force password change).

    Requires: admin role
    """
    # Validate new password
    is_valid, error_msg = validate_password(reset_data.new_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )

    # Hash password
    password_hash = hash_password(reset_data.new_password)

    # Update password
    result = await db.execute(
        update(User)
        .where(User.username == reset_data.username)
        .values(
            password_hash=password_hash,
            must_change_password=reset_data.must_change_password
        )
    )
    await db.commit()

    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Log action
    await log_user_activity(
        db=db,
        username=session_data["username"],
        action_type="admin_reset_password",
        ip_address=get_client_ip(request),
        success=True,
        user_role=session_data.get("role"),
        action_details={"target_username": reset_data.username},
        user_agent=get_user_agent(request)
    )

    return SuccessResponse(
        success=True,
        message=f"Password reset for user '{reset_data.username}'"
    )


@router.post("/force_logout", response_model=ForceLogoutResponse)
@limiter.limit(lambda: settings.api_admin_rate_limit)
async def force_user_logout(
    logout_data: ForceLogoutRequest,
    request: Request,
    session_data: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Force logout of all sessions for a specific user.

    Requires: admin role
    """
    # Delete all sessions for target user
    sessions_deleted = await delete_user_sessions(logout_data.username)

    # Log action
    await log_user_activity(
        db=db,
        username=session_data["username"],
        action_type="force_user_logout",
        ip_address=get_client_ip(request),
        success=True,
        user_role=session_data.get("role"),
        action_details={"target_username": logout_data.username, "sessions_deleted": sessions_deleted},
        user_agent=get_user_agent(request)
    )

    return ForceLogoutResponse(
        success=True,
        message=f"Logged out user '{logout_data.username}'",
        sessions_deleted=sessions_deleted
    )
