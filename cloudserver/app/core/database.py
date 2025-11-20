"""
Async database connection management using SQLAlchemy 2.0.

Provides:
- Async engine with connection pooling
- Async session factory
- Database initialization
- Dependency injection for FastAPI routes
"""
from typing import AsyncGenerator
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
    AsyncEngine
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool  # Only needed for test environments

from app.core.config import settings

# SQLAlchemy base class for models
Base = declarative_base()

# Global engine and session factory
engine: AsyncEngine = None
AsyncSessionLocal: async_sessionmaker = None


def get_engine() -> AsyncEngine:
    """
    Create and configure async database engine.

    Returns:
        Configured async engine with connection pooling
    """
    # For async engines, SQLAlchemy automatically uses AsyncAdaptedQueuePool
    # For test environments, we use NullPool to avoid connection pooling issues
    if settings.is_test():
        return create_async_engine(
            settings.database_url,
            echo=settings.db_echo,
            poolclass=NullPool,
        )

    return create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle,
        pool_timeout=settings.db_pool_timeout,
        pool_pre_ping=True,  # Verify connections before using
        connect_args={
            "command_timeout": settings.db_statement_timeout / 1000,  # Convert ms to seconds
            "server_settings": {
                "statement_timeout": str(settings.db_statement_timeout),  # PostgreSQL statement timeout
            }
        }
    )


def init_db():
    """Initialize database engine and session factory."""
    global engine, AsyncSessionLocal

    engine = get_engine()
    AsyncSessionLocal = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,  # Don't expire objects after commit
        autocommit=False,
        autoflush=False,
    )


async def create_tables():
    """Create all database tables (for development/testing)."""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as e:
        # Ignore "table already exists" errors from concurrent workers
        # This can happen when multiple gunicorn workers start simultaneously
        if "already exists" not in str(e).lower():
            raise


async def drop_tables():
    """Drop all database tables (for testing)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def close_db():
    """Close database connections."""
    global engine
    if engine:
        await engine.dispose()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager for database sessions.

    Usage:
        async with get_db_context() as db:
            result = await db.execute(query)
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()



async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for database sessions.

    Usage in routes:
        @router.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            result = await db.execute(select(Item))
            return result.scalars().all()
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
