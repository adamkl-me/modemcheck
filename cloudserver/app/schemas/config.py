"""
Pydantic schemas for config management API endpoints.

Version 3.0: Simplified 3-state model (UNMANAGED, MANAGED, LOCKED) with sync_status.
"""
from typing import Dict, Any, Optional, List, Literal
from pydantic import BaseModel, Field, field_validator
from datetime import datetime


class ClientConfigSchema(BaseModel):
    """
    Type-safe schema for client configuration values (16 fields).

    Provides compile-time type checking and runtime validation.
    All fields are optional to support partial updates.
    """
    ModemAddress: Optional[str] = Field(None, description="Modem IP address or hostname")
    IgnitePassword: Optional[str] = Field(None, description="Comcast Ignite modem password")
    SpeedTestEnabled: Optional[bool] = Field(None, description="Enable speed tests")
    SpeedTestInterval: Optional[int] = Field(None, ge=1, le=1000, description="Speed test interval (Nth check)")
    SpeedTestConnections: Optional[int] = Field(None, ge=1, le=16, description="Parallel connections for speed tests")
    PingCount: Optional[int] = Field(None, ge=1, le=100, description="Number of ping tests per check")
    AutoUpdateEnabled: Optional[bool] = Field(None, description="Enable automatic client updates")
    UpdateChannel: Optional[Literal["stable", "beta", "test"]] = Field(None, description="Update channel")
    Silent: Optional[bool] = Field(None, description="Silent mode (no console output)")
    NoLogs: Optional[bool] = Field(None, description="Disable local log files")
    LocalCleanupEnabled: Optional[bool] = Field(None, description="Enable local file cleanup")
    LocalRetentionDays: Optional[int] = Field(None, ge=1, le=3650, description="Local file retention (1-3650 days)")
    EnableCloud: Optional[bool] = Field(None, description="Enable cloud uploads")
    CloudHost: Optional[str] = Field(None, description="Cloud server hostname")
    CloudPort: Optional[str] = Field(None, description="Cloud server port (numeric string)")
    CloudAPIKey: Optional[str] = Field(None, description="Cloud API key")

    @field_validator('CloudPort')
    @classmethod
    def validate_cloud_port(cls, v):
        """Validate CloudPort: numeric string, no leading zeros, 1-65535."""
        if v is not None and v:
            if not v.isdigit():
                raise ValueError("CloudPort must be numeric string")
            if len(v) > 1 and v[0] == '0':
                raise ValueError("CloudPort cannot have leading zeros")
            port_int = int(v)
            if port_int < 1 or port_int > 65535:
                raise ValueError(f"CloudPort {port_int} out of range (1-65535)")
        return v

    model_config = {
        "extra": "allow",  # Allow extra fields for forward compatibility
        "json_schema_extra": {
            "example": {
                "ModemAddress": "192.168.100.1",
                "PingCount": 25,
                "SpeedTestEnabled": True,
                "UpdateChannel": "stable"
            }
        }
    }


class ConfigSyncRequest(BaseModel):
    """
    Request schema for client configuration sync.

    Single endpoint handles all sync scenarios (no more preflight).
    HMAC signature format: {timestamp}|{nonce}|{config_hash}
    """
    api_key: str = Field(..., description="API key for authentication")
    modem_id: Optional[str] = Field(None, description="Modem ID for tracking (optional)")
    config: Dict[str, Any] = Field(..., description="Client configuration")
    version: int = Field(0, description="Current config version (0 if first sync)")
    config_hash: str = Field(..., description="SHA256 hash of config (canonical JSON)")
    timestamp: str = Field(..., description="Request timestamp (ISO 8601)")
    nonce: str = Field(..., description="Request nonce for replay protection (SHA256 hex)")
    signature: str = Field(..., description="HMAC-SHA256 signature")

    @field_validator('modem_id')
    @classmethod
    def validate_modem_id(cls, v):
        """Validate modem ID format if provided."""
        if v is not None and len(v) < 3:
            raise ValueError("modem_id must be at least 3 characters if provided")
        return v

    @field_validator('nonce')
    @classmethod
    def validate_nonce(cls, v):
        """Validate nonce is 64-char hex string (SHA256)."""
        if not v or len(v) != 64:
            raise ValueError("nonce must be 64-character hex string")
        try:
            int(v, 16)
        except ValueError:
            raise ValueError("nonce must be valid hexadecimal")
        return v

    @field_validator('version')
    @classmethod
    def validate_version(cls, v):
        """Validate version is non-negative and reasonable."""
        if v < 0:
            raise ValueError("version must be non-negative")
        if v > 999999:
            raise ValueError("version exceeds maximum (999999)")
        return v


