#!/usr/bin/env python3
"""
Authentication and Session Management API
Handles user login, logout, password management, and session verification.

Security Features:
- Argon2id password hashing with PBKDF2 backward compatibility
- Redis-based session storage (atomic operations, auto-expiration)
- Strong password policy validation (12+ chars, complexity, common password check)
- Structured error logging (no stack traces to clients)
- Constant-time password comparison
- Comprehensive audit logging
"""

import cgi
import json
import os
import sys
import secrets
import hashlib
import logging
import traceback
import re
from datetime import datetime, timedelta

# Third-party security libraries
try:
    from argon2 import PasswordHasher, Type
    from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
    ARGON2_AVAILABLE = True
except ImportError:
    ARGON2_AVAILABLE = False
    print("WARNING: argon2-cffi not available, falling back to PBKDF2 only", file=sys.stderr)

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    print("ERROR: redis-py not available, session management will fail", file=sys.stderr)

# Import audit logging and database access
sys.path.insert(0, '/modemcheck-cloud/cgi-bin')
try:
    from audit_schema import log_user_activity, get_audit_connection
except ImportError:
    def log_user_activity(*args, **kwargs):
        pass
    def get_audit_connection():
        raise ImportError("audit_schema not available")

try:
    from common_passwords import is_common_password
except ImportError:
    def is_common_password(password):
        # Fallback if common_passwords module not available
        common = ['password', 'admin', '123456', 'password123', 'admin123']
        return password.lower() in common

# ============================================================================
# CONFIGURATION
# ============================================================================

# Redis configuration (from environment variables)
REDIS_HOST = os.environ.get('REDIS_HOST', 'redis')
REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))
REDIS_DB = int(os.environ.get('REDIS_DB', 0))
SESSION_TTL = 43200  # 12 hours in seconds

# Logging configuration
LOG_FILE = '/modemcheck-cloud/logs/auth_errors.log'
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

# Password policy
PASSWORD_MIN_LENGTH = 12
PASSWORD_REQUIRE_UPPERCASE = True
PASSWORD_REQUIRE_LOWERCASE = True
PASSWORD_REQUIRE_DIGIT = True
PASSWORD_REQUIRE_SPECIAL = True

# Argon2 parameters (if available)
if ARGON2_AVAILABLE:
    # Argon2id with secure parameters
    # Memory: 64 MB, Iterations: 3, Parallelism: 4
    ph = PasswordHasher(
        time_cost=3,
        memory_cost=65536,  # 64 MB
        parallelism=4,
        hash_len=32,
        salt_len=16,
        type=Type.ID  # Argon2id (hybrid mode)
    )

# ============================================================================
# LOGGING SETUP
# ============================================================================

def setup_logging():
    """Configure structured error logging to file"""
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        logging.basicConfig(
            filename=LOG_FILE,
            level=logging.ERROR,
            format=LOG_FORMAT
        )
    except Exception as e:
        # Fallback to stderr if log file can't be created
        logging.basicConfig(level=logging.ERROR, format=LOG_FORMAT)
        logging.error(f"Failed to setup log file: {e}")

setup_logging()
logger = logging.getLogger('auth')

# ============================================================================
# ERROR HANDLING
# ============================================================================

def log_error(error_msg, exc_info=None, context=None):
    """
    Log error details securely without exposing to client.

    Args:
        error_msg: Human-readable error message
        exc_info: Exception info tuple from sys.exc_info()
        context: Dictionary of context information (request params, etc.)
    """
    log_data = {
        'timestamp': datetime.now().isoformat(),
        'error': error_msg,
        'context': context or {}
    }

    if exc_info:
        log_data['exception'] = {
            'type': exc_info[0].__name__ if exc_info[0] else 'Unknown',
            'message': str(exc_info[1]),
            'traceback': ''.join(traceback.format_exception(*exc_info))
        }

    logger.error(json.dumps(log_data))

