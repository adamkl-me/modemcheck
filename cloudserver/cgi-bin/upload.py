#!/usr/bin/env python3
import cgi
import json
import os
import sys
from pathlib import Path
from datetime import datetime

# API keys storage file
API_KEYS_FILE = Path("/modemcheck-cloud/config/api_keys.json")

def load_api_keys():
    """Load API keys from storage"""
    if not API_KEYS_FILE.exists():
        return {}

    try:
        with open(API_KEYS_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def validate_api_key(api_key):
    """Validate if the API key is valid and active"""
    api_keys = load_api_keys()

    if api_key not in api_keys:
        return False, "Invalid API key"

    key_data = api_keys[api_key]

    if not key_data.get('active', True):
        return False, "API key is inactive"

    # Update last used timestamp
    key_data['last_used'] = datetime.now().isoformat()
    api_keys[api_key] = key_data

    # Save updated API keys
    try:
        API_KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(API_KEYS_FILE, 'w') as f:
            json.dump(api_keys, f, indent=2)
    except:
        pass  # Non-critical if we can't update last_used

    return True, key_data.get('name', 'Unknown')

def handle_upload():
    """Handle file upload with multipart form data"""
    # Parse multipart form data
    form = cgi.FieldStorage()

    # Extract fields
    api_key = form.getvalue('api_key', '')
    modem_id = form.getvalue('modem_id', '')
    filename = form.getvalue('filename', '')

    # Validate API key
    is_valid, message = validate_api_key(api_key)
    if not is_valid:
        print("Status: 401 Unauthorized")
        print("Content-Type: application/json")
        print()
        print(json.dumps({'success': False, 'error': message}))
        return

    # Validate required fields
    if not modem_id or not filename:
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

    try:
        with open(file_path, 'wb') as f:
            f.write(file_data)

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
