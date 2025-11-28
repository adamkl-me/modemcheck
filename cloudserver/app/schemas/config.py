"""
Pydantic schemas for config management API endpoints.

Version 2.0: Dual-track versioning with 6 status states.
"""
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, validator
from datetime import datetime


class PreflightRequest(BaseModel):
    """
    Request schema for pre-flight API key validation.

    Called BEFORE modem login to validate API key and get any pending config.
    HMAC signature format: {timestamp}|{nonce} (no modem_id - not known yet)
    """
    api_key: str = Field(..., description="API key for authentication")
    timestamp: str = Field(..., description="Request timestamp (ISO 8601)")
    nonce: str = Field(..., description="Request nonce for replay protection (SHA256 hex)")
    signature: str = Field(..., description="HMAC-SHA256 signature")

    @validator('nonce')
    def validate_nonce(cls, v):
        """Validate nonce is 64-char hex string (SHA256)."""
        if not v or len(v) != 64:
            raise ValueError("nonce must be 64-character hex string")
        try:
            int(v, 16)
        except ValueError:
            raise ValueError("nonce must be valid hexadecimal")
        return v


class PreflightResponse(BaseModel):
    """
    Response schema for pre-flight API key validation.

    Returns whether API key is valid and any pending enforced config.
    """
    success: bool = Field(..., description="Request success status")
    api_key_valid: bool = Field(..., description="Whether API key exists and is active")
    has_existing_config: bool = Field(..., description="Whether a config exists for this API key")
    status: Optional[str] = Field(None, description="Config status if exists (6 states)")
    config: Optional[Dict[str, Any]] = Field(None, description="Enforced config to apply (if any)")
    server_timestamp: str = Field(..., description="Server timestamp (ISO 8601)")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "api_key_valid": True,
                "has_existing_config": True,
                "status": "enforced_ready",
                "config": {
                    "PingCount": 25,
                    "SpeedTestEnabled": True
                },
                "server_timestamp": "2025-01-15T12:34:56.789012"
            }
        }


class ConfigSyncRequest(BaseModel):
    """
    Request schema for client configuration sync.

    Client sends their current config + metadata for sync.
    modem_id is optional - used for tracking/audit only, not as lookup key.
    HMAC signature format: {timestamp}|{nonce}|{config_hash} (no modem_id)
    """
    api_key: str = Field(..., description="API key for authentication")
    modem_id: Optional[str] = Field(None, description="Modem ID for tracking (optional)")
    config: Dict[str, Any] = Field(..., description="Client configuration")
    version: Optional[str] = Field(None, description="Current config version (e.g., 'v2_client')")
    config_hash: str = Field(..., description="SHA256 hash of config (canonical JSON)")
    timestamp: str = Field(..., description="Request timestamp (ISO 8601)")
    nonce: str = Field(..., description="Request nonce for replay protection (SHA256 hex)")
    signature: str = Field(..., description="HMAC-SHA256 signature")

    @validator('modem_id')
    def validate_modem_id(cls, v):
        """Validate modem ID format if provided."""
        if v is not None and len(v) < 3:
            raise ValueError("modem_id must be at least 3 characters if provided")
        return v

    @validator('nonce')
    def validate_nonce(cls, v):
        """Validate nonce is 64-char hex string (SHA256)."""
        if not v or len(v) != 64:
            raise ValueError("nonce must be 64-character hex string")
        try:
            int(v, 16)
        except ValueError:
            raise ValueError("nonce must be valid hexadecimal")
        return v


class ConfigSyncResponse(BaseModel):
    """
    Response schema for configuration sync.

    Server returns authoritative config + metadata.
    """
    success: bool = Field(..., description="Sync success status")
    config: Dict[str, Any] = Field(..., description="Authoritative configuration")
    version: str = Field(..., description="Config version (e.g., 'v1_server')")
    status: str = Field(..., description="Config status (6 states)")
    config_hash: str = Field(..., description="SHA256 hash of config")
    server_timestamp: str = Field(..., description="Server timestamp (ISO 8601)")
    config_changed: bool = Field(..., description="Whether client should apply config")
    active_track: str = Field(..., description="Active version track ('client' or 'server')")
    client_version: int = Field(..., description="Latest client version number")
    server_version: int = Field(..., description="Latest server version number")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "config": {
                    "PingCount": 25,
                    "SpeedTestEnabled": True,
                    "UpdateChannel": "stable"
                },
                "version": "v1_server",
                "status": "enforced_active",
                "config_hash": "abc123...",
                "server_timestamp": "2025-01-15T12:34:56.789012",
                "config_changed": True,
                "active_track": "server",
                "client_version": 2,
                "server_version": 1
            }
        }


