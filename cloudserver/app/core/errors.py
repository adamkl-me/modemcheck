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
from datetime import datetime, timezone


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
        self.timestamp = datetime.now(timezone.utc).isoformat()

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


# ============================================================================
# Config Management Errors (CFG001-CFG012)
# ============================================================================

class ConfigEncryptionError(InternalServerError):
    """CFG001: Configuration encryption/decryption failed."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=f"Encryption error: {message}",
            details={"error_code": "CFG001", **(details or {})}
        )


class ConfigValidationError(ValidationError):
    """CFG002: Configuration validation failed."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=f"Config validation failed: {message}",
            details={"error_code": "CFG002", **(details or {})}
        )


class ConfigNotFoundError(NotFoundError):
    """CFG003: Client configuration not found."""

    def __init__(self, api_key: str, modem_id: str = None):
        # v2.1: modem_id is optional (primary key is api_key only)
        # SECURITY: Do not include API key in error message (information disclosure)
        if modem_id:
            identifier = f"modem {modem_id}"
        else:
            identifier = "for provided API key"
        super().__init__(
            resource="Client configuration",
            identifier=identifier
        )
        self.details["error_code"] = "CFG003"


class ConfigVersionConflictError(ConflictError):
    """CFG004: Configuration version conflict (optimistic locking)."""

    def __init__(self, expected_version: int, actual_version: int):
        super().__init__(
            message="Configuration version conflict - another update occurred",
            details={
                "error_code": "CFG004",
                "expected_version": expected_version,
                "actual_version": actual_version,
                "hint": "Reload configuration and retry"
            }
        )


class ConfigNonceReplayError(AuthenticationError):
    """CFG005: Nonce replay detected (potential attack)."""

    def __init__(self, nonce: str):
        super().__init__(
            message="Request replay detected - nonce already used",
            details={
                "error_code": "CFG005",
                "nonce_prefix": nonce[:16],
                "hint": "Generate a new nonce and retry"
            }
        )


class ConfigClockSkewError(AuthenticationError):
    """CFG006: Request timestamp too far from server time."""

    def __init__(self, client_time: str, server_time: str, max_skew_seconds: int):
        super().__init__(
            message=f"Clock skew too large (max {max_skew_seconds}s)",
            details={
                "error_code": "CFG006",
                "client_timestamp": client_time,
                "server_timestamp": server_time,
                "max_skew_seconds": max_skew_seconds,
                "hint": "Synchronize system clock (NTP) and retry"
            }
        )


class ConfigHashMismatchError(ValidationError):
    """CFG007: Configuration hash verification failed."""

    def __init__(self, expected_hash: str, actual_hash: str):
        super().__init__(
            message="Configuration hash mismatch - integrity check failed",
            details={
                "error_code": "CFG007",
                "expected_hash": expected_hash[:16],
                "actual_hash": actual_hash[:16],
                "hint": "Configuration may have been tampered with"
            }
        )


class ConfigLockedError(AuthorizationError):
    """CFG008: Configuration is locked - client cannot modify."""

    def __init__(self, modem_id: str):
        super().__init__(
            message="Configuration is locked by server - client modification not allowed",
            details={
                "error_code": "CFG008",
                "modem_id": modem_id,
                "hint": "Contact administrator to unlock configuration"
            }
        )


class ConfigBackupNotFoundError(NotFoundError):
    """CFG009: Configuration backup not found for rollback."""

    def __init__(self, api_key: str, version: str, modem_id: str = None):
        # v2.1: modem_id is optional (primary key is api_key only)
        # SECURITY: Do not include API key in error message (information disclosure)
        if modem_id:
            identifier = f"modem {modem_id}, version {version}"
        else:
            identifier = f"version {version}"
        super().__init__(
            resource="Configuration backup",
            identifier=identifier
        )
        self.details["error_code"] = "CFG009"


class ConfigCacheError(CacheError):
    """CFG010: Configuration cache operation failed."""

    def __init__(self, operation: str):
        super().__init__(operation=f"config {operation}")
        self.details["error_code"] = "CFG010"


class ConfigSchemaVersionError(ModemCheckError):
    """CFG011: Client schema version incompatible with server."""

    def __init__(self, client_version: int, server_version: int, minimum_version: int):
        super().__init__(
            error_code="CFG011",
            message="Client configuration schema version is incompatible",
            status_code=426,  # Upgrade Required
            details={
                "client_version": client_version,
                "server_version": server_version,
                "minimum_required_version": minimum_version,
                "hint": "Upgrade client to latest version"
            }
        )


class ConfigRollbackError(InternalServerError):
    """CFG012: Configuration rollback operation failed."""

    def __init__(self, reason: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=f"Rollback failed: {reason}",
            details={"error_code": "CFG012", **(details or {})}
        )
