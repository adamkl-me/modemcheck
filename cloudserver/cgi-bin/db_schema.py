#!/usr/bin/env python3
"""
Database schema and initialization for ModemCheck cloud server.
Compatible with both SQLite and PostgreSQL for easy migration.
"""

import sqlite3
import os
import json

DB_PATH = '/modemcheck-cloud/data/modemcheck.db'

def get_connection():
    """Get database connection. Works with SQLite by default."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Return rows as dicts
    
    # Enable WAL mode for better concurrent access and performance
    conn.execute('PRAGMA journal_mode=WAL')
    # NORMAL synchronous mode is safe with WAL and much faster
    conn.execute('PRAGMA synchronous=NORMAL')
    # Cache size in KB (negative = KB, positive = pages)
    conn.execute('PRAGMA cache_size=-8000')  # 8MB cache
    
    return conn

def init_database():
    """Initialize database schema. Compatible with both SQLite and PostgreSQL."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Create modem_checks table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS modem_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            modem_id TEXT NOT NULL,
            modem_type TEXT,
            check_time TEXT NOT NULL,
            filename TEXT NOT NULL UNIQUE,
            
            -- System info
            firmware TEXT,
            uptime_seconds INTEGER,
            system_time TEXT,
            
            -- Signal quality metrics (for quick queries)
            avg_downstream_power REAL,
            avg_downstream_snr REAL,
            avg_upstream_power REAL,
            total_corrected_errors INTEGER,
            total_uncorrected_errors INTEGER,
            
            -- Speed test results
            ping_google_avg REAL,
            ping_google_loss REAL,
            ping_cloudflare_avg REAL,
            ping_cloudflare_loss REAL,
            iperf3_upload TEXT,
            iperf3_download TEXT,
            
            -- Full JSON data
            full_data TEXT NOT NULL,
            
            -- Metadata
            created_at TEXT NOT NULL,
            
            -- Check constraints for data quality
            CHECK (check_time != ''),
            CHECK (modem_id != ''),
            CHECK (full_data != '')
        )
    ''')
    
    # Create indexes for common queries
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_modem_time 
        ON modem_checks(modem_id, check_time DESC)
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_check_time 
        ON modem_checks(check_time DESC)
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_modem_type 
        ON modem_checks(modem_type)
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_filename 
        ON modem_checks(filename)
    ''')
    
    conn.commit()
    conn.close()