class ConfigCreateRequest(BaseModel):
    """
    Request schema for admin configuration creation.

    Admin can pre-create a config before client syncs.
    Config is keyed by API key only - no modem_id required.
    """
    api_key: str = Field(..., description="API key for the client")
    config: Dict[str, Any] = Field(..., description="Configuration to push to client")
    mode: str = Field("one_time", description="Target mode: 'unmanaged', 'one_time', or 'enforced'")

    @validator('mode')
    def validate_mode(cls, v):
        """Validate mode is valid value."""
        if v not in ['unmanaged', 'one_time', 'enforced']:
            raise ValueError("mode must be 'unmanaged', 'one_time', or 'enforced'")
        return v


class ConfigCreateResponse(BaseModel):
    """Response schema for configuration creation."""
    success: bool = Field(..., description="Creation success status")
    api_key: str = Field(..., description="API key (truncated)")
    version: str = Field(..., description="Initial config version")
    status: str = Field(..., description="Config status")
    target_mode: str = Field(..., description="Target mode when client syncs")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "api_key": "abc123...",
                "version": "v1_server",
                "status": "awaiting_first_sync",
                "target_mode": "one_time"
            }
        }


class ConfigUpdateRequest(BaseModel):
    """
    Request schema for admin configuration update.

    Admin can update config and change mode.
    """
    config: Dict[str, Any] = Field(..., description="New configuration")
    mode: Optional[str] = Field(None, description="Target mode: 'unmanaged', 'one_time', or 'enforced'")
    check_reachability: bool = Field(False, description="Test CloudHost reachability before saving")

    @validator('mode')
    def validate_mode(cls, v):
        """Validate mode is valid value."""
        if v is not None and v not in ['unmanaged', 'one_time', 'enforced']:
            raise ValueError("mode must be 'unmanaged', 'one_time', or 'enforced'")
        return v


class ConfigUpdateResponse(BaseModel):
    """Response schema for configuration update."""
    success: bool = Field(..., description="Update success status")
    version: str = Field(..., description="New config version")
    status: str = Field(..., description="Current config status")
    backup_created: bool = Field(..., description="Whether version was created")
    reachability_test: Optional[Dict[str, Any]] = Field(None, description="Reachability test results")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "version": "v2_server",
                "status": "enforced_ready",
                "backup_created": True,
                "reachability_test": {
                    "reachable": True,
                    "latency_ms": 42.5
                }
            }
        }


class ConfigRollbackRequest(BaseModel):
    """Request schema for configuration rollback."""
    reason: Optional[str] = Field(None, description="Reason for rollback")


class ConfigRollbackResponse(BaseModel):
    """Response schema for configuration rollback."""
    success: bool = Field(..., description="Rollback success status")
    version: str = Field(..., description="New version after rollback")
    rolled_back_to: str = Field(..., description="Target version that was restored")
    config: Dict[str, Any] = Field(..., description="Restored configuration")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "version": "v3_server",
                "rolled_back_to": "v1_server",
                "config": {
                    "PingCount": 25,
                    "EnableCloud": True
                }
            }
        }


class HealthCheckResponse(BaseModel):
    """Response schema for health check endpoint."""
    healthy: bool = Field(..., description="Overall health status")
    timestamp: str = Field(..., description="Server timestamp (ISO 8601)")
    database: str = Field(..., description="Database status: 'ok' or 'error'")
    cache: str = Field(..., description="Cache status: 'ok', 'degraded', or 'error'")
    nonce_count: Optional[int] = Field(None, description="Number of active nonces in database (for monitoring)")

    class Config:
        json_schema_extra = {
            "example": {
                "healthy": True,
                "timestamp": "2025-01-15T12:34:56.789012",
                "database": "ok",
                "cache": "ok",
                "nonce_count": 42
            }
        }


