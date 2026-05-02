"""
Integration tests for split / DFC / adventure / prepare card lookup.

Scryfall stores these cards under a single ``"Front // Back"`` name, but
vision and users typically supply only the front face (e.g. ``"Emeritus
of Woe"`` for the printed split card ``"Emeritus of Woe // Demonic
Tutor"``). Repository methods must resolve front-face queries to the
canonical row so single-card flow and deck flow both find the card.
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


DFC_FULL = "Emeritus of Woe // Demonic Tutor"
DFC_FRONT = "Emeritus of Woe"


async def _seed_sos_with_dfc_card(session: AsyncSession) -> None:
    """Seed SOS with one regular card and one split-name DFC card."""
    set_repo = SetRepository(session)
    await set_repo.get_or_create("SOS", "Sons of the Storm")
    await session.flush()

    card_repo = CardRepository(session)
    await card_repo.upsert_cards([
        CardData(
            name=DFC_FULL,
            set_code="SOS",
            mana_cost="{3}{B}",
            cmc=Decimal("4"),
            colors=["B"],
            type_line="Creature — Vampire Warlock",
            rarity="mythic",
        ),
        CardData(
            name="Sos Native",
            set_code="SOS",
            mana_cost="{2}{R}",
            cmc=Decimal("3"),
            colors=["R"],
            type_line="Creature",
            rarity="common",
        ),
    ])
    await card_repo.upsert_ratings([
        RatingData(
            card_name=DFC_FULL,
            set_code="SOS",
            source="17lands",
            rating=Decimal("4.2"),
            win_rate=Decimal("58.0"),
            games_played=8000,
            format="PremierDraft",
        ),
        RatingData(
            card_name="Sos Native",
            set_code="SOS",
            source="17lands",
            rating=Decimal("3.0"),
            win_rate=Decimal("55.0"),
            games_played=10000,
            format="PremierDraft",
        ),
    ])
    await session.commit()


async def _seed_sos_with_soa_dfc_child(session: AsyncSession) -> None:
    """Seed SOS (parent) and SOA (bonus-sheet child) with a DFC card on SOA."""
    set_repo = SetRepository(session)
    await set_repo.get_or_create("SOS", "Sons of the Storm")
    soa, _ = await set_repo.get_or_create("SOA", "Mystical Archive")
    soa.parent_set_code = "SOS"
    await session.flush()

    card_repo = CardRepository(session)
    await card_repo.upsert_cards([
        CardData(
            name="Adventurous Eater // Have a Bite",
            set_code="SOA",
            mana_cost="{1}{G}",
            cmc=Decimal("2"),
            colors=["G"],
            type_line="Creature — Beast",
            rarity="rare",
        ),
    ])
    await card_repo.upsert_ratings([
        RatingData(
            card_name="Adventurous Eater // Have a Bite",
            set_code="SOA",
            source="17lands",
            rating=Decimal("3.5"),
            win_rate=Decimal("57.0"),
            games_played=4000,
            format="PremierDraft",
        ),
    ])
    await session.commit()


def _patch_get_session(session: AsyncSession):
    """Override src.bot.handlers.analyze.get_session to use the test session."""

    @asynccontextmanager
    async def _fake_get_session():
        yield session

    return patch("src.bot.handlers.analyze.get_session", _fake_get_session)


class TestGetByNameResolvesFrontFace:
    @pytest.mark.asyncio
    async def test_front_face_query_returns_split_card(
        self, clean_session: AsyncSession
    ):
        await _seed_sos_with_dfc_card(clean_session)

        card_repo = CardRepository(clean_session)
        card = await card_repo.get_by_name(DFC_FRONT, "SOS")

        assert card is not None
        assert card.name == DFC_FULL

    @pytest.mark.asyncio
    async def test_full_split_name_query_still_works(
        self, clean_session: AsyncSession
    ):
        await _seed_sos_with_dfc_card(clean_session)

        card_repo = CardRepository(clean_session)
        card = await card_repo.get_by_name(DFC_FULL, "SOS")

        assert card is not None
        assert card.name == DFC_FULL

    @pytest.mark.asyncio
    async def test_exact_name_wins_over_split_match(
        self, clean_session: AsyncSession
    ):
        """
        If both ``"Lightning"`` and ``"Lightning // Thunder"`` exist in the
        same set, querying ``"Lightning"`` must return the exact-name card,
        not the split-form one.
        """
        set_repo = SetRepository(clean_session)
        await set_repo.get_or_create("TST", "Test Set")
        await clean_session.flush()

        card_repo = CardRepository(clean_session)
        await card_repo.upsert_cards([
            CardData(name="Lightning", set_code="TST", rarity="common"),
            CardData(name="Lightning // Thunder", set_code="TST", rarity="rare"),
        ])
        await clean_session.commit()

        card = await card_repo.get_by_name("Lightning", "TST")
        assert card is not None
        assert card.name == "Lightning"

    @pytest.mark.asyncio
    async def test_unrelated_prefix_does_not_match(
        self, clean_session: AsyncSession
    ):
        """
        Querying ``"Light"`` must NOT return ``"Lightning // Thunder"`` —
        the ILIKE pattern requires ``" // "`` directly after the queried
        name, so substring prefix matches are rejected.
        """
        set_repo = SetRepository(clean_session)
        await set_repo.get_or_create("TST", "Test Set")
        await clean_session.flush()

        card_repo = CardRepository(clean_session)
        await card_repo.upsert_cards([
            CardData(name="Lightning // Thunder", set_code="TST", rarity="rare"),
        ])
        await clean_session.commit()

        card = await card_repo.get_by_name("Light", "TST")
        assert card is None

    @pytest.mark.asyncio
    async def test_front_face_resolves_through_child_set(
        self, clean_session: AsyncSession
    ):
        """A DFC card on a bonus-sheet child resolves via the parent code."""
        await _seed_sos_with_soa_dfc_child(clean_session)

        card_repo = CardRepository(clean_session)
        card = await card_repo.get_by_name("Adventurous Eater", "SOS")

        assert card is not None
        assert card.name == "Adventurous Eater // Have a Bite"


class TestGetCardsWithRatingsResolvesFrontFace:
    @pytest.mark.asyncio
    async def test_batch_lookup_with_front_face_name(
        self, clean_session: AsyncSession
    ):
        await _seed_sos_with_dfc_card(clean_session)

        card_repo = CardRepository(clean_session)
        cards = await card_repo.get_cards_with_ratings(
            [DFC_FRONT, "Sos Native"], "SOS"
        )

        names = {c.name for c in cards}
        assert DFC_FULL in names
        assert "Sos Native" in names

    @pytest.mark.asyncio
    async def test_batch_lookup_dedups_when_both_forms_passed(
        self, clean_session: AsyncSession
    ):
        """
        If the caller passes both ``"Front"`` and ``"Front // Back"`` (as
        ``get_card_names_by_set`` now does), the batch must return the
        single underlying row once, not duplicate it.
        """
        await _seed_sos_with_dfc_card(clean_session)

        card_repo = CardRepository(clean_session)
        cards = await card_repo.get_cards_with_ratings(
            [DFC_FRONT, DFC_FULL], "SOS"
        )

        full_matches = [c for c in cards if c.name == DFC_FULL]
        assert len(full_matches) == 1


class TestGetCardNamesByMapsFrontFaceAlias:
    @pytest.mark.asyncio
    async def test_returns_both_full_and_front_face(
        self, clean_session: AsyncSession
    ):
        await _seed_sos_with_dfc_card(clean_session)

        card_repo = CardRepository(clean_session)
        names = await card_repo.get_card_names_by_set("SOS")

        assert DFC_FULL in names
        assert DFC_FRONT in names
        assert "Sos Native" in names


class TestSingleCardHandlerWithDfcCard:
    @pytest.mark.asyncio
    async def test_dfc_card_resolves_via_front_face_recognition(
        self, clean_session: AsyncSession
    ):
        """
        Vision recognizes ``"Emeritus of Woe"`` for SOS. The single-card
        handler must render grade/WR/CMC, not the 'not found' message.
        """
        await _seed_sos_with_dfc_card(clean_session)

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
                DFC_FRONT,
                "SOS",
            )

        processing_msg.edit_text.assert_called_once()
        rendered = processing_msg.edit_text.call_args.args[0]
        assert DFC_FULL in rendered
        assert "не знайдена в базі" not in rendered
        assert "58.0%" in rendered
        assert "CMC: 4" in rendered
