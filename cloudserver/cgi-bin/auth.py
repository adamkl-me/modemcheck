#!/usr/bin/env python3
import cgi
import cgitb
import json
import os
import sys
import secrets
import hashlib
import time
import sqlite3
from datetime import datetime, timedelta

cgitb.enable()

# Import audit logging and database access
sys.path.insert(0, '/modemcheck-cloud/cgi-bin')
try:
    from audit_schema import log_user_activity, get_audit_connection
except ImportError:
    def log_user_activity(*args, **kwargs):
        pass
    def get_audit_connection():
        raise ImportError("audit_schema not available")

SESSION_DIR = '/modemcheck-cloud/config/sessions'

def hash_password(password, salt=None):
    """Hash password with salt"""
    if salt is None:
        salt = secrets.token_hex(32)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
    return salt + ':' + pwd_hash.hex()

def verify_password(password, stored_hash):
    """Verify password against stored hash"""
    try:
        salt, pwd_hash = stored_hash.split(':')
        new_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
        return new_hash.hex() == pwd_hash
    except:
        return False

def ensure_default_admin():
    """Ensure default admin user exists in database"""
    try:
        conn = get_audit_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM users")
        user_count = cursor.fetchone()['count']
        
        if user_count == 0:
            # Create default admin user with full permissions
            cursor.execute("""
                INSERT INTO users (username, password_hash, role, created_at, must_change_password)
                VALUES (?, ?, 'admin', ?, 1)
            """, ('admin', hash_password('changeme'), datetime.now().isoformat()))
            conn.commit()
        
        conn.close()
    except Exception as e:
        print(f"Error ensuring default admin: {e}", file=sys.stderr)

def create_session(username, role):
    """Create a new session"""
    os.makedirs(SESSION_DIR, exist_ok=True)
    session_id = secrets.token_urlsafe(32)
    session_data = {
        'username': username,
        'role': role,
        'created': datetime.now().isoformat(),
        'expires': (datetime.now() + timedelta(hours=12)).isoformat()
    }
    session_file = os.path.join(SESSION_DIR, session_id + '.json')
    with open(session_file, 'w') as f:
        json.dump(session_data, f)
    return session_id

def verify_session(session_id):
    """Verify session and return user info"""
    if not session_id:
        return None
    session_file = os.path.join(SESSION_DIR, session_id + '.json')
    if not os.path.exists(session_file):
        return None
    
    with open(session_file, 'r') as f:
        session_data = json.load(f)
    
    # Check expiration
    expires = datetime.fromisoformat(session_data['expires'])
    if datetime.now() > expires:
        os.remove(session_file)
        return None
    
    return session_data

def delete_session(session_id):
    """Delete a session"""
    if not session_id:
        return
    session_file = os.path.join(SESSION_DIR, session_id + '.json')
    if os.path.exists(session_file):
        os.remove(session_file)

def delete_user_sessions(username):
    """Delete all sessions for a specific user"""
    if not os.path.exists(SESSION_DIR):
        return 0
    
    deleted_count = 0
    for filename in os.listdir(SESSION_DIR):
        if filename.endswith('.json'):
            session_file = os.path.join(SESSION_DIR, filename)
            try:
                with open(session_file, 'r') as f:
                    session_data = json.load(f)
                if session_data.get('username') == username:
                    os.remove(session_file)
                    deleted_count += 1
            except (IOError, json.JSONDecodeError, OSError):
                pass  # Skip files that can't be read or deleted
    return deleted_count

def get_cookie(name):
    """Get cookie value from environment"""
    cookie_string = os.environ.get('HTTP_COOKIE', '')
    cookies = {}
    for cookie in cookie_string.split(';'):
        if '=' in cookie:
            key, value = cookie.strip().split('=', 1)
            cookies[key] = value
    return cookies.get(name)

def main():
    print("Content-Type: application/json")
    
    request_method = os.environ.get('REQUEST_METHOD', 'GET')
    
    if request_method == 'POST':
        # Handle login
        form = cgi.FieldStorage()
        action = form.getvalue('action', 'login')
        
        if action == 'login':
            username = form.getvalue('username', '').strip()
            password = form.getvalue('password', '')
            
            if not username or not password:
                print()
                print(json.dumps({'success': False, 'error': 'Username and password required'}))
                return
            
            # Get client info for logging
            client_ip = os.environ.get('HTTP_CF_CONNECTING_IP') or \
                       os.environ.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or \
                       os.environ.get('REMOTE_ADDR', 'unknown')
            user_agent = os.environ.get('HTTP_USER_AGENT', 'unknown')
            
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
            if not verify_password(password, user['password_hash']):
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
            
            # Update last login info in database
            cursor.execute("""
                UPDATE users 
                SET last_login = ?, last_login_ip = ? 
                WHERE username = ?
            """, (datetime.now().isoformat(), client_ip, username))
            conn.commit()
            conn.close()
            
            # Create session
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
            
            # Set cookie (12 hours)
            print(f"Set-Cookie: modemcheck_session={session_id}; Path=/; Max-Age=43200; HttpOnly; SameSite=Strict")
            print()
            print(json.dumps({
                'success': True,
                'username': username,
                'role': user['role'],
                'must_change_password': bool(user.get('must_change_password', False))
            }))
        
        elif action == 'change_own_password':
            # Allow user to change their own password
            session_id = get_cookie('modemcheck_session')
            session = verify_session(session_id)
            
            client_ip = os.environ.get('HTTP_CF_CONNECTING_IP') or \
                       os.environ.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or \
                       os.environ.get('REMOTE_ADDR', 'unknown')
            user_agent = os.environ.get('HTTP_USER_AGENT', 'unknown')
            
            if not session:
                print()
                print(json.dumps({'success': False, 'error': 'Not authenticated'}))
                return
            
            new_password = form.getvalue('new_password', '')
            
            if not new_password or len(new_password) < 6:
                print()
                print(json.dumps({'success': False, 'error': 'Password must be at least 6 characters'}))
                return
            
            try:
                conn = get_audit_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE users 
                    SET password_hash = ?, must_change_password = 0 
                    WHERE username = ?
                """, (hash_password(new_password), session['username']))
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
                print()
                print(json.dumps({'success': False, 'error': 'Database error'}))
        
        elif action == 'logout':
            session_id = get_cookie('modemcheck_session')
            session = verify_session(session_id)
            
            client_ip = os.environ.get('HTTP_CF_CONNECTING_IP') or \
                       os.environ.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or \
                       os.environ.get('REMOTE_ADDR', 'unknown')
            user_agent = os.environ.get('HTTP_USER_AGENT', 'unknown')
            
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
    
    elif request_method == 'GET':
        # Check session
        session_id = get_cookie('modemcheck_session')
        session = verify_session(session_id)
        
        print()
        if session:
            # Get user data from database to check must_change_password flag
            try:
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
                print(json.dumps({
                    'authenticated': True,
                    'username': session['username'],
                    'role': session.get('role'),
                    'must_change_password': False
                }))
        else:
            print(json.dumps({'authenticated': False}))

if __name__ == '__main__':
    main()
