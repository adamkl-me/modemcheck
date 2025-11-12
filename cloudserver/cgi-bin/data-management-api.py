#!/usr/bin/env python3
"""
Data Management API for Modem Check Cloud Server
Handles bulk upload, bulk download, and deletion of modem check data.

Requires admin or elevated role for most operations.
"""

import sys
import os
import cgi
import json
import sqlite3
import tempfile
import zipfile
import io
from datetime import datetime
from urllib.parse import parse_qs

# Add cgi-bin directory to path
sys.path.insert(0, '/modemcheck-cloud/cgi-bin')

from auth import verify_session, get_cookie
from db_schema import get_connection
from audit_schema import log_user_activity, get_audit_connection

# Get request information
client_ip = os.environ.get('REMOTE_ADDR', 'unknown')
user_agent = os.environ.get('HTTP_USER_AGENT', 'unknown')

def parse_json_check_file(file_content):
    """Parse a JSON check file and extract key information."""
    try:
        data = json.loads(file_content)

        # Extract modem_id (various possible locations)
        modem_id = (
            data.get('modem_id') or
            data.get('modemId') or
            data.get('SystemInfo', {}).get('mac_address') or
            'unknown'
        )

        # Extract timestamp
        timestamp = data.get('timestamp', datetime.now().isoformat())

        return {
            'success': True,
            'modem_id': modem_id,
            'timestamp': timestamp,
            'data': data
        }
    except json.JSONDecodeError as e:
        return {
            'success': False,
            'error': f'Invalid JSON: {str(e)}'
        }
    except Exception as e:
        return {
            'success': False,
            'error': f'Parse error: {str(e)}'
        }

