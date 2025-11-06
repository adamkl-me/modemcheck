#!/usr/bin/env python3
import json
import os
import sys
import secrets
from datetime import datetime
from pathlib import Path

# Import audit logging
sys.path.insert(0, '/modemcheck-cloud/cgi-bin')
try:
    from audit_schema import log_user_activity
except ImportError:
    def log_user_activity(*args, **kwargs):
        pass

# API keys storage file
API_KEYS_FILE = Path("/modemcheck-cloud/config/api_keys.json")
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

def load_api_keys():
    """Load API keys from storage"""
    if not API_KEYS_FILE.exists():
        return {}

    try:
        with open(API_KEYS_FILE, 'r') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError) as e:
        print(f"Error loading API keys: {e}", file=sys.stderr)
        return {}

def save_api_keys(api_keys):
    """Save API keys to storage"""
    try:
        API_KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(API_KEYS_FILE, 'w') as f:
            json.dump(api_keys, f, indent=2)
        return True
    except Exception as e:
        return False

def generate_api_key():
    """Generate a secure random API key"""
    return secrets.token_urlsafe(32)

def list_keys():
    """List all API keys (without exposing the full key)"""
    api_keys = load_api_keys()
    result = []

    for key, data in api_keys.items():
        result.append({
            'key_preview': key[:8] + '...' + key[-4:],  # Show first 8 and last 4 chars
            'full_key': key,  # Include full key for copying
            'name': data.get('name', ''),
            'created': data.get('created', ''),
            'last_used': data.get('last_used', 'Never'),
            'active': data.get('active', True)
        })

    return sorted(result, key=lambda x: x['created'], reverse=True)

def create_key(name):
    """Create a new API key"""
    if not name or len(name.strip()) == 0:
        return None, "Name is required"

    api_keys = load_api_keys()
    new_key = generate_api_key()

    api_keys[new_key] = {
        'name': name.strip(),
        'created': datetime.now().isoformat(),
        'last_used': None,
        'active': True
    }

    if save_api_keys(api_keys):
        return new_key, None
    else:
        return None, "Failed to save API key"

def update_key(key, name, active):
    """Update an existing API key"""
    api_keys = load_api_keys()

    if key not in api_keys:
        return False, "API key not found"

    if name is not None:
        api_keys[key]['name'] = name.strip()

    if active is not None:
        api_keys[key]['active'] = active

    if save_api_keys(api_keys):
        return True, None
    else:
        return False, "Failed to update API key"

def delete_key(key):
    """Delete an API key"""
    api_keys = load_api_keys()

    if key not in api_keys:
        return False, "API key not found"

    del api_keys[key]

    if save_api_keys(api_keys):
        return True, None
    else:
        return False, "Failed to delete API key"

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
        
        # Get key name before deleting
        api_keys = load_api_keys()
        key_name = api_keys.get(key, {}).get('name', 'unknown')
        
        success, error = delete_key(key)
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

    else:
        result = {'success': False, 'error': 'Unknown action'}

    print(json.dumps(result, indent=2))

except Exception as e:
    print(json.dumps({'success': False, 'error': str(e)}))
    sys.exit(1)
