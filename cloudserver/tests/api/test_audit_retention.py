"""
Tests for audit log retention policy.

Tests for:
- Cleanup of old user activity logs
- Cleanup of old client submission logs
- Audit log statistics
- Retention policy enforcement
"""
import pytest
from datetime import datetime, timedelta
from sqlalchemy import select, func, text
from app.models.audit import UserActivityLog, ClientSubmissionLog
from app.core.audit_retention import (
    cleanup_old_user_activity_logs,
    cleanup_old_client_submission_logs,
    cleanup_all_audit_logs,
    get_audit_log_statistics
)


class TestUserActivityLogCleanup:
    """Test cleanup of old user activity logs."""

    @pytest.mark.asyncio
    async def test_cleanup_old_user_activity_logs_no_old_logs(self, db_session):
        """Test cleanup when there are no old logs."""
        deleted, total_before = await cleanup_old_user_activity_logs(db_session, retention_days=90)

        # No logs should be deleted (all are recent from fixtures)
        assert deleted == 0
        assert total_before >= 0

    @pytest.mark.asyncio
    async def test_cleanup_old_user_activity_logs_with_old_logs(self, db_session):
        """Test cleanup when there are old logs to delete."""
        # Create old log (100 days ago)
        old_timestamp = datetime.utcnow() - timedelta(days=100)
        old_log = UserActivityLog(
            timestamp=old_timestamp,
            username="test_cleanup_user",
            action_type="test_action",
            ip_address="192.168.1.100",
            success=True
        )
        db_session.add(old_log)
        await db_session.commit()

        # Create recent log (10 days ago)
        recent_timestamp = datetime.utcnow() - timedelta(days=10)
        recent_log = UserActivityLog(
            timestamp=recent_timestamp,
            username="test_recent_user",
            action_type="test_action",
            ip_address="192.168.1.100",
            success=True
        )
        db_session.add(recent_log)
        await db_session.commit()

        # Cleanup with 90-day retention
        deleted, total_before = await cleanup_old_user_activity_logs(db_session, retention_days=90)

        # Should delete at least the old log
        assert deleted >= 1
        assert total_before > deleted

        # Verify old log is gone
        result = await db_session.execute(
            select(UserActivityLog).where(
                UserActivityLog.username == "test_cleanup_user"
            )
        )
        assert result.scalar_one_or_none() is None

        # Verify recent log remains
        result = await db_session.execute(
            select(UserActivityLog).where(
                UserActivityLog.username == "test_recent_user"
            )
        )
        assert result.scalar_one_or_none() is not None

    @pytest.mark.asyncio
    async def test_cleanup_custom_retention_period(self, db_session):
        """Test cleanup with custom retention period."""
        # Create log 45 days ago
        timestamp_45 = datetime.utcnow() - timedelta(days=45)
        log_45 = UserActivityLog(
            timestamp=timestamp_45,
            username="test_45_day_user",
            action_type="test_action",
            ip_address="192.168.1.100",
            success=True
        )
        db_session.add(log_45)
        await db_session.commit()

        # Cleanup with 30-day retention (should delete 45-day-old log)
        deleted, _ = await cleanup_old_user_activity_logs(db_session, retention_days=30)

        assert deleted >= 1

        # Cleanup with 60-day retention (should not delete 45-day-old log)
        # Create another 45-day-old log
        log_45_2 = UserActivityLog(
            timestamp=timestamp_45,
            username="test_45_day_user_2",
            action_type="test_action",
            ip_address="192.168.1.100",
            success=True
        )
        db_session.add(log_45_2)
        await db_session.commit()

        deleted, _ = await cleanup_old_user_activity_logs(db_session, retention_days=60)

        # Should not delete the 45-day-old log
        result = await db_session.execute(
            select(UserActivityLog).where(
                UserActivityLog.username == "test_45_day_user_2"
            )
        )
        assert result.scalar_one_or_none() is not None


class TestClientSubmissionLogCleanup:
    """Test cleanup of old client submission logs."""

    @pytest.mark.asyncio
    async def test_cleanup_old_client_submission_logs(self, db_session):
        """Test cleanup of old client submission logs."""
        # Create old log (100 days ago)
        old_timestamp = datetime.utcnow() - timedelta(days=100)
        old_log = ClientSubmissionLog(
            timestamp=old_timestamp,
            ip_address="192.168.1.100",
            api_key_hash="test_hash",
            modem_id="XB8-TEST",
            filename="test_old.json",
            success=True
        )
        db_session.add(old_log)
        await db_session.commit()

        # Cleanup with 90-day retention
        deleted, total_before = await cleanup_old_client_submission_logs(db_session, retention_days=90)

        # Should delete at least the old log
        assert deleted >= 1

        # Verify old log is gone
        result = await db_session.execute(
            select(ClientSubmissionLog).where(
                ClientSubmissionLog.timestamp == old_timestamp
            )
        )
        assert result.scalar_one_or_none() is None