class ConfigSyncResponse(BaseModel):
    """
    Response schema for configuration sync.

    Server returns authoritative config + metadata.
    """
    success: bool = Field(..., description="Sync success status")
    config: Dict[str, Any] = Field(..., description="Authoritative configuration")
    version: int = Field(..., description="Config version number")
    status: str = Field(..., description="Config status (unmanaged, managed, locked)")
    sync_status: str = Field(..., description="Sync status (n/a, pending, active)")
    config_hash: str = Field(..., description="SHA256 hash of config")
    config_changed: bool = Field(..., description="Whether client should apply config")
    server_timestamp: str = Field(..., description="Server timestamp (ISO 8601)")

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "config": {
                    "PingCount": 25,
                    "SpeedTestEnabled": True,
                    "UpdateChannel": "stable"
                },
                "version": 3,
                "status": "locked",
                "sync_status": "active",
                "config_hash": "abc123...",
                "config_changed": True,
                "server_timestamp": "2025-01-15T12:34:56.789012"
            }
        }
    }


class ConfigCreateRequest(BaseModel):
    """
    Request schema for admin configuration creation.

    Admin can create a config and optionally download it for manual deployment.
    Config is keyed by API key only.
    """
    api_key: str = Field(..., description="API key for the client")
    config: Dict[str, Any] = Field(..., description="Configuration to push to client")
    mode: str = Field("unmanaged", description="Management mode: 'unmanaged', 'managed', or 'locked'")

    @field_validator('mode')
    @classmethod
    def validate_mode(cls, v):
        """Validate mode is valid value."""
        if v not in ['unmanaged', 'managed', 'locked']:
            raise ValueError("mode must be 'unmanaged', 'managed', or 'locked'")
        return v


class ConfigCreateResponse(BaseModel):
    """Response schema for configuration creation."""
    success: bool = Field(..., description="Creation success status")
    api_key: str = Field(..., description="API key (truncated)")
    version: int = Field(..., description="Initial config version")
    status: str = Field(..., description="Config status")
    sync_status: str = Field(..., description="Sync status")
    config: Dict[str, Any] = Field(..., description="Created configuration (for download)")

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "api_key": "abc123...",
                "version": 1,
                "status": "managed",
                "sync_status": "pending",
                "config": {"PingCount": 100}
            }
        }
    }


class ConfigUpdateRequest(BaseModel):
    """
    Request schema for admin configuration update.

    Admin can update config and optionally change mode.
    """
    config: Dict[str, Any] = Field(..., description="New configuration")
    mode: Optional[str] = Field(None, description="Management mode: 'unmanaged', 'managed', or 'locked'")

    @field_validator('mode')
    @classmethod
    def validate_mode(cls, v):
        """Validate mode is valid value."""
        if v is not None and v not in ['unmanaged', 'managed', 'locked']:
            raise ValueError("mode must be 'unmanaged', 'managed', or 'locked'")
        return v


class ConfigUpdateResponse(BaseModel):
    """Response schema for configuration update."""
    success: bool = Field(..., description="Update success status")
    version: int = Field(..., description="New config version")
    status: str = Field(..., description="Current config status")
    sync_status: str = Field(..., description="Current sync status")
    version_created: bool = Field(..., description="Whether new version was created")

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "version": 2,
                "status": "locked",
                "sync_status": "pending",
                "version_created": True
            }
        }
    }


class ConfigRollbackRequest(BaseModel):
    """Request schema for configuration rollback."""
    reason: Optional[str] = Field(None, description="Reason for rollback")


class ConfigRollbackResponse(BaseModel):
    """Response schema for configuration rollback."""
    success: bool = Field(..., description="Rollback success status")
    version: int = Field(..., description="New version after rollback")
    rolled_back_to: int = Field(..., description="Target version that was restored")
    config: Dict[str, Any] = Field(..., description="Restored configuration")

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "version": 4,
                "rolled_back_to": 2,
                "config": {
                    "PingCount": 25,
                    "EnableCloud": True
                }
            }
        }
    }


class HealthCheckResponse(BaseModel):
    """Response schema for health check endpoint."""
    healthy: bool = Field(..., description="Overall health status")
    timestamp: str = Field(..., description="Server timestamp (ISO 8601)")
    database: str = Field(..., description="Database status: 'ok' or 'error'")
    cache: str = Field(..., description="Cache status: 'ok', 'degraded', or 'error'")

    model_config = {
        "json_schema_extra": {
            "example": {
                "healthy": True,
                "timestamp": "2025-01-15T12:34:56.789012",
                "database": "ok",
                "cache": "ok"
            }
        }
    }


