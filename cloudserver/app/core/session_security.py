"""
Enhanced session security with device fingerprinting and anomaly detection.

Features:
- Device fingerprinting (user-agent + IP tracking)
- Session anomaly detection (location/device changes)
- Concurrent session limits per user
- Session activity tracking
"""
import hashlib
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from fastapi import Request

from app.core.config import settings
from app.core.security import get_redis, delete_session
from app.core.utils import utc_now


def generate_device_fingerprint(request: Request) -> str:
    """
    Generate device fingerprint from request headers.

    Combines user-agent and IP address to create a unique fingerprint.
    This helps detect session hijacking attempts.

    Args:
        request: FastAPI request object

    Returns:
        SHA256 hash of device fingerprint
    """
    user_agent = request.headers.get("user-agent", "unknown")
    ip_address = request.client.host if request.client else "unknown"

    # Create fingerprint from user-agent + IP
    fingerprint_data = f"{user_agent}|{ip_address}"
    fingerprint_hash = hashlib.sha256(fingerprint_data.encode()).hexdigest()

    return fingerprint_hash


def extract_session_metadata(request: Request) -> dict:
    """
    Extract metadata about the session for tracking.

    Args:
        request: FastAPI request object

    Returns:
        Dictionary with session metadata
    """
    return {
        "user_agent": request.headers.get("user-agent", "unknown"),
        "ip_address": request.client.host if request.client else "unknown",
        "fingerprint": generate_device_fingerprint(request),
        "timestamp": utc_now().isoformat()
    }


async def create_session_with_fingerprint(
    session_id: str,
    username: str,
    request: Request
) -> None:
    """
    Store device fingerprint and metadata with session.

    Args:
        session_id: Session ID
        username: Username
        request: FastAPI request object
    """
    redis = await get_redis()

    metadata = extract_session_metadata(request)
    fingerprint_key = f"session_fingerprint:{session_id}"

    # Store fingerprint with same TTL as session
    await redis.setex(
        fingerprint_key,
        settings.session_ttl,
        json.dumps(metadata)
    )


async def verify_session_fingerprint(
    session_id: str,
    request: Request,
    strict: bool = False
) -> tuple[bool, Optional[str]]:
    """
    Verify session fingerprint matches current request.

    Args:
        session_id: Session ID to verify
        request: Current request
        strict: If True, reject on any mismatch. If False, allow IP changes.

    Returns:
        (is_valid, warning_message): Validation result and optional warning
    """
    redis = await get_redis()
    fingerprint_key = f"session_fingerprint:{session_id}"

    # Get stored fingerprint
    stored_metadata_str = await redis.get(fingerprint_key)
    if not stored_metadata_str:
        # No fingerprint stored (legacy session or expired)
        return (True, "No fingerprint stored")

    stored_metadata = json.loads(stored_metadata_str)
    current_metadata = extract_session_metadata(request)

    # Check user-agent (should be stable)
    if stored_metadata["user_agent"] != current_metadata["user_agent"]:
        return (False, "User-agent mismatch - possible session hijacking")

    # Check IP address (can change legitimately with mobile networks, VPNs)
    if stored_metadata["ip_address"] != current_metadata["ip_address"]:
        if strict:
            return (False, "IP address changed")
        else:
            # Log warning but allow (mobile networks change IPs frequently)
            return (True, f"IP changed: {stored_metadata['ip_address']} → {current_metadata['ip_address']}")

    # Check full fingerprint
    if stored_metadata["fingerprint"] != current_metadata["fingerprint"]:
        return (False, "Device fingerprint mismatch")

    return (True, None)


