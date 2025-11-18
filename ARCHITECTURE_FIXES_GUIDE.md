# Architecture Fixes - Implementation Guide

Quick reference for implementing the architectural improvements identified in ARCHITECTURE_REVIEW.md.

## 1. Extract Redis Client to Separate Module (Critical Priority)

### Problem
```python
# Current state: security.py has global Redis singleton
_redis_client: Optional[aioredis.Redis] = None

async def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = await aioredis.from_url(...)
    return _redis_client
```

Redis is used by:
- `app/core/security.py` (password hashing, sessions, CSRF, lockout)
- `app/core/enhanced_limiter.py` (per-user rate limiting)
- `app/core/session_security.py` (device fingerprinting)
- `app/core/api_key_cache.py` (API key caching)

### Solution
**File: `app/core/redis_client.py` (NEW)**
```python
"""Redis connection management with explicit lifecycle."""
import redis.asyncio as aioredis
from typing import Optional
from app.core.config import settings

class RedisConnectionPool:
    """Manages Redis connection lifecycle."""

    def __init__(self):
        self._client: Optional[aioredis.Redis] = None
        self._is_connected = False

    async def connect(self):
        """Establish Redis connection."""
        if self._is_connected:
            return

        redis_url = f"redis://{settings.redis_host}:{settings.redis_port}/{settings.redis_db}"
        self._client = await aioredis.from_url(
            redis_url,
            password=settings.redis_password,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        self._is_connected = True

    async def disconnect(self):
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._is_connected = False

    def get(self) -> aioredis.Redis:
        """Get Redis client instance."""
        if not self._is_connected or not self._client:
            raise RuntimeError("Redis not connected. Call connect() first.")
        return self._client

# Global instance
_redis_pool = RedisConnectionPool()

async def get_redis() -> aioredis.Redis:
    """Get Redis client (must be connected via lifespan)."""
    return _redis_pool.get()

async def connect_redis():
    """Called from app lifespan."""
    await _redis_pool.connect()

async def disconnect_redis():
    """Called from app lifespan."""
    await _redis_pool.disconnect()
```

### Update `app/main.py`
```python
from app.core.redis_client import connect_redis, disconnect_redis

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    print(f"Starting {settings.app_name}...")

    # Initialize database
    init_db()
    await create_tables()
    await create_default_admin()

    # Initialize Redis (NEW)
    try:
        await connect_redis()
        print("Redis connected")
    except Exception as e:
        print(f"Error connecting to Redis: {e}")
        raise

    yield

    # Shutdown
    print("Shutting down...")
    await close_db()
    await disconnect_redis()  # (NEW)
    print("Cleanup complete")
```

### Update `app/core/security.py`
```python
# REMOVE: _redis_client global variable
# REMOVE: get_redis() function (moved to redis_client.py)
# REMOVE: close_redis() function (moved to redis_client.py)

# ADD at top:
from app.core.redis_client import get_redis

# All existing functions stay the same, they just import get_redis from new module
```

### Update `app/core/enhanced_limiter.py`
```python
# Change:
from app.core.security import get_redis

# To:
from app.core.redis_client import get_redis
```

### Update `app/core/session_security.py`
```python
# Change:
from app.core.security import get_redis, delete_session

# To:
from app.core.redis_client import get_redis
from app.core.security import delete_session
```

### Update `app/core/api_key_cache.py`
```python
# Change (BROKEN):
from app.core.redis_client import get_redis_client  # DOESN'T EXIST

# To:
from app.core.redis_client import get_redis
```

---

## 2. Fix Credentials in Docker Logs (Critical Priority)

### Problem
```python
# app/main.py:35 exposes database host
print(f"Database: {settings.database_url.split('@')[1] if '@' in settings.database_url else 'configured'}")
```

### Solution
**File: `app/core/logging_utils.py` (NEW)**
```python
"""Utilities for secure logging of configuration."""
import re
from typing import Optional

def mask_password(value: str, show_chars: int = 3) -> str:
    """Mask password/secret in string."""
    if not value or len(value) <= show_chars:
        return "*" * len(value)
    return value[:show_chars] + "*" * (len(value) - show_chars)

def mask_database_url(url: str) -> str:
    """Mask password in database URL."""
    # Pattern: postgresql://user:password@host:port/db
    pattern = r'(postgresql\+asyncpg://[^:]+:)([^@]+)(@.*)'
    return re.sub(pattern, r'\1***\3', url)

def mask_redis_password(password: Optional[str]) -> str:
    """Mask Redis password."""
    return mask_password(password) if password else "(none)"
```

