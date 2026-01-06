"""
Pytest configuration and fixtures for ModemCheck Cloud v2 tests.

Provides:
- Test client setup
- Database fixtures
- Authentication fixtures
- Test data generation
"""
import os
import sys
import json
import pytest
import hashlib
import time
from datetime import datetime, timezone
from typing import AsyncGenerator, Dict, Any
from pathlib import Path

import httpx
from faker import Faker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
import redis.asyncio as aioredis

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import Base, get_db
from app.core.security import hash_password, create_session
from app.core.utils import utc_now
from app.models import User, APIKey, ModemCheck
from app.core.config import settings

# ============================================================================
# TEST CONFIGURATION
# ============================================================================

# Test server URL
TEST_BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:22560")

# Faker instance for generating test data
fake = Faker()


# ============================================================================
# DATABASE FIXTURES
# ============================================================================

@pytest.fixture(scope="session")
def database_url():
    """Get database URL for testing."""
    return settings.database_url


@pytest.fixture(scope="function")
async def async_db_engine(database_url):
    """Create async database engine for testing."""
    engine = create_async_engine(
        database_url,
        poolclass=NullPool,  # Don't pool connections in tests
        echo=False
    )

    # Don't create tables here - FastAPI app creates them on startup
    # Just yield the engine for test fixtures to use

    yield engine

    # Don't drop tables - they're managed by the FastAPI app lifecycle
    # Just dispose the engine
    await engine.dispose()


