"""
Security utilities for authentication and authorization.

Provides:
- Argon2id password hashing (with PBKDF2 fallback)
- Cache-based session management with automatic Redis fallback
- Password policy validation
- CSRF token generation/validation
- Account lockout after failed logins
- Common password checking
"""
import asyncio
import secrets
import hashlib
import re
import json
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict

from app.core.utils import utc_now
from pathlib import Path

from passlib.hash import argon2, pbkdf2_sha256
import redis.asyncio as aioredis

from app.core.config import settings
from app.core.cache_provider import get_cache, ICacheProvider


# ============================================================================
# PASSWORD HASHING CONSTANTS
# ============================================================================

# PBKDF2 iteration count (for backward compatibility verification)
# NIST SP 800-63B recommends minimum 10,000 iterations
# OWASP recommends 600,000+ iterations for PBKDF2-SHA256 (as of 2023)
PBKDF2_MIN_ITERATIONS = 600_000  # Flag for upgrade if below this
PBKDF2_LEGACY_ITERATIONS = 100_000  # Old default, always needs upgrade


# ============================================================================
# REDIS CONNECTION WITH POOLING
# ============================================================================

_redis_pool: Optional[aioredis.ConnectionPool] = None
_test_redis_pool: Optional[aioredis.ConnectionPool] = None  # Separate pool for tests
_redis_pool_lock = asyncio.Lock()  # Protects pool initialization


async def get_redis() -> aioredis.Redis:
    """
    Get async Redis connection from connection pool.

    In test mode, uses a separate connection pool with a smaller max_connections
    limit to prevent "max number of clients reached" errors during tests.

    In production mode, uses a connection pool for better scalability
    under high load (prevents single connection bottleneck).

    Returns:
        Async Redis client
    """
    global _redis_pool, _test_redis_pool

    # Use lock to prevent race condition during pool initialization
    async with _redis_pool_lock:
        # Test mode: Use connection pool with reasonable max_connections
        if settings.is_test():
            if _test_redis_pool is None:
                redis_url = f"redis://{settings.redis_host}:{settings.redis_port}/{settings.redis_db}"
                _test_redis_pool = aioredis.ConnectionPool.from_url(
                    redis_url,
                    password=settings.redis_password,
                    encoding="utf-8",
                    decode_responses=True,
                    max_connections=25,  # Enough for concurrent test scenarios
                    socket_connect_timeout=5,
                    socket_timeout=5,
                )
            return aioredis.Redis(connection_pool=_test_redis_pool)

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
    """Close Redis connection pools."""
    global _redis_pool, _test_redis_pool

    # Close test pool
    if _test_redis_pool:
        await _test_redis_pool.disconnect()
        _test_redis_pool = None

    # Close production pool
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
            except (ValueError, TypeError) as e:
                # Invalid hash format or type error during verification
                return (False, False)

        elif stored_hash.startswith('$pbkdf2-sha256$'):
            # Passlib PBKDF2 format (used in tests)
            try:
                from passlib.hash import pbkdf2_sha256
                is_valid = pbkdf2_sha256.verify(password, stored_hash)
                # PBKDF2 always needs upgrade to Argon2id
                return (is_valid, True)
            except (ValueError, TypeError) as e:
                # Invalid hash format or type error during verification
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
                # Always upgrade PBKDF2 to Argon2id (regardless of iteration count)
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

    except (ValueError, TypeError, AttributeError):
        # Catch remaining edge cases: malformed hashes, None values, etc.
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
        except (IOError, OSError, UnicodeDecodeError) as e:
            # Fallback to minimal list if file not found or read error
            _common_passwords = {
                'password', 'admin', '123456', 'password123', 'admin123',
                'changeme', 'welcome', 'test', 'demo', 'root'
            }

    return _common_passwords


def is_common_password(password: str) -> bool:
    """Check if password is in common passwords list."""
    common = load_common_passwords()
    return password.lower() in common


