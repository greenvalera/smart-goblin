"""
Async database session factory for Smart Goblin.

Provides an async engine and session factory for SQLAlchemy.
"""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Load .env file for database URL
load_dotenv()

# Global engine and session factory (initialized lazily)
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_database_url() -> str:
    """Get database URL from environment."""
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise ValueError("DATABASE_URL environment variable is required")
    # Ensure URL uses asyncpg driver
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def get_engine() -> AsyncEngine:
    """
    Get or create the async database engine.

    Returns:
        AsyncEngine: The SQLAlchemy async engine instance.
    """
    global _engine
    if _engine is None:
        database_url = _get_database_url()
        echo = os.getenv("LOG_LEVEL", "INFO") == "DEBUG"
        _engine = create_async_engine(
            database_url,
            echo=echo,
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """
    Get or create the async session factory.

    Returns:
        async_sessionmaker: Factory for creating async sessions.
    """
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager for database sessions.

    Yields:
        AsyncSession: An async database session.

    Example:
        async with get_session() as session:
            result = await session.execute(select(User))
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_engine() -> None:
    """
    Close the database engine and release all connections.

    Should be called during application shutdown.
    """
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
