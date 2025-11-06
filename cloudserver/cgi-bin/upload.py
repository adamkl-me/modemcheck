#!/usr/bin/env python3
import cgi
import json
import os
import sys
import hashlib
import time
from pathlib import Path
from datetime import datetime

# Import audit logging and file locking utilities
sys.path.insert(0, '/modemcheck-cloud/cgi-bin')
try:
    from audit_schema import log_client_submission
except ImportError:
    def log_client_submission(*args, **kwargs):
        pass

try:
    from file_lock_util import load_json_safe, update_json_safe
except ImportError:
    # Fallback to non-locking implementation if module not available
    def load_json_safe(filepath, default=None):
        if default is None:
            default = {}
        if not filepath.exists():
            return default
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError):
            return default
    
    def update_json_safe(filepath, update_func):
        try:
            with open(filepath, 'r+') as f:
                data = json.load(f)
                update_func(data)
                f.seek(0)
                f.truncate()
                json.dump(data, f, indent=2)
            return True
        except (IOError, json.JSONDecodeError):
            return False

# API keys storage file
API_KEYS_FILE = Path("/modemcheck-cloud/config/api_keys.json")

def load_api_keys():
    """Load API keys from storage (with file locking)"""
    return load_json_safe(API_KEYS_FILE, default={})

def validate_api_key(api_key):
    """Validate if the API key is valid and active (timing-safe comparison)"""
    import secrets
    
    api_keys = load_api_keys()

    # Timing-safe comparison: check all keys even after finding a match
    found_key = None
    for stored_key in api_keys:
        if secrets.compare_digest(api_key, stored_key):
            found_key = stored_key
            break
    
    if found_key is None:
        return False, "Invalid API key"

    key_data = api_keys[found_key]

    if not key_data.get('active', True):
        return False, "API key is inactive"

    # Update last used timestamp with file locking
    def update_last_used(data):
        if found_key in data:
            data[found_key]['last_used'] = datetime.now().isoformat()
    
    if not update_json_safe(API_KEYS_FILE, update_last_used):
        # Non-critical if we can't update last_used timestamp
        print(f"Warning: Failed to update API key last_used timestamp", file=sys.stderr)

    return True, key_data.get('name', 'Unknown')