def handle_error(error_msg, status_code=500, log_context=None):
    """
    Handle errors by logging details and returning generic JSON to client.

    Args:
        error_msg: Internal error message for logs
        status_code: HTTP status code
        log_context: Additional context for logging
    """
    log_error(error_msg, sys.exc_info(), log_context)

    # Return generic error to client (no sensitive details)
    print("Content-Type: application/json")
    print()
    print(json.dumps({'success': False, 'error': 'Internal Server Error'}))

# ============================================================================
# REDIS SESSION MANAGEMENT
# ============================================================================

def get_redis_connection():
    """Get Redis connection with error handling"""
    try:
        return redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5
        )
    except Exception as e:
        log_error(f"Failed to connect to Redis: {e}", sys.exc_info())
        return None

def create_session(username, role):
    """
    Create a new session in Redis with automatic expiration.

    Args:
        username: User's username
        role: User's role (admin, elevated, basic)

    Returns:
        session_id: 32-byte URL-safe token
    """
    try:
        r = get_redis_connection()
        if not r:
            raise Exception("Redis connection failed")

        session_id = secrets.token_urlsafe(32)
        session_data = {
            'username': username,
            'role': role,
            'created': datetime.now().isoformat(),
            'expires': (datetime.now() + timedelta(seconds=SESSION_TTL)).isoformat()
        }

        # Store session in Redis with TTL (atomic operation)
        session_key = f"session:{session_id}"
        r.setex(session_key, SESSION_TTL, json.dumps(session_data))

        # Add session ID to user's session set (for bulk deletion)
        user_sessions_key = f"user_sessions:{username}"
        r.sadd(user_sessions_key, session_id)
        r.expire(user_sessions_key, SESSION_TTL)

        return session_id
    except Exception as e:
        log_error(f"Failed to create session for {username}", sys.exc_info(), {'username': username})
        raise

def verify_session(session_id):
    """
    Verify session exists in Redis and return user info.

    Args:
        session_id: Session token to verify

    Returns:
        dict: Session data if valid, None if invalid/expired
    """
    if not session_id:
        return None

    try:
        r = get_redis_connection()
        if not r:
            return None

        session_key = f"session:{session_id}"
        session_data_str = r.get(session_key)

        if not session_data_str:
            return None

        session_data = json.loads(session_data_str)

        # Redis TTL handles expiration, but double-check for safety
        expires = datetime.fromisoformat(session_data['expires'])
        if datetime.now() > expires:
            r.delete(session_key)
            return None

        return session_data
    except Exception as e:
        log_error(f"Failed to verify session", sys.exc_info(), {'session_id': session_id[:10] + '...'})
        return None

def delete_session(session_id):
    """Delete a single session from Redis"""
    if not session_id:
        return

    try:
        r = get_redis_connection()
        if not r:
            return

        # Get session data to find username
        session_key = f"session:{session_id}"
        session_data_str = r.get(session_key)

        if session_data_str:
            session_data = json.loads(session_data_str)
            username = session_data.get('username')

            # Remove from user's session set
            if username:
                user_sessions_key = f"user_sessions:{username}"
                r.srem(user_sessions_key, session_id)

        # Delete the session
        r.delete(session_key)
    except Exception as e:
        log_error(f"Failed to delete session", sys.exc_info(), {'session_id': session_id[:10] + '...'})

def delete_user_sessions(username):
    """
    Delete all sessions for a specific user.

    Args:
        username: Username whose sessions should be deleted

    Returns:
        int: Number of sessions deleted
    """
    try:
        r = get_redis_connection()
        if not r:
            return 0

        user_sessions_key = f"user_sessions:{username}"
        session_ids = r.smembers(user_sessions_key)

        deleted_count = 0
        for session_id in session_ids:
            session_key = f"session:{session_id}"
            if r.delete(session_key):
                deleted_count += 1

        # Clear the user sessions set
        r.delete(user_sessions_key)

        return deleted_count
    except Exception as e:
        log_error(f"Failed to delete user sessions", sys.exc_info(), {'username': username})
        return 0

