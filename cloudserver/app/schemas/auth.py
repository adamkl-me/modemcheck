"""
Pydantic schemas for authentication and session management.
"""
from typing import Optional
from pydantic import BaseModel, Field, validator


class LoginRequest(BaseModel):
    """Login request schema."""
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1)

    class Config:
        json_schema_extra = {
            "example": {
                "username": "admin",
                "password": "SecurePassword123!"
            }
        }


class LoginResponse(BaseModel):
    """Login response schema."""
    success: bool
    message: Optional[str] = None
    username: Optional[str] = None
    role: Optional[str] = None
    must_change_password: Optional[bool] = None
    error: Optional[str] = None


class LogoutResponse(BaseModel):
    """Logout response schema."""
    success: bool
    message: str


class SessionCheckResponse(BaseModel):
    """Session check response schema."""
    model_config = {"exclude_none": True}

    authenticated: bool
    username: Optional[str] = None
    role: Optional[str] = None
    csrf_token: Optional[str] = None  # CSRF token for subsequent requests
    must_change_password: Optional[bool] = None


class ChangePasswordRequest(BaseModel):
    """Change password request schema."""
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=12)

    class Config:
        json_schema_extra = {
            "example": {
                "current_password": "OldPassword123!",
                "new_password": "NewSecurePassword456#"
            }
        }


class ChangePasswordResponse(BaseModel):
    """Change password response schema."""
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None


class ChangeOwnPasswordRequest(BaseModel):
    """Change own password request schema (for forced password changes)."""
    new_password: str = Field(..., min_length=12)

    class Config:
        json_schema_extra = {
            "example": {
                "new_password": "NewSecurePassword456#"
            }
        }
