#!/usr/bin/env python3
"""
Database-backed API for ModemCheck viewer.
Replaces file-system scanning with direct database queries.
"""

import json
import os
import sys
import cgi
from datetime import datetime, timedelta

# Add cgi-bin to path for imports
sys.path.insert(0, '/modemcheck-cloud/cgi-bin')

from db_schema import get_modems, get_checks, get_connection

# Import audit logging
try:
    from audit_schema import log_user_activity
except ImportError:
    def log_user_activity(*args, **kwargs):
        pass

# Import session management from auth.py (Redis-based)
from auth import verify_session, get_cookie, get_client_info

def handle_request():
    """Handle API requests"""
    # Debug: Log request
    import sys
    sys.stderr.write(f"DEBUG db-api: Cookie header: {os.environ.get('HTTP_COOKIE', 'NONE')}\n")
    sys.stderr.flush()

    # Verify authentication
    session_id = get_cookie('modemcheck_session')
    session = verify_session(session_id)

    sys.stderr.write(f"DEBUG db-api: Session result: {session}\n")
    sys.stderr.flush()

    if not session:
        print("Status: 401 Unauthorized")
        print("Content-Type: application/json")
        print()
        print(json.dumps({'error': 'Unauthorized - Please log in'}))
        return
    
    # Parse query string
    params = cgi.FieldStorage()
    action = params.getvalue('action', '')
    
    sys.stderr.write(f"DEBUG db-api: Action requested: '{action}'\n")
    sys.stderr.flush()
    
    if action == 'list_modems':
        handle_list_modems()
    elif action == 'list_files':
        handle_list_files(params)
    elif action == 'get_file':
        handle_get_file(params)
    elif action == 'get_all_checks':
        handle_get_all_checks(params)
    else:
        print("Status: 400 Bad Request")
        print("Content-Type: application/json")
        print()
        print(json.dumps({'error': 'Invalid action'}))

def handle_list_modems():
    """List all modems with their metadata"""
    try:
        modems = get_modems()
        
        # Format response to match original API (array of objects)
        # Original format: {'modems': [{'id': 'XB8-MAC', 'type': 'XB8', 'mac': 'MAC', 'display': 'XB8-MAC'}]}
        modem_list = []
        
        for modem in modems:
            modem_id = modem['modem_id']
            modem_type = modem.get('modem_type', 'unknown')
            file_count = modem.get('total_checks', 0)
            
            # Split modem_id into type and MAC (format: TYPE-MAC)
            parts = modem_id.split('-', 1)
            if len(parts) == 2:
                display_type = parts[0]
                mac = parts[1]
            else:
                display_type = modem_type
                mac = modem_id
            
            modem_list.append({
                'id': modem_id,
                'modem_id': modem_id,  # Add for data management compatibility
                'type': display_type,
                'mac': mac,
                'display': modem_id,
                'file_count': file_count  # Add for data management compatibility
            })
        
        # Sort by display name
        modem_list.sort(key=lambda x: x['display'])
        
        response = {'modems': modem_list}
        
        print("Content-Type: application/json")
        print()
        print(json.dumps(response))
        
    except Exception as e:
        print("Status: 500 Internal Server Error")
        print("Content-Type: application/json")
        print()
        print(json.dumps({'error': f'Database error: {str(e)}'}))

def handle_list_files(params):
    """List files for a specific modem and date range"""
    import sys
    import traceback
    
    try:
        # Accept both 'modem' and 'modem_id' parameter names
        modem_id = params.getvalue('modem_id', params.getvalue('modem', ''))
        # Accept both 'start_date' and 'start' parameter names
        start_date = params.getvalue('start_date', params.getvalue('start', ''))
        end_date = params.getvalue('end_date', params.getvalue('end', ''))
        
        # Log to stderr for debugging
        print(f"DEBUG: list_files called with modem={modem_id}, start={start_date}, end={end_date}", file=sys.stderr)
        
        if not modem_id:
            print("Status: 400 Bad Request")
            print("Content-Type: application/json")
            print()
            print(json.dumps({'error': 'Missing modem parameter'}))
            return
        
        # Query database directly for metadata (don't parse full JSON)
        conn = get_connection()
        cursor = conn.cursor()
        
        query = 'SELECT filename, check_time, length(full_data) as size FROM modem_checks WHERE 1=1'
        params = []
        
        if modem_id:
            query += ' AND modem_id = ?'
            params.append(modem_id)
        
        if start_date:
            # Check_time format is YYYY-MM-DD_HH-MM-SS, so we can use LIKE for date matching
            query += ' AND check_time >= ?'
            params.append(start_date)
        
        if end_date:
            # For end date, add one day and use < to include all times on end_date
            # Or use LIKE pattern to match the date prefix
            query += ' AND check_time < ?'
            # Add one day by appending ~zzz (any char after underscore in ASCII)
            # Actually, simpler: just use the next day's date
            from datetime import datetime, timedelta
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            next_day = end_dt + timedelta(days=1)
            params.append(next_day.strftime('%Y-%m-%d'))
        
        query += ' ORDER BY check_time DESC LIMIT 10000'
        
        cursor.execute(query, params)
        checks = cursor.fetchall()
        conn.close()
        
        print(f"DEBUG: Found {len(checks)} checks", file=sys.stderr)
        
        # Format response to match original API
        # Return list of filenames with timestamps
        files = []
        for check in checks:
            files.append({
                'filename': check['filename'].split('/')[-1],  # Just the filename part
                'timestamp': check['check_time'],
                'size': check['size']
            })
        
        print(f"DEBUG: Returning {len(files)} files", file=sys.stderr)
        
        print("Content-Type: application/json")
        print()
        print(json.dumps({'files': files}))
        
    except Exception as e:
        error_details = traceback.format_exc()
        print(f"DEBUG: Exception in list_files: {error_details}", file=sys.stderr)
        print("Status: 500 Internal Server Error")
        print("Content-Type: application/json")
        print()
        print(json.dumps({'error': f'Database error: {str(e)}', 'details': error_details}))