# ============================================================================
# PASSWORD HASHING (Argon2id with PBKDF2 backward compatibility)
# ============================================================================

def hash_password(password):
    """
    Hash password using Argon2id (or PBKDF2 if unavailable).

    Args:
        password: Plain text password

    Returns:
        str: Password hash (format indicates algorithm)
    """
    if ARGON2_AVAILABLE:
        # Use Argon2id (modern, memory-hard)
        return ph.hash(password)
    else:
        # Fallback to PBKDF2-HMAC-SHA256
        salt = secrets.token_hex(32)
        pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 600000)
        return f"pbkdf2:600000:{salt}:{pwd_hash.hex()}"

def verify_password(password, stored_hash):
    """
    Verify password against stored hash with constant-time comparison.
    Supports both Argon2id and PBKDF2 formats.

    Args:
        password: Plain text password to verify
        stored_hash: Stored password hash

    Returns:
        tuple: (is_valid: bool, needs_upgrade: bool)
    """
    try:
        # Detect hash format
        if stored_hash.startswith('$argon2'):
            # Argon2 format
            if not ARGON2_AVAILABLE:
                log_error("Argon2 hash found but library not available", context={'hash_prefix': stored_hash[:20]})
                return (False, False)

            try:
                ph.verify(stored_hash, password)
                # Check if hash needs rehashing (parameters changed)
                needs_upgrade = ph.check_needs_rehash(stored_hash)
                return (True, needs_upgrade)
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                return (False, False)

        elif stored_hash.startswith('pbkdf2:'):
            # New PBKDF2 format with iteration count
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

                # Constant-time comparison
                is_valid = secrets.compare_digest(new_hash.hex(), pwd_hash)
                # Upgrade if using old iteration count
                needs_upgrade = iterations < 600000 if is_valid else False
                return (is_valid, needs_upgrade)
            except (ValueError, IndexError):
                return (False, False)

        elif ':' in stored_hash and stored_hash.count(':') == 1:
            # Legacy PBKDF2 format (salt:hash with 100k iterations)
            try:
                salt, pwd_hash = stored_hash.split(':')
                new_hash = hashlib.pbkdf2_hmac(
                    'sha256',
                    password.encode('utf-8'),
                    salt.encode('utf-8'),
                    100000  # Legacy iteration count
                )

                # Constant-time comparison
                is_valid = secrets.compare_digest(new_hash.hex(), pwd_hash)
                # Definitely needs upgrade (legacy format)
                return (is_valid, is_valid)
            except (ValueError, IndexError):
                return (False, False)

        else:
            # Unknown format
            log_error("Unknown password hash format", context={'hash_prefix': stored_hash[:20]})
            return (False, False)

    except Exception as e:
        log_error("Password verification failed", sys.exc_info())
        return (False, False)

def upgrade_password_hash(username, password):
    """
    Upgrade user's password hash to latest algorithm (Argon2id or PBKDF2-600k).
    Called automatically on successful login with old hash.

    Args:
        username: Username to upgrade
        password: Plain text password (just verified)
    """
    try:
        new_hash = hash_password(password)

        conn = get_audit_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE users
            SET password_hash = ?
            WHERE username = ?
        """, (new_hash, username))
        conn.commit()
        conn.close()

        logger.info(f"Upgraded password hash for user: {username}")
    except Exception as e:
        log_error(f"Failed to upgrade password hash for {username}", sys.exc_info(), {'username': username})

# ============================================================================
# PASSWORD POLICY VALIDATION
# ============================================================================

def validate_password(password):
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
        tuple: (is_valid: bool, error_message: str)
    """
    if not password:
        return (False, "Password is required")

    if len(password) < PASSWORD_MIN_LENGTH:
        return (False, f"Password must be at least {PASSWORD_MIN_LENGTH} characters long")

    if PASSWORD_REQUIRE_UPPERCASE and not re.search(r'[A-Z]', password):
        return (False, "Password must contain at least one uppercase letter")

    if PASSWORD_REQUIRE_LOWERCASE and not re.search(r'[a-z]', password):
        return (False, "Password must contain at least one lowercase letter")

    if PASSWORD_REQUIRE_DIGIT and not re.search(r'\d', password):
        return (False, "Password must contain at least one digit")

    if PASSWORD_REQUIRE_SPECIAL and not re.search(r'[!@#$%^&*()_+\-=\[\]{};:\'",.<>?/\\|`~]', password):
        return (False, "Password must contain at least one special character (!@#$%^&* etc.)")

    # Check against common passwords
    if is_common_password(password):
        return (False, "This password is too common and easily guessed. Please choose a more unique password")

    return (True, "")

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_cookie(name):
    """Get cookie value from HTTP headers"""
    cookie_string = os.environ.get('HTTP_COOKIE', '')
    cookies = {}
    for cookie in cookie_string.split(';'):
        if '=' in cookie:
            key, value = cookie.strip().split('=', 1)
            cookies[key] = value
    return cookies.get(name)

