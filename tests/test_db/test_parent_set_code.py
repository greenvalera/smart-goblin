"""
Unit tests for the bonus-sheet self-FK on `sets.parent_set_code`.

Covers:
- CardRepository.get_card_names_by_set: parent ⊃ children, child does not
  pull parent.
- CardRepository.get_by_name: parent first, then fallback into children.
- CardRepository.get_cards_with_ratings: union with parent-wins dedup.
- CHECK constraint forbids self-loop (`parent_set_code = code`).
"""

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Set as SetModel
from src.db.repository import CardData, CardRepository, SetRepository


async def _seed_parent_and_child(session: AsyncSession) -> None:
    """Create SOS (parent) + SOA (bonus-sheet child) and a few cards in each."""
    set_repo = SetRepository(session)
    parent, _ = await set_repo.get_or_create("SOS", "Strixhaven: School of Stoats")
    child, _ = await set_repo.get_or_create("SOA", "Mystical Archive")
    child.parent_set_code = "SOS"
    await session.flush()

    card_repo = CardRepository(session)
    await card_repo.upsert_cards([
        CardData(name="Sos Card A", set_code="SOS", cmc=Decimal("2"), type_line="Instant"),
        CardData(name="Sos Card B", set_code="SOS", cmc=Decimal("3"), type_line="Sorcery"),
        CardData(name="Soa Card X", set_code="SOA", cmc=Decimal("1"), type_line="Instant"),
        CardData(name="Soa Card Y", set_code="SOA", cmc=Decimal("4"), type_line="Creature"),
    ])
    await session.commit()


class TestGetCardNamesBySet:
    @pytest.mark.asyncio
    async def test_parent_set_includes_children(self, clean_session: AsyncSession):
        await _seed_parent_and_child(clean_session)

        card_repo = CardRepository(clean_session)
        names = await card_repo.get_card_names_by_set("SOS")

        assert set(names) == {"Sos Card A", "Sos Card B", "Soa Card X", "Soa Card Y"}

    @pytest.mark.asyncio
    async def test_child_set_does_not_include_parent(
        self, clean_session: AsyncSession
    ):
        await _seed_parent_and_child(clean_session)

        card_repo = CardRepository(clean_session)
        names = await card_repo.get_card_names_by_set("SOA")

        assert set(names) == {"Soa Card X", "Soa Card Y"}

    @pytest.mark.asyncio
    async def test_set_without_children_unchanged(
        self, clean_session: AsyncSession
    ):
        set_repo = SetRepository(clean_session)
        await set_repo.get_or_create("ECL", "Lorwyn: Eclipsed")
        card_repo = CardRepository(clean_session)
        await card_repo.upsert_cards([
            CardData(name="Lone Card", set_code="ECL"),
        ])
        await clean_session.commit()

        names = await card_repo.get_card_names_by_set("ECL")
        assert names == ["Lone Card"]


class TestGetByName:
    @pytest.mark.asyncio
    async def test_finds_card_in_parent_set(self, clean_session: AsyncSession):
        await _seed_parent_and_child(clean_session)

        card_repo = CardRepository(clean_session)
        card = await card_repo.get_by_name("Sos Card A", "SOS")

        assert card is not None
        assert card.name == "Sos Card A"
        assert card.set.code == "SOS"

    @pytest.mark.asyncio
    async def test_falls_back_to_child_set(self, clean_session: AsyncSession):
        await _seed_parent_and_child(clean_session)

        card_repo = CardRepository(clean_session)
        card = await card_repo.get_by_name("Soa Card X", "SOS")

        assert card is not None
        assert card.name == "Soa Card X"
        assert card.set.code == "SOA"

    @pytest.mark.asyncio
    async def test_lookup_by_child_does_not_return_parent(
        self, clean_session: AsyncSession
    ):
        await _seed_parent_and_child(clean_session)

        card_repo = CardRepository(clean_session)
        card = await card_repo.get_by_name("Sos Card A", "SOA")

        assert card is None

    @pytest.mark.asyncio
    async def test_parent_wins_when_name_collides(
        self, clean_session: AsyncSession
    ):
        """If the same name exists in parent and child, the parent's row is returned."""
        await _seed_parent_and_child(clean_session)

        card_repo = CardRepository(clean_session)
        await card_repo.upsert_cards([
            CardData(name="Shared Card", set_code="SOS", cmc=Decimal("2")),
            CardData(name="Shared Card", set_code="SOA", cmc=Decimal("5")),
        ])
        await clean_session.commit()

        card = await card_repo.get_by_name("Shared Card", "SOS")
        assert card is not None
        assert card.set.code == "SOS"


class TestGetCardsWithRatings:
    @pytest.mark.asyncio
    async def test_returns_union_of_parent_and_children(
        self, clean_session: AsyncSession
    ):
        await _seed_parent_and_child(clean_session)

        card_repo = CardRepository(clean_session)
        cards = await card_repo.get_cards_with_ratings(
            ["Sos Card A", "Soa Card X"], "SOS"
        )

        names_by_set = {(c.name, c.set.code) for c in cards}
        assert ("Sos Card A", "SOS") in names_by_set
        assert ("Soa Card X", "SOA") in names_by_set

    @pytest.mark.asyncio
    async def test_dedup_prefers_parent_on_name_collision(
        self, clean_session: AsyncSession
    ):
        await _seed_parent_and_child(clean_session)

        card_repo = CardRepository(clean_session)
        await card_repo.upsert_cards([
            CardData(name="Shared Card", set_code="SOS", cmc=Decimal("2")),
            CardData(name="Shared Card", set_code="SOA", cmc=Decimal("7")),
        ])
        await clean_session.commit()

        cards = await card_repo.get_cards_with_ratings(["Shared Card"], "SOS")

        assert len(cards) == 1
        assert cards[0].set.code == "SOS"
        assert cards[0].cmc == Decimal("2")

    @pytest.mark.asyncio
    async def test_lookup_by_child_does_not_return_parent(
        self, clean_session: AsyncSession
    ):
        await _seed_parent_and_child(clean_session)

        card_repo = CardRepository(clean_session)
        cards = await card_repo.get_cards_with_ratings(
            ["Sos Card A", "Soa Card X"], "SOA"
        )

        assert {c.name for c in cards} == {"Soa Card X"}


class TestParentSetCheckConstraint:
    @pytest.mark.asyncio
    async def test_self_loop_is_rejected(self, clean_session: AsyncSession):
        """parent_set_code must not equal code (CHECK constraint)."""
        bad = SetModel(code="LOOP", name="Loop", parent_set_code="LOOP")
        clean_session.add(bad)

        with pytest.raises(IntegrityError):
            await clean_session.commit()

        await clean_session.rollback()

    @pytest.mark.asyncio
    async def test_null_parent_is_allowed(self, clean_session: AsyncSession):
        clean_session.add(SetModel(code="OK1", name="Ok one", parent_set_code=None))
        await clean_session.commit()

        set_repo = SetRepository(clean_session)
        result = await set_repo.get_by_code("OK1")
        assert result is not None
        assert result.parent_set_code is None

    @pytest.mark.asyncio
    async def test_valid_parent_link_is_allowed(self, clean_session: AsyncSession):
        clean_session.add(SetModel(code="PRT", name="Parent"))
        await clean_session.flush()
        clean_session.add(SetModel(code="CHD", name="Child", parent_set_code="PRT"))
        await clean_session.commit()

        set_repo = SetRepository(clean_session)
        child = await set_repo.get_by_code("CHD")
        assert child is not None
        assert child.parent_set_code == "PRT"