### Update `app/main.py`
```python
from app.core.logging_utils import mask_database_url, mask_redis_password

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    print(f"Starting {settings.app_name}...")
    print(f"Environment: {settings.app_env}")
    print(f"Database: {mask_database_url(settings.database_url)}")
    print(f"Redis: {settings.redis_host}:{settings.redis_port} (auth: {mask_redis_password(settings.redis_password)})")

    # ... rest of startup ...
```

---

## 3. Add Environment Validation at Startup (Critical Priority)

### File: `app/core/config.py` - Update Settings class

```python
from pydantic import BaseSettings, Field, field_validator
import re

class Settings(BaseSettings):
    # ... existing fields ...

    @field_validator('secret_key')
    @classmethod
    def validate_secret_key(cls, v):
        """Validate SECRET_KEY is sufficiently long."""
        if not v or len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long")
        return v

    @field_validator('csrf_secret_key')
    @classmethod
    def validate_csrf_key(cls, v):
        """Validate CSRF_SECRET_KEY is sufficiently long."""
        if not v or len(v) < 32:
            raise ValueError("CSRF_SECRET_KEY must be at least 32 characters long")
        return v

    @field_validator('database_url')
    @classmethod
    def validate_database_url(cls, v):
        """Validate database URL format."""
        if not v.startswith(('postgresql://', 'postgresql+asyncpg://')):
            raise ValueError(
                "DATABASE_URL must be a PostgreSQL URL, e.g., "
                "postgresql+asyncpg://user:pass@localhost/dbname"
            )
        return v

    @field_validator('allowed_origins')
    @classmethod
    def validate_allowed_origins(cls, v, info):
        """Validate ALLOWED_ORIGINS not wildcard in production."""
        settings_data = info.data
        if v == "*" and settings_data.get('app_env') == 'production':
            raise ValueError(
                "ALLOWED_ORIGINS='*' is not allowed in production. "
                "Specify specific origins: http://example.com,https://example.com"
            )
        return v

    @field_validator('min_password_length')
    @classmethod
    def validate_min_password_length(cls, v):
        """Validate minimum password length is reasonable."""
        if v < 8:
            raise ValueError("min_password_length must be at least 8")
        if v > 128:
            raise ValueError("min_password_length must be at most 128")
        return v
```

### Update `app/main.py` - Add startup checks

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    print(f"Starting {settings.app_name}...")

    # Check database connectivity (BEFORE any other operation)
    print("Checking database connectivity...")
    try:
        async with get_db_context() as db:
            await db.execute(text("SELECT 1"))
        print("✓ Database connected")
    except Exception as e:
        print(f"✗ Cannot connect to database: {e}")
        print("  Ensure DATABASE_URL is correct and PostgreSQL is running")
        raise

    # Check Redis connectivity
    print("Checking Redis connectivity...")
    try:
        await connect_redis()
        redis = await get_redis()
        await redis.ping()
        print("✓ Redis connected")
    except Exception as e:
        print(f"✗ Cannot connect to Redis: {e}")
        print("  Ensure Redis is running at {settings.redis_host}:{settings.redis_port}")
        raise

    # Initialize database tables
    await create_tables()
    await create_default_admin()
    print("✓ Database initialized")

    yield

    # Shutdown
    print("Shutting down...")
    await close_db()
    await disconnect_redis()
    print("Cleanup complete")
```

---

## 4. Add Session Fallback to PostgreSQL (High Priority - Resilience)

### File: `app/models/session.py` (NEW)
```python
"""Session model for PostgreSQL fallback storage."""
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text
from app.core.database import Base

class SessionRecord(Base):
    """Session storage in PostgreSQL for Redis fallback."""
    __tablename__ = "sessions"

    session_id = Column(String(64), primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    data = Column(Text, nullable=False)  # JSON serialized session data
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False, index=True)

    def __repr__(self):
        return f"<Session(user_id='{self.user_id}', expires_at='{self.expires_at}')>"
