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
from datetime import datetime
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

    # Clear DB 0 (sessions, API keys, brute force tracking)
    redis_url_db0 = f"redis://{settings.redis_host}:{settings.redis_port}/0"
    redis_db0 = await Redis.from_url(
        redis_url_db0,
        encoding="utf-8",
        decode_responses=True,
    )

    # Clear DB 1 (rate limiting - though disabled in tests)
    redis_url_db1 = f"redis://{settings.redis_host}:{settings.redis_port}/1"
    redis_db1 = await Redis.from_url(
        redis_url_db1,
        encoding="utf-8",
        decode_responses=True,
    )

    # Clear all Redis data before test
    await redis_db0.flushdb()
    await redis_db1.flushdb()

    yield

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
        created_at=datetime.utcnow(),
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
        created_at=datetime.utcnow(),
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
        created_at=datetime.utcnow(),
        must_change_password=False
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
    """Create active API key in database."""
    api_key = APIKey(
        api_key=test_api_key,
        name="test_key_active",
        created_at=datetime.utcnow(),
        is_active=True
    )
    db_session.add(api_key)
    await db_session.commit()
    await db_session.refresh(api_key)
    return api_key


@pytest.fixture(scope="function")
async def inactive_api_key(db_session: AsyncSession) -> APIKey:
    """Create inactive API key in database."""
    import secrets
    api_key = APIKey(
        api_key=secrets.token_hex(32),
        name="test_key_inactive",
        created_at=datetime.utcnow(),
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
    timestamp = datetime.fromtimestamp(sysinfo["checktime"]).strftime("%Y-%m-%d_%H-%M-%S")
    unique_filename = f"{modem_id}/{timestamp}_{unique_id}.json"

    check = ModemCheck(
        modem_id=modem_id,
        modem_type=sysinfo["modemtype"],
        check_time=datetime.fromtimestamp(sysinfo["checktime"]),
        filename=unique_filename,
        full_data=sample_modem_check_data,
        created_at=datetime.utcnow()
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
        dt = datetime.fromtimestamp(timestamp)
        unique_filename = f"{modem_id}/{dt.strftime('%Y-%m-%d_%H-%M-%S')}_{unique_id}.json"

        check = ModemCheck(
            modem_id=modem_id,
            modem_type=sysinfo["modemtype"],
            check_time=dt,
            filename=unique_filename,
            full_data=sample_modem_check_data,
            created_at=datetime.utcnow()
        )
        db_session.add(check)
        checks.append(check)

    await db_session.commit()
    for check in checks:
        await db_session.refresh(check)

    return checks


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
    from datetime import datetime
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
                        created_at=datetime.utcnow(),
                        must_change_password=False
                    )
                    session.add(user)

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


@pytest.fixture(scope="function", autouse=True)
async def cleanup_redis_connections():
    """Cleanup Redis connections after each test to prevent ResourceWarnings."""
    yield
    # After test completes, close any Redis connections created during the test
    from app.core.security import close_redis
    await close_redis()
