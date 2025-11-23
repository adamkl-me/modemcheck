"""
Centralized error handling for ModemCheck Cloud.

Provides:
- Typed exception hierarchy with correlation IDs
- Consistent error response format
- HTTP status code mapping
- Detailed error information for debugging
"""
import uuid
from typing import Dict, Any, Optional
from datetime import datetime


class ModemCheckError(Exception):
    """
    Base exception for all ModemCheck errors.

    Attributes:
        error_code: Machine-readable error code (e.g., "VALIDATION_ERROR")
        message: Human-readable error message
        status_code: HTTP status code
        details: Additional error context (optional)
        error_id: Unique correlation ID for tracking
        timestamp: When the error occurred
    """

    def __init__(
        self,
        error_code: str,
        message: str,
        status_code: int,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.error_id = str(uuid.uuid4())
        self.timestamp = datetime.utcnow().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Convert error to standardized response format."""
        return {
            "success": False,
            "error": {
                "code": self.error_code,
                "message": self.message,
                "error_id": self.error_id,
                "timestamp": self.timestamp,
                "details": self.details if self.details else None
            }
        }


# ============================================================================
# Validation Errors (400)
# ============================================================================

class ValidationError(ModemCheckError):
    """Input validation failed."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            error_code="VALIDATION_ERROR",
            message=message,
            status_code=400,
            details=details
        )


class InvalidParameterError(ModemCheckError):
    """Invalid parameter value provided."""

    def __init__(self, parameter: str, value: Any, reason: str):
        super().__init__(
            error_code="INVALID_PARAMETER",
            message=f"Invalid parameter '{parameter}': {reason}",
            status_code=400,
            details={"parameter": parameter, "value": str(value), "reason": reason}
        )


class MissingParameterError(ModemCheckError):
    """Required parameter missing."""

    def __init__(self, parameter: str):
        super().__init__(
            error_code="MISSING_PARAMETER",
            message=f"Required parameter '{parameter}' is missing",
            status_code=400,
            details={"parameter": parameter}
        )


# ============================================================================
# Authentication Errors (401)
# ============================================================================

class AuthenticationError(ModemCheckError):
    """Authentication failed."""

    def __init__(self, message: str = "Authentication failed", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            error_code="AUTHENTICATION_ERROR",
            message=message,
            status_code=401,
            details=details
        )


class InvalidCredentialsError(AuthenticationError):
    """Invalid username or password."""

    def __init__(self):
        super().__init__(
            message="Invalid username or password",
            details={"hint": "Check credentials and try again"}
        )


class SessionExpiredError(AuthenticationError):
    """Session has expired."""

    def __init__(self):
        super().__init__(
            message="Session has expired",
            details={"hint": "Please log in again"}
        )


class InvalidAPIKeyError(AuthenticationError):
    """Invalid or inactive API key."""

    def __init__(self):
        super().__init__(
            message="Invalid or inactive API key",
            details={"hint": "Check API key and ensure it is active"}
        )


# ============================================================================
# Authorization Errors (403)
# ============================================================================

class AuthorizationError(ModemCheckError):
    """Authorization failed - insufficient permissions."""

    def __init__(self, message: str = "Insufficient permissions", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            error_code="AUTHORIZATION_ERROR",
            message=message,
            status_code=403,
            details=details
        )


class InsufficientPermissionsError(AuthorizationError):
    """User lacks required permissions."""

    def __init__(self, required_role: str, current_role: str):
        super().__init__(
            message=f"This operation requires '{required_role}' role",
            details={"required_role": required_role, "current_role": current_role}
        )


class AccountLockedError(ModemCheckError):
    """Account is locked due to failed login attempts (rate limiting)."""

    def __init__(self, remaining_seconds: int):
        super().__init__(
            error_code="ACCOUNT_LOCKED",
            message="Account is temporarily locked due to too many failed login attempts",
            status_code=429,  # Rate limit, not authorization
            details={"remaining_seconds": remaining_seconds, "retry_after_seconds": remaining_seconds, "hint": "Wait for the lockout period to expire"}
        )


# ============================================================================
# Not Found Errors (404)
# ============================================================================

class NotFoundError(ModemCheckError):
    """Resource not found."""

    def __init__(self, resource: str, identifier: str):
        super().__init__(
            error_code="NOT_FOUND",
            message=f"{resource} not found",
            status_code=404,
            details={"resource": resource, "identifier": identifier}
        )


# ============================================================================
# Conflict Errors (409)
# ============================================================================

class ConflictError(ModemCheckError):
    """Resource conflict."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            error_code="CONFLICT",
            message=message,
            status_code=409,
            details=details
        )


class DuplicateResourceError(ConflictError):
    """Resource already exists."""

    def __init__(self, resource: str, identifier: str):
        super().__init__(
            message=f"{resource} already exists",
            details={"resource": resource, "identifier": identifier}
        )


# ============================================================================
# Rate Limit Errors (429)
# ============================================================================

class RateLimitError(ModemCheckError):
    """Rate limit exceeded."""

    def __init__(self, retry_after: int):
        super().__init__(
            error_code="RATE_LIMIT_EXCEEDED",
            message="Too many requests - rate limit exceeded",
            status_code=429,
            details={"retry_after_seconds": retry_after}
        )


# ============================================================================
# Server Errors (500)
# ============================================================================

class InternalServerError(ModemCheckError):
    """Internal server error."""

    def __init__(self, message: str = "An internal error occurred", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            error_code="INTERNAL_SERVER_ERROR",
            message=message,
            status_code=500,
            details=details
        )


class DatabaseError(InternalServerError):
    """Database operation failed."""

    def __init__(self, operation: str):
        super().__init__(
            message=f"Database {operation} failed",
            details={"operation": operation}
        )


class CacheError(InternalServerError):
    """Cache operation failed."""

    def __init__(self, operation: str):
        super().__init__(
            message=f"Cache {operation} failed",
            details={"operation": operation}
        )


# ============================================================================
# Service Unavailable Errors (503)
# ============================================================================

class ServiceUnavailableError(ModemCheckError):
    """Service temporarily unavailable."""

    def __init__(self, service: str):
        super().__init__(
            error_code="SERVICE_UNAVAILABLE",
            message=f"{service} is temporarily unavailable",
            status_code=503,
            details={"service": service}
        )
