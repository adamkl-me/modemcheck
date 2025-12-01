"""
Audit logging utilities for tracking user activity and client submissions.
"""
import json
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserActivityLog, ClientSubmissionLog


async def log_user_activity(
    db: AsyncSession,
    username: str,
    action_type: str,
    ip_address: str,
    success: bool,
    user_role: Optional[str] = None,
    action_details: Optional[dict] = None,
    user_agent: Optional[str] = None,
    session_id: Optional[str] = None,
    failure_reason: Optional[str] = None
):
    """
    Log user activity to audit database.

    Args:
        db: Database session
        username: Username performing the action
        action_type: Type of action (login, logout, create_user, delete_key, etc.)
        ip_address: IP address of the user
        success: Whether the action succeeded
        user_role: User's role (admin, elevated, basic)
        action_details: Dictionary with additional details (will be JSON serialized)
        user_agent: User's browser/client user agent
        session_id: Session identifier
        failure_reason: Reason for failure if success=False
    """
    log_entry = UserActivityLog(
        timestamp=datetime.now(timezone.utc),
        username=username,
        user_role=user_role,
        action_type=action_type,
        action_details=json.dumps(action_details) if action_details else None,
        ip_address=ip_address,
        user_agent=user_agent,
        session_id=session_id,
        success=success,
        failure_reason=failure_reason
    )

    db.add(log_entry)
    # Note: Commit is handled by caller or FastAPI's get_db()
    # For critical audit logs that must persist even on failure,
    # caller should commit explicitly before raising exceptions


async def log_client_submission(
    db: AsyncSession,
    ip_address: str,
    api_key_hash: str,
    api_key_name: str,
    modem_id: str,
    filename: str,
    success: bool,
    modem_type: Optional[str] = None,
    modem_mac: Optional[str] = None,
    file_size: Optional[int] = None,
    check_time: Optional[datetime] = None,
    user_agent: Optional[str] = None,
    failure_reason: Optional[str] = None,
    processing_time_ms: Optional[int] = None
):
    """
    Log client check submission to audit database.

    Args:
        db: Database session
        ip_address: IP address of the client
        api_key_hash: SHA256 hash of API key used
        api_key_name: Name of the API key
        modem_id: Modem identifier (TYPE-MAC)
        filename: Filename of the check
        success: Whether the submission succeeded
        modem_type: Type of modem
        modem_mac: MAC address of modem
        file_size: Size of uploaded file in bytes
        check_time: Timestamp of the check
        user_agent: Client user agent
        failure_reason: Reason for failure if success=False
        processing_time_ms: Processing time in milliseconds
    """
    log_entry = ClientSubmissionLog(
        timestamp=datetime.now(timezone.utc),
        ip_address=ip_address,
        api_key_hash=api_key_hash,
        api_key_name=api_key_name,
        modem_id=modem_id,
        modem_type=modem_type,
        modem_mac=modem_mac,
        filename=filename,
        file_size=file_size,
        check_time=check_time,
        user_agent=user_agent,
        success=success,
        failure_reason=failure_reason,
        processing_time_ms=processing_time_ms
    )

    db.add(log_entry)
    # Note: Commit is handled by caller or FastAPI's get_db()
    # For critical audit logs that must persist even on failure,
    # caller should commit explicitly before raising exceptions
