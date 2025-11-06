#!/usr/bin/env python3
import cgi
import cgitb
import json
import os
import sys

cgitb.enable()

# Import from auth.py
sys.path.insert(0, '/modemcheck-cloud/cgi-bin')
from auth import (load_users, save_users, hash_password, verify_session, get_cookie, delete_user_sessions)

# Import audit logging
try:
    from audit_schema import log_user_activity
except ImportError:
    def log_user_activity(*args, **kwargs):
        pass

USER_DB_PATH = '/modemcheck-cloud/config/users.json'

def main():
    print("Content-Type: application/json")
    
    # Get client info for logging
    client_ip = os.environ.get('HTTP_CF_CONNECTING_IP') or \
               os.environ.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or \
               os.environ.get('REMOTE_ADDR', 'unknown')
    user_agent = os.environ.get('HTTP_USER_AGENT', 'unknown')
    
    # Check authentication
    session_id = get_cookie('modemcheck_session')
    session = verify_session(session_id)
    
    if not session or session['role'] != 'admin':
        print()
        print(json.dumps({'success': False, 'error': 'Unauthorized'}))
        return
    
    request_method = os.environ.get('REQUEST_METHOD', 'GET')
    form = cgi.FieldStorage()
    
    print()
    
    if request_method == 'GET':
        # List all users (without passwords)
        users = load_users()
        user_list = []
        for username, data in users.items():
            user_list.append({
                'username': username,
                'role': data['role'],
                'created': data.get('created', 'Unknown'),
                'last_login': data.get('last_login', 'Never'),
                'last_login_ip': data.get('last_login_ip', '-')
            })
        print(json.dumps({'success': True, 'users': user_list}))
    
    elif request_method == 'POST':
        action = form.getvalue('action')
        
        if action == 'create':
            username = form.getvalue('username', '').strip()
            password = form.getvalue('password', '')
            role = form.getvalue('role', 'basic')
            
            if not username or not password:
                print(json.dumps({'success': False, 'error': 'Username and password required'}))
                return
            
            if role not in ['basic', 'admin']:
                print(json.dumps({'success': False, 'error': 'Invalid role'}))
                return
            
            users = load_users()
            
            if username in users:
                print(json.dumps({'success': False, 'error': 'User already exists'}))
                return
            
            from datetime import datetime
            
            users[username] = {
                'password': hash_password(password),
                'role': role,
                'created': datetime.now().isoformat(),
                'must_change_password': True
            }

            save_users(users)
            
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
        
        elif action == 'delete':
            username = form.getvalue('username', '').strip()
            
            if not username:
                print(json.dumps({'success': False, 'error': 'Username required'}))
                return
            
            # Prevent deleting own account
            if username == session['username']:
                print(json.dumps({'success': False, 'error': 'Cannot delete your own account'}))
                return
            
            users = load_users()
            
            if username not in users:
                print(json.dumps({'success': False, 'error': 'User not found'}))
                return
            
            deleted_user_role = users[username].get('role', 'unknown')
            del users[username]
            save_users(users)
            
            # Log user deletion
            log_user_activity(
                username=session['username'],
                action_type='delete_user',
                ip_address=client_ip,
                success=True,
                user_role=session.get('role'),
                action_details=f"Deleted user '{username}' (was {deleted_user_role})",
                user_agent=user_agent,
                session_id=session_id
            )
            print(json.dumps({'success': True, 'message': 'User deleted successfully'}))
        
        elif action == 'change_password':
            username = form.getvalue('username', '').strip()
            new_password = form.getvalue('new_password', '')
            
            if not username or not new_password:
                print(json.dumps({'success': False, 'error': 'Username and new password required'}))
                return
            
            users = load_users()
            
            if username not in users:
                print(json.dumps({'success': False, 'error': 'User not found'}))
                return
            
            users[username]['password'] = hash_password(new_password)
            users[username]['must_change_password'] = True
            save_users(users)
            
            # Log password change
            log_user_activity(
                username=session['username'],
                action_type='change_password',
                ip_address=client_ip,
                success=True,
                user_role=session.get('role'),
                action_details=f"Changed password for user '{username}' and set must_change_password flag",
                user_agent=user_agent,
                session_id=session_id
            )
            
            print(json.dumps({'success': True, 'message': 'Password changed successfully. User must change password on next login.'}))
        
        elif action == 'logout_user':
            username = form.getvalue('username', '').strip()
            
            if not username:
                print(json.dumps({'success': False, 'error': 'Username required'}))
                return
            
            # Prevent logging out yourself
            if username == session['username']:
                print(json.dumps({'success': False, 'error': 'Cannot logout your own account. Use the logout button instead.'}))
                return
            
            users = load_users()
            
            if username not in users:
                print(json.dumps({'success': False, 'error': 'User not found'}))
                return
            
            # Delete all sessions for this user
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
        
        else:
            print(json.dumps({'success': False, 'error': 'Invalid action'}))

if __name__ == '__main__':
    from datetime import datetime
    main()
