#!/usr/bin/env python3
"""
Audit logging schema for ModemCheck cloud server.
Tracks user activity and client check submissions for security and compliance.
"""

import sqlite3
import os
import sys
import json
from datetime import datetime

AUDIT_DB_PATH = '/modemcheck-cloud/data/audit.db'

def get_audit_connection():
    """Get audit database connection."""
    conn = sqlite3.connect(AUDIT_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_audit_database():
    """Initialize audit logging tables."""
    conn = get_audit_connection()
    cursor = conn.cursor()
    
    # User activity audit log
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            username TEXT NOT NULL,
            user_role TEXT,
            action_type TEXT NOT NULL,
            action_details TEXT,
            ip_address TEXT NOT NULL,
            user_agent TEXT,
            session_id TEXT,
            success BOOLEAN NOT NULL,
            failure_reason TEXT,
            
            -- Indexes for common queries
            CHECK (timestamp != ''),
            CHECK (username != ''),
            CHECK (action_type != ''),
            CHECK (ip_address != '')
        )
    ''')
    
    # Client check submission audit log
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS client_submission_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            api_key_hash TEXT NOT NULL,
            api_key_name TEXT,
            modem_id TEXT NOT NULL,
            modem_type TEXT,
            modem_mac TEXT,
            filename TEXT NOT NULL,
            file_size INTEGER,
            check_time TEXT,
            user_agent TEXT,
            success BOOLEAN NOT NULL,
            failure_reason TEXT,
            processing_time_ms INTEGER,
            
            -- Indexes for common queries
            CHECK (timestamp != ''),
            CHECK (ip_address != ''),
            CHECK (api_key_hash != ''),
            CHECK (modem_id != '')
        )
    ''')
    
    # Create indexes for efficient querying
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_user_activity_timestamp 
        ON user_activity_log(timestamp DESC)
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_user_activity_username 
        ON user_activity_log(username, timestamp DESC)
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_user_activity_action 
        ON user_activity_log(action_type, timestamp DESC)
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_user_activity_ip 
        ON user_activity_log(ip_address, timestamp DESC)
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_client_submission_timestamp 
        ON client_submission_log(timestamp DESC)
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_client_submission_api_key 
        ON client_submission_log(api_key_hash, timestamp DESC)
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_client_submission_modem 
        ON client_submission_log(modem_id, timestamp DESC)
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_client_submission_ip 
        ON client_submission_log(ip_address, timestamp DESC)
    ''')
    
    conn.commit()
    conn.close()

def log_user_activity(username, action_type, ip_address, success=True, 
                      user_role=None, action_details=None, user_agent=None, 
                      session_id=None, failure_reason=None):
    """
    Log user activity (login, logout, password change, admin actions, etc.)
    
    Args:
        username: Username performing the action
        action_type: Type of action (login, logout, create_user, delete_key, etc.)
        ip_address: IP address of the user
        success: Whether the action succeeded
        user_role: User's role (admin, viewer)
        action_details: JSON string with additional details
        user_agent: User's browser/client user agent
        session_id: Session identifier
        failure_reason: Reason for failure if success=False
    """
    conn = get_audit_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO user_activity_log 
            (timestamp, username, user_role, action_type, action_details, 
             ip_address, user_agent, session_id, success, failure_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.utcnow().isoformat() + 'Z',
            username,
            user_role,
            action_type,
            action_details,
            ip_address,
            user_agent,
            session_id,
            1 if success else 0,
            failure_reason
        ))
        conn.commit()
    except Exception as e:
        print(f"Error logging user activity: {e}", file=sys.stderr)
    finally:
        conn.close()

def log_client_submission(ip_address, api_key_hash, modem_id, filename, success=True,
                         api_key_name=None, modem_type=None, modem_mac=None,
                         file_size=None, check_time=None, user_agent=None,
                         failure_reason=None, processing_time_ms=None):
    """
    Log client check data submission.
    
    Args:
        ip_address: IP address of the client
        api_key_hash: SHA256 hash of the API key (first 16 chars for privacy)
        modem_id: Modem identifier (TYPE-MAC format)
        filename: Name of the submitted file
        success: Whether the submission succeeded
        api_key_name: Friendly name of the API key
        modem_type: Type of modem (DM1000, XB8, etc.)
        modem_mac: MAC address of the modem
        file_size: Size of submitted data in bytes
        check_time: Timestamp of the check
        user_agent: User agent of the client
        failure_reason: Reason for failure if success=False
        processing_time_ms: Time taken to process the submission
    """
    conn = get_audit_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO client_submission_log 
            (timestamp, ip_address, api_key_hash, api_key_name, modem_id, 
             modem_type, modem_mac, filename, file_size, check_time, 
             user_agent, success, failure_reason, processing_time_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.utcnow().isoformat() + 'Z',
            ip_address,
            api_key_hash,
            api_key_name,
            modem_id,
            modem_type,
            modem_mac,
            filename,
            file_size,
            check_time,
            user_agent,
            1 if success else 0,
            failure_reason,
            processing_time_ms
        ))
        conn.commit()
    except Exception as e:
        print(f"Error logging client submission: {e}", file=sys.stderr)
    finally:
        conn.close()

def get_user_activity_logs(limit=100, username=None, action_type=None, 
                           start_date=None, end_date=None, ip_address=None):
    """
    Retrieve user activity logs with optional filters.
    
    Returns list of dict objects with log entries.
    """
    conn = get_audit_connection()
    cursor = conn.cursor()
    
    query = 'SELECT * FROM user_activity_log WHERE 1=1'
    params = []
    
    if username:
        query += ' AND username = ?'
        params.append(username)
    
    if action_type:
        query += ' AND action_type = ?'
        params.append(action_type)
    
    if ip_address:
        query += ' AND ip_address = ?'
        params.append(ip_address)
    
    if start_date:
        query += ' AND timestamp >= ?'
        params.append(start_date)
    
    if end_date:
        # Make end date inclusive by adding one day
        query += ' AND timestamp < ?'
        params.append(end_date)
    
    query += ' ORDER BY timestamp DESC LIMIT ?'
    params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]

def get_client_submission_logs(limit=100, api_key_hash=None, modem_id=None,
                               start_date=None, end_date=None, ip_address=None):
    """
    Retrieve client submission logs with optional filters.
    
    Returns list of dict objects with log entries.
    """
    conn = get_audit_connection()
    cursor = conn.cursor()
    
    query = 'SELECT * FROM client_submission_log WHERE 1=1'
    params = []
    
    if api_key_hash:
        query += ' AND api_key_hash = ?'
        params.append(api_key_hash)
    
    if modem_id:
        query += ' AND modem_id = ?'
        params.append(modem_id)
    
    if ip_address:
        query += ' AND ip_address = ?'
        params.append(ip_address)
    
    if start_date:
        query += ' AND timestamp >= ?'
        params.append(start_date)
    
    if end_date:
        # Make end date inclusive
        query += ' AND timestamp < ?'
        params.append(end_date)
    
    query += ' ORDER BY timestamp DESC LIMIT ?'
    params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]

def get_user_activity_stats():
    """Get summary statistics for user activity."""
    conn = get_audit_connection()
    cursor = conn.cursor()
    
    stats = {}
    
    # Total actions
    cursor.execute('SELECT COUNT(*) as total FROM user_activity_log')
    stats['total_actions'] = cursor.fetchone()['total']
    
    # Failed actions
    cursor.execute('SELECT COUNT(*) as failed FROM user_activity_log WHERE success = 0')
    stats['failed_actions'] = cursor.fetchone()['failed']
    
    # Unique users
    cursor.execute('SELECT COUNT(DISTINCT username) as unique_users FROM user_activity_log')
    stats['unique_users'] = cursor.fetchone()['unique_users']
    
    # Actions by type
    cursor.execute('''
        SELECT action_type, COUNT(*) as count 
        FROM user_activity_log 
        GROUP BY action_type 
        ORDER BY count DESC
    ''')
    stats['actions_by_type'] = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return stats

def get_client_submission_stats():
    """Get summary statistics for client submissions."""
    conn = get_audit_connection()
    cursor = conn.cursor()
    
    stats = {}
    
    # Total submissions
    cursor.execute('SELECT COUNT(*) as total FROM client_submission_log')
    stats['total_submissions'] = cursor.fetchone()['total']
    
    # Failed submissions
    cursor.execute('SELECT COUNT(*) as failed FROM client_submission_log WHERE success = 0')
    stats['failed_submissions'] = cursor.fetchone()['failed']
    
    # Unique modems
    cursor.execute('SELECT COUNT(DISTINCT modem_id) as unique_modems FROM client_submission_log')
    stats['unique_modems'] = cursor.fetchone()['unique_modems']
    
    # Unique API keys
    cursor.execute('SELECT COUNT(DISTINCT api_key_hash) as unique_keys FROM client_submission_log')
    stats['unique_api_keys'] = cursor.fetchone()['unique_keys']
    
    # Submissions by modem type
    cursor.execute('''
        SELECT modem_type, COUNT(*) as count 
        FROM client_submission_log 
        WHERE modem_type IS NOT NULL
        GROUP BY modem_type 
        ORDER BY count DESC
    ''')
    stats['submissions_by_modem_type'] = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return stats

# Initialize database on import
if __name__ == '__main__':
    init_audit_database()
    print("Audit database initialized successfully")
else:
    # Auto-initialize when module is imported
    try:
        init_audit_database()
    except Exception as e:
        import sys
        print(f"Warning: Could not initialize audit database: {e}", file=sys.stderr)
