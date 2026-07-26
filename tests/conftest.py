"""
Shared pytest fixtures and environment setup for the test suite.

`v2hub_api.core.config.Settings` requires several env vars (DATABASE_URL, REDIS_URL,
SECRET_KEY, ADMIN_SECRET_KEY) to be present at import time. We set sane
defaults here *before* anything under `src` gets imported, so that unit
tests can exercise pure logic without needing a real Postgres/Redis
instance running.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/testdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ADMIN_SECRET_KEY", "test-admin-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DEBUG", "false")

import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from v2hub_api.db.models import Base


@pytest_asyncio.fixture
async def db_engine():
    """
    Create a fresh in-memory SQLite engine with all tables for each test.

    Repository/service tests use this instead of connecting to the
    `DATABASE_URL` above, keeping the suite hermetic and fast while still
    exercising the real SQLAlchemy models and query logic.

    A StaticPool is used so that all sessions/connections created during a
    test share the *same* underlying in-memory SQLite database (by default
    every new connection to ":memory:" gets its own empty database).
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncSession:
    """Provide a clean AsyncSession backed by the in-memory SQLite engine."""
    session_factory = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )

    async with session_factory() as session:
        yield session
        await session.rollback()
