"""
Integration tests for parser operations.

Tests cover:
- TC-17.5: Parser integration — fetch + upsert cycle doesn't create duplicates
"""

from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Card, CardRating, Set
from src.db.repository import CardData, CardRepository, RatingData, SetRepository
from src.parsers.base import CardData as ParserCardData, SetData
from src.parsers.scryfall import ScryfallParser


# ============================================================================
# TC-17.5: Parser Integration — Fetch + Upsert Cycle Doesn't Create Duplicates
# ============================================================================


class TestTC175ParserUpsertNoDuplicates:
    """TC-17.5: Parser integration — fetch + upsert cycle doesn't create duplicates."""

    @pytest.mark.asyncio
    async def test_upsert_cards_no_duplicates(self, clean_session: AsyncSession):
        """
        Upserting the same cards twice should not create duplicates.
        """
        set_code = "DUP"
        card_repo = CardRepository(clean_session)
        set_repo = SetRepository(clean_session)

        # Ensure set exists
        await set_repo.get_or_create(set_code, "Duplicate Test Set")

        # First batch of cards
        cards_batch1 = [
            CardData(
                name="Test Card A",
                set_code=set_code,
                mana_cost="{1}{R}",
                cmc=Decimal("2"),
                colors=["R"],
                rarity="common",
            ),
            CardData(
                name="Test Card B",
                set_code=set_code,
                mana_cost="{2}{U}",
                cmc=Decimal("3"),
                colors=["U"],
                rarity="uncommon",
            ),
        ]

        # First upsert
        count1 = await card_repo.upsert_cards(cards_batch1)
        await clean_session.commit()

        # Count cards after first upsert
        result = await clean_session.execute(
            select(func.count(Card.id))
            .join(Set)
            .where(Set.code == set_code)
        )
        cards_after_first = result.scalar_one()

        # Second upsert with same cards
        count2 = await card_repo.upsert_cards(cards_batch1)
        await clean_session.commit()

        # Count cards after second upsert
        result = await clean_session.execute(
            select(func.count(Card.id))
            .join(Set)
            .where(Set.code == set_code)
        )
        cards_after_second = result.scalar_one()

        # Should be same count — no duplicates
        assert cards_after_first == 2
        assert cards_after_second == 2
        assert count1 == 2
        assert count2 == 2

    @pytest.mark.asyncio
    async def test_upsert_cards_updates_existing(self, clean_session: AsyncSession):
        """
        Upserting should update existing cards, not create new ones.
        """
        set_code = "UPD"
        card_repo = CardRepository(clean_session)
        set_repo = SetRepository(clean_session)

        await set_repo.get_or_create(set_code, "Update Test Set")

        # Initial card
        initial = [
            CardData(
                name="Updatable Card",
                set_code=set_code,
                mana_cost="{R}",
                cmc=Decimal("1"),
                colors=["R"],
                rarity="common",
            ),
        ]

        await card_repo.upsert_cards(initial)
        await clean_session.commit()

        # Get the card
        card_before = await card_repo.get_by_name("Updatable Card", set_code)
        assert card_before is not None
        assert card_before.rarity == "common"

        # Update with new rarity
        updated = [
            CardData(
                name="Updatable Card",
                set_code=set_code,
                mana_cost="{R}",
                cmc=Decimal("1"),
                colors=["R"],
                rarity="rare",  # Changed
            ),
        ]

        await card_repo.upsert_cards(updated)
        await clean_session.commit()

        # Verify update, not duplicate
        await clean_session.refresh(card_before)
        card_after = await card_repo.get_by_name("Updatable Card", set_code)

        assert card_after is not None
        assert card_after.id == card_before.id  # Same record
        assert card_after.rarity == "rare"  # Updated value

    @pytest.mark.asyncio
    async def test_upsert_ratings_no_duplicates(self, clean_session: AsyncSession):
        """
        Upserting ratings twice should not create duplicates.
        """
        set_code = "RTG"
        card_repo = CardRepository(clean_session)
        set_repo = SetRepository(clean_session)

        await set_repo.get_or_create(set_code, "Rating Test Set")

        # Create card first
        cards = [
            CardData(
                name="Rated Card",
                set_code=set_code,
                mana_cost="{2}",
                cmc=Decimal("2"),
            ),
        ]
        await card_repo.upsert_cards(cards)
        await clean_session.commit()

        # First rating upsert
        ratings1 = [
            RatingData(
                card_name="Rated Card",
                set_code=set_code,
                source="17lands",
                rating=Decimal("3.5"),
                win_rate=Decimal("52.0"),
                games_played=5000,
                format="PremierDraft",
            ),
        ]

        await card_repo.upsert_ratings(ratings1)
        await clean_session.commit()

        # Count ratings
        result = await clean_session.execute(
            select(func.count(CardRating.id))
        )
        count_after_first = result.scalar_one()

        # Second rating upsert
        await card_repo.upsert_ratings(ratings1)
        await clean_session.commit()

        # Count ratings again
        result = await clean_session.execute(
            select(func.count(CardRating.id))
        )
        count_after_second = result.scalar_one()

        # Should be same — no duplicates
        assert count_after_first == 1
        assert count_after_second == 1

    @pytest.mark.asyncio
    async def test_upsert_ratings_updates_values(self, clean_session: AsyncSession):
        """
        Upserting ratings should update existing values.
        """
        set_code = "RTGU"
        card_repo = CardRepository(clean_session)
        set_repo = SetRepository(clean_session)

        await set_repo.get_or_create(set_code)

        # Create card
        await card_repo.upsert_cards([
            CardData(name="Rating Update Card", set_code=set_code, cmc=Decimal("1")),
        ])
        await clean_session.commit()

        # Initial rating
        initial_rating = [
            RatingData(
                card_name="Rating Update Card",
                set_code=set_code,
                source="17lands",
                rating=Decimal("3.0"),
                win_rate=Decimal("50.0"),
                games_played=1000,
                format="PremierDraft",
            ),
        ]
        await card_repo.upsert_ratings(initial_rating)
        await clean_session.commit()

        # Get rating
        card = await card_repo.get_by_name("Rating Update Card", set_code)
        assert card.ratings[0].rating == Decimal("3.0")

        # Update rating
        updated_rating = [
            RatingData(
                card_name="Rating Update Card",
                set_code=set_code,
                source="17lands",
                rating=Decimal("4.5"),  # Changed
                win_rate=Decimal("58.0"),  # Changed
                games_played=10000,  # Changed
                format="PremierDraft",
            ),
        ]
        await card_repo.upsert_ratings(updated_rating)
        await clean_session.commit()

        # Verify update
        await clean_session.refresh(card)
        card = await card_repo.get_by_name("Rating Update Card", set_code)

        assert len(card.ratings) == 1  # Still just one rating
        assert card.ratings[0].rating == Decimal("4.5")
        assert card.ratings[0].win_rate == Decimal("58.0")
        assert card.ratings[0].games_played == 10000

    @pytest.mark.asyncio
    async def test_parser_fetch_and_upsert_cycle(
        self, clean_session: AsyncSession
    ):
        """
        Simulate a full parser cycle: fetch cards from Scryfall and upsert to DB.
        Running the cycle twice should not create duplicates.
        """
        set_code = "CYC"
        card_repo = CardRepository(clean_session)
        set_repo = SetRepository(clean_session)

        await set_repo.get_or_create(set_code, "Cycle Test Set")
        await clean_session.commit()

        # Mock Scryfall response
        mock_cards = [
            ParserCardData(
                name="Cycle Card Alpha",
                scryfall_id=uuid4(),
                mana_cost="{W}",
                cmc=Decimal("1"),
                colors=["W"],
                type_line="Creature",
                rarity="common",
                image_uri="https://example.com/alpha.jpg",
            ),
            ParserCardData(
                name="Cycle Card Beta",
                scryfall_id=uuid4(),
                mana_cost="{U}{U}",
                cmc=Decimal("2"),
                colors=["U"],
                type_line="Instant",
                rarity="uncommon",
                image_uri="https://example.com/beta.jpg",
            ),
        ]

        # Convert parser cards to repository cards
        def convert_to_repo_cards(parser_cards, set_code):
            return [
                CardData(
                    name=c.name,
                    set_code=set_code,
                    scryfall_id=c.scryfall_id,
                    mana_cost=c.mana_cost,
                    cmc=c.cmc,
                    colors=c.colors,
                    type_line=c.type_line,
                    rarity=c.rarity,
                    image_uri=c.image_uri,
                )
                for c in parser_cards
            ]

        # First cycle
        repo_cards = convert_to_repo_cards(mock_cards, set_code)
        await card_repo.upsert_cards(repo_cards)
        await clean_session.commit()

        count_after_first = await clean_session.scalar(
            select(func.count(Card.id)).join(Set).where(Set.code == set_code)
        )

        # Second cycle (simulate daily parser run)
        await card_repo.upsert_cards(repo_cards)
        await clean_session.commit()

        count_after_second = await clean_session.scalar(
            select(func.count(Card.id)).join(Set).where(Set.code == set_code)
        )

        # No duplicates
        assert count_after_first == 2
        assert count_after_second == 2

    @pytest.mark.asyncio
    async def test_mixed_new_and_existing_cards(
        self, clean_session: AsyncSession
    ):
        """
        Upserting a mix of new and existing cards should work correctly.
        """
        set_code = "MIX"
        card_repo = CardRepository(clean_session)
        set_repo = SetRepository(clean_session)

        await set_repo.get_or_create(set_code)

        # Initial batch
        initial = [
            CardData(name="Existing Card", set_code=set_code, cmc=Decimal("1")),
        ]
        await card_repo.upsert_cards(initial)
        await clean_session.commit()

        # Mixed batch (one existing, one new)
        mixed = [
            CardData(
                name="Existing Card",
                set_code=set_code,
                cmc=Decimal("1"),
                rarity="rare",  # Update
            ),
            CardData(
                name="New Card",
                set_code=set_code,
                cmc=Decimal("2"),
            ),
        ]
        await card_repo.upsert_cards(mixed)
        await clean_session.commit()

        # Verify
        all_cards = await card_repo.get_by_set(set_code)
        assert len(all_cards) == 2

        existing = await card_repo.get_by_name("Existing Card", set_code)
        assert existing is not None
        assert existing.rarity == "rare"

        new = await card_repo.get_by_name("New Card", set_code)
        assert new is not None

    @pytest.mark.asyncio
    async def test_set_get_or_create_no_duplicates(
        self, clean_session: AsyncSession
    ):
        """
        get_or_create for sets should not create duplicates.
        """
        set_repo = SetRepository(clean_session)

        # Create set
        set1, created1 = await set_repo.get_or_create("NDP", "No Duplicate Set")
        await clean_session.commit()

        assert created1 is True
        assert set1.code == "NDP"

        # Try to create again
        set2, created2 = await set_repo.get_or_create("NDP", "No Duplicate Set")
        await clean_session.commit()

        assert created2 is False
        assert set2.id == set1.id  # Same set

        # Count sets with this code
        result = await clean_session.execute(
            select(func.count(Set.id)).where(Set.code == "NDP")
        )
        count = result.scalar_one()
        assert count == 1