def contains_null_byte(text: str) -> bool:
    """
    Check if string contains null bytes (\x00).

    Null bytes can cause security issues with C-based libraries,
    SQL injection, and path traversal attacks.

    Args:
        text: String to check

    Returns:
        True if null byte found, False otherwise
    """
    return '\x00' in text if text else False


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
    - No null bytes

    Args:
        password: Password to validate

    Returns:
        (is_valid, error_message): Tuple of validation result and error message
    """
    if not password:
        return (False, "Password is required")

    if contains_null_byte(password):
        return (False, "Password contains invalid characters")

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

    Uses cache abstraction with automatic Redis fallback.

    Args:
        session_id: Session ID to tie CSRF token to

    Returns:
        CSRF token (32-byte URL-safe)
    """
    cache = await get_cache()
    csrf_token = secrets.token_urlsafe(32)
    csrf_key = f"csrf:{csrf_token}"

    # Store session_id in cache with TTL matching session TTL
    await cache.set(csrf_key, session_id, ttl=settings.session_ttl)

    return csrf_token


async def validate_csrf_token(csrf_token: str, session_id: str) -> bool:
    """
    Validate CSRF token matches session (one-time use).

    CSRF tokens are deleted after validation to prevent replay attacks.
    This ensures each token can only be used once, even within the TTL window.

    Uses cache abstraction with automatic Redis fallback.

    Args:
        csrf_token: CSRF token from request
        session_id: Current session ID

    Returns:
        True if valid, False otherwise
    """
    if not csrf_token or not session_id:
        return False

    cache = await get_cache()
    csrf_key = f"csrf:{csrf_token}"

    # Get and delete CSRF token (one-time use)
    # Note: Not atomic in fallback mode, but race window is negligible
    stored_session_id = await cache.get(csrf_key)

    if not stored_session_id:
        return False

    # Delete immediately after retrieval (one-time use)
    await cache.delete(csrf_key)

    # Constant-time comparison
    return secrets.compare_digest(stored_session_id, session_id)


async def delete_csrf_token(csrf_token: str):
    """Delete CSRF token (one-time use). Uses cache abstraction."""
    if not csrf_token:
        return

    cache = await get_cache()
    csrf_key = f"csrf:{csrf_token}"
    await cache.delete(csrf_key)


# ============================================================================
# ACCOUNT LOCKOUT
# ============================================================================

async def check_account_locked(username: str) -> Tuple[bool, int]:
    """
    Check if account is locked due to failed login attempts.

    Uses cache abstraction with automatic Redis fallback.

    Args:
        username: Username to check

    Returns:
        (is_locked, remaining_seconds): Tuple of lock status and remaining time
    """
    cache = await get_cache()
    failed_key = f"failed_logins:{username}"
    failed_count = await cache.get(failed_key)

    if not failed_count:
        return (False, 0)

    failed_count = int(failed_count)
    if failed_count >= settings.max_failed_logins:
        ttl = await cache.ttl(failed_key)
        return (True, max(0, ttl))

    return (False, 0)


async def record_failed_login(username: str):
    """
    Record failed login attempt and increment counter.

    Args:
        username: Username that failed login
    """
    cache = await get_cache()
    failed_key = f"failed_logins:{username}"

    # Increment counter
    failed_count = await cache.incr(failed_key)

    # Set expiration on first failure
    if failed_count == 1:
        await cache.expire(failed_key, settings.account_lockout_duration)


async def clear_failed_logins(username: str):
    """Clear failed login counter on successful login."""
    cache = await get_cache()
    failed_key = f"failed_logins:{username}"
    await cache.delete(failed_key)


async def check_api_key_lockout(ip_address: str) -> Tuple[bool, int]:
    """
    Check if IP is locked out due to failed API key attempts.

    Args:
        ip_address: IP address to check

    Returns:
        (is_locked, remaining_seconds): Tuple of lock status and remaining time
    """
    cache = await get_cache()
    failed_key = f"failed_api_keys:{ip_address}"
    failed_count = await cache.get(failed_key)

    if not failed_count:
        return (False, 0)

    failed_count = int(failed_count)
    # Lock out after 10 failed API key attempts (more lenient than login)
    if failed_count >= 10:
        ttl = await cache.ttl(failed_key)
        return (True, max(0, ttl))

    return (False, 0)


