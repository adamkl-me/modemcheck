#!/usr/bin/env python3
import json
import os
import sys
import secrets
import sqlite3
from datetime import datetime

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

def get_cookie(name):
    """Get cookie value from environment"""
    cookie_string = os.environ.get('HTTP_COOKIE', '')
    cookies = {}
    for cookie in cookie_string.split(';'):
        if '=' in cookie:
            key, value = cookie.strip().split('=', 1)
            cookies[key] = value
    return cookies.get(name)

def generate_api_key():
    """Generate a secure random API key"""
    return secrets.token_urlsafe(32)

def list_keys():
    """List all API keys from database"""
    try:
        conn = get_audit_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT api_key, name, created_at, last_used, is_active 
            FROM api_keys 
            ORDER BY created_at DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        
        result = []
        for row in rows:
            result.append({
                'key_preview': row['api_key'][:8] + '...' + row['api_key'][-4:],
                'full_key': row['api_key'],
                'name': row['name'],
                'created': row['created_at'],
                'last_used': row['last_used'] or 'Never',
                'active': bool(row['is_active'])
            })
        
        return result
    except Exception as e:
        print(f"Error listing API keys: {e}", file=sys.stderr)
        return []

def create_key(name):
    """Create a new API key in database"""
    if not name or len(name.strip()) == 0:
        return None, "Name is required"

    try:
        conn = get_audit_connection()
        cursor = conn.cursor()
        new_key = generate_api_key()
        
        cursor.execute("""
            INSERT INTO api_keys (api_key, name, created_at, is_active)
            VALUES (?, ?, ?, 1)
        """, (new_key, name.strip(), datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
        return new_key, None
    except Exception as e:
        print(f"Error creating API key: {e}", file=sys.stderr)
        if 'conn' in locals():
            conn.close()
        return None, f"Failed to create API key: {str(e)}"

def update_key(key, name, active):
    """Update an existing API key in database"""
    try:
        conn = get_audit_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE api_keys 
            SET name = ?, is_active = ? 
            WHERE api_key = ?
        """, (name.strip(), 1 if active else 0, key))
        
        conn.commit()
        
        if cursor.rowcount == 0:
            conn.close()
            return False, "API key not found"
        
        conn.close()
        return True, None
    except Exception as e:
        print(f"Error updating API key: {e}", file=sys.stderr)
        if 'conn' in locals():
            conn.close()
        return False, f"Failed to update API key: {str(e)}"

def delete_key(key):
    """Delete an API key from database"""
    try:
        conn = get_audit_connection()
        cursor = conn.cursor()
        
        # Get key name for logging before deletion
        cursor.execute("SELECT name FROM api_keys WHERE api_key = ?", (key,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False, "API key not found", "unknown"
        
        key_name = row['name']
        
        cursor.execute("DELETE FROM api_keys WHERE api_key = ?", (key,))
        conn.commit()
        conn.close()
        
        return True, None, key_name
    except Exception as e:
        print(f"Error deleting API key: {e}", file=sys.stderr)
        if 'conn' in locals():
            conn.close()
        return False, f"Failed to delete API key: {str(e)}", "unknown"

# AUTHENTICATION CHECK - Admin role required
session_id = get_cookie('modemcheck_session')
session = verify_session(session_id)

# Set response headers
print("Content-Type: application/json")
print()

# Require authentication and admin role
if not session or session.get('role') != 'admin':
    print(json.dumps({'success': False, 'error': 'Unauthorized - Admin access required'}))
    sys.exit(1)

# Handle CORS preflight
if os.environ.get('REQUEST_METHOD') == 'OPTIONS':
    print(json.dumps({'success': True}))
    sys.exit(0)

# Parse query string for GET requests
query_string = os.environ.get('QUERY_STRING', '')
params = dict(param.split('=', 1) if '=' in param else (param, '')
              for param in query_string.split('&') if param)

# Parse POST data for POST/PUT/DELETE requests
request_method = os.environ.get('REQUEST_METHOD', 'GET')
post_data = {}

if request_method in ['POST', 'PUT', 'DELETE']:
    try:
        content_length = int(os.environ.get('CONTENT_LENGTH', 0))
        if content_length > 0:
            post_body = sys.stdin.read(content_length)
            post_data = json.loads(post_body)
    except:
        pass

action = params.get('action', post_data.get('action', 'list'))

# Get client info for logging
client_ip = os.environ.get('HTTP_CF_CONNECTING_IP') or \
           os.environ.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or \
           os.environ.get('REMOTE_ADDR', 'unknown')
user_agent = os.environ.get('HTTP_USER_AGENT', 'unknown')

try:
    if action == 'list':
        result = {'success': True, 'keys': list_keys()}

    elif action == 'create':
        name = post_data.get('name', '')
        key, error = create_key(name)
        if error:
            result = {'success': False, 'error': error}
        else:
            # Log API key creation
            log_user_activity(
                username=session['username'],
                action_type='create_api_key',
                ip_address=client_ip,
                success=True,
                user_role=session.get('role'),
                action_details=f"Created API key '{name}'",
                user_agent=user_agent,
                session_id=session_id
            )
            result = {'success': True, 'key': key, 'message': 'API key created successfully'}

    elif action == 'update':
        key = post_data.get('key', '')
        name = post_data.get('name')
        active = post_data.get('active')

        success, error = update_key(key, name, active)
        if error:
            result = {'success': False, 'error': error}
        else:
            result = {'success': True, 'message': 'API key updated successfully'}

    elif action == 'delete':
        key = post_data.get('key', params.get('key', ''))
        
        success, error, key_name = delete_key(key)
        if error:
            result = {'success': False, 'error': error}
        else:
            # Log API key deletion
            log_user_activity(
                username=session['username'],
                action_type='delete_api_key',
                ip_address=client_ip,
                success=True,
                user_role=session.get('role'),
                action_details=f"Deleted API key '{key_name}'",
                user_agent=user_agent,
                session_id=session_id
            )
            result = {'success': True, 'message': 'API key deleted successfully'}
    
    elif action == 'get_user_activity_logs':
        # Import audit schema
        sys.path.insert(0, '/modemcheck-cloud/cgi-bin')
        from audit_schema import get_user_activity_logs, get_user_activity_stats
        
        limit = int(params.get('limit', post_data.get('limit', 100)))
        username = params.get('username', post_data.get('username'))
        action_type = params.get('action_type', post_data.get('action_type'))
        start_date = params.get('start_date', post_data.get('start_date'))
        end_date = params.get('end_date', post_data.get('end_date'))
        ip_address = params.get('ip_address', post_data.get('ip_address'))
        
        logs = get_user_activity_logs(limit, username, action_type, start_date, end_date, ip_address)
        stats = get_user_activity_stats()
        
        result = {
            'success': True, 
            'logs': logs,
            'stats': stats,
            'count': len(logs)
        }
    
    elif action == 'get_client_submission_logs':
        # Import audit schema
        sys.path.insert(0, '/modemcheck-cloud/cgi-bin')
        from audit_schema import get_client_submission_logs, get_client_submission_stats
        
        limit = int(params.get('limit', post_data.get('limit', 100)))
        api_key_hash = params.get('api_key_hash', post_data.get('api_key_hash'))
        modem_id = params.get('modem_id', post_data.get('modem_id'))
        start_date = params.get('start_date', post_data.get('start_date'))
        end_date = params.get('end_date', post_data.get('end_date'))
        ip_address = params.get('ip_address', post_data.get('ip_address'))
        
        logs = get_client_submission_logs(limit, api_key_hash, modem_id, start_date, end_date, ip_address)
        stats = get_client_submission_stats()
        
        result = {
            'success': True,
            'logs': logs,
            'stats': stats,
            'count': len(logs)
        }
    
    elif action == 'list_users':
        # Get list of users
        try:
            conn = get_audit_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT username, role, created_at, must_change_password 
                FROM users 
                ORDER BY username
            """)
            users = []
            for row in cursor.fetchall():
                users.append({
                    'username': row['username'],
                    'role': row['role'],
                    'created_at': row['created_at'],
                    'must_change_password': bool(row['must_change_password'])
                })
            conn.close()
            result = {'success': True, 'users': users}
        except Exception as e:
            print(f"Error listing users: {e}", file=sys.stderr)
            if 'conn' in locals():
                conn.close()
            result = {'success': False, 'error': f'Failed to list users: {str(e)}'}
    
    elif action == 'change_role':
        username = post_data.get('username', '')
        new_role = post_data.get('role', '')
        
        if not username or not new_role:
            result = {'success': False, 'error': 'Missing username or role'}
        elif new_role not in ['basic', 'admin']:
            result = {'success': False, 'error': 'Invalid role. Must be "admin" or "basic"'}
        elif username == 'admin':
            result = {'success': False, 'error': 'Cannot change the admin account'}
        elif username == session['username']:
            result = {'success': False, 'error': 'Cannot change your own role'}
        else:
            try:
                conn = get_audit_connection()
                cursor = conn.cursor()
                
                # Check if user exists and get old role
                cursor.execute("SELECT role FROM users WHERE username = ?", (username,))
                user_row = cursor.fetchone()
                
                if not user_row:
                    conn.close()
                    result = {'success': False, 'error': 'User not found'}
                else:
                    old_role = user_row['role']
                    
                    # Update role
                    cursor.execute(
                        "UPDATE users SET role = ? WHERE username = ?",
                        (new_role, username)
                    )
                    conn.commit()
                    conn.close()
                    
                    # Log the action
                    log_user_activity(
                        username=session['username'],
                        action_type='user_role_changed',
                        ip_address=client_ip,
                        success=True,
                        user_role=session.get('role'),
                        action_details=f"Changed {username}'s role from {old_role} to {new_role}",
                        user_agent=user_agent,
                        session_id=session_id
                    )
                    
                    result = {'success': True, 'message': f'Role changed from {old_role} to {new_role}'}
            except Exception as e:
                print(f"Error changing role: {e}", file=sys.stderr)
                if 'conn' in locals():
                    conn.close()
                result = {'success': False, 'error': f'Failed to change role: {str(e)}'}

    else:
        result = {'success': False, 'error': 'Unknown action'}

    print(json.dumps(result, indent=2))

except Exception as e:
    print(json.dumps({'success': False, 'error': str(e)}))
    sys.exit(1)