```

### File: `app/core/sessions/hybrid_storage.py` (NEW)
```python
"""Hybrid session storage with Redis primary and PostgreSQL fallback."""
import json
from datetime import datetime, timedelta
from typing import Optional, Dict
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.redis_client import get_redis
from app.core.config import settings
from app.core.database import get_db_context
from app.models.session import SessionRecord

class HybridSessionStore:
    """Session store with Redis primary + PostgreSQL fallback."""

    @staticmethod
    async def create(session_id: str, user_id: str, session_data: Dict, ttl_seconds: int = 3600):
        """Create session in Redis + PostgreSQL."""
        data_json = json.dumps(session_data)
        expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)

        # Try Redis first
        try:
            redis = await get_redis()
            await redis.setex(
                f"session:{session_id}",
                ttl_seconds,
                data_json
            )
        except Exception as e:
            print(f"Warning: Redis write failed: {e}")

        # Always write to PostgreSQL for durability
        try:
            async with get_db_context() as db:
                record = SessionRecord(
                    session_id=session_id,
                    user_id=user_id,
                    data=data_json,
                    expires_at=expires_at
                )
                db.add(record)
                await db.commit()
        except Exception as e:
            print(f"Warning: PostgreSQL write failed: {e}")
            # If both fail, raise error
            raise

    @staticmethod
    async def verify(session_id: str) -> Optional[Dict]:
        """Verify session from Redis with PostgreSQL fallback."""

        # Try Redis first (fast path)
        try:
            redis = await get_redis()
            data = await redis.get(f"session:{session_id}")
            if data:
                return json.loads(data)
        except Exception as e:
            print(f"Warning: Redis read failed: {e}")

        # Fall back to PostgreSQL
        try:
            async with get_db_context() as db:
                result = await db.execute(
                    select(SessionRecord)
                    .where(SessionRecord.session_id == session_id)
                    .where(SessionRecord.expires_at > datetime.utcnow())
                )
                record = result.scalar_one_or_none()
                if record:
                    session_data = json.loads(record.data)

                    # Refill Redis cache from PostgreSQL
                    try:
                        redis = await get_redis()
                        await redis.setex(
                            f"session:{session_id}",
                            3600,
                            record.data
                        )
                    except Exception:
                        pass  # Ignore Redis write failure

                    return session_data
        except Exception as e:
            print(f"Warning: PostgreSQL read failed: {e}")

        return None

    @staticmethod
    async def delete(session_id: str):
        """Delete session from Redis + PostgreSQL."""
        # Try Redis
        try:
            redis = await get_redis()
            await redis.delete(f"session:{session_id}")
        except Exception:
            pass  # Best effort

        # Delete from PostgreSQL
        try:
            async with get_db_context() as db:
                await db.execute(
                    delete(SessionRecord)
                    .where(SessionRecord.session_id == session_id)
                )
                await db.commit()
        except Exception:
            pass  # Best effort
```

### Update `app/core/security.py` - Use hybrid storage

```python
from app.core.sessions.hybrid_storage import HybridSessionStore

async def create_session(username: str, role: str, max_sessions: int = 5) -> str:
    """Create session with hybrid storage."""
    session_id = secrets.token_urlsafe(32)

    session_data = {
        "username": username,
        "role": role,
        "created_at": datetime.utcnow().isoformat(),
        "expires_at": (datetime.utcnow() + timedelta(seconds=settings.session_ttl)).isoformat()
    }

    # Store in both Redis and PostgreSQL
    await HybridSessionStore.create(session_id, username, session_data, settings.session_ttl)

    return session_id

async def verify_session(session_id: str, refresh_ttl: bool = True) -> Optional[Dict]:
    """Verify session with hybrid storage."""
    return await HybridSessionStore.verify(session_id)
```

---

## 5. Implement Repository Pattern (High Priority - Testability)

### File: `app/core/repositories/base.py` (NEW)
```python
"""Base repository interface for data access abstraction."""
from abc import ABC, abstractmethod
from typing import List, Optional, Generic, TypeVar
from dataclasses import dataclass

T = TypeVar('T')

@dataclass
class QueryFilter:
    """Generic query filter."""
    field: str
    operator: str  # 'eq', 'gt', 'lt', 'contains'
    value: any

