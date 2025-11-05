#!/usr/bin/env python3
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Set content type for JSON
print("Content-Type: application/json")
print("Access-Control-Allow-Origin: *")
print()

def list_modems():
    """List all modem directories"""
    datafiles_dir = Path("/modemcheck-cloud/datafiles")
    modems = []
    
    if datafiles_dir.exists():
        for item in datafiles_dir.iterdir():
            if item.is_dir():
                # Extract modem type and MAC from directory name
                # Format: ModemType-MAC (e.g., DM1000-64677213D56A)
                dir_name = item.name
                parts = dir_name.split('-', 1)
                if len(parts) == 2:
                    modems.append({
                        'id': dir_name,
                        'type': parts[0],
                        'mac': parts[1],
                        'display': dir_name
                    })
    
    return sorted(modems, key=lambda x: x['display'])

def list_files(modem_id, start_date=None, end_date=None):
    """List JSON files for a specific modem, optionally filtered by date range"""
    # SECURITY: Validate modem_id to prevent path traversal
    import re
    if not modem_id or not re.match(r'^[a-zA-Z0-9_-]+$', modem_id):
        return []

    # SECURITY: Validate date format if provided
    if start_date and not re.match(r'^\d{4}-\d{2}-\d{2}$', start_date):
        return []
    if end_date and not re.match(r'^\d{4}-\d{2}-\d{2}$', end_date):
        return []

    datafiles_dir = Path("/modemcheck-cloud/datafiles") / modem_id
    files = []

    if datafiles_dir.exists():
        for item in datafiles_dir.glob("*.json"):
            # Parse filename: YYYY-MM-DD_HH-MM-SS.json
            filename = item.stem
            try:
                file_date = datetime.strptime(filename, "%Y-%m-%d_%H-%M-%S")

                # Apply date filters if provided
                if start_date:
                    start = datetime.strptime(start_date, "%Y-%m-%d")
                    if file_date.date() < start.date():
                        continue

                if end_date:
                    end = datetime.strptime(end_date, "%Y-%m-%d")
                    if file_date.date() > end.date():
                        continue
                
                files.append({
                    'filename': item.name,
                    'timestamp': filename,
                    'date': file_date.strftime("%Y-%m-%d %H:%M:%S"),
                    'size': item.stat().st_size
                })
            except ValueError:
                # Skip files that don't match the expected format
                continue
    
    return sorted(files, key=lambda x: x['timestamp'], reverse=True)

def get_file_content(modem_id, filename):
    """Get the content of a specific JSON file"""
    # SECURITY: Validate inputs to prevent path traversal
    import re
    if not modem_id or not re.match(r'^[a-zA-Z0-9_-]+$', modem_id):
        return None
    if not filename or not re.match(r'^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.json$', filename):
        return None

    file_path = Path("/modemcheck-cloud/datafiles") / modem_id / filename

    # SECURITY: Verify resolved path is still within datafiles directory
    datafiles_dir = Path("/modemcheck-cloud/datafiles")
    try:
        resolved_path = file_path.resolve()
        if not str(resolved_path).startswith(str(datafiles_dir.resolve())):
            return None
    except:
        return None

    if file_path.exists() and file_path.is_file():
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except:
            return None

    return None

# Parse query string
query_string = os.environ.get('QUERY_STRING', '')
params = dict(param.split('=') if '=' in param else (param, '') 
              for param in query_string.split('&') if param)

action = params.get('action', 'list_modems')

try:
    if action == 'list_modems':
        result = {'modems': list_modems()}
    elif action == 'list_files':
        modem_id = params.get('modem_id', '')
        start_date = params.get('start_date')
        end_date = params.get('end_date')
        result = {'files': list_files(modem_id, start_date, end_date)}
    elif action == 'get_file':
        modem_id = params.get('modem_id', '')
        filename = params.get('filename', '')
        content = get_file_content(modem_id, filename)
        if content:
            result = {'success': True, 'data': content}
        else:
            result = {'success': False, 'error': 'File not found'}
    else:
        result = {'error': 'Unknown action'}
    
    print(json.dumps(result, indent=2))
except Exception as e:
    print(json.dumps({'error': str(e)}))
    sys.exit(1)
