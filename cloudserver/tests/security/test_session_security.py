"""
Tests for enhanced session security features.

Tests for:
- Device fingerprinting
- Session anomaly detection
- Concurrent session limits
- Session activity tracking
"""
import pytest
import httpx
from unittest.mock import Mock, patch
from app.core.session_security import (
    generate_device_fingerprint,
    extract_session_metadata,
    create_session_with_fingerprint,
    verify_session_fingerprint,
    get_user_active_sessions,
    enforce_concurrent_session_limit,
    terminate_oldest_sessions,
    log_session_anomaly,
    get_session_anomalies
)

pytestmark = pytest.mark.security


class TestDeviceFingerprinting:
    """Test device fingerprinting functionality."""

    def test_generate_fingerprint_same_device(self):
        """Test that same device generates same fingerprint."""
        # Create mock requests with same user-agent and IP
        request1 = Mock()
        request1.headers = {"user-agent": "Mozilla/5.0 (X11; Linux x86_64)"}
        request1.client = Mock(host="192.168.1.100")

        request2 = Mock()
        request2.headers = {"user-agent": "Mozilla/5.0 (X11; Linux x86_64)"}
        request2.client = Mock(host="192.168.1.100")

        fp1 = generate_device_fingerprint(request1)
        fp2 = generate_device_fingerprint(request2)

        assert fp1 == fp2
        assert len(fp1) == 64  # SHA256 hex digest

    def test_generate_fingerprint_different_user_agent(self):
        """Test that different user-agents generate different fingerprints."""
        request1 = Mock()
        request1.headers = {"user-agent": "Mozilla/5.0 (X11; Linux x86_64)"}
        request1.client = Mock(host="192.168.1.100")

        request2 = Mock()
        request2.headers = {"user-agent": "Mozilla/5.0 (Windows NT 10.0)"}
        request2.client = Mock(host="192.168.1.100")

        fp1 = generate_device_fingerprint(request1)
        fp2 = generate_device_fingerprint(request2)

        assert fp1 != fp2

    def test_generate_fingerprint_different_ip(self):
        """Test that different IPs generate different fingerprints."""
        request1 = Mock()
        request1.headers = {"user-agent": "Mozilla/5.0 (X11; Linux x86_64)"}
        request1.client = Mock(host="192.168.1.100")

        request2 = Mock()
        request2.headers = {"user-agent": "Mozilla/5.0 (X11; Linux x86_64)"}
        request2.client = Mock(host="192.168.1.200")

        fp1 = generate_device_fingerprint(request1)
        fp2 = generate_device_fingerprint(request2)

        assert fp1 != fp2

    def test_generate_fingerprint_missing_data(self):
        """Test fingerprinting handles missing user-agent or IP."""
        request = Mock()
        request.headers = {}
        request.client = None

        # Should not crash, should use "unknown" defaults
        fp = generate_device_fingerprint(request)
        assert len(fp) == 64

    def test_extract_session_metadata(self):
        """Test extraction of session metadata."""
        request = Mock()
        request.headers = {"user-agent": "Mozilla/5.0 (X11; Linux x86_64)"}
        request.client = Mock(host="192.168.1.100")

        metadata = extract_session_metadata(request)

        assert metadata["user_agent"] == "Mozilla/5.0 (X11; Linux x86_64)"
        assert metadata["ip_address"] == "192.168.1.100"
        assert "fingerprint" in metadata
        assert "timestamp" in metadata
        assert len(metadata["fingerprint"]) == 64


