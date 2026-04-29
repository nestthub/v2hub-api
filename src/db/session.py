"""
Database session management for async SQLAlchemy.

Provides:
- Async engine and session factory configuration
- Dependency injection for FastAPI routes
- Proper connection pooling and lifecycle management
"""

from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.core.config import settings

# ═══════════════════════════════════════════════════════════════════════════
# Engine Configuration
# ═══════════════════════════════════════════════════════════════════════════

engine: AsyncEngine = create_async_engine(
    settings.database_url_str,
    echo=settings.db_echo,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_pre_ping=True,  # Verify connections before using
    pool_recycle=3600,   # Recycle connections after 1 hour
)

# ═══════════════════════════════════════════════════════════════════════════
# Session Factory
# ═══════════════════════════════════════════════════════════════════════════

AsyncSessionFactory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Allow object access after commit
    autoflush=False,         # Explicit control over flush operations
    autocommit=False,        # Require explicit commits
)


# ═══════════════════════════════════════════════════════════════════════════
# Dependency for FastAPI
# ═══════════════════════════════════════════════════════════════════════════

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides an async database session.
    
    Usage:
        @router.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db_session)):
            ...
    
    The session is automatically committed on success and rolled back
    on exception.
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_db_session_no_commit() -> AsyncGenerator[AsyncSession, None]:
    """
    Provide a database session without auto-commit.
    
    Useful for read-only operations or when manual transaction control
    is needed.
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
        finally:
            await session.close()


# ═══════════════════════════════════════════════════════════════════════════
# Lifecycle Management
# ═══════════════════════════════════════════════════════════════════════════

async def init_db() -> None:
    """
    Initialize database connection.
    
    Call this during application startup to verify database connectivity.
    """
    async with engine.begin() as conn:
        # Test connection
        await conn.execute(text("SELECT 1"))


async def close_db() -> None:
    """
    Close database connections.
    
    Call this during application shutdown to cleanup resources.
    """
    await engine.dispose()