class ConfigListItem(BaseModel):
    """Schema for config list item (admin dashboard)."""
    api_key: str = Field(..., description="API key (truncated for display)")
    api_key_full: str = Field(..., description="Full API key (for API calls)")
    last_seen_modem_id: Optional[str] = Field(None, description="Last seen modem ID (tracking only)")
    status: str = Field(..., description="Config status (unmanaged, managed, locked)")
    sync_status: str = Field(..., description="Sync status (n/a, pending, active)")
    version: int = Field(..., description="Current version number")
    last_sync: Optional[datetime] = Field(None, description="Last sync timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    updated_by: str = Field(..., description="Last updated by")

    model_config = {"from_attributes": True}


class ConfigListResponse(BaseModel):
    """Response schema for config list (admin dashboard)."""
    configs: List[ConfigListItem] = Field(..., description="List of configurations")
    total: int = Field(..., description="Total number of configurations")
    filtered: int = Field(..., description="Number after filtering")


class ConfigDetailResponse(BaseModel):
    """Response schema for detailed config view."""
    api_key: str = Field(..., description="API key")
    last_seen_modem_id: Optional[str] = Field(None, description="Last seen modem ID (tracking only)")
    config: Dict[str, Any] = Field(..., description="Configuration (plaintext)")
    status: str = Field(..., description="Config status")
    sync_status: str = Field(..., description="Sync status")
    version: int = Field(..., description="Current version")
    last_sync: Optional[datetime] = Field(None, description="Last sync timestamp")
    created_at: datetime = Field(..., description="Created timestamp")
    created_by: str = Field(..., description="Created by")
    updated_at: datetime = Field(..., description="Updated timestamp")
    updated_by: str = Field(..., description="Updated by")

    model_config = {"from_attributes": True}


class ConfigVersionItem(BaseModel):
    """Schema for config version history item."""
    id: int = Field(..., description="Version ID")
    version_number: int = Field(..., description="Version number")
    config: Dict[str, Any] = Field(..., description="Configuration snapshot")
    status_at_creation: str = Field(..., description="Status when version was created")
    sync_status_at_creation: Optional[str] = Field(None, description="Sync status when version was created")
    modem_id_at_creation: Optional[str] = Field(None, description="Modem ID when version was created")
    created_at: datetime = Field(..., description="When version was created")
    created_by: str = Field(..., description="Who created version")
    creation_reason: str = Field(..., description="Reason for version creation")
    ip_address: Optional[str] = Field(None, description="Client IP address")

    model_config = {"from_attributes": True}

    @property
    def version_display(self) -> str:
        """Get the display string for the version (e.g., 'v3')."""
        return f"v{self.version_number}"


class ModemEventItem(BaseModel):
    """Schema for modem event in history timeline."""
    id: int = Field(..., description="Event ID")
    event_type: str = Field(..., description="Event type: 'modem_change'")
    timestamp: datetime = Field(..., description="When event occurred")
    old_modem_id: Optional[str] = Field(None, description="Previous modem ID")
    new_modem_id: str = Field(..., description="New/current modem ID")
    ip_address: Optional[str] = Field(None, description="Client IP address")

    model_config = {"from_attributes": True}


class ConfigHistoryResponse(BaseModel):
    """Response schema for config history."""
    api_key: str = Field(..., description="API key")
    last_seen_modem_id: Optional[str] = Field(None, description="Last seen modem ID")
    versions: List[ConfigVersionItem] = Field(..., description="List of versions")
    modem_events: List[ModemEventItem] = Field(default_factory=list, description="List of modem events")
    total: int = Field(..., description="Total number of versions")
    total_modem_events: int = Field(default=0, description="Total number of modem events")
    current_version: int = Field(..., description="Current active version number")


class ConfigSSEUpdate(BaseModel):
    """Schema for SSE config update event."""
    api_key: str = Field(..., description="API key (truncated)")
    last_seen_modem_id: Optional[str] = Field(None, description="Last seen modem ID")
    status: str = Field(..., description="Current status")
    sync_status: str = Field(..., description="Current sync status")
    version: int = Field(..., description="Current version")
    last_sync: Optional[str] = Field(None, description="Last sync timestamp")
    updated_at: str = Field(..., description="Update timestamp")
