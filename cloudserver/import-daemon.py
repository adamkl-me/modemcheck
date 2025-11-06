#!/usr/bin/env python3
"""
Background job that monitors /modemcheck-cloud/datafiles for new JSON files
and imports them into the database.

Runs continuously, scanning for new files every 30 seconds.
"""

import os
import json
import time
import sys
from pathlib import Path
from datetime import datetime

# Add cgi-bin to path for imports
sys.path.insert(0, '/modemcheck-cloud/cgi-bin')

from db_schema import insert_check, init_database, check_exists

DATAFILES_DIR = Path('/modemcheck-cloud/datafiles')
SCAN_INTERVAL = 30  # seconds

def scan_and_import():
    """Scan datafiles directory and import new JSON files"""
    if not DATAFILES_DIR.exists():
        print(f"[{datetime.now()}] Datafiles directory does not exist yet")
        return 0
    
    imported_count = 0
    
    # Walk through all subdirectories
    for modem_dir in DATAFILES_DIR.iterdir():
        if not modem_dir.is_dir():
            continue
        
        modem_id = modem_dir.name
        
        # Check all JSON files in this modem directory
        for json_file in modem_dir.glob('*.json'):
            filename = f"{modem_id}/{json_file.name}"
            
            # Skip if already imported
            if check_exists(filename):
                continue
            
            # Try to import
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)
                
                row_id = insert_check(data, filename)
                
                if row_id:
                    imported_count += 1
                    print(f"[{datetime.now()}] Imported: {filename} (ID: {row_id})")
                else:
                    print(f"[{datetime.now()}] Skipped (duplicate): {filename}")
                    
            except json.JSONDecodeError as e:
                print(f"[{datetime.now()}] ERROR: Invalid JSON in {filename}: {e}")
            except Exception as e:
                print(f"[{datetime.now()}] ERROR: Failed to import {filename}: {e}")
    
    return imported_count

def main():
    """Main loop"""
    import argparse

    parser = argparse.ArgumentParser(description='ModemCheck Database Import Service')
    parser.add_argument('--once', action='store_true',
                       help='Run once and exit (useful for testing)')
    args = parser.parse_args()

    if args.once:
        print(f"[{datetime.now()}] Running single import scan (test mode)...")
    else:
        print(f"[{datetime.now()}] ModemCheck Database Import Service Starting...")
        print(f"[{datetime.now()}] Monitoring: {DATAFILES_DIR}")
        print(f"[{datetime.now()}] Scan interval: {SCAN_INTERVAL} seconds")

    # Initialize database
    try:
        init_database()
        print(f"[{datetime.now()}] Database initialized")
    except Exception as e:
        print(f"[{datetime.now()}] ERROR: Failed to initialize database: {e}")
        sys.exit(1)

    # Initial import of existing files
    print(f"[{datetime.now()}] Performing scan...")
    initial_count = scan_and_import()
    print(f"[{datetime.now()}] Scan complete: {initial_count} files imported")

    # Exit if --once flag is set
    if args.once:
        sys.exit(0)

    # Continuous monitoring
    while True:
        try:
            time.sleep(SCAN_INTERVAL)
            count = scan_and_import()
            if count > 0:
                print(f"[{datetime.now()}] Scan complete: {count} new files imported")
        except KeyboardInterrupt:
            print(f"\n[{datetime.now()}] Shutting down...")
            break
        except Exception as e:
            print(f"[{datetime.now()}] ERROR in main loop: {e}")
            time.sleep(SCAN_INTERVAL)

if __name__ == '__main__':
    main()
