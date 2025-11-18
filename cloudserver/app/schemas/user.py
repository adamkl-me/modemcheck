"""
Pydantic schemas for user management.
"""
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field

from app.models.user import UserRole


class UserCreate(BaseModel):
    """Schema for creating a new user."""
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=12)
    role: UserRole = Field(default=UserRole.BASIC)
    must_change_password: bool = Field(default=True)

    class Config:
        json_schema_extra = {
            "example": {
                "username": "newuser",
                "password": "SecurePassword123!",
                "role": "basic",
                "must_change_password": True
            }
        }


class UserResponse(BaseModel):
    """Schema for user response (without password)."""
    username: str
    role: str
    created_at: datetime
    last_login: Optional[datetime] = None
    last_login_ip: Optional[str] = None
    must_change_password: bool

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    """Schema for user list response."""
    success: bool
    users: List[UserResponse]


class UserDeleteRequest(BaseModel):
    """Schema for deleting a user."""
    username: str = Field(..., min_length=1, max_length=255)


class UserChangeRoleRequest(BaseModel):
    """Schema for changing user role."""
    username: str = Field(..., min_length=1, max_length=255)
    new_role: UserRole


class AdminPasswordResetRequest(BaseModel):
    """Schema for admin password reset."""
    username: str = Field(..., min_length=1, max_length=255)
    new_password: str = Field(..., min_length=12)
    must_change_password: bool = Field(default=True)


class ForceLogoutRequest(BaseModel):
    """Schema for forcing user logout."""
    username: str = Field(..., min_length=1, max_length=255)


class ForceLogoutResponse(BaseModel):
    """Schema for force logout response."""
    success: bool
    message: str
    sessions_deleted: int
