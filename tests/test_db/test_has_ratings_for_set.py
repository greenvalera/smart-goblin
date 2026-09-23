"""
Tests for CardRepository.has_ratings_for_set.

Covers:
- Set with cards but no ratings → False.
- Set with at least one rating → True.
- Rating on a bonus-sheet child counts for the parent code.
- Unknown set → False.
"""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.repository import CardData, CardRepository, RatingData, SetRepository


async def _seed(session: AsyncSession) -> None:
    set_repo = SetRepository(session)
    await set_repo.get_or_create("NEW", "Brand New Set")
    await set_repo.get_or_create("OLD", "Old Set")
    child, _ = await set_repo.get_or_create("OLB", "Old Bonus Sheet")
    child.parent_set_code = "OLD"
    await session.flush()

    card_repo = CardRepository(session)
    await card_repo.upsert_cards([
        CardData(name="New Card", set_code="NEW"),
        CardData(name="Old Card", set_code="OLD"),
        CardData(name="Bonus Card", set_code="OLB"),
    ])
    await session.commit()


class TestHasRatingsForSet:
    async def test_no_ratings_returns_false(self, clean_session: AsyncSession):
        await _seed(clean_session)
        assert await CardRepository(clean_session).has_ratings_for_set("NEW") is False

    async def test_with_rating_returns_true(self, clean_session: AsyncSession):
        await _seed(clean_session)
        repo = CardRepository(clean_session)
        await repo.upsert_ratings([
            RatingData(card_name="Old Card", set_code="OLD", source="17lands",
                       rating=Decimal("3.5"), format="PremierDraft"),
        ])
        await clean_session.commit()
        assert await repo.has_ratings_for_set("old") is True

    async def test_child_rating_counts_for_parent(self, clean_session: AsyncSession):
        await _seed(clean_session)
        repo = CardRepository(clean_session)
        await repo.upsert_ratings([
            RatingData(card_name="Bonus Card", set_code="OLB", source="17lands",
                       rating=Decimal("2.0"), format="PremierDraft"),
        ])
        await clean_session.commit()
        assert await repo.has_ratings_for_set("OLD") is True

    async def test_unknown_set_returns_false(self, clean_session: AsyncSession):
        assert await CardRepository(clean_session).has_ratings_for_set("ZZZ") is False
