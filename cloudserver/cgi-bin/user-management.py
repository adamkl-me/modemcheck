#!/usr/bin/env python3
import cgi
import cgitb
import json
import os
import sys

cgitb.enable()

# Import from auth.py
sys.path.insert(0, '/modemcheck-cloud/cgi-bin')
from auth import (load_users, save_users, hash_password, verify_session, get_cookie)

USER_DB_PATH = '/modemcheck-cloud/config/users.json'

def main():
    print("Content-Type: application/json")
    
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
            
            users[username] = {
                'password': hash_password(password),
                'role': role,
                'created': datetime.now().isoformat(),
                'must_change_password': True
            }

            save_users(users)
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
            
            del users[username]
            save_users(users)
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
            print(json.dumps({'success': True, 'message': 'Password changed successfully'}))
        
        else:
            print(json.dumps({'success': False, 'error': 'Invalid action'}))

if __name__ == '__main__':
    from datetime import datetime
    main()