def insert_check_to_database(modem_id, filename, data_json):
    """Insert a check directly into the database."""
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Insert the check data
        cursor.execute("""
            INSERT INTO modem_checks (
                modem_id,
                filename,
                full_data,
                check_time,
                created_at
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            modem_id,
            filename,
            data_json,
            datetime.now().isoformat(),
            datetime.now().isoformat()
        ))

        check_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return {'success': True, 'check_id': check_id}
    except Exception as e:
        if 'conn' in locals():
            conn.close()
        return {'success': False, 'error': str(e)}

def get_checks_for_download(modem_id=None, start_date=None, end_date=None, limit=None):
    """Retrieve modem_checks from database for download."""
    try:
        conn = get_connection()
        cursor = conn.cursor()

        query = "SELECT id, modem_id, filename, full_data, check_time, created_at FROM modem_checks WHERE 1=1"
        params = []

        if modem_id:
            query += " AND modem_id = ?"
            params.append(modem_id)

        if start_date:
            query += " AND date(created_at) >= date(?)"
            params.append(start_date)

        if end_date:
            query += " AND date(created_at) <= date(?)"
            params.append(end_date)

        query += " ORDER BY created_at DESC"

        if limit:
            query += " LIMIT ?"
            params.append(int(limit))

        cursor.execute(query, params)

        modem_checks = []
        for row in cursor.fetchall():
            modem_checks.append({
                'id': row['id'],
                'modem_id': row['modem_id'],
                'filename': row['filename'],
                'full_data': row['full_data'],
                'timestamp': row['created_at']
            })

        conn.close()
        return {'success': True, 'checks': modem_checks}
    except Exception as e:
        if 'conn' in locals():
            conn.close()
        return {'success': False, 'error': str(e)}

def delete_check_by_id(check_id):
    """Delete a specific check by ID."""
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Get check info before deleting
        cursor.execute("SELECT modem_id, filename FROM modem_checks WHERE id = ?", (check_id,))
        row = cursor.fetchone()

        if not row:
            conn.close()
            return {'success': False, 'error': 'Check not found'}

        info = {'modem_id': row['modem_id'], 'filename': row['filename']}

        # Delete the check
        cursor.execute("DELETE FROM modem_checks WHERE id = ?", (check_id,))
        conn.commit()
        conn.close()

        return {'success': True, 'info': info}
    except Exception as e:
        if 'conn' in locals():
            conn.close()
        return {'success': False, 'error': str(e)}

def delete_all_checks_for_modem(modem_id):
    """Delete all modem_checks for a specific modem."""
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Count modem_checks before deleting
        cursor.execute("SELECT COUNT(*) as count FROM modem_checks WHERE modem_id = ?", (modem_id,))
        count = cursor.fetchone()['count']

        if count == 0:
            conn.close()
            return {'success': False, 'error': 'No modem_checks found for this modem'}

        # Delete all checks
        cursor.execute("DELETE FROM modem_checks WHERE modem_id = ?", (modem_id,))
        conn.commit()
        conn.close()

        return {'success': True, 'count': count}
    except Exception as e:
        if 'conn' in locals():
            conn.close()
        return {'success': False, 'error': str(e)}

# AUTHENTICATION CHECK - Admin or elevated role required
session_id = get_cookie('modemcheck_session')
session = verify_session(session_id)

# Determine request method and get parameters
request_method = os.environ.get('REQUEST_METHOD', 'GET')
form = None  # Will hold FieldStorage for multipart requests

if request_method == 'GET':
    query_string = os.environ.get('QUERY_STRING', '')
    params = parse_qs(query_string)
    # Convert lists to single values
    params = {k: v[0] if len(v) == 1 else v for k, v in params.items()}
    action = params.get('action', '')
    post_data = {}
elif request_method == 'POST':
    content_type = os.environ.get('CONTENT_TYPE', '')

    if 'multipart/form-data' in content_type:
        # Handle file uploads
        form = cgi.FieldStorage()
        action = form.getvalue('action', '')
        params = {}
        post_data = {}
    elif 'application/json' in content_type:
        content_length = int(os.environ.get('CONTENT_LENGTH', 0))
        post_body = sys.stdin.read(content_length)
        post_data = json.loads(post_body) if post_body else {}
        action = post_data.get('action', '')
        params = {}
    else:
        # URL-encoded form data
        content_length = int(os.environ.get('CONTENT_LENGTH', 0))
        post_body = sys.stdin.read(content_length)
        params = parse_qs(post_body)
        params = {k: v[0] if len(v) == 1 else v for k, v in params.items()}
        action = params.get('action', '')
        post_data = params
else:
    params = {}
    post_data = {}
    action = ''

# Don't print headers yet - will be done after determining action type

# Require authentication and admin or elevated role for most operations
if not session:
    print("Content-Type: application/json")
    print()
    print(json.dumps({'success': False, 'error': 'Unauthorized - Authentication required'}))
    sys.exit(1)

user_role = session.get('role', '')

# Check permissions based on action
if action in ['delete_check', 'delete_all_checks']:
    # Only admin can delete
    if user_role != 'admin':
        print("Content-Type: application/json")
        print()
        print(json.dumps({'success': False, 'error': 'Unauthorized - Admin access required for deletion'}))
        log_user_activity(
            username=session['username'],
            action_type=f'unauthorized_{action}',
            ip_address=client_ip,
            success=False,
            user_role=user_role,
            action_details=f'Attempted {action} without admin permissions',
            user_agent=user_agent,
            session_id=session_id
        )
        sys.exit(1)
elif user_role not in ['admin', 'elevated']:
    # Elevated or admin required for upload/download
    print("Content-Type: application/json")
    print()
    print(json.dumps({'success': False, 'error': 'Unauthorized - Admin or elevated access required'}))
    sys.exit(1)

# Process the request
try:
    result = {}

    if action == 'bulk_upload':
        # Handle bulk upload of check files
        # Reuse form object from request parsing (FieldStorage can only be read once)
        if form is None or 'files' not in form:
            result = {'success': False, 'error': 'No files provided'}
        else:
            files = form['files']
            if not isinstance(files, list):
                files = [files]

            results = []
            success_count = 0
            error_count = 0

            for file_item in files:
                if file_item.filename:
                    # SECURITY: Validate file extension
                    if not file_item.filename.lower().endswith('.json'):
                        error_count += 1
                        results.append({
                            'filename': file_item.filename,
                            'success': False,
                            'error': 'Invalid file type. Only .json files are allowed'
                        })
                        continue
                    
                    # SECURITY: Limit file size (10MB max per file in bulk upload)
                    file_content_bytes = file_item.file.read()
                    if len(file_content_bytes) > 10 * 1024 * 1024:
                        error_count += 1
                        results.append({
                            'filename': file_item.filename,
                            'success': False,
                            'error': 'File too large. Maximum 10MB per file'
                        })
                        continue
                    
                    try:
                        file_content = file_content_bytes.decode('utf-8')
                    except UnicodeDecodeError:
                        error_count += 1
                        results.append({
                            'filename': file_item.filename,
                            'success': False,
                            'error': 'Invalid file encoding. UTF-8 required'
                        })
                        continue
                    
                    parsed = parse_json_check_file(file_content)

                    if parsed['success']:
                        # Insert into database
                        insert_result = insert_check_to_database(
                            parsed['modem_id'],
                            file_item.filename,
                            json.dumps(parsed['data'])
                        )

                        if insert_result['success']:
                            success_count += 1
                            results.append({
                                'filename': file_item.filename,
                                'success': True,
                                'check_id': insert_result['check_id']
                            })
                        else:
                            error_count += 1
                            results.append({
                                'filename': file_item.filename,
                                'success': False,
                                'error': insert_result['error']
                            })
                    else:
                        error_count += 1
                        results.append({
                            'filename': file_item.filename,
                            'success': False,
                            'error': parsed['error']
                        })

            result = {
                'success': True,
                'total': len(files),
                'success_count': success_count,
                'error_count': error_count,
                'results': results
            }

            # Log the bulk upload
            log_user_activity(
                username=session['username'],
                action_type='bulk_upload',
                ip_address=client_ip,
                success=True,
                user_role=user_role,
                action_details=f'Uploaded {success_count} of {len(files)} checks',
                user_agent=user_agent,
                session_id=session_id
            )

    elif action == 'bulk_download':
        # Handle bulk download as zip file
        modem_id = params.get('modem_id', post_data.get('modem_id'))
        start_date = params.get('start_date', post_data.get('start_date'))
        end_date = params.get('end_date', post_data.get('end_date'))
        limit = params.get('limit', post_data.get('limit'))

        # Get modem_checks from database
        checks_result = get_checks_for_download(modem_id, start_date, end_date, limit)

        if not checks_result['success']:
            result = checks_result
        else:
            modem_checks = checks_result['checks']

            if len(modem_checks) == 0:
                result = {'success': False, 'error': 'No modem_checks found matching criteria'}
            else:
                # SECURITY: Limit maximum number of files in a single download (prevent zip bombs)
                MAX_FILES_PER_DOWNLOAD = 1000
                if len(modem_checks) > MAX_FILES_PER_DOWNLOAD:
                    result = {'success': False, 'error': f'Too many files requested. Maximum {MAX_FILES_PER_DOWNLOAD} per download'}
                else:
                    # Create zip file in memory
                    zip_buffer = io.BytesIO()
                    total_uncompressed_size = 0
                    MAX_TOTAL_SIZE = 100 * 1024 * 1024  # 100MB uncompressed max
                    
                    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                        for check in modem_checks:
                            # Use original filename or create one
                            filename = check['filename'] or f"check_{check['id']}_{check['timestamp']}.json"
                            
                            # SECURITY: Sanitize filename to prevent path traversal in zip extraction
                            # Remove any path components and dangerous characters
                            safe_filename = os.path.basename(filename)
                            safe_filename = safe_filename.replace('..', '_').replace('/', '_').replace('\\', '_')
                            
                            # SECURITY: Check total uncompressed size to prevent zip bombs
                            file_data = check['full_data']
                            total_uncompressed_size += len(file_data)
                            if total_uncompressed_size > MAX_TOTAL_SIZE:
                                result = {'success': False, 'error': 'Download size limit exceeded'}
                                break
                            
                            zip_file.writestr(safe_filename, file_data)
                    
                    if 'error' not in result:
                        # Return zip file
                        zip_data = zip_buffer.getvalue()

                        # Change headers for binary download
                        print("Content-Type: application/zip")
                        print(f"Content-Disposition: attachment; filename=modemcheck_bulk_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")
                        print(f"Content-Length: {len(zip_data)}")
                        print()  # Empty line to separate headers from body
                        sys.stdout.flush()  # Flush text mode before switching to binary

                        # Write binary data to stdout
                        sys.stdout.buffer.write(zip_data)
                        sys.stdout.buffer.flush()

                        # Log the download
                        log_user_activity(
                            username=session['username'],
                            action_type='bulk_download',
                            ip_address=client_ip,
                            success=True,
                            user_role=user_role,
                            action_details=f'Downloaded {len(modem_checks)} modem_checks as zip',
                            user_agent=user_agent,
                            session_id=session_id
                        )

                        sys.exit(0)

    elif action == 'get_checks_summary':
        # Get summary of modem_checks for display/deletion UI
        modem_id = params.get('modem_id', post_data.get('modem_id'))
        start_date = params.get('start_date', post_data.get('start_date'))
        end_date = params.get('end_date', post_data.get('end_date'))
        limit = params.get('limit', post_data.get('limit', 100))

        checks_result = get_checks_for_download(modem_id, start_date, end_date, limit)

        if checks_result['success']:
            # Return summary without full full_data
            summary_checks = []
            for check in checks_result['checks']:
                summary_checks.append({
                    'id': check['id'],
                    'modem_id': check['modem_id'],
                    'filename': check['filename'],
                    'timestamp': check['timestamp']
                })

            result = {
                'success': True,
                'checks': summary_checks,
                'count': len(summary_checks)
            }
        else:
            result = checks_result

    elif action == 'delete_check':
        # Delete a specific check by ID
        check_id = params.get('check_id', post_data.get('check_id'))

        if not check_id:
            result = {'success': False, 'error': 'No check_id provided'}
        else:
            delete_result = delete_check_by_id(check_id)

            if delete_result['success']:
                result = {'success': True, 'message': 'Check deleted successfully'}

                # Log the deletion
                log_user_activity(
                    username=session['username'],
                    action_type='delete_check',
                    ip_address=client_ip,
                    success=True,
                    user_role=user_role,
                    action_details=f"Deleted check {check_id} for {delete_result['info']['modem_id']}",
                    user_agent=user_agent,
                    session_id=session_id
                )
            else:
                result = delete_result

    elif action == 'delete_all_checks':
        # Delete all modem_checks for a modem
        modem_id = params.get('modem_id', post_data.get('modem_id'))

        if not modem_id:
            result = {'success': False, 'error': 'No modem_id provided'}
        else:
            delete_result = delete_all_checks_for_modem(modem_id)

            if delete_result['success']:
                result = {
                    'success': True,
                    'message': f"Deleted {delete_result['count']} checks",
                    'count': delete_result['count']
                }

                # Log the bulk deletion
                log_user_activity(
                    username=session['username'],
                    action_type='delete_all_checks',
                    ip_address=client_ip,
                    success=True,
                    user_role=user_role,
                    action_details=f"Deleted all {delete_result['count']} modem_checks for {modem_id}",
                    user_agent=user_agent,
                    session_id=session_id
                )
            else:
                result = delete_result

    else:
        result = {'success': False, 'error': f'Unknown action: {action}'}

    # Print JSON headers and result (bulk_download handles its own headers)
    print("Content-Type: application/json")
    print()
    print(json.dumps(result))

except Exception as e:
    print("Content-Type: application/json")
    print()
    print(json.dumps({'success': False, 'error': f'Server error: {str(e)}'}))
    import traceback
    print(f"Error: {traceback.format_exc()}", file=sys.stderr)
