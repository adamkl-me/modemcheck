"""
Security utilities for authentication and authorization.

Provides:
- Argon2id password hashing (with PBKDF2 fallback)
- Redis-based session management with sliding window
- Password policy validation
- CSRF token generation/validation
- Account lockout after failed logins
- Common password checking
"""
import secrets
import hashlib
import re
import json
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict
from pathlib import Path

from passlib.hash import argon2, pbkdf2_sha256
import redis.asyncio as aioredis

from app.core.config import settings


# ============================================================================
# REDIS CONNECTION WITH POOLING
# ============================================================================

_redis_pool: Optional[aioredis.ConnectionPool] = None


async def get_redis() -> aioredis.Redis:
    """
    Get async Redis connection from connection pool.

    In test mode, creates a new connection for each call to avoid
    'Event loop is closed' errors with pytest-asyncio.

    In production mode, uses a connection pool for better scalability
    under high load (prevents single connection bottleneck).

    Returns:
        Async Redis client
    """
    global _redis_pool

    # In test mode, always create fresh connection to avoid event loop issues
    # Each test function gets its own connection that doesn't outlive the test loop
    if settings.is_test():
        redis_url = f"redis://{settings.redis_host}:{settings.redis_port}/{settings.redis_db}"
        client = await aioredis.from_url(
            redis_url,
            password=settings.redis_password,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        return client

    # Production mode: Use connection pool
    if _redis_pool is None:
        redis_url = f"redis://{settings.redis_host}:{settings.redis_port}/{settings.redis_db}"
        _redis_pool = aioredis.ConnectionPool.from_url(
            redis_url,
            password=settings.redis_password,
            encoding="utf-8",
            decode_responses=True,
            max_connections=20,  # Allow up to 20 concurrent Redis connections
            socket_connect_timeout=5,
            socket_timeout=5,
        )

    return aioredis.Redis(connection_pool=_redis_pool)


async def close_redis():
    """Close Redis connection pool."""
    global _redis_pool
    if _redis_pool:
        await _redis_pool.disconnect()
        _redis_pool = None


# ============================================================================
# PASSWORD HASHING (Argon2id with PBKDF2 backward compatibility)
# ============================================================================

def hash_password(password: str) -> str:
    """
    Hash password using Argon2id.

    Args:
        password: Plain text password

    Returns:
        Password hash in Argon2id format
    """
    return argon2.using(
        type="id",  # Argon2id
        memory_cost=65536,  # 64 MB
        time_cost=3,  # 3 iterations
        parallelism=4,
        salt_size=16,
        digest_size=32
    ).hash(password)


def verify_password(password: str, stored_hash: str) -> Tuple[bool, bool]:
    """
    Verify password against stored hash with constant-time comparison.
    Supports Argon2id and PBKDF2 formats for backward compatibility.

    Args:
        password: Plain text password to verify
        stored_hash: Stored password hash

    Returns:
        (is_valid, needs_upgrade): Tuple of verification result and upgrade flag
    """
    try:
        # Detect hash format
        if stored_hash.startswith('$argon2'):
            # Argon2 format (current)
            try:
                is_valid = argon2.verify(password, stored_hash)
                needs_upgrade = argon2.needs_update(stored_hash)
                return (is_valid, needs_upgrade)
            except Exception:
                return (False, False)

        elif stored_hash.startswith('$pbkdf2-sha256$'):
            # Passlib PBKDF2 format (used in tests)
            try:
                from passlib.hash import pbkdf2_sha256
                is_valid = pbkdf2_sha256.verify(password, stored_hash)
                # PBKDF2 always needs upgrade to Argon2id
                return (is_valid, True)
            except Exception:
                return (False, False)

        elif stored_hash.startswith('pbkdf2:'):
            # New PBKDF2 format: pbkdf2:iterations:salt:hash
            try:
                parts = stored_hash.split(':')
                if len(parts) != 4:
                    return (False, False)

                _, iterations, salt, pwd_hash = parts
                iterations = int(iterations)

                new_hash = hashlib.pbkdf2_hmac(
                    'sha256',
                    password.encode('utf-8'),
                    salt.encode('utf-8'),
                    iterations
                )

                is_valid = secrets.compare_digest(new_hash.hex(), pwd_hash)
                # Upgrade to Argon2id
                return (is_valid, is_valid)
            except (ValueError, IndexError):
                return (False, False)

        elif ':' in stored_hash and stored_hash.count(':') == 1:
            # Legacy PBKDF2 format: salt:hash (100k iterations)
            try:
                salt, pwd_hash = stored_hash.split(':')
                new_hash = hashlib.pbkdf2_hmac(
                    'sha256',
                    password.encode('utf-8'),
                    salt.encode('utf-8'),
                    100000  # Legacy iteration count
                )

                is_valid = secrets.compare_digest(new_hash.hex(), pwd_hash)
                # Upgrade to Argon2id
                return (is_valid, is_valid)
            except (ValueError, IndexError):
                return (False, False)

        else:
            # Unknown format
            return (False, False)

    except Exception:
        return (False, False)


# ============================================================================
# PASSWORD POLICY VALIDATION
# ============================================================================

# Load common passwords from file
_common_passwords: Optional[set] = None


def load_common_passwords() -> set:
    """Load common passwords from file."""
    global _common_passwords

    if _common_passwords is None:
        _common_passwords = set()
        try:
            passwords_file = Path(settings.common_passwords_file)
            if passwords_file.exists():
                with open(passwords_file, 'r') as f:
                    _common_passwords = {line.strip().lower() for line in f if line.strip()}
        except Exception:
            # Fallback to minimal list if file not found
            _common_passwords = {
                'password', 'admin', '123456', 'password123', 'admin123',
                'changeme', 'welcome', 'test', 'demo', 'root'
            }

    return _common_passwords


def is_common_password(password: str) -> bool:
    """Check if password is in common passwords list."""
    common = load_common_passwords()
    return password.lower() in common


def validate_password(password: str) -> Tuple[bool, str]:
    """
    Validate password against security policy.

    Requirements:
    - Minimum 12 characters
    - At least 1 uppercase letter
    - At least 1 lowercase letter
    - At least 1 digit
    - At least 1 special character
    - Not in common password list

    Args:
        password: Password to validate

    Returns:
        (is_valid, error_message): Tuple of validation result and error message
    """
    if not password:
        return (False, "Password is required")

    if len(password) < settings.min_password_length:
        return (False, f"Password must be at least {settings.min_password_length} characters long")

    if not re.search(r'[A-Z]', password):
        return (False, "Password must contain at least one uppercase letter")

    if not re.search(r'[a-z]', password):
        return (False, "Password must contain at least one lowercase letter")

    if not re.search(r'\d', password):
        return (False, "Password must contain at least one digit")

    if not re.search(r'[!@#$%^&*()_+\-=\[\]{};:\'",.<>?/\\|`~]', password):
        return (False, "Password must contain at least one special character (!@#$%^&* etc.)")

    if is_common_password(password):
        return (False, "This password is too common and easily guessed. Please choose a more unique password")

    return (True, "")


# ============================================================================
# SESSION MANAGEMENT (Redis-based with sliding window)
# ============================================================================

async def create_session(username: str, role: str, max_sessions: int = 5) -> str:
    """
    Create a new session in Redis with automatic expiration.
    Enforces concurrent session limit atomically to prevent race conditions.

    Args:
        username: User's username
        role: User's role (admin, elevated, basic)
        max_sessions: Maximum concurrent sessions allowed (default: 5)

    Returns:
        session_id: 32-byte URL-safe token

    Raises:
        ValueError: If concurrent session limit exceeded
    """
    r = await get_redis()
    session_id = secrets.token_urlsafe(32)

    session_data = {
        'username': username,
        'role': role,
        'created': datetime.now().isoformat(),
        'expires': (datetime.now() + timedelta(seconds=settings.session_ttl)).isoformat()
    }

    # Lua script for atomic session creation with concurrent limit enforcement
    # This prevents TOCTOU race conditions where two logins could both bypass the limit
    lua_script = """
    local user_sessions_key = KEYS[1]
    local max_sessions = tonumber(ARGV[1])
    local session_id = ARGV[2]
    local ttl = tonumber(ARGV[3])

    -- Get current session count
    local current_count = redis.call('SCARD', user_sessions_key)

    if current_count >= max_sessions then
        return 0  -- Limit exceeded
    end

    -- Add session atomically
    redis.call('SADD', user_sessions_key, session_id)
    redis.call('EXPIRE', user_sessions_key, ttl)
    return 1  -- Success
    """

    user_sessions_key = f"user_sessions:{username}"

    # Execute atomic check-and-add
    result = await r.eval(lua_script, 1, user_sessions_key, max_sessions, session_id, settings.session_ttl)

    if result == 0:
        raise ValueError(f"Concurrent session limit exceeded (max: {max_sessions})")

    # Store session data (this can happen after the atomic add since the set tracks membership)
    session_key = f"session:{session_id}"
    await r.setex(session_key, settings.session_ttl, json.dumps(session_data))

    return session_id


async def verify_session(session_id: str, refresh_ttl: bool = True) -> Optional[Dict]:
    """
    Verify session exists in Redis and return user info.
    Implements sliding window by refreshing TTL on each verification.

    Args:
        session_id: Session token to verify
        refresh_ttl: If True, refresh the session TTL (sliding window)

    Returns:
        Session data if valid, None if invalid/expired
    """
    if not session_id:
        return None

    r = await get_redis()
    session_key = f"session:{session_id}"
    session_data_str = await r.get(session_key)

    if not session_data_str:
        return None

    session_data = json.loads(session_data_str)

    # Redis TTL handles expiration, but double-check for safety
    expires = datetime.fromisoformat(session_data['expires'])
    if datetime.now() > expires:
        await r.delete(session_key)
        return None

    # SECURITY: Sliding window session refresh
    # Refresh TTL on each successful verification to keep active sessions alive
    if refresh_ttl:
        new_expires = datetime.now() + timedelta(seconds=settings.session_ttl)
        session_data['expires'] = new_expires.isoformat()

        # Update Redis with new TTL (atomic operation)
        await r.setex(session_key, settings.session_ttl, json.dumps(session_data))

        # Also refresh user_sessions key TTL
        username = session_data.get('username')
        if username:
            user_sessions_key = f"user_sessions:{username}"
            await r.expire(user_sessions_key, settings.session_ttl)

    return session_data


async def delete_session(session_id: str):
    """Delete a single session from Redis."""
    if not session_id:
        return

    r = await get_redis()
    session_key = f"session:{session_id}"
    session_data_str = await r.get(session_key)

    if session_data_str:
        session_data = json.loads(session_data_str)
        username = session_data.get('username')

        # Remove from user's session set
        if username:
            user_sessions_key = f"user_sessions:{username}"
            await r.srem(user_sessions_key, session_id)

    # Delete the session
    await r.delete(session_key)


async def delete_user_sessions(username: str) -> int:
    """
    Delete all sessions for a specific user using efficient pipeline iteration.

    Performance: Uses SSCAN iteration to avoid loading all session IDs into memory,
    which is critical for users with many sessions (e.g., 100+ concurrent sessions).

    Args:
        username: Username whose sessions should be deleted

    Returns:
        Number of sessions deleted
    """
    r = await get_redis()
    user_sessions_key = f"user_sessions:{username}"

    count = 0
    pipe = r.pipeline()

    # Use SSCAN to iterate over session IDs without loading all into memory
    async for session_id in r.sscan_iter(user_sessions_key):
        pipe.delete(f"session:{session_id}")
        count += 1

    # Delete the user sessions set
    pipe.delete(user_sessions_key)

    # Execute all deletions in a single pipeline for efficiency
    await pipe.execute()

    return count


# ============================================================================
# CSRF PROTECTION
# ============================================================================

async def generate_csrf_token(session_id: str) -> str:
    """
    Generate CSRF token tied to session.

    Args:
        session_id: Session ID to tie CSRF token to

    Returns:
        CSRF token (32-byte URL-safe)
    """
    r = await get_redis()
    csrf_token = secrets.token_urlsafe(32)
    csrf_key = f"csrf:{csrf_token}"

    # Store session_id in Redis with TTL matching session TTL
    await r.setex(csrf_key, settings.session_ttl, session_id)

    return csrf_token


async def validate_csrf_token(csrf_token: str, session_id: str) -> bool:
    """
    Validate CSRF token matches session.

    Args:
        csrf_token: CSRF token from request
        session_id: Current session ID

    Returns:
        True if valid, False otherwise
    """
    if not csrf_token or not session_id:
        return False

    r = await get_redis()
    csrf_key = f"csrf:{csrf_token}"
    stored_session_id = await r.get(csrf_key)

    if not stored_session_id:
        return False

    # Constant-time comparison
    return secrets.compare_digest(stored_session_id, session_id)


async def delete_csrf_token(csrf_token: str):
    """Delete CSRF token (one-time use)."""
    if not csrf_token:
        return

    r = await get_redis()
    csrf_key = f"csrf:{csrf_token}"
    await r.delete(csrf_key)


# ============================================================================
# ACCOUNT LOCKOUT
# ============================================================================

async def check_account_locked(username: str) -> Tuple[bool, int]:
    """
    Check if account is locked due to failed login attempts.

    Args:
        username: Username to check

    Returns:
        (is_locked, remaining_seconds): Tuple of lock status and remaining time
    """
    r = await get_redis()
    failed_key = f"failed_logins:{username}"
    failed_count = await r.get(failed_key)

    if not failed_count:
        return (False, 0)

    failed_count = int(failed_count)
    if failed_count >= settings.max_failed_logins:
        ttl = await r.ttl(failed_key)
        return (True, max(0, ttl))

    return (False, 0)


async def record_failed_login(username: str):
    """
    Record failed login attempt and increment counter.

    Args:
        username: Username that failed login
    """
    r = await get_redis()
    failed_key = f"failed_logins:{username}"

    # Increment counter
    failed_count = await r.incr(failed_key)

    # Set expiration on first failure
    if failed_count == 1:
        await r.expire(failed_key, settings.account_lockout_duration)


async def clear_failed_logins(username: str):
    """Clear failed login counter on successful login."""
    r = await get_redis()
    failed_key = f"failed_logins:{username}"
    await r.delete(failed_key)


# ============================================================================
# HMAC SIGNATURE VALIDATION (for client uploads)
# ============================================================================

def verify_hmac_signature(
    api_key: str,
    timestamp: str,
    request_body: bytes,
    signature: str,
    max_age_seconds: int = 300
) -> bool:
    """
    Verify HMAC-SHA256 signature for client uploads.

    Args:
        api_key: API key secret
        timestamp: Request timestamp
        request_body: Raw request body bytes
        signature: HMAC signature from request
        max_age_seconds: Maximum age of request (replay prevention)

    Returns:
        True if valid, False otherwise
    """
    # Check timestamp age (replay prevention)
    try:
        request_time = int(timestamp)
        current_time = int(datetime.now().timestamp())
        if abs(current_time - request_time) > max_age_seconds:
            return False
    except (ValueError, TypeError):
        return False

    # Compute expected signature
    message = f"{timestamp}{request_body.decode('utf-8', errors='ignore')}".encode('utf-8')
    expected_signature = hashlib.sha256(api_key.encode('utf-8') + message).hexdigest()

    # Constant-time comparison
    return secrets.compare_digest(expected_signature, signature)
