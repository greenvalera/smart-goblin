"""
Unit tests for ``src.parsers.grade_validator``.

Each scenario seeds a small set of cards + ratings into the test DB, mocks
``SeventeenLandsParser.fetch_ratings`` with hand-crafted ``RatingData``, and
asserts the resulting ``ValidationReport`` reflects the expected match /
mismatch / missing counts.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.repository import (
    CardData as RepoCardData,
    CardRepository,
    RatingData as RepoRatingData,
    SetRepository,
)
from src.parsers.base import NotFoundError, RatingData
from src.parsers.grade_validator import (
    ValidationReport,
    validate_set_grades,
)
from src.parsers.seventeen_lands import SeventeenLandsParser


SET_CODE = "VLD"
FORMAT_NAME = "PremierDraft"


def _fresh_rating(
    name: str,
    grade: str | None,
    win_rate: float | None = 55.0,
    games: int = 1000,
) -> RatingData:
    """Build a 17lands-style RatingData with grade already assigned."""
    return RatingData(
        card_name=name,
        source=SeventeenLandsParser.SOURCE_NAME,
        rating=None,  # validate_set_grades only reads .grade, not .rating
        win_rate=Decimal(str(win_rate)) if win_rate is not None else None,
        games_played=games,
        format=FORMAT_NAME,
        grade=grade,
    )


def _make_parser_mock(
    fresh: list[RatingData] | None = None,
    raise_exc: Exception | None = None,
) -> MagicMock:
    """A mock SeventeenLandsParser with fetch_ratings stubbed."""
    parser = MagicMock(spec=SeventeenLandsParser)
    parser.SOURCE_NAME = SeventeenLandsParser.SOURCE_NAME
    if raise_exc is not None:
        parser.fetch_ratings = AsyncMock(side_effect=raise_exc)
    else:
        parser.fetch_ratings = AsyncMock(return_value=fresh or [])
    return parser


async def _seed(
    session: AsyncSession,
    cards: list[tuple[str, Decimal | None]],
) -> None:
    """
    Seed the DB with a Set + Cards + CardRatings.

    ``cards`` is a list of ``(card_name, db_rating)`` tuples. ``db_rating`` of
    ``None`` means the card has no 17lands rating row at all.
    """
    set_repo = SetRepository(session)
    await set_repo.get_or_create(SET_CODE, "Validator Test Set")

    card_repo = CardRepository(session)
    repo_cards = [
        RepoCardData(name=name, set_code=SET_CODE, rarity="common")
        for name, _ in cards
    ]
    await card_repo.upsert_cards(repo_cards)
    await session.commit()

    rated = [
        RepoRatingData(
            card_name=name,
            set_code=SET_CODE,
            source=SeventeenLandsParser.SOURCE_NAME,
            rating=db_rating,
            format=FORMAT_NAME,
        )
        for name, db_rating in cards
        if db_rating is not None
    ]
    if rated:
        await card_repo.upsert_ratings(rated)
    await session.commit()


class TestValidateSetGrades:
    @pytest.mark.asyncio
    async def test_perfect_match_all_cards(self, clean_session: AsyncSession):
        """Every card's fresh grade matches its DB rating round-tripped."""
        # DB rating 4.5 → "A", 3.0 → "B", 1.5 → "C"
        await _seed(
            clean_session,
            [
                ("Card A", Decimal("4.5")),
                ("Card B", Decimal("3.0")),
                ("Card C", Decimal("1.5")),
            ],
        )

        parser = _make_parser_mock(
            fresh=[
                _fresh_rating("Card A", "A"),
                _fresh_rating("Card B", "B"),
                _fresh_rating("Card C", "C"),
            ]
        )

        report = await validate_set_grades(
            clean_session, SET_CODE, parser, {"Card A", "Card B", "Card C"}
        )

        assert isinstance(report, ValidationReport)
        assert report.total == 3
        assert report.matched == 3
        assert report.mismatched == 0
        assert report.diffs == []
        assert report.missing_in_db == []
        assert report.missing_on_17lands == []
        assert report.skipped is False

    @pytest.mark.asyncio
    async def test_grade_mismatch_is_reported(self, clean_session: AsyncSession):
        """A card whose DB grade no longer matches the fresh grade is logged."""
        # DB rating 3.0 → "B", but fresh fetch grades it "A"
        await _seed(clean_session, [("Drifted Card", Decimal("3.0"))])

        parser = _make_parser_mock(
            fresh=[_fresh_rating("Drifted Card", "A", win_rate=62.5, games=2000)]
        )

        report = await validate_set_grades(
            clean_session, SET_CODE, parser, {"Drifted Card"}
        )

        assert report.total == 1
        assert report.matched == 0
        assert report.mismatched == 1
        assert len(report.diffs) == 1
        diff = report.diffs[0]
        assert diff.card_name == "Drifted Card"
        assert diff.expected_grade == "A"
        assert diff.actual_grade == "B"
        assert diff.win_rate == Decimal("62.5")
        assert diff.games_played == 2000

    @pytest.mark.asyncio
    async def test_card_in_17lands_but_missing_in_db(
        self, clean_session: AsyncSession
    ):
        """Cards 17lands knows but our DB doesn't go to ``missing_in_db``."""
        await _seed(clean_session, [("Card A", Decimal("3.0"))])

        parser = _make_parser_mock(
            fresh=[
                _fresh_rating("Card A", "B"),
                _fresh_rating("Unknown Reprint", "C"),
            ]
        )

        report = await validate_set_grades(
            clean_session, SET_CODE, parser, {"Card A"}
        )

        assert report.total == 1  # only Card A is paired
        assert report.matched == 1
        assert report.mismatched == 0
        assert "Unknown Reprint" in report.missing_in_db
        assert len(report.missing_in_db) == 1

    @pytest.mark.asyncio
    async def test_card_in_db_but_missing_on_17lands(
        self, clean_session: AsyncSession
    ):
        """DB cards with a rating that 17lands didn't return are flagged."""
        await _seed(
            clean_session,
            [
                ("Card A", Decimal("3.0")),
                ("Stale Card", Decimal("2.0")),  # has a rating, not in fresh
            ],
        )

        parser = _make_parser_mock(fresh=[_fresh_rating("Card A", "B")])

        report = await validate_set_grades(
            clean_session, SET_CODE, parser, {"Card A", "Stale Card"}
        )

        assert report.total == 1
        assert report.matched == 1
        assert "Stale Card" in report.missing_on_17lands
        # Card A was paired, so it shouldn't appear in missing lists
        assert "Card A" not in report.missing_on_17lands

    @pytest.mark.asyncio
    async def test_card_in_db_without_rating_not_flagged_as_stale(
        self, clean_session: AsyncSession
    ):
        """
        A DB card that never had a 17lands rating shouldn't appear in
        ``missing_on_17lands`` even if 17lands omits it from the fresh fetch.
        Otherwise every never-rated card would noisily flag every run.
        """
        await _seed(
            clean_session,
            [
                ("Card A", Decimal("3.0")),
                ("Never Rated", None),
            ],
        )

        parser = _make_parser_mock(fresh=[_fresh_rating("Card A", "B")])

        report = await validate_set_grades(
            clean_session, SET_CODE, parser, {"Card A", "Never Rated"}
        )

        assert report.missing_on_17lands == []

    @pytest.mark.asyncio
    async def test_both_sides_unrated_counts_as_match(
        self, clean_session: AsyncSession
    ):
        """
        When fresh fetch can't grade (e.g. tiny stats pool → grade=None) AND
        DB rating is also None for that card, treat as matched — no false
        alarm just because both ends agree there's no data.
        """
        # Seed a card with NO rating row at all
        await _seed(clean_session, [("Card A", None)])

        parser = _make_parser_mock(
            fresh=[_fresh_rating("Card A", grade=None, win_rate=None)]
        )

        report = await validate_set_grades(
            clean_session, SET_CODE, parser, {"Card A"}
        )

        assert report.total == 1
        assert report.matched == 1
        assert report.mismatched == 0

    @pytest.mark.asyncio
    async def test_normalization_matches_unicode_variants(
        self, clean_session: AsyncSession
    ):
        """
        17lands sometimes returns ASCII spellings of cards we store with
        diacritics. ``normalize_card_name`` should bridge the gap.
        """
        # DB has the diacritic version
        await _seed(clean_session, [("Jötun Grunt", Decimal("3.0"))])

        # 17lands returns the ASCII version
        parser = _make_parser_mock(fresh=[_fresh_rating("Jotun Grunt", "B")])

        report = await validate_set_grades(
            clean_session, SET_CODE, parser, {"Jötun Grunt"}
        )

        assert report.total == 1
        assert report.matched == 1
        assert report.missing_in_db == []

    @pytest.mark.asyncio
    async def test_skipped_on_404(self, clean_session: AsyncSession):
        """``NotFoundError`` from the parser → skipped report, no failure."""
        await _seed(clean_session, [("Card A", Decimal("3.0"))])

        parser = _make_parser_mock(raise_exc=NotFoundError("no data"))

        report = await validate_set_grades(
            clean_session, SET_CODE, parser, {"Card A"}
        )

        assert report.skipped is True
        assert report.skip_reason == "17lands returned 404"
        assert report.total == 0

    @pytest.mark.asyncio
    async def test_skipped_on_empty_response(self, clean_session: AsyncSession):
        """An empty list from 17lands → skipped, not zero-card matched."""
        await _seed(clean_session, [("Card A", Decimal("3.0"))])

        parser = _make_parser_mock(fresh=[])

        report = await validate_set_grades(
            clean_session, SET_CODE, parser, {"Card A"}
        )

        assert report.skipped is True
        assert report.total == 0