def handle_get_file(params):
    """Get full data for a specific file"""
    # Accept both 'modem_id' and 'modem' parameter names
    modem_id = params.getvalue('modem_id', params.getvalue('modem', ''))
    # Accept both 'filename' and 'file' parameter names
    filename = params.getvalue('filename', params.getvalue('file', ''))
    
    if not modem_id or not filename:
        print("Status: 400 Bad Request")
        print("Content-Type: application/json")
        print()
        print(json.dumps({'error': 'Missing modem or file parameter'}))
        return
    
    try:
        # Query database for specific file
        conn = get_connection()
        cursor = conn.cursor()
        
        full_filename = f"{modem_id}/{filename}"
        cursor.execute(
            'SELECT full_data FROM modem_checks WHERE filename = ?',
            (full_filename,)
        )
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            print("Content-Type: application/json")
            print()
            print(json.dumps({'success': False, 'error': 'File not found'}))
            return
        
        # Parse the JSON data and wrap it in success response
        data = json.loads(row['full_data'])
        print("Content-Type: application/json")
        print()
        print(json.dumps({'success': True, 'data': data}))
        
    except Exception as e:
        print("Status: 500 Internal Server Error")
        print("Content-Type: application/json")
        print()
        print(json.dumps({'error': f'Database error: {str(e)}'}))

def handle_get_all_checks(params):
    """Get all check data for a modem and date range in a single response"""
    import sys
    import traceback
    
    try:
        # Accept both 'modem_id' and 'modem' parameter names
        modem_id = params.getvalue('modem_id', params.getvalue('modem', ''))
        # Accept both 'start_date' and 'start' parameter names
        start_date = params.getvalue('start_date', params.getvalue('start', ''))
        end_date = params.getvalue('end_date', params.getvalue('end', ''))
        
        print(f"DEBUG: get_all_checks called with modem={modem_id}, start={start_date}, end={end_date}", file=sys.stderr)
        
        if not modem_id:
            print("Status: 400 Bad Request")
            print("Content-Type: application/json")
            print()
            print(json.dumps({'error': 'Missing modem parameter'}))
            return
        
        # Query database using the existing get_checks function
        checks = get_checks(
            modem_id=modem_id,
            start_date=start_date if start_date else None,
            end_date=end_date if end_date else None,
            limit=10000
        )
        
        print(f"DEBUG: Found {len(checks)} checks", file=sys.stderr)
        
        # Extract just the full_data (already parsed as dict) from each check
        all_data = [check['full_data'] for check in checks]
        
        print(f"DEBUG: Returning {len(all_data)} data objects", file=sys.stderr)

        # Log the view action (server-side, invisible to user)
        session_id = get_cookie('modemcheck_session')
        session = verify_session(session_id)
        if session:
            client_ip, user_agent = get_client_info()
            
            # Build action details with date range if specified
            details_parts = [f"Viewed {len(all_data)} check(s) for modem '{modem_id}'"]
            if start_date or end_date:
                date_range = []
                if start_date:
                    date_range.append(f"from {start_date}")
                if end_date:
                    date_range.append(f"to {end_date}")
                details_parts.append(f"Date range: {' '.join(date_range)}")
            
            action_details = ". ".join(details_parts)
            
            log_user_activity(
                username=session['username'],
                action_type='view_checks',
                ip_address=client_ip,
                success=True,
                user_role=session.get('role'),
                action_details=action_details,
                user_agent=user_agent,
                session_id=session_id
            )
        
        print("Content-Type: application/json")
        print()
        print(json.dumps({'success': True, 'checks': all_data}))
        
    except Exception as e:
        error_details = traceback.format_exc()
        print(f"DEBUG: Exception in get_all_checks: {error_details}", file=sys.stderr)
        print("Status: 500 Internal Server Error")
        print("Content-Type: application/json")
        print()
        print(json.dumps({'error': f'Database error: {str(e)}', 'details': error_details}))

# Main execution
try:
    handle_request()
except Exception as e:
    print("Status: 500 Internal Server Error")
    print("Content-Type: application/json")
    print()
    print(json.dumps({'error': f'Unexpected error: {str(e)}'}))
    sys.exit(1)
