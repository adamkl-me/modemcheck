"""
Audit log retention policy management.

Automatically cleans up old audit logs to prevent database bloat
while maintaining compliance requirements.

Default retention: 90 days
"""
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select, func
from typing import Tuple

from app.models.audit import UserActivityLog, ClientSubmissionLog
from app.core.config import settings


async def cleanup_old_user_activity_logs(
    db: AsyncSession,
    retention_days: int = 90
) -> Tuple[int, int]:
    """
    Delete user activity logs older than retention period.

    Args:
        db: Database session
        retention_days: Number of days to retain (default: 90)

    Returns:
        (deleted_count, total_before): Number of logs deleted and total before cleanup
    """
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)

    # Count total before deletion
    result = await db.execute(select(func.count()).select_from(UserActivityLog))
    total_before = result.scalar()

    # Delete old logs
    stmt = delete(UserActivityLog).where(UserActivityLog.timestamp < cutoff_date)
    result = await db.execute(stmt)
    await db.commit()

    deleted_count = result.rowcount

    return (deleted_count, total_before)


async def cleanup_old_client_submission_logs(
    db: AsyncSession,
    retention_days: int = 90
) -> Tuple[int, int]:
    """
    Delete client submission logs older than retention period.

    Args:
        db: Database session
        retention_days: Number of days to retain (default: 90)

    Returns:
        (deleted_count, total_before): Number of logs deleted and total before cleanup
    """
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)

    # Count total before deletion
    result = await db.execute(select(func.count()).select_from(ClientSubmissionLog))
    total_before = result.scalar()

    # Delete old logs
    stmt = delete(ClientSubmissionLog).where(ClientSubmissionLog.timestamp < cutoff_date)
    result = await db.execute(stmt)
    await db.commit()

    deleted_count = result.rowcount

    return (deleted_count, total_before)


async def cleanup_all_audit_logs(
    db: AsyncSession,
    user_retention_days: int = 90,
    client_retention_days: int = 90
) -> dict:
    """
    Clean up all audit logs based on retention policy.

    Args:
        db: Database session
        user_retention_days: Days to retain user activity logs (default: 90)
        client_retention_days: Days to retain client submission logs (default: 90)

    Returns:
        Dictionary with cleanup statistics
    """
    user_deleted, user_total = await cleanup_old_user_activity_logs(db, user_retention_days)
    client_deleted, client_total = await cleanup_old_client_submission_logs(db, client_retention_days)

    return {
        "user_activity_logs": {
            "total_before": user_total,
            "deleted": user_deleted,
            "retained": user_total - user_deleted,
            "retention_days": user_retention_days
        },
        "client_submission_logs": {
            "total_before": client_total,
            "deleted": client_deleted,
            "retained": client_total - client_deleted,
            "retention_days": client_retention_days
        },
        "total_deleted": user_deleted + client_deleted,
        "cleanup_timestamp": datetime.now(timezone.utc).isoformat()
    }


async def get_audit_log_statistics(db: AsyncSession) -> dict:
    """
    Get statistics about audit logs.

    Args:
        db: Database session

    Returns:
        Dictionary with audit log statistics
    """
    # User activity log stats
    user_count_result = await db.execute(select(func.count()).select_from(UserActivityLog))
    user_count = user_count_result.scalar()

    user_oldest_result = await db.execute(
        select(func.min(UserActivityLog.timestamp)).select_from(UserActivityLog)
    )
    user_oldest = user_oldest_result.scalar()

    user_newest_result = await db.execute(
        select(func.max(UserActivityLog.timestamp)).select_from(UserActivityLog)
    )
    user_newest = user_newest_result.scalar()

    # Client submission log stats
    client_count_result = await db.execute(select(func.count()).select_from(ClientSubmissionLog))
    client_count = client_count_result.scalar()

    client_oldest_result = await db.execute(
        select(func.min(ClientSubmissionLog.timestamp)).select_from(ClientSubmissionLog)
    )
    client_oldest = client_oldest_result.scalar()

    client_newest_result = await db.execute(
        select(func.max(ClientSubmissionLog.timestamp)).select_from(ClientSubmissionLog)
    )
    client_newest = client_newest_result.scalar()

    return {
        "user_activity_logs": {
            "total_count": user_count,
            "oldest_timestamp": user_oldest.isoformat() if user_oldest else None,
            "newest_timestamp": user_newest.isoformat() if user_newest else None,
            "age_days": (datetime.now(timezone.utc) - user_oldest).days if user_oldest else 0
        },
        "client_submission_logs": {
            "total_count": client_count,
            "oldest_timestamp": client_oldest.isoformat() if client_oldest else None,
            "newest_timestamp": client_newest.isoformat() if client_newest else None,
            "age_days": (datetime.now(timezone.utc) - client_oldest).days if client_oldest else 0
        },
        "total_logs": user_count + client_count,
        "statistics_timestamp": datetime.now(timezone.utc).isoformat()
    }
