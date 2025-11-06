#!/usr/bin/env python3
import cgi
import cgitb
import json
import os
import sys
import secrets
import hashlib
import time
from datetime import datetime, timedelta
from pathlib import Path

cgitb.enable()

# Import audit logging and file locking utilities
sys.path.insert(0, '/modemcheck-cloud/cgi-bin')
try:
    from audit_schema import log_user_activity
except ImportError:
    # Fallback if audit module not available
    def log_user_activity(*args, **kwargs):
        pass

try:
    from file_lock_util import load_json_safe, save_json_safe, update_json_safe
except ImportError:
    # Fallback implementations
    def load_json_safe(filepath, default=None):
        if default is None:
            default = {}
        filepath = Path(filepath)
        if not filepath.exists():
            return default
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError):
            return default
    
    def save_json_safe(filepath, data):
        try:
            filepath = Path(filepath)
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            return True
        except IOError:
            return False
    
    def update_json_safe(filepath, update_func):
        try:
            filepath = Path(filepath)
            with open(filepath, 'r+') as f:
                data = json.load(f)
                update_func(data)
                f.seek(0)
                f.truncate()
                json.dump(data, f, indent=2)
            return True
        except (IOError, json.JSONDecodeError):
            return False

USER_DB_PATH = Path('/modemcheck-cloud/config/users.json')
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

def load_users():
    """Load user database (with file locking)"""
    users = load_json_safe(USER_DB_PATH, default={})
    
    # Create default admin user if no users exist
    if not users:
        default_users = {
            'admin': {
                'password': hash_password('changeme'),
                'role': 'admin',
                'created': datetime.now().isoformat(),
                'must_change_password': True
            }
        }
        save_users(default_users)
        return default_users
    
    return users

def save_users(users):
    """Save user database (with file locking)"""
    save_json_safe(USER_DB_PATH, users)

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
            
            users = load_users()
            if username not in users:
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
            
            user = users[username]
            if not verify_password(password, user['password']):
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
            
            # Update last login info
            user['last_login'] = datetime.now().isoformat()
            user['last_login_ip'] = client_ip
            save_users(users)
            
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
                'must_change_password': user.get('must_change_password', False)
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
            
            users = load_users()
            if session['username'] in users:
                users[session['username']]['password'] = hash_password(new_password)
                users[session['username']]['must_change_password'] = False
                save_users(users)
                
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
            else:
                print()
                print(json.dumps({'success': False, 'error': 'User not found'}))
        
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
            # Get user's must_change_password flag
            users = load_users()
            user = users.get(session['username'], {})
            
            print(json.dumps({
                'authenticated': True,
                'username': session['username'],
                'role': session['role'],
                'must_change_password': user.get('must_change_password', False)
            }))
        else:
            print(json.dumps({'authenticated': False}))

if __name__ == '__main__':
    main()