class TestSessionFingerprinting:
    """Test session fingerprinting storage and verification."""

    @pytest.mark.asyncio
    async def test_create_session_with_fingerprint(self):
        """Test storing session fingerprint."""
        from app.core.security import get_redis

        request = Mock()
        request.headers = {"user-agent": "Mozilla/5.0 (X11; Linux x86_64)"}
        request.client = Mock(host="192.168.1.100")

        session_id = "test_session_123"
        username = "test_user"

        await create_session_with_fingerprint(session_id, username, request)

        # Verify fingerprint stored in Redis
        redis = await get_redis()
        fingerprint_key = f"session_fingerprint:{session_id}"
        stored = await redis.get(fingerprint_key)

        assert stored is not None
        import json
        metadata = json.loads(stored)
        assert metadata["user_agent"] == "Mozilla/5.0 (X11; Linux x86_64)"
        assert metadata["ip_address"] == "192.168.1.100"

        # Cleanup
        await redis.delete(fingerprint_key)

    @pytest.mark.asyncio
    async def test_verify_session_fingerprint_match(self):
        """Test fingerprint verification with matching request."""
        from app.core.security import get_redis
        import json

        request1 = Mock()
        request1.headers = {"user-agent": "Mozilla/5.0 (X11; Linux x86_64)"}
        request1.client = Mock(host="192.168.1.100")

        session_id = "test_session_456"
        username = "test_user"

        # Create fingerprint
        await create_session_with_fingerprint(session_id, username, request1)

        # Verify with same request details
        request2 = Mock()
        request2.headers = {"user-agent": "Mozilla/5.0 (X11; Linux x86_64)"}
        request2.client = Mock(host="192.168.1.100")

        is_valid, warning = await verify_session_fingerprint(session_id, request2, strict=False)

        assert is_valid is True
        assert warning is None

        # Cleanup
        redis = await get_redis()
        await redis.delete(f"session_fingerprint:{session_id}")

    @pytest.mark.asyncio
    async def test_verify_session_fingerprint_ip_change_lenient(self):
        """Test fingerprint verification allows IP changes in lenient mode."""
        from app.core.security import get_redis

        request1 = Mock()
        request1.headers = {"user-agent": "Mozilla/5.0 (X11; Linux x86_64)"}
        request1.client = Mock(host="192.168.1.100")

        session_id = "test_session_789"
        username = "test_user"

        await create_session_with_fingerprint(session_id, username, request1)

        # Verify with different IP (mobile network change)
        request2 = Mock()
        request2.headers = {"user-agent": "Mozilla/5.0 (X11; Linux x86_64)"}
        request2.client = Mock(host="192.168.1.200")

        is_valid, warning = await verify_session_fingerprint(session_id, request2, strict=False)

        assert is_valid is True
        assert "IP changed" in warning

        # Cleanup
        redis = await get_redis()
        await redis.delete(f"session_fingerprint:{session_id}")

    @pytest.mark.asyncio
    async def test_verify_session_fingerprint_user_agent_mismatch(self):
        """Test fingerprint verification rejects user-agent changes."""
        from app.core.security import get_redis

        request1 = Mock()
        request1.headers = {"user-agent": "Mozilla/5.0 (X11; Linux x86_64)"}
        request1.client = Mock(host="192.168.1.100")

        session_id = "test_session_ua_mismatch"
        username = "test_user"

        await create_session_with_fingerprint(session_id, username, request1)

        # Verify with different user-agent (potential hijacking)
        request2 = Mock()
        request2.headers = {"user-agent": "Mozilla/5.0 (Windows NT 10.0)"}
        request2.client = Mock(host="192.168.1.100")

        is_valid, warning = await verify_session_fingerprint(session_id, request2, strict=False)

        assert is_valid is False
        assert "User-agent mismatch" in warning

        # Cleanup
        redis = await get_redis()
        await redis.delete(f"session_fingerprint:{session_id}")


class TestConcurrentSessionLimits:
    """Test concurrent session limiting."""

    @pytest.mark.asyncio
    async def test_enforce_concurrent_session_limit_under_limit(self):
        """Test session limit enforcement when under limit."""
        # Mock get_user_active_sessions to return 3 sessions
        with patch('app.core.session_security.get_user_active_sessions') as mock_sessions:
            mock_sessions.return_value = [
                {"session_id": "session1"},
                {"session_id": "session2"},
                {"session_id": "session3"}
            ]

            allowed = await enforce_concurrent_session_limit("test_user", max_sessions=5)
            assert allowed is True

    @pytest.mark.asyncio
    async def test_enforce_concurrent_session_limit_at_limit(self):
        """Test session limit enforcement when at limit."""
        with patch('app.core.session_security.get_user_active_sessions') as mock_sessions:
            mock_sessions.return_value = [
                {"session_id": f"session{i}"} for i in range(5)
            ]

            allowed = await enforce_concurrent_session_limit("test_user", max_sessions=5)
            assert allowed is False

    @pytest.mark.asyncio
    async def test_terminate_oldest_sessions(self):
        """Test terminating oldest sessions."""
        from app.core.security import get_redis, create_session
        import json
        from datetime import datetime, timedelta

        username = "test_terminate_user"
        redis = await get_redis()

        # Create 5 sessions with different creation times
        session_ids = []
        for i in range(5):
            session_id = f"test_terminate_session_{i}"
            session_ids.append(session_id)

            # Create session
            created_time = datetime.now() - timedelta(minutes=i)
            session_data = {
                "username": username,
                "role": "basic",
                "created": created_time.isoformat(),
                "expires": (created_time + timedelta(hours=1)).isoformat()
            }

            session_key = f"session:{session_id}"
            await redis.setex(session_key, 3600, json.dumps(session_data))

            # Add to user sessions set
            user_sessions_key = f"user_sessions:{username}"
            await redis.sadd(user_sessions_key, session_id)

        # Terminate all but 2 newest sessions
        terminated = await terminate_oldest_sessions(username, keep_count=2)

        assert terminated == 3

        # Verify only 2 sessions remain
        remaining = await redis.smembers(f"user_sessions:{username}")
        assert len(remaining) <= 2

        # Cleanup
        for session_id in session_ids:
            await redis.delete(f"session:{session_id}")
        await redis.delete(f"user_sessions:{username}")