def get_client_info():
    """Extract client IP and user agent from environment"""
    client_ip = (os.environ.get('HTTP_CF_CONNECTING_IP') or
                os.environ.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or
                os.environ.get('REMOTE_ADDR', 'unknown'))
    user_agent = os.environ.get('HTTP_USER_AGENT', 'unknown')
    return client_ip, user_agent

def ensure_default_admin():
    """Ensure default admin user exists in database"""
    try:
        conn = get_audit_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM users")
        user_count = cursor.fetchone()['count']

        if user_count == 0:
            # Create default admin user with Argon2id hash
            cursor.execute("""
                INSERT INTO users (username, password_hash, role, created_at, must_change_password)
                VALUES (?, ?, 'admin', ?, 1)
            """, ('admin', hash_password('changeme'), datetime.now().isoformat()))
            conn.commit()
            logger.info("Created default admin user")

        conn.close()
    except Exception as e:
        log_error("Failed to ensure default admin exists", sys.exc_info())

# ============================================================================
# REQUEST HANDLERS
# ============================================================================

def handle_login(form):
    """Handle user login request"""
    username = form.getvalue('username', '').strip()
    password = form.getvalue('password', '')

    if not username or not password:
        print()
        print(json.dumps({'success': False, 'error': 'Username and password required'}))
        return

    client_ip, user_agent = get_client_info()

    try:
        # Ensure default admin exists
        ensure_default_admin()

        # Lookup user in database
        conn = get_audit_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT password_hash, role, must_change_password
            FROM users
            WHERE username = ?
        """, (username,))
        user_row = cursor.fetchone()

        if user_row is None:
            conn.close()
            # Log failed login attempt
            log_user_activity(
                username=username,
                action_type='login',
                ip_address=client_ip,
                success=False,
                failure_reason='User not found',
                user_agent=user_agent
            )
            print()
            print(json.dumps({'success': False, 'error': 'Invalid credentials'}))
            return

        user = dict(user_row)
        is_valid, needs_upgrade = verify_password(password, user['password_hash'])

        if not is_valid:
            conn.close()
            # Log failed login attempt
            log_user_activity(
                username=username,
                action_type='login',
                ip_address=client_ip,
                success=False,
                failure_reason='Invalid password',
                user_role=user.get('role'),
                user_agent=user_agent
            )
            print()
            print(json.dumps({'success': False, 'error': 'Invalid credentials'}))
            return

        # Upgrade password hash if needed
        if needs_upgrade:
            upgrade_password_hash(username, password)

        # Update last login info in database
        cursor.execute("""
            UPDATE users
            SET last_login = ?, last_login_ip = ?
            WHERE username = ?
        """, (datetime.now().isoformat(), client_ip, username))
        conn.commit()
        conn.close()

        # Create session in Redis
        session_id = create_session(username, user['role'])

        # Log successful login
        log_user_activity(
            username=username,
            action_type='login',
            ip_address=client_ip,
            success=True,
            user_role=user.get('role'),
            user_agent=user_agent,
            session_id=session_id
        )

        # Set secure cookie
        print(f"Set-Cookie: modemcheck_session={session_id}; Path=/; Max-Age={SESSION_TTL}; HttpOnly; SameSite=Strict")
        print()
        print(json.dumps({
            'success': True,
            'username': username,
            'role': user['role'],
            'must_change_password': bool(user.get('must_change_password', False))
        }))

    except Exception as e:
        handle_error(f"Login failed for {username}", log_context={'username': username})

def handle_change_password(form):
    """Handle user password change request"""
    session_id = get_cookie('modemcheck_session')
    session = verify_session(session_id)

    client_ip, user_agent = get_client_info()

    if not session:
        print()
        print(json.dumps({'success': False, 'error': 'Not authenticated'}))
        return

    new_password = form.getvalue('new_password', '')

    # Validate password against policy
    is_valid, error_message = validate_password(new_password)
    if not is_valid:
        print()
        print(json.dumps({'success': False, 'error': error_message}))
        return

    try:
        # Hash with latest algorithm
        new_hash = hash_password(new_password)

        conn = get_audit_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE users
            SET password_hash = ?, must_change_password = 0
            WHERE username = ?
        """, (new_hash, session['username']))
        conn.commit()
        conn.close()

        # Log password change
        log_user_activity(
            username=session['username'],
            action_type='change_password',
            ip_address=client_ip,
            success=True,
            user_role=session.get('role'),
            user_agent=user_agent,
            session_id=session_id
        )

        print()
        print(json.dumps({'success': True, 'message': 'Password changed successfully'}))

    except Exception as e:
        handle_error(f"Password change failed for {session['username']}",
                    log_context={'username': session['username']})

