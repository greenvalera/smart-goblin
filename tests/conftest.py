"""
Pytest fixtures and test configuration for Smart Goblin.

Provides fixtures for:
- Async test support
- PostgreSQL test database via testcontainers
- Database session management
- Mock environment variables
- LLM mocking utilities
"""

import asyncio
import os
from collections.abc import AsyncGenerator
from typing import Any
from unittest import mock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer

from src.db.models import Base


@pytest.fixture(scope="session")
def anyio_backend():
    """Use asyncio as the async backend."""
    return "asyncio"


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def postgres_container():
    """
    Start a PostgreSQL container for the test session.

    Uses testcontainers to spin up a real PostgreSQL instance.
    The container is shared across all tests in the session.
    """
    with PostgresContainer("postgres:15-alpine") as postgres:
        yield postgres


@pytest.fixture(scope="session")
def database_url(postgres_container) -> str:
    """Get the database URL from the running container."""
    # Get the connection URL and convert to asyncpg format
    url = postgres_container.get_connection_url()
    # Replace psycopg2 driver with asyncpg
    url = url.replace("psycopg2", "asyncpg")
    url = url.replace("postgresql://", "postgresql+asyncpg://")
    return url


@pytest.fixture(scope="session")
def mock_env_session(database_url):
    """
    Mock environment variables for the entire test session.

    Sets up required environment variables for the application.
    """
    env_vars = {
        "TELEGRAM_BOT_TOKEN": "test-token-12345",
        "OPENAI_API_KEY": "sk-test-key-12345",
        "DATABASE_URL": database_url,
        "OPENAI_MODEL": "gpt-4o",
        "OPENAI_VISION_MODEL": "gpt-4o",
        "LOG_LEVEL": "DEBUG",
    }
    with mock.patch.dict(os.environ, env_vars, clear=False):
        yield env_vars


@pytest_asyncio.fixture(scope="session")
async def db_engine(database_url, mock_env_session) -> AsyncGenerator[AsyncEngine, None]:
    """
    Create the async database engine for tests.

    Creates all tables at session start and drops them at session end.
    """
    engine = create_async_engine(
        database_url,
        echo=False,
        pool_pre_ping=True,
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Drop all tables after tests
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def session_factory(db_engine) -> async_sessionmaker[AsyncSession]:
    """Create the async session factory bound to the test engine."""
    return async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@pytest_asyncio.fixture
async def db_session(session_factory) -> AsyncGenerator[AsyncSession, None]:
    """
    Provide a database session for each test.

    Each test gets a fresh session. After the test, all changes are rolled back
    to ensure test isolation.
    """
    async with session_factory() as session:
        yield session
        # Roll back any changes made during the test
        await session.rollback()


@pytest_asyncio.fixture
async def clean_session(session_factory) -> AsyncGenerator[AsyncSession, None]:
    """
    Provide a database session with a clean database state.

    Truncates all tables before yielding the session, ensuring
    test isolation for integration tests.
    """
    # First, clean the database
    async with session_factory() as cleanup_session:
        for table in reversed(Base.metadata.sorted_tables):
            await cleanup_session.execute(table.delete())
        await cleanup_session.commit()

    # Then provide a fresh session for the test
    async with session_factory() as session:
        yield session
        await session.commit()


@pytest.fixture
def mock_env():
    """
    Mock environment variables for individual tests.

    Use this fixture when you need environment variables
    but don't need a real database.
    """
    env_vars = {
        "TELEGRAM_BOT_TOKEN": "test-token",
        "OPENAI_API_KEY": "sk-test-key",
        "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/testdb",
    }
    with mock.patch.dict(os.environ, env_vars, clear=True):
        yield env_vars


# ============================================================================
# LLM Mocking Utilities
# ============================================================================


def create_mock_vision_response(
    main_deck: list[str],
    sideboard: list[str] | None = None,
    detected_set: str | None = None,
) -> dict[str, Any]:
    """Create a mock LLM vision response for card recognition."""
    return {
        "main_deck": main_deck,
        "sideboard": sideboard or [],
        "detected_set": detected_set,
    }


def create_mock_advice_response(advice_text: str = None) -> str:
    """Create a mock LLM advice response."""
    if advice_text:
        return advice_text
    return """Загальна оцінка: Ваша колода має хороший потенціал!

Рекомендації:
• Колода має збалансовану криву мани
• Рекомендую тримати поточний склад
• Зверніть увагу на сайдборд для конкретних матчапів"""


# ============================================================================
# Test Data Fixtures
# ============================================================================


@pytest.fixture
def sample_card_names() -> list[str]:
    """Sample card names for testing."""
    return [
        "Lightning Bolt",
        "Counterspell",
        "Doom Blade",
        "Llanowar Elves",
        "Serra Angel",
    ]


@pytest.fixture
def sample_deck_data() -> dict[str, Any]:
    """Sample deck data for testing."""
    return {
        "main_deck": [
            "Lightning Bolt",
            "Lightning Bolt",
            "Counterspell",
            "Counterspell",
            "Doom Blade",
            "Serra Angel",
            "Llanowar Elves",
            "Llanowar Elves",
        ],
        "sideboard": [
            "Negate",
            "Disenchant",
        ],
        "set_code": "TST",
    }


@pytest.fixture
def sample_image_bytes() -> bytes:
    """Sample image bytes for testing (1x1 PNG)."""
    return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