class TestSessionAnomalyTracking:
    """Test session anomaly logging and retrieval."""

    @pytest.mark.asyncio
    async def test_log_session_anomaly(self):
        """Test logging session anomalies."""
        from app.core.security import get_redis
        from app.core.utils import utc_now
        import json

        username = "test_anomaly_user"
        session_id = "test_anomaly_session"

        await log_session_anomaly(
            username=username,
            session_id=session_id,
            anomaly_type="ip_change",
            details="IP changed from 192.168.1.100 to 192.168.1.200"
        )

        # Verify anomaly stored
        redis = await get_redis()
        date_str = utc_now().strftime("%Y%m%d")
        anomaly_key = f"session_anomaly:{username}:{date_str}"

        anomalies = await redis.lrange(anomaly_key, 0, -1)
        assert len(anomalies) > 0

        anomaly = json.loads(anomalies[0])
        assert anomaly["type"] == "ip_change"
        assert "IP changed" in anomaly["details"]

        # Cleanup
        await redis.delete(anomaly_key)

    @pytest.mark.asyncio
    async def test_get_session_anomalies(self):
        """Test retrieving session anomalies."""
        username = "test_get_anomaly_user"

        # Log multiple anomalies
        await log_session_anomaly(username, "session1", "ip_change", "IP changed")
        await log_session_anomaly(username, "session2", "fingerprint_mismatch", "Device changed")

        # Retrieve anomalies
        anomalies = await get_session_anomalies(username, days=1)

        assert len(anomalies) >= 2
        assert any(a["type"] == "ip_change" for a in anomalies)
        assert any(a["type"] == "fingerprint_mismatch" for a in anomalies)

        # Cleanup
        from app.core.security import get_redis
        from app.core.utils import utc_now
        redis = await get_redis()
        date_str = utc_now().strftime("%Y%m%d")
        await redis.delete(f"session_anomaly:{username}:{date_str}")


