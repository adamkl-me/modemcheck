"""
Audit logging for configuration management operations.

Records all config changes with:
- Sensitive field redaction (passwords, API keys)
- Field-level change tracking (summary of what changed, not values)
- Actor identification (username or API key)
- Success/failure tracking

Audit logs are stored in partitioned tables (config_audit_logs_YYYYMM)
with 90-day retention.

Version 3.0: Updated for simplified 3-state model with single-track versioning.
"""

import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Set, Union
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_config import ConfigAuditLog, ConfigStatus, SyncStatus
from app.core.errors import InternalServerError


# Fields that contain sensitive data (never log values)
SENSITIVE_FIELDS = {
    "CloudAPIKey",
    "IgnitePassword",
}


def get_changed_fields(
    old_config: Optional[Dict[str, Any]],
    new_config: Dict[str, Any]
) -> Set[str]:
    """
    Identify which fields changed between configurations.

    Args:
        old_config: Previous configuration (None for first sync)
        new_config: New configuration

    Returns:
        Set of field names that changed
    """
    if old_config is None:
        return set(new_config.keys())

    changed = set()

    for field, new_value in new_config.items():
        if field not in old_config:
            changed.add(field)
        elif old_config[field] != new_value:
            changed.add(field)

    for field in old_config:
        if field not in new_config:
            changed.add(field)

    return changed