class BaseRepository(ABC, Generic[T]):
    """Base repository interface."""

    @abstractmethod
    async def create(self, obj: T) -> T:
        """Create entity."""
        pass

    @abstractmethod
    async def get_by_id(self, id: any) -> Optional[T]:
        """Get entity by primary key."""
        pass

    @abstractmethod
    async def get_all(self, limit: int = 100, offset: int = 0) -> List[T]:
        """Get all entities with pagination."""
        pass

    @abstractmethod
    async def update(self, id: any, updates: dict) -> Optional[T]:
        """Update entity."""
        pass

    @abstractmethod
    async def delete(self, id: any) -> bool:
        """Delete entity."""
        pass
```

### File: `app/core/repositories/modem_check.py` (NEW)
```python
"""Repository for ModemCheck data access."""
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from datetime import datetime, timedelta

from app.models import ModemCheck
from app.core.repositories.base import BaseRepository, QueryFilter

class ModemCheckRepository(BaseRepository[ModemCheck]):
    """PostgreSQL implementation of ModemCheck repository."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, obj: ModemCheck) -> ModemCheck:
        """Create modem check record."""
        self.db.add(obj)
        await self.db.commit()
        return obj

    async def get_by_id(self, id: int) -> Optional[ModemCheck]:
        """Get modem check by ID."""
        return await self.db.get(ModemCheck, id)

    async def get_all(self, limit: int = 100, offset: int = 0) -> List[ModemCheck]:
        """Get all modem checks with pagination."""
        result = await self.db.execute(
            select(ModemCheck)
            .order_by(desc(ModemCheck.check_time))
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def get_by_modem_id(self, modem_id: str, limit: int = 100) -> List[ModemCheck]:
        """Get modem checks for specific modem."""
        result = await self.db.execute(
            select(ModemCheck)
            .where(ModemCheck.modem_id == modem_id)
            .order_by(desc(ModemCheck.check_time))
            .limit(limit)
        )
        return result.scalars().all()

    async def get_recent(self, hours: int = 24, limit: int = 100) -> List[ModemCheck]:
        """Get modem checks from last N hours."""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        result = await self.db.execute(
            select(ModemCheck)
            .where(ModemCheck.check_time >= cutoff)
            .order_by(desc(ModemCheck.check_time))
            .limit(limit)
        )
        return result.scalars().all()

    async def update(self, id: int, updates: dict) -> Optional[ModemCheck]:
        """Update modem check record."""
        obj = await self.get_by_id(id)
        if not obj:
            return None

        for key, value in updates.items():
            setattr(obj, key, value)

        await self.db.commit()
        return obj

    async def delete(self, id: int) -> bool:
        """Delete modem check record."""
        obj = await self.get_by_id(id)
        if not obj:
            return False

        await self.db.delete(obj)
        await self.db.commit()
        return True
```

### Update `app/routers/upload.py` - Use repository

```python
from app.core.repositories.modem_check import ModemCheckRepository

async def upload_check(
    request: Request,
    api_key: str = Form(...),
    modem_id: str = Form(...),
    filename: str = Form(...),
    checksum: str = Form(...),
    file: UploadFile = File(...),
    x_request_timestamp: Optional[str] = Header(None),
    x_request_signature: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """Upload modem check data."""

    # Validate signature
    is_valid, error = validate_request_signature(...)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error)

    # Use repository for data access
    repo = ModemCheckRepository(db)

    # Create modem check record
    check_data = ModemCheck(
        modem_id=modem_id,
        filename=filename,
        # ... other fields ...
    )

    saved_check = await repo.create(check_data)

    return ModemCheckUploadResponse(
        success=True,
        check_id=saved_check.id,
        # ... other response fields ...
    )
```

---

## Summary of Changes by Priority

### Critical (Implement First Week)
1. Extract Redis client → `app/core/redis_client.py`
2. Mask credentials in logs → `app/core/logging_utils.py`
3. Add startup validation → Update `app/core/config.py` + `app/main.py`

### High Priority (Implement Next Sprint)
1. Hybrid session storage → `app/core/sessions/hybrid_storage.py`
2. Repository pattern → `app/core/repositories/`

### Medium Priority (Next Release)
1. Decompose security module (passwords, sessions, CSRF separate)
2. Abstract configuration with interface
3. Audit logger interface for extensibility

These changes build on each other and improve testability, reliability, and maintainability progressively.
