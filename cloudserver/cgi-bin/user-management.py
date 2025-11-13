#!/usr/bin/env python3
"""
User Management API
Handles user CRUD operations, password resets, and session management.
Requires admin authentication for all operations.

Security Features:
- Admin-only access control
- Password policy validation
- Secure error logging (no stack traces to clients)
- Comprehensive audit logging
- Redis session management
"""

import cgi
import json
import os
import sys
import sqlite3
import logging
import traceback
from datetime import datetime

# Import from auth.py (now with all security improvements)
sys.path.insert(0, '/modemcheck-cloud/cgi-bin')
from auth import (
    hash_password,
    verify_session,
    get_cookie,
    delete_user_sessions,
    validate_password,
    log_error,
    get_client_info
)

# Import audit logging and database access
try:
    from audit_schema import log_user_activity, get_audit_connection
except ImportError:
    def log_user_activity(*args, **kwargs):
        pass
    def get_audit_connection():
        raise ImportError("audit_schema not available")

# Logging configuration
LOG_FILE = '/modemcheck-cloud/logs/user_management_errors.log'
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

def setup_logging():
    """Configure structured error logging"""
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        logging.basicConfig(
            filename=LOG_FILE,
            level=logging.ERROR,
            format=LOG_FORMAT
        )
    except Exception as e:
        logging.basicConfig(level=logging.ERROR, format=LOG_FORMAT)

setup_logging()
logger = logging.getLogger('user_management')

def handle_error(error_msg, log_context=None):
    """Handle errors by logging and returning generic message to client"""
    log_data = {
        'timestamp': datetime.now().isoformat(),
        'error': error_msg,
        'context': log_context or {},
        'exception': ''.join(traceback.format_exception(*sys.exc_info()))
    }
    logger.error(json.dumps(log_data))

    print(json.dumps({'success': False, 'error': 'Internal Server Error'}))

def main():
    """Main CGI entry point with comprehensive error handling"""
    try:
        print("Content-Type: application/json")

        client_ip, user_agent = get_client_info()

        # Check authentication
        session_id = get_cookie('modemcheck_session')
        session = verify_session(session_id)

        # Only admin can access user management
        if not session or session.get('role') != 'admin':
            print()
            print(json.dumps({'success': False, 'error': 'Unauthorized - Admin access required'}))
            return

        request_method = os.environ.get('REQUEST_METHOD', 'GET')
        form = cgi.FieldStorage()

        print()

        if request_method == 'GET':
            handle_get_users(session, client_ip, user_agent, session_id)

        elif request_method == 'POST':
            action = form.getvalue('action')

            if action == 'create':
                handle_create_user(form, session, client_ip, user_agent, session_id)
            elif action == 'delete':
                handle_delete_user(form, session, client_ip, user_agent, session_id)
            elif action == 'change_password':
                handle_change_password(form, session, client_ip, user_agent, session_id)
            elif action == 'logout_user':
                handle_logout_user(form, session, client_ip, user_agent, session_id)
            else:
                print(json.dumps({'success': False, 'error': 'Invalid action'}))
        else:
            print(json.dumps({'success': False, 'error': 'Method not allowed'}))

    except Exception as e:
        handle_error("Unhandled exception in main()", {'method': os.environ.get('REQUEST_METHOD')})

def handle_get_users(session, client_ip, user_agent, session_id):
    """Handle GET request - list all users"""
    try:
        conn = get_audit_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT username, role, created_at, last_login, last_login_ip
            FROM users
        """)
        user_list = [dict(row) for row in cursor.fetchall()]
        conn.close()

        # Fix key names for frontend compatibility
        for user in user_list:
            user['created'] = user.pop('created_at')
            user['last_login'] = user['last_login'] or 'Never'
            user['last_login_ip'] = user['last_login_ip'] or '-'

        print(json.dumps({'success': True, 'users': user_list}))
    except Exception as e:
        handle_error("Failed to list users", {'session_user': session['username']})

def handle_create_user(form, session, client_ip, user_agent, session_id):
    """Handle POST create action - create new user"""
    username = form.getvalue('username', '').strip()
    password = form.getvalue('password', '')
    role = form.getvalue('role', 'basic')

    if not username or not password:
        print(json.dumps({'success': False, 'error': 'Username and password required'}))
        return

    if role not in ['basic', 'elevated', 'admin']:
        print(json.dumps({'success': False, 'error': 'Invalid role'}))
        return

    # Only admin can create other admins
    if role == 'admin' and session.get('role') != 'admin':
        print(json.dumps({'success': False, 'error': 'Only admin can create admin users'}))
        return

    # Validate password against policy
    is_valid, error_message = validate_password(password)
    if not is_valid:
        print(json.dumps({'success': False, 'error': error_message}))
        return

    try:
        # Hash password with latest algorithm (Argon2id or PBKDF2-600k)
        password_hash = hash_password(password)

        conn = get_audit_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (username, password_hash, role, created_at, must_change_password)
            VALUES (?, ?, ?, ?, 1)
        """, (username, password_hash, role, datetime.now().isoformat()))
        conn.commit()
        conn.close()

        # Log user creation
        log_user_activity(
            username=session['username'],
            action_type='create_user',
            ip_address=client_ip,
            success=True,
            user_role=session.get('role'),
            action_details=f"Created user '{username}' with role '{role}'",
            user_agent=user_agent,
            session_id=session_id
        )

        print(json.dumps({'success': True, 'message': 'User created successfully'}))
    except sqlite3.IntegrityError:
        print(json.dumps({'success': False, 'error': 'User already exists'}))
    except Exception as e:
        handle_error(f"Failed to create user {username}", {
            'session_user': session['username'],
            'new_user': username
        })