def handle_upload():
    """Handle file upload with multipart form data"""
    start_time = time.time()
    
    # Get client info for logging
    client_ip = os.environ.get('HTTP_CF_CONNECTING_IP') or \
               os.environ.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or \
               os.environ.get('REMOTE_ADDR', 'unknown')
    user_agent = os.environ.get('HTTP_USER_AGENT', 'unknown')
    
    # Parse multipart form data
    form = cgi.FieldStorage()

    # Extract fields
    api_key = form.getvalue('api_key', '')
    modem_id = form.getvalue('modem_id', '')
    filename = form.getvalue('filename', '')

    # Create API key hash for logging (privacy-preserving)
    api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16] if api_key else 'none'

    # Validate API key
    is_valid, key_name = validate_api_key(api_key)
    if not is_valid:
        # Log failed submission
        log_client_submission(
            ip_address=client_ip,
            api_key_hash=api_key_hash,
            modem_id=modem_id or 'unknown',
            filename=filename or 'unknown',
            success=False,
            failure_reason='Invalid or inactive API key',
            user_agent=user_agent
        )
        print("Status: 401 Unauthorized")
        print("Content-Type: application/json")
        print()
        print(json.dumps({'success': False, 'error': key_name}))
        return

    # Validate required fields
    if not modem_id or not filename:
        log_client_submission(
            ip_address=client_ip,
            api_key_hash=api_key_hash,
            api_key_name=key_name,
            modem_id=modem_id or 'unknown',
            filename=filename or 'unknown',
            success=False,
            failure_reason='Missing modem_id or filename',
            user_agent=user_agent
        )
        print("Status: 400 Bad Request")
        print("Content-Type: application/json")
        print()
        print(json.dumps({'success': False, 'error': 'Missing modem_id or filename'}))
        return

    # SECURITY: Validate modem_id and filename to prevent path traversal
    # Only allow alphanumeric, hyphens, underscores, and dots
    import re
    if not re.match(r'^[a-zA-Z0-9_-]+$', modem_id):
        print("Status: 400 Bad Request")
        print("Content-Type: application/json")
        print()
        print(json.dumps({'success': False, 'error': 'Invalid modem_id format'}))
        return

    # Filename should match: YYYY-MM-DD_HH-MM-SS.json
    if not re.match(r'^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.json$', filename):
        print("Status: 400 Bad Request")
        print("Content-Type: application/json")
        print()
        print(json.dumps({'success': False, 'error': 'Invalid filename format'}))
        return

    # Get file data
    if 'file' not in form:
        print("Status: 400 Bad Request")
        print("Content-Type: application/json")
        print()
        print(json.dumps({'success': False, 'error': 'No file provided'}))
        return

    file_item = form['file']
    if not file_item.file:
        print("Status: 400 Bad Request")
        print("Content-Type: application/json")
        print()
        print(json.dumps({'success': False, 'error': 'Invalid file data'}))
        return

    # Create directory structure
    datafiles_dir = Path("/modemcheck-cloud/datafiles")
    modem_dir = datafiles_dir / modem_id

    try:
        modem_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print("Status: 500 Internal Server Error")
        print("Content-Type: application/json")
        print()
        print(json.dumps({'success': False, 'error': f'Failed to create directory: {str(e)}'}))
        return

    # SECURITY: Limit file size to 10MB to prevent DoS
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    file_data = file_item.file.read(MAX_FILE_SIZE + 1)

    if len(file_data) > MAX_FILE_SIZE:
        print("Status: 413 Payload Too Large")
        print("Content-Type: application/json")
        print()
        print(json.dumps({'success': False, 'error': 'File size exceeds 10MB limit'}))
        return

    # Save file
    file_path = modem_dir / filename

    # Check if file already exists
    if file_path.exists():
        log_client_submission(
            ip_address=client_ip,
            api_key_hash=api_key_hash,
            api_key_name=key_name,
            modem_id=modem_id,
            filename=filename,
            success=False,
            failure_reason='File already exists',
            user_agent=user_agent
        )
        print("Status: 409 Conflict")
        print("Content-Type: application/json")
        print()
        print(json.dumps({'success': False, 'error': 'File already exists'}))
        return

    try:
        with open(file_path, 'wb') as f:
            f.write(file_data)

        # Calculate processing time
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        # Extract info for audit log (parse JSON for metadata only)
        modem_type = None
        modem_mac = None
        check_time = None
        
        try:
            json_data = json.loads(file_data.decode('utf-8'))
            if 'sysinfo' in json_data:
                modem_type = json_data['sysinfo'].get('modemtype', 'unknown')
                modem_mac = json_data['sysinfo'].get('modemmac', 'unknown')
                check_time = json_data['sysinfo'].get('checktime')
        except Exception as parse_error:
            # JSON parsing failed - log with unknown metadata
            print(f"[WARN] Failed to parse JSON for audit log: {parse_error}", file=sys.stderr)
        
        # Log successful submission
        log_client_submission(
            ip_address=client_ip,
            api_key_hash=api_key_hash,
            api_key_name=key_name,
            modem_id=modem_id,
            modem_type=modem_type,
            modem_mac=modem_mac,
            filename=filename,
            file_size=len(file_data),
            check_time=check_time,
            user_agent=user_agent,
            success=True,
            processing_time_ms=processing_time_ms
        )

        # Success response
        print("Content-Type: application/json")
        print()
        print(json.dumps({
            'success': True,
            'message': 'File uploaded successfully',
            'path': f'/datafiles/{modem_id}/{filename}',
            'size': file_path.stat().st_size
        }))
    except Exception as e:
        print("Status: 500 Internal Server Error")
        print("Content-Type: application/json")
        print()
        print(json.dumps({'success': False, 'error': f'Failed to save file: {str(e)}'}))

# Main execution
try:
    handle_upload()
except Exception as e:
    print("Status: 500 Internal Server Error")
    print("Content-Type: application/json")
    print()
    print(json.dumps({'success': False, 'error': f'Unexpected error: {str(e)}'}))
    sys.exit(1)