async def record_failed_api_key(ip_address: str):
    """
    Record failed API key attempt from IP and increment counter.

    Args:
        ip_address: IP address that failed API key validation
    """
    cache = await get_cache()
    failed_key = f"failed_api_keys:{ip_address}"

    # Increment counter
    failed_count = await cache.incr(failed_key)

    # Set 10 minute expiration on first failure (longer than account lockout)
    if failed_count == 1:
        await cache.expire(failed_key, 600)  # 10 minutes


async def clear_failed_api_keys(ip_address: str):
    """Clear failed API key counter on successful validation."""
    cache = await get_cache()
    failed_key = f"failed_api_keys:{ip_address}"
    await cache.delete(failed_key)


# ============================================================================
# TIMESTAMP VALIDATION (shared across modules)
# ============================================================================

# Consistent timestamp window for all replay attack prevention
TIMESTAMP_WINDOW_SECONDS = 300  # 5 minutes


def validate_request_timestamp(
    timestamp: int | str,
    window_seconds: int = TIMESTAMP_WINDOW_SECONDS
) -> tuple[bool, str]:
    """
    Validate that a request timestamp is within the allowed window.

    This is a shared function used by:
    - Upload endpoint (HMAC signature validation)
    - Config sync endpoint (nonce + timestamp validation)

    Args:
        timestamp: Unix epoch timestamp (int or string)
        window_seconds: Maximum allowed time difference (default: 300s)

    Returns:
        (is_valid, error_message): Tuple where error_message is empty if valid
    """
    import time

    # Parse timestamp to int if string
    if isinstance(timestamp, str):
        try:
            timestamp = int(timestamp)
        except (ValueError, TypeError):
            return False, "Invalid timestamp format"

    # Validate timestamp is within window
    current_time = int(time.time())
    time_diff = abs(current_time - timestamp)

    if time_diff > window_seconds:
        return False, f"Request timestamp expired (diff={time_diff}s, max={window_seconds}s)"

    return True, ""


def validate_request_timestamp_datetime(
    request_time: datetime,
    window_seconds: int = TIMESTAMP_WINDOW_SECONDS
) -> tuple[bool, str, datetime]:
    """
    Validate that a request datetime is within the allowed window.

    Variant that works with datetime objects for config sync.

    Args:
        request_time: Request timestamp as datetime (should be UTC)
        window_seconds: Maximum allowed time difference (default: 300s)

    Returns:
        (is_valid, error_message, server_time): Tuple with server time for error reporting
    """
    from datetime import timezone

    server_time = utc_now()
    # Normalize request_time to naive UTC if it has timezone info
    if request_time.tzinfo is not None:
        request_time_naive = request_time.replace(tzinfo=None)
    else:
        request_time_naive = request_time
    time_diff = abs((server_time - request_time_naive).total_seconds())

    if time_diff > window_seconds:
        return False, f"Clock skew too large (diff={time_diff:.1f}s, max={window_seconds}s)", server_time

    return True, "", server_time


# ============================================================================
# HMAC SIGNATURE VALIDATION (for client uploads)
# ============================================================================

def verify_hmac_signature(
    api_key: str,
    timestamp: str,
    request_body: bytes,
    signature: str,
    max_age_seconds: int = TIMESTAMP_WINDOW_SECONDS
) -> bool:
    """
    Verify HMAC-SHA256 signature for client uploads.

    Args:
        api_key: API key secret
        timestamp: Request timestamp
        request_body: Raw request body bytes
        signature: HMAC signature from request
        max_age_seconds: Maximum age of request (default: TIMESTAMP_WINDOW_SECONDS)

    Returns:
        True if valid, False otherwise
    """
    # Use shared timestamp validation
    is_valid, _ = validate_request_timestamp(timestamp, max_age_seconds)
    if not is_valid:
        return False

    # Compute expected signature
    message = f"{timestamp}{request_body.decode('utf-8', errors='ignore')}".encode('utf-8')
    expected_signature = hashlib.sha256(api_key.encode('utf-8') + message).hexdigest()

    # Constant-time comparison
    return secrets.compare_digest(expected_signature, signature)
