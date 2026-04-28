"""
Integration tests for the bonus-sheet parent_set_code feature.

Verifies that with `SOA.parent_set_code = 'SOS'`:
- A user whose active set is SOS sees SOA cards in the known_cards prompt
  pre-fetch and can resolve a SOA card via _handle_single_card.
- A user whose active set is SOA still only sees SOA-only data
  (asymmetric link).
"""

from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.handlers.analyze import _handle_single_card
from src.db.repository import (
    CardData,
    CardRepository,
    RatingData,
    SetRepository,
)


async def _seed_sos_with_soa_child(session: AsyncSession) -> None:
    """Seed SOS (parent) and SOA (bonus-sheet child) with cards + ratings."""
    set_repo = SetRepository(session)
    await set_repo.get_or_create("SOS", "Strixhaven: School of Stoats")
    soa, _ = await set_repo.get_or_create("SOA", "Mystical Archive")
    soa.parent_set_code = "SOS"
    await session.flush()

    card_repo = CardRepository(session)
    await card_repo.upsert_cards([
        CardData(
            name="Sos Native",
            set_code="SOS",
            mana_cost="{2}{R}",
            cmc=Decimal("3"),
            colors=["R"],
            type_line="Creature",
            rarity="common",
        ),
        CardData(
            name="Mystic Archive Card",
            set_code="SOA",
            mana_cost="{U}",
            cmc=Decimal("1"),
            colors=["U"],
            type_line="Instant",
            rarity="rare",
        ),
    ])
    await card_repo.upsert_ratings([
        RatingData(
            card_name="Sos Native",
            set_code="SOS",
            source="17lands",
            rating=Decimal("3.0"),
            win_rate=Decimal("55.0"),
            games_played=10000,
            format="PremierDraft",
        ),
        RatingData(
            card_name="Mystic Archive Card",
            set_code="SOA",
            source="17lands",
            rating=Decimal("4.0"),
            win_rate=Decimal("60.0"),
            games_played=5000,
            format="PremierDraft",
        ),
    ])
    await session.commit()


def _patch_get_session(session: AsyncSession):
    """Build a replacement for src.bot.handlers.analyze.get_session bound to test session."""

    @asynccontextmanager
    async def _fake_get_session():
        yield session

    return patch("src.bot.handlers.analyze.get_session", _fake_get_session)


class TestKnownCardsIncludesChildren:
    @pytest.mark.asyncio
    async def test_get_card_names_for_sos_contains_soa_cards(
        self, clean_session: AsyncSession
    ):
        """The known_cards list pre-fetched for SOS must include SOA cards."""
        await _seed_sos_with_soa_child(clean_session)

        card_repo = CardRepository(clean_session)
        names = await card_repo.get_card_names_by_set("SOS")

        assert "Sos Native" in names
        assert "Mystic Archive Card" in names

    @pytest.mark.asyncio
    async def test_get_card_names_for_soa_does_not_contain_sos_cards(
        self, clean_session: AsyncSession
    ):
        """Active /set SOA should still see only SOA cards (asymmetric)."""
        await _seed_sos_with_soa_child(clean_session)

        card_repo = CardRepository(clean_session)
        names = await card_repo.get_card_names_by_set("SOA")

        assert "Mystic Archive Card" in names
        assert "Sos Native" not in names


class TestSingleCardHandlerWithBonusSheet:
    @pytest.mark.asyncio
    async def test_soa_card_resolves_under_active_sos(
        self, clean_session: AsyncSession
    ):
        """
        User with active_set_code=SOS sends a photo of a SOA card.
        _handle_single_card should look it up via the parent → child fallback
        and render grade/WR/CMC, not the 'not found' message.
        """
        await _seed_sos_with_soa_child(clean_session)

        processing_msg = AsyncMock()
        processing_msg.edit_text = AsyncMock()

        db_user = MagicMock()
        db_user.id = 1
        db_user.telegram_id = 12345
        db_user.active_set_code = "SOS"

        with _patch_get_session(clean_session):
            await _handle_single_card(
                processing_msg,
                db_user,
                "Mystic Archive Card",
                "SOS",
            )

        processing_msg.edit_text.assert_called_once()
        rendered_text = processing_msg.edit_text.call_args.args[0]
        assert "Mystic Archive Card" in rendered_text
        assert "не знайдена в базі" not in rendered_text
        assert "60.0%" in rendered_text  # win rate from seeded SOA rating
        assert "CMC: 1" in rendered_text

    @pytest.mark.asyncio
    async def test_native_sos_card_still_resolves(
        self, clean_session: AsyncSession
    ):
        """Sanity: regular SOS card lookup still works under active SOS."""
        await _seed_sos_with_soa_child(clean_session)

        processing_msg = AsyncMock()
        processing_msg.edit_text = AsyncMock()

        db_user = MagicMock()
        db_user.id = 1
        db_user.telegram_id = 12345
        db_user.active_set_code = "SOS"

        with _patch_get_session(clean_session):
            await _handle_single_card(
                processing_msg, db_user, "Sos Native", "SOS"
            )

        rendered_text = processing_msg.edit_text.call_args.args[0]
        assert "Sos Native" in rendered_text
        assert "55.0%" in rendered_text

    @pytest.mark.asyncio
    async def test_sos_card_not_found_under_active_soa(
        self, clean_session: AsyncSession
    ):
        """
        Active /set SOA must not pull SOS cards through the link.
        Looking up a SOS-only card under active=SOA returns 'not found'.
        """
        await _seed_sos_with_soa_child(clean_session)

        processing_msg = AsyncMock()
        processing_msg.edit_text = AsyncMock()

        db_user = MagicMock()
        db_user.id = 1
        db_user.telegram_id = 12345
        db_user.active_set_code = "SOA"

        with _patch_get_session(clean_session):
            await _handle_single_card(
                processing_msg, db_user, "Sos Native", "SOA"
            )

        rendered_text = processing_msg.edit_text.call_args.args[0]
        assert "не знайдена в базі" in rendered_text
        assert "SOA" in rendered_text