async def get_user_active_sessions(username: str) -> List[Dict]:
    """
    Get all active sessions for a user with metadata.

    Args:
        username: Username to check

    Returns:
        List of active session dictionaries with metadata
    """
    redis = await get_redis()
    user_sessions_key = f"user_sessions:{username}"

    # Get session IDs
    session_ids = await redis.smembers(user_sessions_key)

    sessions = []
    for session_id in session_ids:
        # Get session data
        session_key = f"session:{session_id}"
        session_data_str = await redis.get(session_key)

        if not session_data_str:
            continue

        session_data = json.loads(session_data_str)

        # Get fingerprint metadata
        fingerprint_key = f"session_fingerprint:{session_id}"
        metadata_str = await redis.get(fingerprint_key)

        metadata = json.loads(metadata_str) if metadata_str else {}

        sessions.append({
            "session_id": session_id[:16] + "...",  # Truncate for security
            "created": session_data.get("created"),
            "expires": session_data.get("expires"),
            "ip_address": metadata.get("ip_address", "unknown"),
            "user_agent": metadata.get("user_agent", "unknown")[:100],  # Truncate long UAs
            "last_seen": metadata.get("timestamp", "unknown")
        })

    return sessions


async def enforce_concurrent_session_limit(
    username: str,
    max_sessions: int = 5
) -> bool:
    """
    Enforce maximum concurrent sessions per user.

    Args:
        username: Username to check
        max_sessions: Maximum allowed concurrent sessions (default: 5)

    Returns:
        True if under limit, False if limit exceeded
    """
    sessions = await get_user_active_sessions(username)
    return len(sessions) < max_sessions


async def terminate_oldest_sessions(
    username: str,
    keep_count: int = 3
) -> int:
    """
    Terminate oldest sessions for a user, keeping only the most recent.

    Useful when a user has too many active sessions.

    Args:
        username: Username
        keep_count: Number of newest sessions to keep

    Returns:
        Number of sessions terminated
    """
    redis = await get_redis()
    user_sessions_key = f"user_sessions:{username}"

    # Get all session IDs
    session_ids = await redis.smembers(user_sessions_key)

    if len(session_ids) <= keep_count:
        return 0  # Under limit

    # Get session creation times
    session_times = []
    for session_id in session_ids:
        session_key = f"session:{session_id}"
        session_data_str = await redis.get(session_key)

        if session_data_str:
            session_data = json.loads(session_data_str)
            created = datetime.fromisoformat(session_data["created"])
            session_times.append((session_id, created))

    # Sort by creation time (newest first)
    session_times.sort(key=lambda x: x[1], reverse=True)

    # Terminate oldest sessions
    terminated = 0
    for session_id, _ in session_times[keep_count:]:
        await delete_session(session_id)
        terminated += 1

    return terminated


async def log_session_anomaly(
    username: str,
    session_id: str,
    anomaly_type: str,
    details: str
) -> None:
    """
    Log session security anomaly for monitoring.

    Args:
        username: Username
        session_id: Session ID
        anomaly_type: Type of anomaly (e.g., "fingerprint_mismatch", "ip_change")
        details: Additional details
    """
    redis = await get_redis()
    anomaly_key = f"session_anomaly:{username}:{utc_now().strftime('%Y%m%d')}"

    anomaly_data = {
        "timestamp": utc_now().isoformat(),
        "session_id": session_id[:16],  # Truncated for security
        "type": anomaly_type,
        "details": details
    }

    # Store as list (Redis LIST) with size limit to prevent memory exhaustion
    await redis.rpush(anomaly_key, json.dumps(anomaly_data))

    # Trim to keep only the most recent 100 anomalies per day
    # This prevents unbounded growth while maintaining useful audit history
    await redis.ltrim(anomaly_key, -100, -1)

    # Set expiration (keep for 7 days - reduced from 30 to save memory)
    await redis.expire(anomaly_key, 7 * 24 * 60 * 60)


async def get_session_anomalies(
    username: str,
    days: int = 7
) -> List[Dict]:
    """
    Get recent session anomalies for a user.

    Args:
        username: Username
        days: Number of days to look back

    Returns:
        List of anomaly dictionaries
    """
    redis = await get_redis()
    anomalies = []

    # Check each day
    for day_offset in range(days):
        date = utc_now() - timedelta(days=day_offset)
        date_str = date.strftime("%Y%m%d")
        anomaly_key = f"session_anomaly:{username}:{date_str}"

        # Get all anomalies for this day
        anomaly_list = await redis.lrange(anomaly_key, 0, -1)

        for anomaly_str in anomaly_list:
            anomalies.append(json.loads(anomaly_str))

    return anomalies