class TestCleanupAllAuditLogs:
    """Test cleanup of all audit logs together."""

    @pytest.mark.asyncio
    async def test_cleanup_all_audit_logs(self, db_session):
        """Test cleanup of all audit log types."""
        # Create old logs for both types
        old_timestamp = datetime.utcnow() - timedelta(days=100)

        user_log = UserActivityLog(
            timestamp=old_timestamp,
            username="test_all_cleanup_user",
            action_type="test_action",
            ip_address="192.168.1.100",
            success=True
        )
        db_session.add(user_log)

        client_log = ClientSubmissionLog(
            timestamp=old_timestamp,
            ip_address="192.168.1.100",
            api_key_hash="test_hash",
            modem_id="XB8-TEST",
            filename="test_all_cleanup.json",
            success=True
        )
        db_session.add(client_log)

        await db_session.commit()

        # Cleanup all logs
        result = await cleanup_all_audit_logs(
            db_session,
            user_retention_days=90,
            client_retention_days=90
        )

        assert "user_activity_logs" in result
        assert "client_submission_logs" in result
        assert "total_deleted" in result
        assert result["total_deleted"] >= 2


class TestAuditLogStatistics:
    """Test audit log statistics reporting."""

    @pytest.mark.asyncio
    async def test_get_audit_log_statistics_empty(self, db_session):
        """Test statistics with minimal logs."""
        # Clear all logs first
        await db_session.execute(text("DELETE FROM user_activity_log"))
        await db_session.execute(text("DELETE FROM client_submission_log"))
        await db_session.commit()

        stats = await get_audit_log_statistics(db_session)

        assert "user_activity_logs" in stats
        assert "client_submission_logs" in stats
        assert stats["user_activity_logs"]["total_count"] == 0
        assert stats["client_submission_logs"]["total_count"] == 0

    @pytest.mark.asyncio
    async def test_get_audit_log_statistics_with_logs(self, db_session):
        """Test statistics with existing logs."""
        # Create some logs with known timestamps
        old_timestamp = datetime.utcnow() - timedelta(days=50)
        recent_timestamp = datetime.utcnow() - timedelta(days=5)

        # Add user activity log
        user_log = UserActivityLog(
            timestamp=old_timestamp,
            username="stats_test_user",
            action_type="test_action",
            ip_address="192.168.1.100",
            success=True
        )
        db_session.add(user_log)

        # Add client submission log
        client_log = ClientSubmissionLog(
            timestamp=recent_timestamp,
            ip_address="192.168.1.100",
            api_key_hash="test_hash",
            modem_id="XB8-STATS",
            filename="stats_test.json",
            success=True
        )
        db_session.add(client_log)

        await db_session.commit()

        # Get statistics
        stats = await get_audit_log_statistics(db_session)

        # Verify statistics structure
        assert stats["user_activity_logs"]["total_count"] >= 1
        assert stats["client_submission_logs"]["total_count"] >= 1
        assert stats["total_logs"] >= 2

        # Verify timestamps are included
        user_stats = stats["user_activity_logs"]
        if user_stats["oldest_timestamp"]:
            assert "oldest_timestamp" in user_stats
            assert "newest_timestamp" in user_stats
            assert "age_days" in user_stats


class TestCleanupEdgeCases:
    """Test edge cases in cleanup functionality."""

    @pytest.mark.asyncio
    async def test_cleanup_with_zero_retention(self, db_session):
        """Test cleanup with zero retention (delete all)."""
        # Create recent log
        recent_log = UserActivityLog(
            timestamp=datetime.utcnow(),
            username="test_zero_retention",
            action_type="test_action",
            ip_address="192.168.1.100",
            success=True
        )
        db_session.add(recent_log)
        await db_session.commit()

        # Cleanup with 0-day retention should delete everything
        deleted, _ = await cleanup_old_user_activity_logs(db_session, retention_days=0)

        # All logs should be deleted
        assert deleted >= 1

    @pytest.mark.asyncio
    async def test_cleanup_with_large_retention(self, db_session):
        """Test cleanup with very large retention period."""
        # Create old log
        old_log = UserActivityLog(
            timestamp=datetime.utcnow() - timedelta(days=100),
            username="test_large_retention",
            action_type="test_action",
            ip_address="192.168.1.100",
            success=True
        )
        db_session.add(old_log)
        await db_session.commit()

        # Cleanup with 365-day retention should keep 100-day-old log
        deleted, total_before = await cleanup_old_user_activity_logs(db_session, retention_days=365)

        # Should not delete the 100-day-old log
        result = await db_session.execute(
            select(UserActivityLog).where(
                UserActivityLog.username == "test_large_retention"
            )
        )
        assert result.scalar_one_or_none() is not None


class TestCleanupScriptOutput:
    """Test cleanup script output format."""

    @pytest.mark.asyncio
    async def test_cleanup_returns_statistics(self, db_session):
        """Test that cleanup returns proper statistics."""
        result = await cleanup_all_audit_logs(db_session)

        # Verify result structure
        assert "user_activity_logs" in result
        assert "client_submission_logs" in result
        assert "total_deleted" in result
        assert "cleanup_timestamp" in result

        # Verify user activity log stats
        user_stats = result["user_activity_logs"]
        assert "total_before" in user_stats
        assert "deleted" in user_stats
        assert "retained" in user_stats
        assert "retention_days" in user_stats

        # Verify client submission log stats
        client_stats = result["client_submission_logs"]
        assert "total_before" in client_stats
        assert "deleted" in client_stats
        assert "retained" in client_stats
        assert "retention_days" in client_stats

        # Verify math
        assert user_stats["retained"] == user_stats["total_before"] - user_stats["deleted"]
        assert client_stats["retained"] == client_stats["total_before"] - client_stats["deleted"]
        assert result["total_deleted"] == user_stats["deleted"] + client_stats["deleted"]