@pytest.fixture(scope="function")
async def db_session(async_db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create async database session for testing."""
    async_session_maker = async_sessionmaker(
        async_db_engine,
        class_=AsyncSession,
        expire_on_commit=False
    )

    async with async_session_maker() as session:
        yield session
        await session.close()  # Explicitly close session


@pytest.fixture(scope="function", autouse=True)
async def clear_redis():
    """Clear Redis data between tests to ensure isolation."""
    from redis.asyncio import Redis
    from app.core.config import settings
    from app.core.security import get_redis
    from app.core.cache_provider import init_cache, close_cache

    # Build Redis URL with optional password
    # Note: Test environment may have REDIS_PASSWORD set from .env file,
    # so we need to include password if configured
    if settings.redis_password:
        redis_url_db0 = f"redis://:{settings.redis_password}@{settings.redis_host}:{settings.redis_port}/0"
        redis_url_db1 = f"redis://:{settings.redis_password}@{settings.redis_host}:{settings.redis_port}/1"
    else:
        redis_url_db0 = f"redis://{settings.redis_host}:{settings.redis_port}/0"
        redis_url_db1 = f"redis://{settings.redis_host}:{settings.redis_port}/1"

    # Clear DB 0 (sessions, API keys, brute force tracking)
    redis_db0 = await Redis.from_url(
        redis_url_db0,
        encoding="utf-8",
        decode_responses=True,
    )

    # Clear DB 1 (rate limiting - though disabled in tests)
    redis_db1 = await Redis.from_url(
        redis_url_db1,
        encoding="utf-8",
        decode_responses=True,
    )

    # Clear all Redis data before test
    await redis_db0.flushdb()
    await redis_db1.flushdb()

    # Initialize cache provider for tests
    redis_client = await get_redis()
    await init_cache(redis_client, enable_fallback=True)

    yield

    # Close cache
    await close_cache()

    # Clear all Redis data after test
    await redis_db0.flushdb()
    await redis_db1.flushdb()
    await redis_db0.close()
    await redis_db1.close()


# ============================================================================
# HTTP CLIENT FIXTURES
# ============================================================================

@pytest.fixture(scope="function")
async def http_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Create async HTTP client for API testing with cookie tracking enabled."""
    async with httpx.AsyncClient(
        base_url=TEST_BASE_URL,
        timeout=30.0,
        follow_redirects=True,
        cookies=httpx.Cookies()  # Enable cookie jar for session tracking
    ) as client:
        yield client


@pytest.fixture(scope="function")
async def authenticated_client(http_client: httpx.AsyncClient, admin_user_credentials: Dict[str, str]) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Create authenticated HTTP client with admin session."""
    # Login
    response = await http_client.post("/api/auth/login", json=admin_user_credentials)
    assert response.status_code == 200
    
    # Client now has session cookie
    yield http_client


# ============================================================================
# USER FIXTURES
# ============================================================================

@pytest.fixture(scope="function")
def admin_user_credentials() -> Dict[str, str]:
    """Default admin user credentials."""
    return {
        "username": "admin",
        "password": "TestPass123!"
    }


@pytest.fixture(scope="function")
def elevated_user_credentials() -> Dict[str, str]:
    """Default elevated user credentials."""
    return {
        "username": "test_elevated",
        "password": "ElevatedPass123!"
    }


@pytest.fixture(scope="function")
def basic_user_credentials() -> Dict[str, str]:
    """Default basic user credentials."""
    return {
        "username": "test_basic",
        "password": "BasicPass123!"
    }


@pytest.fixture(scope="function")
async def admin_user(db_session: AsyncSession, admin_user_credentials: Dict[str, str]) -> User:
    """Get or create admin user in database."""
    from sqlalchemy import select, update

    # Try to get existing admin user first (created by FastAPI startup)
    result = await db_session.execute(
        select(User).where(User.username == admin_user_credentials["username"])
    )
    user = result.scalars().first()

    if user is not None:
        # Reset password to test default (in case previous test changed it)
        await db_session.execute(
            update(User)
            .where(User.username == admin_user_credentials["username"])
            .values(password_hash=hash_password(admin_user_credentials["password"]))
        )
        await db_session.commit()
        await db_session.refresh(user)
        return user

    # Create if doesn't exist (shouldn't happen in test env, but fallback)
    user = User(
        username=admin_user_credentials["username"],
        password_hash=hash_password(admin_user_credentials["password"]),
        role="admin",
        created_at=utc_now(),
        must_change_password=False
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
async def elevated_user(db_session: AsyncSession, elevated_user_credentials: Dict[str, str]) -> User:
    """Get or create elevated user in database."""
    from sqlalchemy import select, update

    # Try to get existing user first
    result = await db_session.execute(
        select(User).where(User.username == elevated_user_credentials["username"])
    )
    user = result.scalars().first()

    if user is not None:
        # Reset password to test default (in case previous test changed it)
        await db_session.execute(
            update(User)
            .where(User.username == elevated_user_credentials["username"])
            .values(password_hash=hash_password(elevated_user_credentials["password"]))
        )
        await db_session.commit()
        await db_session.refresh(user)
        return user

    # Create if doesn't exist
    user = User(
        username=elevated_user_credentials["username"],
        password_hash=hash_password(elevated_user_credentials["password"]),
        role="elevated",
        created_at=utc_now(),
        must_change_password=False
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
async def basic_user(db_session: AsyncSession, basic_user_credentials: Dict[str, str]) -> User:
    """Get or create basic user in database."""
    from sqlalchemy import select, update

    # Try to get existing user first
    result = await db_session.execute(
        select(User).where(User.username == basic_user_credentials["username"])
    )
    user = result.scalars().first()

    if user is not None:
        # Reset password to test default (in case previous test changed it)
        await db_session.execute(
            update(User)
            .where(User.username == basic_user_credentials["username"])
            .values(password_hash=hash_password(basic_user_credentials["password"]))
        )
        await db_session.commit()
        await db_session.refresh(user)
        return user

    # Create if doesn't exist
    user = User(
        username=basic_user_credentials["username"],
        password_hash=hash_password(basic_user_credentials["password"]),
        role="basic",
        created_at=utc_now(),
        must_change_password=False
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
async def test_user_must_change_password(db_session: AsyncSession) -> User:
    """Create a user that must change their password (for testing password change flow)."""
    from sqlalchemy import select, delete

    test_username = "test_must_change_user"
    test_password = "TempPassword123!"

    # Clean up any existing user with this username
    await db_session.execute(
        delete(User).where(User.username == test_username)
    )
    await db_session.commit()

    # Create user with must_change_password=True
    user = User(
        username=test_username,
        password_hash=hash_password(test_password),
        role="basic",
        created_at=utc_now(),
        must_change_password=True
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ============================================================================
# SESSION/TOKEN FIXTURES
# ============================================================================

@pytest.fixture(scope="function")
async def admin_session_token(admin_user: User) -> str:
    """Create session token for admin user."""
    return await create_session(admin_user.username, admin_user.role.value)


@pytest.fixture(scope="function")
async def elevated_session_token(elevated_user: User) -> str:
    """Create session token for elevated user."""
    return await create_session(elevated_user.username, elevated_user.role.value)


@pytest.fixture(scope="function")
async def basic_session_token(basic_user: User) -> str:
    """Create session token for basic user."""
    return await create_session(basic_user.username, basic_user.role.value)


@pytest.fixture(scope="function")
async def test_admin_session(admin_session_token: str) -> str:
    """Alias for admin_session_token for test compatibility."""
    return admin_session_token


@pytest.fixture(scope="function")
async def test_basic_session(basic_session_token: str) -> str:
    """Alias for basic_session_token for test compatibility."""
    return basic_session_token


@pytest.fixture(scope="function")
async def admin_client_with_token(http_client: httpx.AsyncClient, admin_user: User, admin_user_credentials: Dict[str, str]) -> AsyncGenerator[httpx.AsyncClient, None]:
    """HTTP client with admin session cookie obtained via login."""
    # Ensure user exists (via admin_user fixture dependency)
    # Login to get real session cookie
    response = await http_client.post("/api/auth/login", json=admin_user_credentials)
    assert response.status_code == 200, f"Admin login failed: {response.text}"
    assert "modemcheck_session" in response.cookies, "No session cookie returned"
    yield http_client


@pytest.fixture(scope="function")
async def elevated_client_with_token(http_client: httpx.AsyncClient, elevated_user: User, elevated_user_credentials: Dict[str, str]) -> AsyncGenerator[httpx.AsyncClient, None]:
    """HTTP client with elevated session cookie obtained via login."""
    # Ensure user exists (via elevated_user fixture dependency)
    # Login to get real session cookie
    response = await http_client.post("/api/auth/login", json=elevated_user_credentials)
    assert response.status_code == 200, f"Elevated login failed: {response.text}"
    assert "modemcheck_session" in response.cookies, "No session cookie returned"
    yield http_client


@pytest.fixture(scope="function")
async def basic_client_with_token(http_client: httpx.AsyncClient, basic_user: User, basic_user_credentials: Dict[str, str]) -> AsyncGenerator[httpx.AsyncClient, None]:
    """HTTP client with basic session cookie obtained via login."""
    # Ensure user exists (via basic_user fixture dependency)
    # Login to get real session cookie
    response = await http_client.post("/api/auth/login", json=basic_user_credentials)
    assert response.status_code == 200, f"Basic login failed: {response.text}"
    assert "modemcheck_session" in response.cookies, "No session cookie returned"
    yield http_client


# ============================================================================
# API KEY FIXTURES
# ============================================================================

@pytest.fixture(scope="function")
def test_api_key() -> str:
    """Generate test API key."""
    import secrets
    return secrets.token_hex(32)


@pytest.fixture(scope="function")
async def active_api_key(db_session: AsyncSession, test_api_key: str) -> APIKey:
    """Create active API key in database with dual storage (v7.1+)."""
    from app.core.api_key_crypto import encrypt_api_key_for_storage

    # Hash + encrypt for dual storage
    api_key_hash, encrypted_hex, salt_hex = encrypt_api_key_for_storage(test_api_key)

    api_key = APIKey(
        api_key_hash=api_key_hash,  # Hash for validation (primary key)
        api_key_encrypted=encrypted_hex,  # Encrypted for reveal
        encryption_salt=salt_hex,  # Salt for decryption
        name="test_key_active",
        created_at=utc_now(),
        is_active=True
    )
    db_session.add(api_key)
    await db_session.commit()
    await db_session.refresh(api_key)
    return api_key


@pytest.fixture(scope="function")
async def inactive_api_key(db_session: AsyncSession) -> APIKey:
    """Create inactive API key in database with dual storage (v7.1+)."""
    import secrets
    from app.core.api_key_crypto import encrypt_api_key_for_storage

    plaintext_key = secrets.token_hex(32)

    # Hash + encrypt for dual storage
    api_key_hash, encrypted_hex, salt_hex = encrypt_api_key_for_storage(plaintext_key)

    api_key = APIKey(
        api_key_hash=api_key_hash,  # Hash for validation (primary key)
        api_key_encrypted=encrypted_hex,  # Encrypted for reveal
        encryption_salt=salt_hex,  # Salt for decryption
        name="test_key_inactive",
        created_at=utc_now(),
        is_active=False
    )
    db_session.add(api_key)
    await db_session.commit()
    await db_session.refresh(api_key)
    return api_key


# ============================================================================
# MODEM CHECK FIXTURES
# ============================================================================

@pytest.fixture(scope="function")
def sample_modem_check_data() -> Dict[str, Any]:
    """Generate sample modem check JSON data."""
    check_time = int(time.time())
    modem_mac = "AA:BB:CC:DD:EE:FF"
    modem_type = "XB8"
    
    return {
        "sysinfo": {
            "checktime": check_time,
            "modemmac": modem_mac,
            "modemtype": modem_type,
            "clientversion": "6.0.0"
        },
        "downstream": [
            {
                "channel_id": 1,
                "frequency": 555000000,
                "power": 5.2,
                "snr": 40.5,
                "modulation": "256-QAM",
                "corrected": 0,
                "uncorrected": 0
            }
        ],
        "upstream": [
            {
                "channel_id": 1,
                "frequency": 36000000,
                "power": 45.0,
                "modulation": "ATDMA",
                "symbol_rate": 5120
            }
        ],
        "diagnostics": {
            "public_ip": "203.0.113.1",
            "isp": "Test ISP",
            "download_mbps": 500,
            "upload_mbps": 50,
            "ping_ms": 15
        }
    }


@pytest.fixture(scope="function")
async def sample_modem_check(db_session: AsyncSession, sample_modem_check_data: Dict[str, Any]) -> ModemCheck:
    """Create sample modem check in database."""
    import uuid
    sysinfo = sample_modem_check_data["sysinfo"]
    modem_id = f"{sysinfo['modemtype']}-{sysinfo['modemmac']}"

    # Use unique filename with UUID to prevent duplicate key violations
    unique_id = str(uuid.uuid4())[:8]
    timestamp = datetime.utcfromtimestamp(sysinfo["checktime"]).strftime("%Y-%m-%d_%H-%M-%S")
    unique_filename = f"{modem_id}/{timestamp}_{unique_id}.json"

    check = ModemCheck(
        modem_id=modem_id,
        modem_type=sysinfo["modemtype"],
        check_time=datetime.utcfromtimestamp(sysinfo["checktime"]),
        filename=unique_filename,
        full_data=sample_modem_check_data,
        created_at=utc_now()
    )
    db_session.add(check)
    await db_session.commit()
    await db_session.refresh(check)
    return check


@pytest.fixture(scope="function")
async def sample_modem_checks_in_db(db_session: AsyncSession, sample_modem_check_data: Dict[str, Any]) -> list[ModemCheck]:
    """Create multiple sample modem checks in database for testing queries."""
    import uuid
    checks = []
    sysinfo = sample_modem_check_data["sysinfo"]
    base_modem_id = f"{sysinfo['modemtype']}-{sysinfo['modemmac']}"
    base_timestamp = sysinfo["checktime"]

    # Create 3 checks with different timestamps for the same modem
    for i in range(3):
        timestamp = base_timestamp + (i * 3600)  # 1 hour apart
        modem_id = base_modem_id

        # Use unique filename with UUID to prevent duplicate key violations
        unique_id = str(uuid.uuid4())[:8]
        dt = datetime.utcfromtimestamp(timestamp)
        unique_filename = f"{modem_id}/{dt.strftime('%Y-%m-%d_%H-%M-%S')}_{unique_id}.json"

        check = ModemCheck(
            modem_id=modem_id,
            modem_type=sysinfo["modemtype"],
            check_time=dt,
            filename=unique_filename,
            full_data=sample_modem_check_data,
            created_at=utc_now()
        )
        db_session.add(check)
        checks.append(check)

    await db_session.commit()
    for check in checks:
        await db_session.refresh(check)

    return checks


# ============================================================================
# REAL MODEM DATA FIXTURES
# ============================================================================

@pytest.fixture(scope="session")
def real_modem_data() -> Dict[str, list[Dict[str, Any]]]:
    """Load all anonymized real modem check data.

    Returns dictionary with keys "xb8", "dm1000", "coda56" mapping to lists of checks.
    Data is loaded once per test session for efficiency.
    """
    from tests.fixtures.modem_data.loader import load_all_fixture_data
    return load_all_fixture_data()


@pytest.fixture(scope="function")
async def populated_modem_database(
    db_session: AsyncSession,
    real_modem_data: Dict[str, list[Dict[str, Any]]]
) -> Dict[str, list[ModemCheck]]:
    """Populate database with real modem checks for comprehensive testing.

    Creates all checks from all 3 modem types (75 total checks).
    Returns dictionary mapping modem_type to list of ModemCheck objects.
    """
    import uuid
    from tests.fixtures.modem_data.loader import get_modem_ids

    modem_ids = get_modem_ids()
    result = {"xb8": [], "dm1000": [], "coda56": []}

    for modem_type, checks in real_modem_data.items():
        modem_id = modem_ids[modem_type]

        for i, check_data in enumerate(checks):
            sysinfo = check_data.get("sysinfo", {})
            check_time = sysinfo.get("checktime", int(time.time()) + i)

            # Create unique filename
            unique_id = str(uuid.uuid4())[:8]
            dt = datetime.utcfromtimestamp(check_time)  # Naive UTC
            filename = f"{modem_id}/{dt.strftime('%Y-%m-%d_%H-%M-%S')}_{unique_id}.json"

            # Determine modem type from data or ID
            detected_type = sysinfo.get("modemtype", modem_type.upper())

            check = ModemCheck(
                modem_id=modem_id,
                modem_type=detected_type,
                check_time=dt,
                filename=filename,
                full_data=check_data,
                created_at=utc_now()
            )
            db_session.add(check)
            result[modem_type].append(check)

    await db_session.commit()

    # Refresh all checks
    for modem_type in result:
        for check in result[modem_type]:
            await db_session.refresh(check)

    return result


@pytest.fixture(scope="function")
async def single_modem_populated(
    db_session: AsyncSession,
    real_modem_data: Dict[str, list[Dict[str, Any]]]
) -> tuple[str, list[ModemCheck]]:
    """Populate database with real checks from just one modem (XB8).

    Useful for simpler tests that don't need all 3 modems.
    Returns tuple of (modem_id, list of ModemCheck objects).
    """
    import uuid
    from tests.fixtures.modem_data.loader import get_modem_ids

    modem_ids = get_modem_ids()
    modem_id = modem_ids["xb8"]
    checks = []

    for i, check_data in enumerate(real_modem_data["xb8"]):
        sysinfo = check_data.get("sysinfo", {})
        check_time = sysinfo.get("checktime", int(time.time()) + i)

        # Create unique filename
        unique_id = str(uuid.uuid4())[:8]
        dt = datetime.utcfromtimestamp(check_time)  # Naive UTC
        filename = f"{modem_id}/{dt.strftime('%Y-%m-%d_%H-%M-%S')}_{unique_id}.json"

        check = ModemCheck(
            modem_id=modem_id,
            modem_type=sysinfo.get("modemtype", "XB8"),
            check_time=dt,
            filename=filename,
            full_data=check_data,
            created_at=utc_now()
        )
        db_session.add(check)
        checks.append(check)

    await db_session.commit()
    for check in checks:
        await db_session.refresh(check)

    return (modem_id, checks)


# ============================================================================
# UI TEST DATA FIXTURES
# ============================================================================

@pytest.fixture(scope="function")
async def ui_client_config():
    """Create a ClientConfig record for UI tests.

    This fixture creates its own database connection and commits data directly,
    making it visible to the Docker web server. Cleans up data after test.

    Returns tuple of (api_key_preview, modem_id) for test use.
    """
    import asyncio
    import secrets
    import hashlib
    import json
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import delete
    import os

    from app.models import APIKey
    from app.models.client_config import ClientConfig, ConfigStatus
    from app.core.utils import utc_now
    from app.core.api_key_crypto import encrypt_api_key_for_storage
    from app.core.config_encryption import generate_salt, _encrypt_sync

    # Create async engine for test database
    db_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://modemcheck:modemcheck_test_password@localhost:5433/modemcheck_test"
    )
    engine = create_async_engine(db_url, echo=False)
    async_session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Generate unique test API key
    plaintext_key = secrets.token_hex(32)
    api_key_hash, encrypted_hex, salt_hex = encrypt_api_key_for_storage(plaintext_key)

    # Test modem ID for this config
    test_modem_id = "UI-TEST-AA:BB:CC:DD:EE:FF"

    # Simple config for testing
    config_plaintext = {
        "SpeedTestEnabled": True,
        "SpeedTestInterval": 5,
        "AutoUpdateEnabled": True,
        "UpdateChannel": "stable"
    }

    # Generate config hash (SHA256 of canonical JSON)
    canonical_json = json.dumps(config_plaintext, sort_keys=True, separators=(',', ':'))
    config_hash = hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()

    # Encrypt config (synchronous version since we're in test)
    config_salt = generate_salt()
    config_encrypted, _ = _encrypt_sync(config_plaintext, config_salt)

    async with async_session_factory() as session:
        # Clean up any existing test data first
        await session.execute(
            delete(ClientConfig).where(ClientConfig.last_seen_modem_id == test_modem_id)
        )
        await session.execute(
            delete(APIKey).where(APIKey.name == "ui_test_config_key")
        )

        # Create API key (v8.0+: no plaintext column)
        api_key = APIKey(
            api_key_hash=api_key_hash,
            api_key_encrypted=encrypted_hex,
            encryption_salt=salt_hex,
            name="ui_test_config_key",
            created_at=utc_now(),
            is_active=True
        )
        session.add(api_key)
        await session.flush()  # Ensure API key exists before creating config

        # Create ClientConfig (v8.0+: no plaintext column, api_key_hash is PK)
        client_config = ClientConfig(
            api_key_hash=api_key_hash,
            last_seen_modem_id=test_modem_id,
            config_plaintext=config_plaintext,
            config_encrypted=config_encrypted,
            config_hash=config_hash,
            encryption_salt=config_salt,  # Required NOT NULL field
            status=ConfigStatus.UNMANAGED,
            version=1,
            created_at=utc_now(),
            created_by="test_fixture",  # Required NOT NULL field
            updated_at=utc_now(),
            updated_by="test_fixture",  # Required NOT NULL field
        )
        session.add(client_config)
        await session.commit()

    # Return preview (first 8 chars) and modem ID for test use
    api_key_preview = plaintext_key[:8]

    yield (api_key_preview, test_modem_id)

    # Cleanup: remove test data after test completes
    async with async_session_factory() as session:
        await session.execute(
            delete(ClientConfig).where(ClientConfig.last_seen_modem_id == test_modem_id)
        )
        await session.execute(
            delete(APIKey).where(APIKey.name == "ui_test_config_key")
        )
        await session.commit()

    await engine.dispose()


@pytest.fixture(scope="function")
async def ui_modem_data(real_modem_data: Dict[str, list[Dict[str, Any]]]) -> list[str]:
    """Populate database with real modem data for UI tests.

    This fixture creates its own database connection and commits data directly,
    making it visible to the Docker web server. Cleans up data after test.

    Returns list of modem IDs that were populated.
    """
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import delete
    import uuid
    import os

    from app.models import ModemCheck
    from app.core.utils import utc_now
    from tests.fixtures.modem_data.loader import get_modem_ids

    # Create async engine for test database
    db_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://modemcheck:modemcheck_test_password@localhost:5433/modemcheck_test"
    )
    engine = create_async_engine(db_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    modem_ids_map = get_modem_ids()
    created_ids = list(modem_ids_map.values())

    async with async_session() as session:
        # Clean up any existing test modem data first
        for modem_type, modem_id in modem_ids_map.items():
            await session.execute(
                delete(ModemCheck).where(ModemCheck.modem_id == modem_id)
            )

        # Insert real modem data
        for modem_type, checks in real_modem_data.items():
            modem_id = modem_ids_map[modem_type]

            for i, check_data in enumerate(checks):
                sysinfo = check_data.get("sysinfo", {})
                check_time = sysinfo.get("checktime", int(time.time()) + i)

                # Create unique filename
                unique_id = str(uuid.uuid4())[:8]
                dt = datetime.utcfromtimestamp(check_time)
                filename = f"{modem_id}/{dt.strftime('%Y-%m-%d_%H-%M-%S')}_{unique_id}.json"

                # Determine modem type from data or ID
                detected_type = sysinfo.get("modemtype", modem_type.upper())

                check = ModemCheck(
                    modem_id=modem_id,
                    modem_type=detected_type,
                    check_time=dt,
                    filename=filename,
                    full_data=check_data,
                    created_at=utc_now()
                )
                session.add(check)

        await session.commit()

    # Small delay to ensure database changes are visible to web server
    await asyncio.sleep(0.5)

    yield created_ids

    # Cleanup: remove test data after test completes
    async with async_session() as session:
        for modem_id in created_ids:
            await session.execute(
                delete(ModemCheck).where(ModemCheck.modem_id == modem_id)
            )
        await session.commit()

    await engine.dispose()


# ============================================================================
# CSRF TOKEN FIXTURES
# ============================================================================

@pytest.fixture(scope="function")
async def csrf_token(admin_client_with_token: httpx.AsyncClient) -> str:
    """Get CSRF token for admin user authenticated requests."""
    # Client is already authenticated from admin_client_with_token
    response = await admin_client_with_token.get("/api/auth/session_check")
    assert response.status_code == 200, f"Session check failed: {response.text}"
    data = response.json()
    assert "csrf_token" in data, f"No CSRF token in response: {data}"
    return data["csrf_token"]


@pytest.fixture(scope="function")
async def csrf_token_elevated(elevated_client_with_token: httpx.AsyncClient) -> str:
    """Get CSRF token for elevated user authenticated requests."""
    # Client is already authenticated from elevated_client_with_token
    response = await elevated_client_with_token.get("/api/auth/session_check")
    assert response.status_code == 200, f"Session check failed: {response.text}"
    data = response.json()
    assert "csrf_token" in data, f"No CSRF token in response: {data}"
    return data["csrf_token"]


@pytest.fixture(scope="function")
async def csrf_token_basic(basic_client_with_token: httpx.AsyncClient) -> str:
    """Get CSRF token for basic user authenticated requests."""
    # Client is already authenticated from basic_client_with_token
    response = await basic_client_with_token.get("/api/auth/session_check")
    assert response.status_code == 200, f"Session check failed: {response.text}"
    data = response.json()
    assert "csrf_token" in data, f"No CSRF token in response: {data}"
    return data["csrf_token"]


# ============================================================================
# UPLOAD DATA FIXTURES
# ============================================================================

@pytest.fixture(scope="function")
def create_upload_signature():
    """Helper to create proper HMAC signatures for upload requests."""
    def _create_signature(api_key: str, timestamp: str, modem_id: str, filename: str, checksum: str) -> str:
        import hmac
        message = f"{timestamp}|{modem_id}|{filename}|{checksum}"
        return hmac.new(api_key.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).hexdigest()
    return _create_signature


@pytest.fixture(scope="function")
def upload_form_data(sample_modem_check_data: Dict[str, Any], test_api_key: str, create_upload_signature) -> Dict[str, Any]:
    """Generate upload form data with HMAC signature."""
    sysinfo = sample_modem_check_data["sysinfo"]
    modem_id = f"{sysinfo['modemtype']}-{sysinfo['modemmac']}"
    filename = "2024-01-01_12-00-00.json"

    # Calculate checksum
    file_content = json.dumps(sample_modem_check_data).encode('utf-8')
    checksum = hashlib.sha256(file_content).hexdigest()

    # Create HMAC signature using the helper
    timestamp = str(int(time.time()))
    signature = create_upload_signature(test_api_key, timestamp, modem_id, filename, checksum)

    return {
        "api_key": test_api_key,
        "modem_id": modem_id,
        "filename": filename,
        "checksum": checksum,
        "file_content": file_content,
        "timestamp": timestamp,
        "signature": signature
    }


# ============================================================================
# ERROR RESPONSE HELPERS
# ============================================================================

def assert_error_response(response, expected_code: str, expected_status: int) -> Dict[str, Any]:
    """Assert response is a ModemCheckError with expected code and status.

    Args:
        response: The HTTP response object
        expected_code: Expected error code (e.g., "AUTHENTICATION_ERROR")
        expected_status: Expected HTTP status code

    Returns:
        The error dict for further assertions
    """
    assert response.status_code == expected_status, (
        f"Expected status {expected_status}, got {response.status_code}: {response.text}"
    )
    data = response.json()
    assert data.get("success") is False, f"Expected success=False, got: {data}"
    assert "error" in data, f"No 'error' field in response: {data}"
    assert data["error"]["code"] == expected_code, (
        f"Expected error code '{expected_code}', got '{data['error'].get('code')}': {data}"
    )
    assert "error_id" in data["error"], f"No error_id in error response: {data}"
    assert "timestamp" in data["error"], f"No timestamp in error response: {data}"
    return data["error"]


def assert_error_message_contains(error: Dict[str, Any], substring: str) -> None:
    """Assert error message contains expected text (case-insensitive).

    Args:
        error: The error dict from assert_error_response
        substring: Text that should appear in the message
    """
    message = error.get("message", "")
    assert substring.lower() in message.lower(), (
        f"Expected '{substring}' in message, got: '{message}'"
    )


# ============================================================================
# TEST DATA GENERATORS
# ============================================================================

def generate_random_username() -> str:
    """Generate random username for testing."""
    return fake.user_name() + str(fake.random_int(min=1000, max=9999))


def generate_random_password() -> str:
    """Generate random strong password for testing."""
    return fake.password(length=12, special_chars=True, digits=True, upper_case=True, lower_case=True)


def generate_random_modem_id() -> str:
    """Generate random modem ID for testing."""
    mac = ":".join([fake.hexify(text="^^") for _ in range(6)])
    modem_type = fake.random_element(elements=("XB8", "XB7", "SB8200", "DM1000"))
    return f"{modem_type}-{mac}"


# ============================================================================
# PYTEST CONFIGURATION
# ============================================================================

def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "api: API endpoint tests")
    config.addinivalue_line("markers", "ui: UI/Playwright tests")
    config.addinivalue_line("markers", "security: Security vulnerability tests")
    config.addinivalue_line("markers", "rbac: Role-based access control tests")
    config.addinivalue_line("markers", "slow: Slow-running tests")
    config.addinivalue_line("markers", "integration: Integration tests requiring full stack")


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Setup test environment before running tests."""
    # Wait for services to be ready
    max_retries = 30
    retry_delay = 2
    
    for i in range(max_retries):
        try:
            import httpx
            response = httpx.get(f"{TEST_BASE_URL}/health", timeout=5.0)
            if response.status_code == 200:
                print(f"\n✓ Test server ready at {TEST_BASE_URL}")
                break
        except Exception as e:
            if i < max_retries - 1:
                time.sleep(retry_delay)
            else:
                raise RuntimeError(f"Test server not available at {TEST_BASE_URL} after {max_retries * retry_delay}s") from e
    
    yield

    # Cleanup after all tests
    print("\n✓ Test suite completed")


@pytest.fixture(scope="session", autouse=True)
def ensure_ui_test_users():
    """Ensure test users exist for UI tests.

    Creates admin, elevated, and basic users in the database before UI tests run.
    This is needed because UI tests interact via HTTP and can't use database fixtures.
    """
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select
    from app.models import User
    from app.core.security import hash_password
    from datetime import datetime, timezone
    import os

    async def create_users():
        # Create async engine for test database
        db_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://modemcheck:modemcheck_test_password@localhost:5433/modemcheck_test")
        engine = create_async_engine(db_url, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            # Define test users
            test_users = [
                {
                    "username": "admin",
                    "password": "TestPass123!",
                    "role": "admin"
                },
                {
                    "username": "test_elevated",
                    "password": "ElevatedPass123!",
                    "role": "elevated"
                },
                {
                    "username": "test_basic",
                    "password": "BasicPass123!",
                    "role": "basic"
                }
            ]

            # Create or update each user
            for user_data in test_users:
                result = await session.execute(
                    select(User).where(User.username == user_data["username"])
                )
                existing_user = result.scalars().first()

                if existing_user is None:
                    # Create new user
                    user = User(
                        username=user_data["username"],
                        password_hash=hash_password(user_data["password"]),
                        role=user_data["role"],
                        created_at=utc_now(),
                        must_change_password=False
                    )
                    session.add(user)
                else:
                    # Update existing user's password and role for tests
                    # This handles the case where default admin was created with 'changeme'
                    existing_user.password_hash = hash_password(user_data["password"])
                    existing_user.role = user_data["role"]
                    existing_user.must_change_password = False

            await session.commit()
            print("\n✓ Test users created for UI tests")

        await engine.dispose()

    # Create and use our own event loop for session scope
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(create_users())
    finally:
        loop.close()

    yield

    # No cleanup needed - users persist for all tests


# ============================================================================
# CACHE FIXTURES
# ============================================================================

@pytest.fixture(scope="function")
async def test_cache():
    """
    Provide in-memory cache for unit tests.

    Uses in-memory backend to avoid Redis dependency in unit tests.
    Automatically initializes and cleans up cache manager.

    Note: This fixture mocks BOTH cache systems:
    - app.core.cache (CacheManager with InMemoryBackend)
    - app.core.cache_provider (InMemoryCache)

    The security functions (check_account_locked, record_failed_login, etc.)
    use app.core.cache_provider, so we must mock both to avoid Redis dependency.
    """
    from app.core.cache import CacheManager, InMemoryBackend
    import app.core.cache as cache_module
    from app.core.cache_provider import InMemoryCache, close_cache
    import app.core.cache_provider as cache_provider_module

    # Close any existing cache_provider instance first
    await close_cache()

    # Setup app.core.cache (CacheManager)
    manager = CacheManager()
    manager.memory_backend = InMemoryBackend(max_size=1000)
    manager.current_backend = manager.memory_backend
    manager._redis_available = False

    original_manager = cache_module._cache_manager
    cache_module._cache_manager = manager

    # Setup app.core.cache_provider (InMemoryCache)
    # This is used by security functions like check_account_locked()
    in_memory_cache = InMemoryCache(max_size=1000, default_ttl=3600)
    original_cache_instance = cache_provider_module._cache_instance
    cache_provider_module._cache_instance = in_memory_cache

    yield manager

    # Cleanup both cache systems
    cache_module._cache_manager = original_manager
    cache_provider_module._cache_instance = original_cache_instance
    await manager.current_backend.close()
    await in_memory_cache.close()


@pytest.fixture(scope="function")
async def mock_redis():
    """
    Mock Redis backend for tests that need cache operations.

    Returns in-memory cache backend that implements Redis interface.
    """
    from app.core.cache import InMemoryBackend

    backend = InMemoryBackend(max_size=1000)
    yield backend
    await backend.close()


@pytest.fixture(scope="function", autouse=True)
async def cleanup_redis_connections():
    """Cleanup Redis connections after each test to prevent ResourceWarnings."""
    yield
    # After test completes, close any Redis connections created during the test
    from app.core.security import close_redis
    await close_redis()


# ============================================================================
# PLAYWRIGHT / BROWSER FIXTURES
# ============================================================================

# UI test server URL
UI_TEST_BASE_URL = os.getenv("UI_TEST_BASE_URL", "http://localhost:23894")

# Viewport configurations for responsive testing
VIEWPORT_MOBILE_SE = {"width": 375, "height": 667}   # iPhone SE
VIEWPORT_MOBILE_14 = {"width": 390, "height": 844}   # iPhone 14
VIEWPORT_TABLET = {"width": 768, "height": 1024}     # iPad
VIEWPORT_DESKTOP_SM = {"width": 1280, "height": 800}
VIEWPORT_DESKTOP_LG = {"width": 1920, "height": 1080}


@pytest.fixture(scope="function")
async def browser_page():
    """Create a basic Playwright browser page for UI testing."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        yield page
        await context.close()
        await browser.close()


@pytest.fixture(params=["chromium", "firefox", "webkit"])
def browser_type_name(request) -> str:
    """Parametrized browser type for cross-browser testing."""
    return request.param


@pytest.fixture(scope="function")
async def cross_browser_page(browser_type_name: str):
    """Create browser page for specified browser type (cross-browser testing)."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser_launcher = getattr(p, browser_type_name)
        browser = await browser_launcher.launch(headless=True)
        # Create context with options to ensure consistent cookie handling
        context = await browser.new_context(
            ignore_https_errors=True,
            java_script_enabled=True,
        )
        page = await context.new_page()
        yield page, browser_type_name
        await context.close()
        await browser.close()


@pytest.fixture(scope="function")
async def firefox_page():
    """Firefox-specific browser page."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        yield page
        await context.close()
        await browser.close()


@pytest.fixture(scope="function")
async def webkit_page():
    """WebKit/Safari browser page."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.webkit.launch(headless=True)
        context = await browser.new_context(
            ignore_https_errors=True,
            java_script_enabled=True,
        )
        page = await context.new_page()
        yield page
        await context.close()
        await browser.close()


@pytest.fixture(scope="function")
async def playwright_instance():
    """Provide raw playwright instance for advanced context creation.

    Used by tests that need direct access to Playwright for custom browser
    context creation, such as WebKit storage_state workaround.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        yield p


# ============================================================================
# RESPONSIVE / VIEWPORT FIXTURES
# ============================================================================

@pytest.fixture(params=[
    ("mobile_se", VIEWPORT_MOBILE_SE),
    ("mobile_14", VIEWPORT_MOBILE_14),
    ("tablet", VIEWPORT_TABLET),
    ("desktop_sm", VIEWPORT_DESKTOP_SM),
    ("desktop_lg", VIEWPORT_DESKTOP_LG),
])
def viewport_config(request):
    """Parametrized viewport configuration for responsive testing."""
    return request.param


@pytest.fixture(scope="function")
async def responsive_page(viewport_config):
    """Create browser page with specific viewport for responsive testing."""
    from playwright.async_api import async_playwright

    name, viewport = viewport_config
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport=viewport)
        page = await context.new_page()
        yield page, name, viewport
        await context.close()
        await browser.close()


@pytest.fixture(scope="function")
async def mobile_page():
    """Mobile viewport browser page (iPhone SE)."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport=VIEWPORT_MOBILE_SE)
        page = await context.new_page()
        yield page
        await context.close()
        await browser.close()


@pytest.fixture(scope="function")
async def tablet_page():
    """Tablet viewport browser page (iPad)."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport=VIEWPORT_TABLET)
        page = await context.new_page()
        yield page
        await context.close()
        await browser.close()


# ============================================================================
# THEME TESTING FIXTURES
# ============================================================================

@pytest.fixture(scope="function")
async def dark_theme_page():
    """Browser page with dark theme preset via localStorage."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        # Set localStorage before navigation
        await page.add_init_script("""
            localStorage.setItem('modemcheck-theme', 'dark');
        """)
        yield page
        await context.close()
        await browser.close()


@pytest.fixture(scope="function")
async def light_theme_page():
    """Browser page with light theme preset via localStorage."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        await page.add_init_script("""
            localStorage.setItem('modemcheck-theme', 'light');
        """)
        yield page
        await context.close()
        await browser.close()


@pytest.fixture(params=["dark", "light"])
def theme_name(request) -> str:
    """Parametrized theme for testing both themes."""
    return request.param


@pytest.fixture(scope="function")
async def themed_page(theme_name: str):
    """Browser page with specified theme preset."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        await page.add_init_script(f"""
            localStorage.setItem('modemcheck-theme', '{theme_name}');
        """)
        yield page, theme_name
        await context.close()
        await browser.close()
