"""
Pydantic schemas for request/response validation.
"""
from app.schemas.common import SuccessResponse, ErrorResponse, PaginationParams
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    SessionCheckResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
)
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
from app.schemas.api_key import (
    APIKeyCreate,
    APIKeyCreateResponse,
    APIKeyResponse,
    APIKeyListResponse,
    APIKeyToggleRequest,
    APIKeyDeleteRequest,
)
from app.schemas.modem_check import (
    ModemCheckUploadResponse,
    ModemInfo,
    ModemListResponse,
    CheckListItem,
    CheckListResponse,
    CheckDetailResponse,
    DateRangeRequest,
    BulkUploadResponse,
    DeleteCheckRequest,
    DeleteAllChecksRequest,
)

__all__ = [
    # Common
    "SuccessResponse",
    "ErrorResponse",
    "PaginationParams",
    # Auth
    "LoginRequest",
    "LoginResponse",
    "LogoutResponse",
    "SessionCheckResponse",
    "ChangePasswordRequest",
    "ChangePasswordResponse",
    # User
    "UserCreate",
    "UserResponse",
    "UserListResponse",
    "UserDeleteRequest",
    "UserChangeRoleRequest",
    "AdminPasswordResetRequest",
    "ForceLogoutRequest",
    "ForceLogoutResponse",
    # API Key
    "APIKeyCreate",
    "APIKeyCreateResponse",
    "APIKeyResponse",
    "APIKeyListResponse",
    "APIKeyToggleRequest",
    "APIKeyDeleteRequest",
    # Modem Check
    "ModemCheckUploadResponse",
    "ModemInfo",
    "ModemListResponse",
    "CheckListItem",
    "CheckListResponse",
    "CheckDetailResponse",
    "DateRangeRequest",
    "BulkUploadResponse",
    "DeleteCheckRequest",
    "DeleteAllChecksRequest",
]