class ConfigListItem(BaseModel):
    """Schema for config list item (admin dashboard)."""
    api_key: str = Field(..., description="API key (truncated for display)")
    api_key_full: str = Field(..., description="Full API key (for API calls)")
    last_seen_modem_id: Optional[str] = Field(None, description="Last seen modem ID (tracking only)")
    status: str = Field(..., description="Config status (6 states)")
    version: str = Field(..., description="Active version (e.g., 'v3_client')")
    client_version: int = Field(..., description="Latest client version number")
    server_version: int = Field(..., description="Latest server version number")
    active_track: str = Field(..., description="Active version track")
    last_sync: Optional[datetime] = Field(None, description="Last sync timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    updated_by: str = Field(..., description="Last updated by")

    class Config:
        from_attributes = True


class ConfigListResponse(BaseModel):
    """Response schema for config list (admin dashboard)."""
    configs: List[ConfigListItem] = Field(..., description="List of configurations")
    total: int = Field(..., description="Total number of configurations")
    filtered: int = Field(..., description="Number after filtering")


class ConfigDetailResponse(BaseModel):
    """Response schema for detailed config view."""
    api_key: str = Field(..., description="API key")
    last_seen_modem_id: Optional[str] = Field(None, description="Last seen modem ID (tracking only)")
    config: Dict[str, Any] = Field(..., description="Configuration (plaintext, no redaction)")
    status: str = Field(..., description="Config status")
    version: str = Field(..., description="Active version")
    client_version: int = Field(..., description="Latest client version number")
    server_version: int = Field(..., description="Latest server version number")
    active_track: str = Field(..., description="Active version track")
    client_acked_version: Optional[int] = Field(None, description="Version client acknowledged")
    client_acked_track: Optional[str] = Field(None, description="Track client acknowledged")
    last_sync: Optional[datetime] = Field(None, description="Last sync timestamp")
    created_at: datetime = Field(..., description="Created timestamp")
    created_by: str = Field(..., description="Created by")
    updated_at: datetime = Field(..., description="Updated timestamp")
    updated_by: str = Field(..., description="Updated by")

    class Config:
        from_attributes = True


class ConfigVersionItem(BaseModel):
    """Schema for config version history item."""
    id: int = Field(..., description="Version ID")
    version_display: str = Field(..., description="Version display (e.g., 'v3_client')")
    version_number: int = Field(..., description="Version number")
    version_track: str = Field(..., description="Version track ('client' or 'server')")
    config: Dict[str, Any] = Field(..., description="Configuration snapshot")
    status_at_creation: str = Field(..., description="Status when version was created")
    modem_id_at_creation: Optional[str] = Field(None, description="Modem ID when version was created")
    created_at: datetime = Field(..., description="When version was created")
    created_by: str = Field(..., description="Who created version")
    creation_reason: str = Field(..., description="Reason for version creation")
    ip_address: Optional[str] = Field(None, description="Client IP address")

    class Config:
        from_attributes = True


class ModemEventItem(BaseModel):
    """Schema for modem event in history timeline."""
    id: int = Field(..., description="Event ID")
    event_type: str = Field(..., description="Event type: 'modem_change'")
    timestamp: datetime = Field(..., description="When event occurred")
    old_modem_id: Optional[str] = Field(None, description="Previous modem ID (null for first modem association)")
    new_modem_id: str = Field(..., description="New/current modem ID")
    ip_address: Optional[str] = Field(None, description="Client IP address")

    class Config:
        from_attributes = True


class ConfigHistoryResponse(BaseModel):
    """Response schema for config history."""
    api_key: str = Field(..., description="API key")
    last_seen_modem_id: Optional[str] = Field(None, description="Last seen modem ID")
    versions: List[ConfigVersionItem] = Field(..., description="List of versions")
    modem_events: List[ModemEventItem] = Field(default_factory=list, description="List of modem events")
    total: int = Field(..., description="Total number of versions")
    total_modem_events: int = Field(default=0, description="Total number of modem events")
    filter_track: Optional[str] = Field(None, description="Track filter applied")


# Backward compatibility aliases
class ConfigHistoryItem(BaseModel):
    """DEPRECATED: Use ConfigVersionItem instead."""
    backup_id: int = Field(..., description="Backup ID")
    version: int = Field(..., description="Config version")
    mode: str = Field(..., description="Config mode")
    backup_timestamp: datetime = Field(..., description="When backup was created")
    backup_reason: str = Field(..., description="Reason for backup")
    backed_up_by: str = Field(..., description="Who created backup")

    class Config:
        from_attributes = True


# SSE update schema
class ConfigSSEUpdate(BaseModel):
    """Schema for SSE config update event."""
    api_key: str = Field(..., description="API key (truncated)")
    last_seen_modem_id: Optional[str] = Field(None, description="Last seen modem ID")
    status: str = Field(..., description="New status")
    version: str = Field(..., description="Current version")
    client_version: int = Field(..., description="Client version number")
    server_version: int = Field(..., description="Server version number")
    active_track: str = Field(..., description="Active track")
    last_sync: Optional[str] = Field(None, description="Last sync timestamp")
    updated_at: str = Field(..., description="Update timestamp")
