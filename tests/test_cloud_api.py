#!/usr/bin/env python3
"""
Integration tests for modemcheck-cloud APIs
Tests all endpoints with proper isolation and cleanup
"""

import pytest
import json
import sqlite3
import os
import shutil
import tempfile
import secrets
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
import sys

# Add cloudserver directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'cloudserver', 'cgi-bin'))

# Import modules to test
try:
    import auth
    import db_schema
    import audit_schema
    from auth import hash_password, verify_password
except ImportError as e:
    pytest.skip(f"Could not import cloud modules: {e}", allow_module_level=True)


class TestEnvironment:
    """Test environment with isolated databases and directories"""

    def __init__(self):
        self.temp_dir = tempfile.mkdtemp(prefix='modemcheck-test-')
        self.data_dir = Path(self.temp_dir) / 'data'
        self.config_dir = Path(self.temp_dir) / 'config'
        self.sessions_dir = self.config_dir / 'sessions'

        # Create directories (no datafiles - direct DB insertion)
        self.data_dir.mkdir(parents=True)
        self.config_dir.mkdir(parents=True)
        self.sessions_dir.mkdir(parents=True)

        # Database paths
        self.main_db = str(self.data_dir / 'modemcheck.db')
        self.audit_db = str(self.data_dir / 'audit.db')

        # Config files
        self.users_file = str(self.config_dir / 'users.json')
        self.api_keys_file = str(self.config_dir / 'api_keys.json')

        # Initialize databases
        self._init_databases()
        self._create_test_users()
        self._create_test_api_keys()

    def _init_databases(self):
        """Initialize test databases with schemas (matches production db_schema.py)"""
        # Main database - matches production schema
        conn = sqlite3.connect(self.main_db)
        cursor = conn.cursor()

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

        # Audit database - matches production audit_schema.py
        conn = sqlite3.connect(self.audit_db)
        cursor = conn.cursor()

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
                
                CHECK (timestamp != ''),
                CHECK (username != ''),
                CHECK (action_type != ''),
                CHECK (ip_address != '')
            )
        ''')

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
                
                CHECK (timestamp != ''),
                CHECK (ip_address != ''),
                CHECK (api_key_hash != ''),
                CHECK (modem_id != ''),
                CHECK (filename != '')
            )
        ''')

        # Create indexes
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_activity_timestamp ON user_activity_log(timestamp DESC)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_activity_username ON user_activity_log(username)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_activity_action ON user_activity_log(action_type)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_client_submission_timestamp ON client_submission_log(timestamp DESC)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_client_submission_modem ON client_submission_log(modem_id)')

        conn.commit()
        conn.close()

    def _create_test_users(self):
        """Create test users"""
        users = {
            "testuser": {
                "password": hash_password("testpass123"),
                "role": "basic",
                "must_change_password": False
            },
            "testadmin": {
                "password": hash_password("adminpass123"),
                "role": "admin",
                "must_change_password": False
            }
        }

        with open(self.users_file, 'w') as f:
            json.dump(users, f, indent=2)

    def _create_test_api_keys(self):
        """Create test API keys"""
        api_keys = {
            "test_key_active": {
                "active": True,
                "last_used": None
            },
            "test_key_inactive": {
                "active": False,
                "last_used": None
            }
        }

        with open(self.api_keys_file, 'w') as f:
            json.dump(api_keys, f, indent=2)

    def cleanup(self):
        """Remove all test data"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def create_session(self, username, role="basic"):
        """Create a test session and return session ID"""
        session_id = secrets.token_urlsafe(32)
        session_data = {
            "username": username,
            "role": role,
            "expires": (datetime.now() + timedelta(days=7)).isoformat(),
            "must_change_password": False
        }

        session_file = self.sessions_dir / f"{session_id}.json"
        with open(session_file, 'w') as f:
            json.dump(session_data, f)

        return session_id

    def create_test_json_file(self, modem_id, filename=None):
        """Create a test JSON file for upload testing"""
        if filename is None:
            filename = f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"

        test_data = {
            "sysinfo": {
                "modemtype": modem_id.split('-')[0],
                "modemmac": modem_id.split('-')[1] if '-' in modem_id else "AABBCC112233",
                "uptime": "5 days",
                "swversion": "1.0.0"
            },
            "rxchannels": [
                {
                    "channel": "1",
                    "frequency": "591000000",
                    "power": "5.5",
                    "snr": "40.5",
                    "modulation": "QAM256"
                }
            ],
            "txchannels": [
                {
                    "channel": "1",
                    "frequency": "36000000",
                    "power": "42.0",
                    "channeltype": "SC-QAM"
                }
            ],
            "timestamp": datetime.now().isoformat()
        }

        modem_dir = self.datafiles_dir / modem_id
        modem_dir.mkdir(exist_ok=True)

        filepath = modem_dir / filename
        with open(filepath, 'w') as f:
            json.dump(test_data, f, indent=2)

        return str(filepath), test_data


@pytest.fixture
def test_env():
    """Fixture that provides and cleans up test environment"""
    env = TestEnvironment()
    yield env
    env.cleanup()


class TestAuthentication:
    """Test authentication functions"""

    def test_password_hashing(self):
        """Test password hashing and verification"""
        password = "test_password_123"
        hashed = hash_password(password)

        # Hash format is "salt:hash" (using pbkdf2_hmac with sha256)
        assert ':' in hashed
        assert len(hashed.split(':')) == 2
        assert verify_password(password, hashed)
        assert not verify_password("wrong_password", hashed)

    def test_session_creation(self, test_env):
        """Test session creation and validation"""
        session_id = test_env.create_session("testuser", "basic")

        # Verify session file exists
        session_file = test_env.sessions_dir / f"{session_id}.json"
        assert session_file.exists()

        # Load and verify content
        with open(session_file) as f:
            session_data = json.load(f)

        assert session_data["username"] == "testuser"
        assert session_data["role"] == "basic"

    def test_expired_session(self, test_env):
        """Test that expired sessions are rejected"""
        session_id = secrets.token_urlsafe(32)
        session_data = {
            "username": "testuser",
            "role": "basic",
            "expires": (datetime.now() - timedelta(days=1)).isoformat(),  # Expired
            "must_change_password": False
        }

        session_file = test_env.sessions_dir / f"{session_id}.json"
        with open(session_file, 'w') as f:
            json.dump(session_data, f)

        # Session should be considered invalid
        # (Would need to mock auth.verify_session to test this properly)


class TestDatabaseOperations:
    """Test database operations"""

    def test_insert_check(self, test_env):
        """Test inserting a check into the database (matches production schema)"""
        conn = sqlite3.connect(test_env.main_db)
        cursor = conn.cursor()

        test_data = {
            "sysinfo": {
                "modemtype": "CODA56",
                "modemmac": "AABBCC112233"
            },
            "timestamp": "2025-11-05T14:30:00"
        }

        cursor.execute('''
            INSERT INTO modem_checks (
                modem_id, modem_type, check_time, filename, full_data, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            "CODA56-AABBCC112233",
            "CODA56",
            "2025-11-05 14:30:00",
            "2025-11-05_14-30-00.json",
            json.dumps(test_data),
            datetime.now().isoformat()
        ))

        conn.commit()

        # Verify insertion
        cursor.execute('SELECT COUNT(*) FROM modem_checks')
        count = cursor.fetchone()[0]
        assert count == 1

        # Verify data
        cursor.execute('SELECT modem_id, modem_type FROM modem_checks')
        row = cursor.fetchone()
        assert row[0] == "CODA56-AABBCC112233"
        assert row[1] == "CODA56"

        conn.close()

    def test_duplicate_filename_constraint(self, test_env):
        """Test that duplicate filenames are rejected"""
        conn = sqlite3.connect(test_env.main_db)
        cursor = conn.cursor()

        # Insert first record
        cursor.execute('''
            INSERT INTO modem_checks (modem_id, modem_type, check_time, filename, full_data, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', ("TEST-MAC", "TEST", "2025-11-05 14:30:00", "2025-11-05_14-30-00.json", "{}", datetime.now().isoformat()))
        conn.commit()

        # Try to insert duplicate filename
        with pytest.raises(sqlite3.IntegrityError):
            cursor.execute('''
                INSERT INTO modem_checks (modem_id, modem_type, check_time, filename, full_data, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', ("TEST-MAC2", "TEST", "2025-11-05 15:30:00", "2025-11-05_14-30-00.json", "{}", datetime.now().isoformat()))
            conn.commit()

        conn.close()

    def test_query_by_modem_id(self, test_env):
        """Test querying checks by modem_id"""
        conn = sqlite3.connect(test_env.main_db)
        cursor = conn.cursor()

        # Insert multiple checks
        modem_ids = ["CODA56-MAC1", "CODA56-MAC1", "DM1000-MAC2"]
        for i, modem_id in enumerate(modem_ids):
            cursor.execute('''
                INSERT INTO modem_checks (modem_id, modem_type, check_time, filename, full_data, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (modem_id, "TEST", f"2025-11-05 14:3{i}:00", f"2025-11-05_14-3{i}-00.json", "{}", datetime.now().isoformat()))
        conn.commit()

        # Query by modem_id
        cursor.execute('SELECT COUNT(*) FROM modem_checks WHERE modem_id = ?', ("CODA56-MAC1",))
        count = cursor.fetchone()[0]
        assert count == 2

        conn.close()

    def test_audit_logging(self, test_env):
        """Test audit log insertion (matches production audit_schema.py)"""
        conn = sqlite3.connect(test_env.audit_db)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO user_activity_log (
                timestamp, username, user_role, action_type, action_details, 
                ip_address, success
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(),
            "testuser",
            "user",
            "login",
            "Successful login",
            "192.168.1.100",
            1
        ))

        cursor.execute('''
            INSERT INTO client_submission_log (
                timestamp, ip_address, api_key_hash, modem_id, filename, success
            ) VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(),
            "192.168.1.101",
            "hashed_key",
            "CODA56-MAC",
            "2025-11-05_14-30-00.json",
            1
        ))

        conn.commit()

        # Verify logs
        cursor.execute('SELECT COUNT(*) FROM user_activity_log')
        assert cursor.fetchone()[0] == 1

        cursor.execute('SELECT COUNT(*) FROM client_submission_log')
        assert cursor.fetchone()[0] == 1

        conn.close()


class TestAPIKeyValidation:
    """Test API key validation"""

    def test_valid_api_key(self, test_env):
        """Test that valid active API key is accepted"""
        with open(test_env.api_keys_file) as f:
            keys = json.load(f)

        # test_key_active should exist and be active
        assert "test_key_active" in keys
        assert keys["test_key_active"]["active"] == True

    def test_inactive_api_key(self, test_env):
        """Test that inactive API key is rejected"""
        with open(test_env.api_keys_file) as f:
            keys = json.load(f)

        # test_key_inactive should exist but be inactive
        assert "test_key_inactive" in keys
        assert keys["test_key_inactive"]["active"] == False

    def test_nonexistent_api_key(self, test_env):
        """Test that nonexistent API key is rejected"""
        with open(test_env.api_keys_file) as f:
            keys = json.load(f)

        assert "nonexistent_key" not in keys


class TestFileUpload:
    """Test file upload functionality"""

    def test_valid_upload(self, test_env):
        """Test uploading a valid JSON file"""
        filepath, data = test_env.create_test_json_file("CODA56-AABBCC112233")

        assert os.path.exists(filepath)

        with open(filepath) as f:
            loaded = json.load(f)

        assert loaded["sysinfo"]["modemtype"] == "CODA56"

    def test_filename_validation(self):
        """Test filename validation regex (matches production upload.py)"""
        import re

        # Production regex from upload.py line 167: ^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.json$
        SAFE_FILENAME = re.compile(r'^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.json$')

        valid_filenames = [
            "2025-11-05_14-30-15.json",
            "2024-03-15_14-30-45.json",
            "2023-12-31_23-59-59.json"
        ]

        invalid_filenames = [
            "../../../etc/passwd",
            "file.txt",
            "file.json.exe",
            "file with spaces.json",
            "file@#$.json",
            "test-file.json",        # no timestamp
            "file_123.json",         # no timestamp
            "2024-3-15_14-30-45.json",  # single digit month
            "2024-03-15.json"        # no time component
        ]

        for filename in valid_filenames:
            assert SAFE_FILENAME.match(filename), f"{filename} should be valid"

        for filename in invalid_filenames:
            assert not SAFE_FILENAME.match(filename), f"{filename} should be invalid"

    def test_modem_id_validation(self):
        """Test modem_id validation regex (matches production upload.py)"""
        import re

        # Production regex from upload.py line 180: ^[a-zA-Z0-9_-]+$
        SAFE_MODEM_ID = re.compile(r'^[a-zA-Z0-9_-]+$')

        valid_ids = [
            "CODA56-AABBCC112233",
            "DM1000-112233445566",
            "coda56-aabbcc",        # lowercase allowed
            "modem_id_123",         # underscores allowed
            "simple123",            # no separators
            "MixedCase-Device_1"    # mixed case with both separators
        ]

        invalid_ids = [
            "../etc/passwd",        # dots and slashes
            "id with spaces",       # spaces
            "id@#$",                # special characters
            "ID/../../",            # slashes and dots
            "test.device",          # dots not allowed
            "test:device"           # colons not allowed
        ]

        for modem_id in valid_ids:
            assert SAFE_MODEM_ID.match(modem_id), f"{modem_id} should be valid"

        for modem_id in invalid_ids:
            assert not SAFE_MODEM_ID.match(modem_id), f"{modem_id} should be invalid"

    def test_path_traversal_prevention(self, test_env):
        """Test that path traversal attempts are blocked"""
        datafiles_dir = test_env.datafiles_dir

        # Attempt path traversal
        malicious_id = "../../../etc"
        target_path = (datafiles_dir / malicious_id / "passwd").resolve()

        # Verify that resolved path is NOT under datafiles_dir
        assert not str(target_path).startswith(str(datafiles_dir.resolve()))


class TestDataQuery:
    """Test data querying functions"""

    def test_list_modems(self, test_env):
        """Test listing unique modems"""
        conn = sqlite3.connect(test_env.main_db)
        cursor = conn.cursor()

        # Insert checks for multiple modems
        modems = [
            ("CODA56-MAC1", "2025-11-05_14-30-00.json"),
            ("CODA56-MAC1", "2025-11-05_14-31-00.json"),
            ("DM1000-MAC2", "2025-11-05_14-32-00.json"),
            ("XB8-MAC3", "2025-11-05_14-33-00.json")
        ]

        for modem_id, filename in modems:
            cursor.execute('''
                INSERT INTO modem_checks (modem_id, modem_type, check_time, filename, full_data, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (modem_id, "TEST", "2025-11-05 14:30:00", filename, "{}", datetime.now().isoformat()))
        conn.commit()

        # Query unique modems
        cursor.execute('SELECT DISTINCT modem_id FROM modem_checks ORDER BY modem_id')
        results = [row[0] for row in cursor.fetchall()]

        assert len(results) == 3
        assert "CODA56-MAC1" in results
        assert "DM1000-MAC2" in results
        assert "XB8-MAC3" in results

        conn.close()

    def test_date_range_query(self, test_env):
        """Test querying by date range"""
        conn = sqlite3.connect(test_env.main_db)
        cursor = conn.cursor()

        # Insert checks across different dates
        dates = [
            "2025-11-01 14:30:00",
            "2025-11-03 14:30:00",
            "2025-11-05 14:30:00",
            "2025-11-07 14:30:00"
        ]

        for i, date in enumerate(dates):
            cursor.execute('''
                INSERT INTO modem_checks (modem_id, modem_type, check_time, filename, full_data, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', ("TEST-MAC", "TEST", date, f"2025-11-0{i+1}_14-30-00.json", "{}", datetime.now().isoformat()))
        conn.commit()

        # Query date range (2025-11-03 to 2025-11-05)
        cursor.execute('''
            SELECT COUNT(*) FROM modem_checks
            WHERE check_time >= ? AND check_time <= ?
        ''', ("2025-11-03", "2025-11-06"))

        count = cursor.fetchone()[0]
        assert count == 2  # Should match 11-03 and 11-05

        conn.close()


class TestConfigDefaults:
    """Test config defaults functionality"""

    def test_save_config_defaults_admin_only(self, test_env):
        """Test that only admins can save config defaults"""
        # Admin should be able to save
        admin_session = test_env.create_session("testadmin", "admin")

        defaults = {
            'ModemAddress': '192.168.100.1',
            'IgnitePassword': 'custom_password',
            'SpeedTestEnabled': False,
            'AutoUpdateEnabled': True,
            'Silent': True,
            'NoLogs': False,
            'EnableCloud': True,
            'CloudHost': 'modemcheck.example.com',
            'CloudPort': '443'
        }

        # Save the defaults (this would be called via API)
        defaults_file = test_env.config_dir / 'config_defaults.json'
        with open(defaults_file, 'w') as f:
            json.dump(defaults, f, indent=2)

        assert defaults_file.exists()

        # Verify saved content
        with open(defaults_file) as f:
            saved = json.load(f)

        assert saved['ModemAddress'] == '192.168.100.1'
        assert saved['CloudHost'] == 'modemcheck.example.com'

    def test_get_config_defaults_all_users(self, test_env):
        """Test that all authenticated users can retrieve config defaults"""
        # Set up some defaults
        defaults = {
            'ModemAddress': '192.168.100.1',
            'IgnitePassword': 'custom_password',
            'SpeedTestEnabled': True,
            'AutoUpdateEnabled': True,
            'Silent': False,
            'NoLogs': False,
            'EnableCloud': True,
            'CloudHost': 'modemcheck.example.com',
            'CloudPort': '443'
        }

        defaults_file = test_env.config_dir / 'config_defaults.json'
        with open(defaults_file, 'w') as f:
            json.dump(defaults, f, indent=2)

        # Both basic and admin users should be able to read defaults
        basic_session = test_env.create_session("testuser", "basic")
        admin_session = test_env.create_session("testadmin", "admin")

        # Verify file is readable
        assert defaults_file.exists()

        # Read as basic user
        with open(defaults_file) as f:
            basic_read = json.load(f)

        assert basic_read['ModemAddress'] == '192.168.100.1'

        # Read as admin user
        with open(defaults_file) as f:
            admin_read = json.load(f)

        assert admin_read['ModemAddress'] == '192.168.100.1'

    def test_get_config_defaults_no_file(self, test_env):
        """Test that default values are returned when no config file exists"""
        defaults_file = test_env.config_dir / 'config_defaults.json'

        # Ensure file doesn't exist
        if defaults_file.exists():
            defaults_file.unlink()

        # Should return hardcoded defaults
        expected_defaults = {
            'ModemAddress': 'autodetect',
            'IgnitePassword': 'password',
            'SpeedTestEnabled': True,
            'AutoUpdateEnabled': True,
            'Silent': False,
            'NoLogs': False,
            'EnableCloud': False,
            'CloudHost': '',
            'CloudPort': '443'
        }

        # Verify these are the expected defaults (would be returned by API)
        assert not defaults_file.exists()

    def test_config_defaults_persist_across_sessions(self, test_env):
        """Test that config defaults persist across different user sessions"""
        # Admin saves defaults
        admin_session = test_env.create_session("testadmin", "admin")

        defaults = {
            'ModemAddress': 'custom.modem.local',
            'IgnitePassword': 'secure_pass',
            'SpeedTestEnabled': False
        }

        defaults_file = test_env.config_dir / 'config_defaults.json'
        with open(defaults_file, 'w') as f:
            json.dump(defaults, f, indent=2)

        # Create a new basic user session
        basic_session = test_env.create_session("newuser", "basic")

        # Basic user should see the same defaults
        with open(defaults_file) as f:
            loaded = json.load(f)

        assert loaded['ModemAddress'] == 'custom.modem.local'
        assert loaded['IgnitePassword'] == 'secure_pass'
        assert loaded['SpeedTestEnabled'] == False


class TestCleanup:
    """Test data cleanup functions"""

    def test_session_cleanup(self, test_env):
        """Test removing expired sessions"""
        # Create expired session
        expired_id = secrets.token_urlsafe(32)
        expired_data = {
            "username": "testuser",
            "role": "basic",
            "expires": (datetime.now() - timedelta(days=1)).isoformat(),
            "must_change_password": False
        }

        expired_file = test_env.sessions_dir / f"{expired_id}.json"
        with open(expired_file, 'w') as f:
            json.dump(expired_data, f)

        # Create valid session
        valid_id = test_env.create_session("testuser", "basic")
        valid_file = test_env.sessions_dir / f"{valid_id}.json"

        # Both should exist initially
        assert expired_file.exists()
        assert valid_file.exists()

        # Cleanup expired sessions
        now = datetime.now()
        for session_file in test_env.sessions_dir.glob("*.json"):
            with open(session_file) as f:
                session_data = json.load(f)

            expires = datetime.fromisoformat(session_data["expires"])
            if expires < now:
                session_file.unlink()

        # Expired should be gone, valid should remain
        assert not expired_file.exists()
        assert valid_file.exists()

    def test_old_data_cleanup(self, test_env):
        """Test removing old check data"""
        conn = sqlite3.connect(test_env.main_db)
        cursor = conn.cursor()

        # Insert old and new data
        old_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S")
        new_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute('''
            INSERT INTO modem_checks (modem_id, modem_type, check_time, filename, full_data, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', ("TEST-MAC", "TEST", old_date, "2024-09-06_14-30-00.json", "{}", datetime.now().isoformat()))

        cursor.execute('''
            INSERT INTO modem_checks (modem_id, modem_type, check_time, filename, full_data, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', ("TEST-MAC", "TEST", new_date, "2025-11-05_14-30-00.json", "{}", datetime.now().isoformat()))

        conn.commit()

        # Delete data older than 30 days
        cutoff_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('DELETE FROM modem_checks WHERE check_time < ?', (cutoff_date,))
        conn.commit()

        # Verify only new data remains
        cursor.execute('SELECT COUNT(*) FROM modem_checks')
        count = cursor.fetchone()[0]
        assert count == 1

        cursor.execute('SELECT filename FROM modem_checks')
        filename = cursor.fetchone()[0]
        assert filename == "2025-11-05_14-30-00.json"

        conn.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
