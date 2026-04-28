"""
Tests for the `--parent` flag of `scripts.add_set`.

Covers:
- Parent must already exist in DB (fail-fast).
- Parent FK is set on a freshly-created child.
- Parent FK is updated on an existing child set.
- `--parent <CODE>` equal to the child code is rejected.
"""

from contextlib import asynccontextmanager
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from scripts.add_set import add_set
from src.db.models import Set as SetModel
from src.db.repository import SetRepository
from src.parsers.base import SetData


def _patch_session(session: AsyncSession):
    @asynccontextmanager
    async def _fake_get_session():
        yield session

    return patch("scripts.add_set.get_session", _fake_get_session)


def _patch_scryfall(set_code: str, name: str = "Test Set"):
    """Stub ScryfallParser to return a minimal SetData and zero cards."""
    fake_parser = AsyncMock()
    fake_parser.fetch_set_info = AsyncMock(
        return_value=SetData(
            code=set_code,
            name=name,
            release_date=date(2026, 4, 1),
        )
    )
    fake_parser.fetch_set_cards = AsyncMock(return_value=[])
    fake_parser.close = AsyncMock()
    return patch("scripts.add_set.ScryfallParser", return_value=fake_parser)


class TestAddSetParent:
    @pytest.mark.asyncio
    async def test_missing_parent_fails_fast(self, clean_session: AsyncSession):
        """If --parent points at a code not in DB, exit non-zero."""
        with _patch_session(clean_session), _patch_scryfall("SOA", "Mystical Archive"):
            with pytest.raises(SystemExit) as excinfo:
                await add_set("SOA", fetch_cards=False, parent_code="SOS")

        assert excinfo.value.code != 0

        set_repo = SetRepository(clean_session)
        assert await set_repo.get_by_code("SOA") is None

    @pytest.mark.asyncio
    async def test_creates_set_with_parent_link(
        self, clean_session: AsyncSession
    ):
        """Happy path: parent exists, child is created with FK populated."""
        clean_session.add(SetModel(code="SOS", name="Strixhaven: School of Stoats"))
        await clean_session.commit()

        with _patch_session(clean_session), _patch_scryfall("SOA", "Mystical Archive"):
            await add_set("SOA", fetch_cards=False, parent_code="SOS")

        await clean_session.commit()
        set_repo = SetRepository(clean_session)
        child = await set_repo.get_by_code("SOA")
        assert child is not None
        assert child.parent_set_code == "SOS"

    @pytest.mark.asyncio
    async def test_updates_existing_set_parent(self, clean_session: AsyncSession):
        """If the child already exists without a parent, --parent links it."""
        clean_session.add(SetModel(code="SOS", name="Strixhaven: School of Stoats"))
        clean_session.add(SetModel(code="SOA", name="Mystical Archive"))
        await clean_session.commit()

        with _patch_session(clean_session), _patch_scryfall("SOA", "Mystical Archive"):
            await add_set("SOA", fetch_cards=False, parent_code="SOS")

        await clean_session.commit()
        set_repo = SetRepository(clean_session)
        child = await set_repo.get_by_code("SOA")
        assert child is not None
        assert child.parent_set_code == "SOS"

    @pytest.mark.asyncio
    async def test_self_parent_rejected(self, clean_session: AsyncSession):
        """--parent equal to the set code itself is refused before DB work."""
        with _patch_session(clean_session), _patch_scryfall("SOA"):
            with pytest.raises(SystemExit) as excinfo:
                await add_set("SOA", fetch_cards=False, parent_code="SOA")

        assert excinfo.value.code != 0