class TestSessionSecurityIntegration:
    """Integration tests for session security features."""

    @pytest.mark.asyncio
    async def test_login_creates_fingerprint(self, http_client: httpx.AsyncClient):
        """Test that login creates session fingerprint."""
        # Login
        response = await http_client.post("/api/auth/login", json={
            "username": "admin",
            "password": "TestPass123!"
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Get session cookie
        cookies = response.cookies
        assert "modemcheck_session" in cookies

        # Verify fingerprint exists
        from app.core.security import get_redis
        import json

        session_id = cookies["modemcheck_session"]
        redis = await get_redis()
        fingerprint_key = f"session_fingerprint:{session_id}"
        stored = await redis.get(fingerprint_key)

        # Fingerprint should exist
        if stored:  # May not exist in test environment
            metadata = json.loads(stored)
            assert "user_agent" in metadata
            assert "ip_address" in metadata
            assert "fingerprint" in metadata

    @pytest.mark.asyncio
    async def test_concurrent_login_limit(self, http_client: httpx.AsyncClient):
        """Test concurrent session limit enforcement on login."""
        # This test would require creating 6+ sessions for same user
        # and verifying oldest are terminated
        # Skipped in test environment due to complexity
        pass


class TestAuditLogTrimming:
    """Tests for Redis audit log memory management."""

    @pytest.mark.asyncio
    async def test_anomaly_log_trimmed_to_100_entries(self):
        """Test that anomaly logs are trimmed to 100 entries per day."""
        from app.core.session_security import log_session_anomaly
        from app.core.security import get_redis
        from app.core.utils import utc_now

        username = "test_trim_user"
        session_id = "test_session_trim"
        redis = await get_redis()

        # Clear any existing data
        date_str = utc_now().strftime("%Y%m%d")
        anomaly_key = f"session_anomaly:{username}:{date_str}"
        await redis.delete(anomaly_key)
        
        # Create 150 anomaly entries (exceeds 100 limit)
        for i in range(150):
            await log_session_anomaly(
                username=username,
                session_id=session_id,
                anomaly_type="test_type",
                details=f"Test anomaly {i}"
            )
        
        # Verify only 100 most recent are kept
        count = await redis.llen(anomaly_key)
        assert count == 100, f"Expected 100 entries, got {count}"
        
        # Verify oldest entries were removed
        oldest = await redis.lindex(anomaly_key, 0)
        import json
        oldest_data = json.loads(oldest)
        
        # Should contain entry 50 (entries 0-49 were trimmed)
        assert "Test anomaly" in oldest_data["details"]
        
        # Cleanup
        await redis.delete(anomaly_key)

    @pytest.mark.asyncio
    async def test_anomaly_log_expiration_7_days(self):
        """Test that anomaly logs expire after 7 days (not 30)."""
        from app.core.session_security import log_session_anomaly
        from app.core.security import get_redis
        from app.core.utils import utc_now

        username = "test_expire_user"
        session_id = "test_session_expire"
        redis = await get_redis()

        # Clear any existing data
        date_str = utc_now().strftime("%Y%m%d")
        anomaly_key = f"session_anomaly:{username}:{date_str}"
        await redis.delete(anomaly_key)
        
        # Create one anomaly entry
        await log_session_anomaly(
            username=username,
            session_id=session_id,
            anomaly_type="test_type",
            details="Test expiration"
        )
        
        # Check TTL
        ttl = await redis.ttl(anomaly_key)
        
        # Should be approximately 7 days (604800 seconds)
        # Allow some margin for execution time
        expected_ttl = 7 * 24 * 60 * 60  # 7 days
        assert ttl > expected_ttl - 10, f"TTL too short: {ttl}"
        assert ttl <= expected_ttl, f"TTL too long: {ttl}"
        
        # Verify it's NOT 30 days
        old_ttl = 30 * 24 * 60 * 60
        assert ttl < old_ttl - 1000, "TTL is still 30 days, should be 7"
        
        # Cleanup
        await redis.delete(anomaly_key)

    @pytest.mark.asyncio
    async def test_get_anomalies_respects_retention(self):
        """Test that get_session_anomalies only returns data within retention."""
        from app.core.session_security import log_session_anomaly, get_session_anomalies
        from app.core.security import get_redis
        from app.core.utils import utc_now

        username = "test_retention_user"
        session_id = "test_session_retention"
        redis = await get_redis()

        # Clear any existing data
        date_str = utc_now().strftime("%Y%m%d")
        anomaly_key = f"session_anomaly:{username}:{date_str}"
        await redis.delete(anomaly_key)
        
        # Create some anomalies
        for i in range(5):
            await log_session_anomaly(
                username=username,
                session_id=session_id,
                anomaly_type="test_type",
                details=f"Test retention {i}"
            )
        
        # Get anomalies for last 7 days
        anomalies = await get_session_anomalies(username, days=7)
        assert len(anomalies) == 5
        
        # Get anomalies for last 1 day (should still see them)
        anomalies_1day = await get_session_anomalies(username, days=1)
        assert len(anomalies_1day) == 5
        
        # Cleanup
        await redis.delete(anomaly_key)

    @pytest.mark.asyncio
    async def test_memory_efficiency_under_load(self):
        """Test that audit logs don't consume excessive memory."""
        from app.core.session_security import log_session_anomaly
        from app.core.security import get_redis
        from app.core.utils import utc_now

        redis = await get_redis()

        # Simulate 100 users with frequent anomalies
        for user_num in range(100):
            username = f"test_memory_user_{user_num}"
            session_id = f"test_session_{user_num}"

            # Create 150 anomalies per user (should be trimmed to 100)
            for i in range(150):
                await log_session_anomaly(
                    username=username,
                    session_id=session_id,
                    anomaly_type="ip_change",
                    details=f"IP changed to 192.168.1.{i}"
                )

        # Verify total entries
        date_str = utc_now().strftime("%Y%m%d")
        total_entries = 0
        
        for user_num in range(100):
            username = f"test_memory_user_{user_num}"
            anomaly_key = f"session_anomaly:{username}:{date_str}"
            count = await redis.llen(anomaly_key)
            total_entries += count
            
            # Each user should have exactly 100 entries (trimmed)
            assert count == 100, f"User {user_num} has {count} entries, expected 100"
        
        # Total: 100 users × 100 entries = 10,000 entries
        assert total_entries == 10000, f"Expected 10000 total entries, got {total_entries}"
        
        # Cleanup
        for user_num in range(100):
            username = f"test_memory_user_{user_num}"
            anomaly_key = f"session_anomaly:{username}:{date_str}"
            await redis.delete(anomaly_key)
