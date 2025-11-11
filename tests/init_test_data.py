#!/usr/bin/env python3
"""Initialize test databases with test data"""

import sys
sys.path.insert(0, '/modemcheck-cloud/cgi-bin')

import sqlite3
from datetime import datetime
from pathlib import Path

# Initialize main database
db_path = '/modemcheck-cloud/data/modemcheck.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Use db_schema to initialize the main database properly
from db_schema import init_database
init_database()

conn.commit()
conn.close()

# Initialize audit database (includes users and api_keys tables)
audit_path = '/modemcheck-cloud/data/audit.db'

# Initialize schema using audit_schema module (creates all tables)
from audit_schema import init_audit_database
init_audit_database()

# Now connect and populate with test data
conn = sqlite3.connect(audit_path)
cursor = conn.cursor()

# Clear any existing test data from previous runs
cursor.execute('DELETE FROM user_activity_log')
cursor.execute('DELETE FROM client_submission_log')
# Don't delete users - let ensure_default_admin() create the default admin
# cursor.execute('DELETE FROM users')
cursor.execute('DELETE FROM api_keys')

# Insert test API keys
cursor.execute('''
    INSERT INTO api_keys (api_key, name, created_at, is_active)
    VALUES 
        ('test_key_active', 'Test Active Key', ?, 1),
        ('test_key_inactive', 'Test Inactive Key', ?, 0)
''', (datetime.now().isoformat(), datetime.now().isoformat()))

conn.commit()
count = cursor.execute('SELECT COUNT(*) FROM api_keys').fetchone()[0]
print(f"Inserted {count} API keys")
conn.close()

# Fix permissions so fcgiwrap (nginx user) can write to the audit database
import os
import stat
os.chmod(audit_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)  # 0666
os.chmod(db_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)  # 0666

print("Databases initialized successfully!")