def create_config_summary(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create audit-safe config summary (field names only, no values).

    For sensitive fields, indicates presence but not value.
    For non-sensitive fields, includes field name and type.

    Args:
        config: Configuration dictionary

    Returns:
        Sanitized summary for audit log
    """
    regular_fields = []
    sensitive_fields = []
    field_types = {}

    for field, value in config.items():
        if field in SENSITIVE_FIELDS:
            sensitive_fields.append(field)
        else:
            regular_fields.append(field)
            field_types[field] = type(value).__name__

    return {
        "fields": sorted(regular_fields),
        "sensitive_fields": sorted(sensitive_fields),
        "field_types": field_types,
        "total_fields": len(config)
    }


def create_change_summary(
    old_config: Optional[Dict[str, Any]],
    new_config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Create audit-safe summary of changes (what changed, not values).

    Args:
        old_config: Previous configuration (None for first sync)
        new_config: New configuration

    Returns:
        Change summary for audit log
    """
    if old_config is None:
        return create_config_summary(new_config)

    changed = []
    added = []
    removed = []

    for field, new_value in new_config.items():
        if field not in old_config:
            added.append(field)
        elif old_config[field] != new_value:
            changed.append(field)

    for field in old_config:
        if field not in new_config:
            removed.append(field)

    return {
        "changed_fields": sorted(changed),
        "added_fields": sorted(added),
        "removed_fields": sorted(removed),
        "total_changes": len(changed) + len(added) + len(removed)
    }


async def log_config_sync(
    db: AsyncSession,
    api_key: str,
    modem_id: Optional[str],
    ip_address: str,
    old_config: Optional[Dict[str, Any]],
    new_config: Dict[str, Any],
    old_version: Optional[int],
    new_version: int,
    old_status: Optional[ConfigStatus] = None,
    new_status: Optional[ConfigStatus] = None,
    old_sync_status: Optional[SyncStatus] = None,
    new_sync_status: Optional[SyncStatus] = None,
    success: bool = True,
    failure_reason: Optional[str] = None
) -> None:
    """
    Log a configuration sync operation.

    Args:
        db: Database session
        api_key: Client API key (will be hashed for storage)
        modem_id: Client modem ID (optional, for tracking metadata)
        ip_address: Client IP address
        old_config: Previous config (None if first sync)
        new_config: New config
        old_version: Previous version number or None
        new_version: New version number
        old_status: Previous status (optional)
        new_status: New status (optional)
        old_sync_status: Previous sync status (optional)
        new_sync_status: New sync status (optional)
        success: Whether sync succeeded
        failure_reason: Error message if failed
    """
    config_summary = create_change_summary(old_config, new_config)

    # Hash API key for secure storage (SHA256)
    api_key_hash = hashlib.sha256(api_key.encode('utf-8')).hexdigest()

    audit_entry = ConfigAuditLog(
        timestamp=datetime.now(timezone.utc),
        username=None,  # Client-initiated (no user)
        api_key_hash=api_key_hash,
        ip_address=ip_address,
        api_key=None,  # Don't store plaintext API key
        modem_id=modem_id,
        action="sync",
        config_summary=config_summary,
        old_version=old_version,
        new_version=new_version,
        old_status=old_status,
        new_status=new_status,
        old_sync_status=old_sync_status,
        new_sync_status=new_sync_status,
        success=success,
        failure_reason=failure_reason
    )

    db.add(audit_entry)


async def log_config_update(
    db: AsyncSession,
    username: str,
    api_key: str,
    modem_id: Optional[str],
    ip_address: str,
    old_config: Optional[Dict[str, Any]],
    new_config: Dict[str, Any],
    old_version: Optional[int],
    new_version: int,
    old_status: Optional[ConfigStatus],
    new_status: ConfigStatus,
    old_sync_status: Optional[SyncStatus] = None,
    new_sync_status: Optional[SyncStatus] = None,
    success: bool = True,
    failure_reason: Optional[str] = None
) -> None:
    """
    Log an admin configuration update.

    Args:
        db: Database session
        username: Admin username
        api_key: Target client API key (will be hashed for storage)
        modem_id: Target client modem ID (optional, for tracking metadata)
        ip_address: Admin IP address
        old_config: Previous config (None for new configs)
        new_config: New config
        old_version: Previous version number or None
        new_version: New version number
        old_status: Previous status (ConfigStatus enum or None)
        new_status: New status (ConfigStatus enum)
        old_sync_status: Previous sync status (optional)
        new_sync_status: New sync status (optional)
        success: Whether update succeeded
        failure_reason: Error message if failed
    """
    config_summary = create_change_summary(old_config, new_config)

    # Hash API key for secure storage (SHA256)
    api_key_hash = hashlib.sha256(api_key.encode('utf-8')).hexdigest()

    audit_entry = ConfigAuditLog(
        timestamp=datetime.now(timezone.utc),
        username=username,
        api_key_hash=api_key_hash,
        ip_address=ip_address,
        api_key=None,  # Don't store plaintext API key
        modem_id=modem_id,
        action="update",
        config_summary=config_summary,
        old_version=old_version,
        new_version=new_version,
        old_status=old_status,
        new_status=new_status,
        old_sync_status=old_sync_status,
        new_sync_status=new_sync_status,
        success=success,
        failure_reason=failure_reason
    )

    db.add(audit_entry)


async def log_config_rollback(
    db: AsyncSession,
    username: str,
    api_key: str,
    modem_id: Optional[str],
    ip_address: str,
    target_version: int,
    current_version: int,
    new_version: int,
    success: bool,
    failure_reason: Optional[str] = None
) -> None:
    """
    Log a configuration rollback operation.

    Args:
        db: Database session
        username: Admin username
        api_key: Target client API key (will be hashed for storage)
        modem_id: Target client modem ID (optional, for tracking metadata)
        ip_address: Admin IP address
        target_version: Version being rolled back to
        current_version: Current version before rollback
        new_version: New version after rollback
        success: Whether rollback succeeded
        failure_reason: Error message if failed
    """
    # Hash API key for secure storage (SHA256)
    api_key_hash = hashlib.sha256(api_key.encode('utf-8')).hexdigest()

    audit_entry = ConfigAuditLog(
        timestamp=datetime.now(timezone.utc),
        username=username,
        api_key_hash=api_key_hash,
        ip_address=ip_address,
        api_key=None,  # Don't store plaintext API key
        modem_id=modem_id,
        action="rollback",
        config_summary={
            "rollback_to_version": target_version,
            "from_version": current_version
        },
        old_version=current_version,
        new_version=new_version,
        old_status=None,
        new_status=None,
        old_sync_status=None,
        new_sync_status=None,
        success=success,
        failure_reason=failure_reason
    )

    db.add(audit_entry)


async def log_status_change(
    db: AsyncSession,
    username: str,
    api_key: str,
    modem_id: Optional[str],
    ip_address: str,
    old_status: ConfigStatus,
    new_status: ConfigStatus,
    old_sync_status: SyncStatus,
    new_sync_status: SyncStatus,
    version: int,
    success: bool,
    failure_reason: Optional[str] = None
) -> None:
    """
    Log a configuration status/sync_status change.

    Args:
        db: Database session
        username: Admin username (or 'client' for client-initiated)
        api_key: Target client API key (will be hashed for storage)
        modem_id: Target client modem ID (optional, for tracking metadata)
        ip_address: Admin/client IP address
        old_status: Previous status (ConfigStatus enum)
        new_status: New status (ConfigStatus enum)
        old_sync_status: Previous sync status (SyncStatus enum)
        new_sync_status: New sync status (SyncStatus enum)
        version: Current version number
        success: Whether status change succeeded
        failure_reason: Error message if failed
    """
    # Hash API key for secure storage (SHA256)
    api_key_hash = hashlib.sha256(api_key.encode('utf-8')).hexdigest()

    audit_entry = ConfigAuditLog(
        timestamp=datetime.now(timezone.utc),
        username=username,
        api_key_hash=api_key_hash,
        ip_address=ip_address,
        api_key=None,  # Don't store plaintext API key
        modem_id=modem_id,
        action="status_change",
        config_summary={
            "old_status": old_status.value,
            "new_status": new_status.value,
            "old_sync_status": old_sync_status.value,
            "new_sync_status": new_sync_status.value
        },
        old_version=version,
        new_version=version,  # Version doesn't change on status-only change
        old_status=old_status,
        new_status=new_status,
        old_sync_status=old_sync_status,
        new_sync_status=new_sync_status,
        success=success,
        failure_reason=failure_reason
    )

    db.add(audit_entry)


async def get_modem_events_for_history(
    db: AsyncSession,
    api_key: str,
    limit: int = 50
) -> list:
    """
    Retrieve modem events for history timeline.

    Returns modem_change events from audit log (when modem switches).

    Args:
        db: Database session
        api_key: API key to filter by (will be hashed for query)
        limit: Maximum events to return

    Returns:
        List of dicts with event_type, timestamp, old_modem_id, new_modem_id, ip_address
    """
    from sqlalchemy import select
    from app.models.client_config import ConfigAuditLog

    events = []

    # Hash API key for secure lookup
    api_key_hash = hashlib.sha256(api_key.encode('utf-8')).hexdigest()

    modem_changes = await db.execute(
        select(
            ConfigAuditLog.id,
            ConfigAuditLog.timestamp,
            ConfigAuditLog.old_modem_id,
            ConfigAuditLog.new_modem_id,
            ConfigAuditLog.ip_address
        ).where(
            ConfigAuditLog.api_key_hash == api_key_hash,
            ConfigAuditLog.action == 'modem_change',
            ConfigAuditLog.success == True
        ).order_by(ConfigAuditLog.timestamp.desc())
        .limit(limit)
    )

    for row in modem_changes.fetchall():
        events.append({
            'id': row.id,
            'event_type': 'modem_change',
            'timestamp': row.timestamp,
            'old_modem_id': row.old_modem_id,
            'new_modem_id': row.new_modem_id,
            'ip_address': row.ip_address
        })

    return events


async def get_recent_audit_logs(
    db: AsyncSession,
    api_key: Optional[str] = None,
    modem_id: Optional[str] = None,
    username: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 100
) -> list:
    """
    Retrieve recent audit logs with optional filtering.

    Args:
        db: Database session
        api_key: Filter by API key (optional, will be hashed for query)
        modem_id: Filter by modem ID (optional)
        username: Filter by username (optional)
        action: Filter by action type (optional)
        limit: Maximum number of logs to return

    Returns:
        List of ConfigAuditLog entries
    """
    from sqlalchemy import select

    query = select(ConfigAuditLog).order_by(ConfigAuditLog.timestamp.desc())

    if api_key:
        # Hash API key for secure lookup
        api_key_hash = hashlib.sha256(api_key.encode('utf-8')).hexdigest()
        query = query.where(ConfigAuditLog.api_key_hash == api_key_hash)
    if modem_id:
        query = query.where(ConfigAuditLog.modem_id == modem_id)
    if username:
        query = query.where(ConfigAuditLog.username == username)
    if action:
        query = query.where(ConfigAuditLog.action == action)

    query = query.limit(limit)

    result = await db.execute(query)
    return result.scalars().all()