def insert_check(data_dict, filename):
    """
    Insert a modem check into the database.
    Extracts key metrics for indexing while storing full JSON.
    Returns the inserted row ID or None on failure.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Extract system info
        sysinfo = data_dict.get('sysinfo', {})
        modem_mac = sysinfo.get('modemmac', sysinfo.get('mac', 'unknown'))
        modem_type = sysinfo.get('modemtype', 'unknown')
        # Construct modem_id in format TYPE-MAC (matches directory structure)
        modem_id = f"{modem_type}-{modem_mac}"
        check_time = sysinfo.get('checktime', sysinfo.get('timestamp', ''))
        firmware = sysinfo.get('firmware', '')
        
        # Parse uptime (could be string like "6 days 18h: 5m: 44s" or integer)
        uptime_str = sysinfo.get('uptime', '')
        if isinstance(uptime_str, int):
            uptime_seconds = uptime_str
        else:
            uptime_seconds = 0  # Would need parsing logic for string format
        
        system_time = sysinfo.get('systime', sysinfo.get('systemtime', ''))
        
        # Calculate average downstream power and SNR
        rx_channels = data_dict.get('rx', [])
        if rx_channels:
            powers = [float(ch.get('power', 0)) for ch in rx_channels if ch.get('power')]
            snrs = [float(ch.get('snr', 0)) for ch in rx_channels if ch.get('snr')]
            avg_downstream_power = sum(powers) / len(powers) if powers else None
            avg_downstream_snr = sum(snrs) / len(snrs) if snrs else None
        else:
            avg_downstream_power = None
            avg_downstream_snr = None
        
        # Calculate average upstream power
        tx_channels = data_dict.get('tx', [])
        if tx_channels:
            powers = [float(ch.get('power', 0)) for ch in tx_channels if ch.get('power')]
            avg_upstream_power = sum(powers) / len(powers) if powers else None
        else:
            avg_upstream_power = None
        
        # Calculate total errors
        total_corrected = 0
        total_uncorrected = 0
        for ch in rx_channels:
            total_corrected += int(ch.get('corrected', 0))
            total_uncorrected += int(ch.get('uncorrected', 0))
        
        # Extract ping results
        ping_google_avg = data_dict.get('ping_google_avg')
        if ping_google_avg and ping_google_avg not in ['Failed', 'N/A']:
            try:
                ping_google_avg = float(ping_google_avg)
            except:
                ping_google_avg = None
        else:
            ping_google_avg = None
            
        ping_google_loss = data_dict.get('ping_google_loss')
        if ping_google_loss and ping_google_loss not in ['Failed', 'N/A']:
            try:
                ping_google_loss = float(ping_google_loss.rstrip('%'))
            except:
                ping_google_loss = None
        else:
            ping_google_loss = None
        
        ping_cloudflare_avg = data_dict.get('ping_cloudflare_avg')
        if ping_cloudflare_avg and ping_cloudflare_avg not in ['Failed', 'N/A']:
            try:
                ping_cloudflare_avg = float(ping_cloudflare_avg)
            except:
                ping_cloudflare_avg = None
        else:
            ping_cloudflare_avg = None
            
        ping_cloudflare_loss = data_dict.get('ping_cloudflare_loss')
        if ping_cloudflare_loss and ping_cloudflare_loss not in ['Failed', 'N/A']:
            try:
                ping_cloudflare_loss = float(ping_cloudflare_loss.rstrip('%'))
            except:
                ping_cloudflare_loss = None
        else:
            ping_cloudflare_loss = None
        
        # Speed test results (stored as text)
        iperf3_upload = data_dict.get('iperf3test_ul', '')
        iperf3_download = data_dict.get('iperf3test_dl', '')
        
        # Store full JSON as text
        full_data = json.dumps(data_dict)
        
        # Get current timestamp
        from datetime import datetime
        created_at = datetime.now().isoformat()
        
        cursor.execute('''
            INSERT INTO modem_checks (
                modem_id, modem_type, check_time, filename,
                firmware, uptime_seconds, system_time,
                avg_downstream_power, avg_downstream_snr, avg_upstream_power,
                total_corrected_errors, total_uncorrected_errors,
                ping_google_avg, ping_google_loss,
                ping_cloudflare_avg, ping_cloudflare_loss,
                iperf3_upload, iperf3_download,
                full_data, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            modem_id, modem_type, check_time, filename,
            firmware, uptime_seconds, system_time,
            avg_downstream_power, avg_downstream_snr, avg_upstream_power,
            total_corrected, total_uncorrected,
            ping_google_avg, ping_google_loss,
            ping_cloudflare_avg, ping_cloudflare_loss,
            iperf3_upload, iperf3_download,
            full_data, created_at
        ))
        
        conn.commit()
        row_id = cursor.lastrowid
        conn.close()
        return row_id
        
    except sqlite3.IntegrityError:
        # File already exists in database
        conn.close()
        return None
    except Exception as e:
        conn.close()
        raise e

def get_modems():
    """Get list of all modems with their latest check time."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            modem_id,
            modem_type,
            MAX(check_time) as latest_check,
            COUNT(*) as total_checks
        FROM modem_checks
        GROUP BY modem_id
        ORDER BY modem_id
    ''')
    
    modems = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return modems

def get_checks(modem_id=None, start_date=None, end_date=None, limit=1000):
    """
    Get modem checks with optional filtering.
    Returns list of dicts with full JSON data.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    query = 'SELECT * FROM modem_checks WHERE 1=1'
    params = []
    
    if modem_id:
        query += ' AND modem_id = ?'
        params.append(modem_id)
    
    if start_date:
        query += ' AND check_time >= ?'
        params.append(start_date)
    
    if end_date:
        query += ' AND check_time <= ?'
        params.append(end_date)
    
    query += ' ORDER BY check_time DESC LIMIT ?'
    params.append(limit)
    
    cursor.execute(query, params)
    
    results = []
    for row in cursor.fetchall():
        row_dict = dict(row)
        # Parse full_data JSON
        row_dict['full_data'] = json.loads(row_dict['full_data'])
        results.append(row_dict)
    
    conn.close()
    return results

def check_exists(filename):
    """Check if a file has already been imported."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT id FROM modem_checks WHERE filename = ?', (filename,))
    exists = cursor.fetchone() is not None
    
    conn.close()
    return exists

if __name__ == '__main__':
    # Initialize database when run directly
    print("Initializing database...")
    init_database()
    print(f"Database initialized at {DB_PATH}")
