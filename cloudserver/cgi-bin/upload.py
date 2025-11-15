#!/usr/bin/env python3
import cgi
import json
import os
import sys
import hashlib
import hmac
import time
import secrets
from datetime import datetime

# Import audit logging and database access
sys.path.insert(0, '/modemcheck-cloud/cgi-bin')
try:
    from audit_schema import log_client_submission, get_audit_connection
except ImportError:
    def log_client_submission(*args, **kwargs):
        pass
    def get_audit_connection():
        raise ImportError("audit_schema not available")

try:
    from db_schema import insert_check, init_database
except ImportError:
    def insert_check(*args, **kwargs):
        raise ImportError("db_schema not available")
    def init_database():
        raise ImportError("db_schema not available")

def validate_request_signature(api_key, timestamp, modem_id, filename, checksum, provided_signature):
    """
    Validate HMAC-SHA256 request signature to prevent replay attacks and ensure request integrity.

    Returns: (is_valid: bool, error_message: str)
    """
    # Validate timestamp is present
    if not timestamp:
        return False, "Missing request timestamp"

    # Parse timestamp
    try:
        request_time = int(timestamp)
    except (ValueError, TypeError):
        return False, "Invalid timestamp format"

    # Check timestamp is within 5 minutes (300 seconds) to prevent replay attacks
    current_time = int(time.time())
    time_diff = abs(current_time - request_time)
    if time_diff > 300:  # 5 minutes
        return False, f"Request timestamp too old (difference: {time_diff}s, max: 300s)"

    # Compute expected signature using same algorithm as client
    # Format: HMAC-SHA256(api_key, timestamp|modem_id|filename|checksum)
    message = f"{timestamp}|{modem_id}|{filename}|{checksum}"
    expected_signature = hmac.new(
        api_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    # Timing-safe comparison to prevent timing attacks
    if not secrets.compare_digest(provided_signature, expected_signature):
        return False, "Invalid request signature"

    return True, ""

def validate_api_key(api_key):
    """Validate if the API key is valid and active (timing-safe comparison)"""
    # Load API keys from database
    try:
        conn = get_audit_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT api_key, is_active, name
            FROM api_keys
            WHERE is_active = 1
        """)
        api_keys = {row['api_key']: row['name'] for row in cursor.fetchall()}
        conn.close()
    except Exception as e:
        print(f"Error loading API keys: {e}", file=sys.stderr)
        return False, "Database error"

    # Timing-safe comparison: check all keys
    found_key = None
    for stored_key in api_keys:
        if secrets.compare_digest(api_key, stored_key):
            found_key = stored_key
            break

    if found_key is None:
        return False, "Invalid API key"

    # Update last_used timestamp in database
    try:
        conn = get_audit_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE api_keys
            SET last_used = ?
            WHERE api_key = ?
        """, (datetime.now().isoformat(), found_key))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Warning: Failed to update last_used: {e}", file=sys.stderr)

    return True, api_keys[found_key]