def handle_logout(form):
    """Handle user logout request"""
    session_id = get_cookie('modemcheck_session')
    session = verify_session(session_id)

    client_ip, user_agent = get_client_info()

    # Log logout if we have a valid session
    if session:
        log_user_activity(
            username=session['username'],
            action_type='logout',
            ip_address=client_ip,
            success=True,
            user_role=session.get('role'),
            user_agent=user_agent,
            session_id=session_id
        )

    delete_session(session_id)

    # Clear cookie
    print("Set-Cookie: modemcheck_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict")
    print()
    print(json.dumps({'success': True}))

def handle_session_check():
    """Handle session verification (GET request)"""
    session_id = get_cookie('modemcheck_session')
    session = verify_session(session_id)

    print()
    if session:
        try:
            # Get user data from database to check must_change_password flag
            conn = get_audit_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT must_change_password
                FROM users
                WHERE username = ?
            """, (session['username'],))
            user_row = cursor.fetchone()
            conn.close()

            must_change = bool(user_row['must_change_password']) if user_row else False

            print(json.dumps({
                'authenticated': True,
                'username': session['username'],
                'role': session.get('role'),
                'must_change_password': must_change
            }))
        except Exception as e:
            # Fallback if database query fails
            print(json.dumps({
                'authenticated': True,
                'username': session['username'],
                'role': session.get('role'),
                'must_change_password': False
            }))
    else:
        print(json.dumps({'authenticated': False}))

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Main CGI entry point with comprehensive error handling"""
    try:
        print("Content-Type: application/json")

        request_method = os.environ.get('REQUEST_METHOD', 'GET')

        if request_method == 'POST':
            form = cgi.FieldStorage()
            action = form.getvalue('action', 'login')

            if action == 'login':
                handle_login(form)
            elif action == 'change_own_password':
                handle_change_password(form)
            elif action == 'logout':
                handle_logout(form)
            else:
                print()
                print(json.dumps({'success': False, 'error': 'Unknown action'}))

        elif request_method == 'GET':
            handle_session_check()

        else:
            print()
            print(json.dumps({'success': False, 'error': 'Method not allowed'}))

    except Exception as e:
        # Catch all unhandled exceptions
        handle_error("Unhandled exception in main()", log_context={'method': os.environ.get('REQUEST_METHOD')})

if __name__ == '__main__':
    main()