def handle_delete_user(form, session, client_ip, user_agent, session_id):
    """Handle POST delete action - delete user"""
    username = form.getvalue('username', '').strip()

    if not username:
        print(json.dumps({'success': False, 'error': 'Username required'}))
        return

    # Prevent deleting the admin account
    if username == 'admin':
        print(json.dumps({'success': False, 'error': 'Cannot delete the admin account'}))
        return

    # Prevent deleting own account
    if username == session['username']:
        print(json.dumps({'success': False, 'error': 'Cannot delete your own account'}))
        return

    try:
        conn = get_audit_connection()
        cursor = conn.cursor()

        # Get user role before deletion
        cursor.execute("SELECT role FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            print(json.dumps({'success': False, 'error': 'User not found'}))
            return

        deleted_user_role = row['role']

        cursor.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.commit()
        conn.close()

        # Delete user's sessions from Redis
        deleted_sessions = delete_user_sessions(username)

        # Log user deletion
        log_user_activity(
            username=session['username'],
            action_type='delete_user',
            ip_address=client_ip,
            success=True,
            user_role=session.get('role'),
            action_details=f"Deleted user '{username}' (was {deleted_user_role}), removed {deleted_sessions} session(s)",
            user_agent=user_agent,
            session_id=session_id
        )

        print(json.dumps({'success': True, 'message': 'User deleted successfully'}))
    except Exception as e:
        handle_error(f"Failed to delete user {username}", {
            'session_user': session['username'],
            'target_user': username
        })

def handle_change_password(form, session, client_ip, user_agent, session_id):
    """Handle POST change_password action - admin password reset"""
    username = form.getvalue('username', '').strip()
    new_password = form.getvalue('new_password', '')

    if not username or not new_password:
        print(json.dumps({'success': False, 'error': 'Username and new password required'}))
        return

    # Validate password against policy
    is_valid, error_message = validate_password(new_password)
    if not is_valid:
        print(json.dumps({'success': False, 'error': error_message}))
        return

    try:
        # Hash password with latest algorithm
        password_hash = hash_password(new_password)

        conn = get_audit_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE users
            SET password_hash = ?, must_change_password = 1
            WHERE username = ?
        """, (password_hash, username))

        if cursor.rowcount == 0:
            conn.close()
            print(json.dumps({'success': False, 'error': 'User not found'}))
            return

        conn.commit()
        conn.close()

        # Log password change
        log_user_activity(
            username=session['username'],
            action_type='admin_password_reset',
            ip_address=client_ip,
            success=True,
            user_role=session.get('role'),
            action_details=f"Reset password for user '{username}' and set must_change_password flag",
            user_agent=user_agent,
            session_id=session_id
        )

        print(json.dumps({'success': True, 'message': 'Password changed successfully. User must change password on next login.'}))
    except Exception as e:
        handle_error(f"Failed to change password for {username}", {
            'session_user': session['username'],
            'target_user': username
        })

def handle_logout_user(form, session, client_ip, user_agent, session_id):
    """Handle POST logout_user action - force logout another user"""
    username = form.getvalue('username', '').strip()

    if not username:
        print(json.dumps({'success': False, 'error': 'Username required'}))
        return

    # Prevent logging out yourself
    if username == session['username']:
        print(json.dumps({'success': False, 'error': 'Cannot logout your own account. Use the logout button instead.'}))
        return

    # Check if user exists
    try:
        conn = get_audit_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM users WHERE username = ?", (username,))
        user_row = cursor.fetchone()
        conn.close()

        if not user_row:
            print(json.dumps({'success': False, 'error': 'User not found'}))
            return

        # Delete all sessions for this user from Redis
        deleted_sessions = delete_user_sessions(username)

        # Log user logout action
        log_user_activity(
            username=session['username'],
            action_type='logout_user',
            ip_address=client_ip,
            success=True,
            user_role=session.get('role'),
            action_details=f"Logged out user '{username}' (deleted {deleted_sessions} session(s))",
            user_agent=user_agent,
            session_id=session_id
        )

        print(json.dumps({'success': True, 'message': f'User logged out successfully. Deleted {deleted_sessions} active session(s).'}))
    except Exception as e:
        handle_error(f"Failed to logout user {username}", {
            'session_user': session['username'],
            'target_user': username
        })

if __name__ == '__main__':
    main()