def handle_upload():
    """Handle data upload and insert directly into database"""
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
    client_checksum = form.getvalue('checksum', '')

    # Extract HMAC signature and timestamp from headers
    request_timestamp = os.environ.get('HTTP_X_REQUEST_TIMESTAMP', '')
    request_signature = os.environ.get('HTTP_X_REQUEST_SIGNATURE', '')

    # Create API key hash for logging (privacy-preserving)
    api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16] if api_key else 'none'

    # Validate API key first
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

    # Validate HMAC signature (prevents replay attacks and ensures request integrity)
    sig_valid, sig_error = validate_request_signature(
        api_key, request_timestamp, modem_id, filename, client_checksum, request_signature
    )
    if not sig_valid:
        # Log failed submission
        log_client_submission(
            ip_address=client_ip,
            api_key_hash=api_key_hash,
            api_key_name=key_name,
            modem_id=modem_id or 'unknown',
            filename=filename or 'unknown',
            success=False,
            failure_reason=f'Invalid request signature: {sig_error}',
            user_agent=user_agent
        )
        print("Status: 401 Unauthorized")
        print("Content-Type: application/json")
        print()
        print(json.dumps({'success': False, 'error': f'Authentication failed: {sig_error}'}))
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

    # SECURITY: Validate modem_id and filename format
    import re
    if not re.match(r'^[a-zA-Z0-9_-]+$', modem_id):
        print("Status: 400 Bad Request")
        print("Content-Type: application/json")
        print()
        print(json.dumps({'success': False, 'error': 'Invalid modem_id format'}))
        return

    # Filename should match: YYYY-MM-DD_HH-MM-SS.json or YYYY-MM-DD_HH-MM-SS_nanoseconds.json
    if not re.match(r'^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(_\d+)?\.json$', filename):
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

    # SECURITY: Limit file size to 10MB to prevent DoS
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    file_data = file_item.file.read(MAX_FILE_SIZE + 1)

    if len(file_data) > MAX_FILE_SIZE:
        print("Status: 413 Payload Too Large")
        print("Content-Type: application/json")
        print()
        print(json.dumps({'success': False, 'error': 'File size exceeds 10MB limit'}))
        return

    # Validate checksum (data integrity check)
    if client_checksum:
        # Calculate SHA-256 of received data
        server_checksum = hashlib.sha256(file_data).hexdigest()

        # Timing-safe comparison to prevent timing attacks
        if not secrets.compare_digest(client_checksum.lower(), server_checksum.lower()):
            log_client_submission(
                ip_address=client_ip,
                api_key_hash=api_key_hash,
                api_key_name=key_name,
                modem_id=modem_id,
                filename=filename,
                file_size=len(file_data),
                success=False,
                failure_reason='Checksum validation failed (data corruption or tampering)',
                user_agent=user_agent
            )
            print("Status: 400 Bad Request")
            print("Content-Type: application/json")
            print()
            print(json.dumps({'success': False, 'error': 'Checksum validation failed'}))
            return
    else:
        # Checksum is required for all uploads (v6.0.0+)
        log_client_submission(
            ip_address=client_ip,
            api_key_hash=api_key_hash,
            api_key_name=key_name,
            modem_id=modem_id,
            filename=filename,
            file_size=len(file_data),
            success=False,
            failure_reason='Missing checksum field (upgrade client to v6.0.0+)',
            user_agent=user_agent
        )
        print("Status: 400 Bad Request")
        print("Content-Type: application/json")
        print()
        print(json.dumps({'success': False, 'error': 'Missing checksum field (upgrade client to v6.0.0+)'}))
        return

    # Parse JSON data (in memory, no disk I/O)
    modem_type = None
    modem_mac = None
    check_time = None
    json_data = None

    try:
        json_data = json.loads(file_data.decode('utf-8'))
        if 'sysinfo' in json_data:
            modem_type = json_data['sysinfo'].get('modemtype', 'unknown')
            modem_mac = json_data['sysinfo'].get('modemmac', 'unknown')
            check_time = json_data['sysinfo'].get('checktime')
    except Exception as parse_error:
        log_client_submission(
            ip_address=client_ip,
            api_key_hash=api_key_hash,
            api_key_name=key_name,
            modem_id=modem_id,
            filename=filename,
            success=False,
            failure_reason=f'Invalid JSON: {str(parse_error)}',
            user_agent=user_agent
        )
        print("Status: 400 Bad Request")
        print("Content-Type: application/json")
        print()
        print(json.dumps({'success': False, 'error': f'Invalid JSON data: {str(parse_error)}'}))
        return

    # Insert directly into database (single source of truth)
    db_row_id = None
    try:
        # Use the modem_id/filename format for database record
        db_filename = f"{modem_id}/{filename}"
        db_row_id = insert_check(json_data, db_filename)

        if db_row_id is None:
            # insert_check returns None for duplicates
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
                success=False,
                failure_reason='Duplicate entry (already in database)'
            )
            print("Status: 409 Conflict")
            print("Content-Type: application/json")
            print()
            print(json.dumps({'success': False, 'error': 'Duplicate entry (already in database)'}))
            return

    except Exception as db_err:
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
            success=False,
            failure_reason=f'Database error: {str(db_err)}'
        )
        print(f"[ERROR] Database insertion failed: {db_err}", file=sys.stderr)
        print("Status: 500 Internal Server Error")
        print("Content-Type: application/json")
        print()
        print(json.dumps({'success': False, 'error': f'Database error: {str(db_err)}'}))
        return

    # Calculate processing time
    processing_time_ms = int((time.time() - start_time) * 1000)

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

    # Success response - minimal data to prevent information disclosure
    # Internal metrics still logged in audit trail above (lines 258-271)
    response = {
        'success': True,
        'message': 'Data uploaded successfully'
    }

    print("Content-Type: application/json")
    print()
    print(json.dumps(response))

# Main execution
try:
    handle_upload()
except Exception as e:
    print("Status: 500 Internal Server Error")
    print("Content-Type: application/json")
    print()
    print(json.dumps({'success': False, 'error': f'Unexpected error: {str(e)}'}))
    sys.exit(1)
