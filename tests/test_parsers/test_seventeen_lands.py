"""
Unit tests for the 17lands parser's grade calculation.

Focus on the two pieces of logic that determine the final letter grade:
- ``z_score_to_grade``: the formula extracted from the 17lands frontend bundle.
- ``SeventeenLandsParser._apply_grades``: assigning grades from a global pool.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from src.parsers.base import RatingData
from src.parsers.seventeen_lands import (
    MIN_CARDS_FOR_STATS,
    SeventeenLandsParser,
    is_under_embargo,
    z_score_to_grade,
)


class TestRequestUrl:
    """
    Pin the endpoint and parameter names.

    17lands moved this feed from /card_ratings/data to /api/card_data and
    renamed ``format`` to ``event_type``. The legacy path still answers 200
    with every statistic nulled out rather than failing, so a regression
    here is invisible at runtime — it just silently stops carrying data.
    """

    async def test_calls_api_card_data_with_event_type(self):
        parser = SeventeenLandsParser()
        parser._request = AsyncMock(return_value={"data": []})

        await parser.fetch_ratings("SOS", format_name="PremierDraft")

        url = parser._request.await_args.args[0]
        assert "/api/card_data?" in url
        assert "expansion=SOS" in url
        assert "event_type=PremierDraft" in url
        assert "card_ratings/data" not in url
        assert "format=" not in url

    async def test_start_date_is_forwarded(self):
        parser = SeventeenLandsParser()
        parser._request = AsyncMock(return_value={"data": []})

        await parser.fetch_ratings("SOS", start_date=date(2026, 1, 31))

        assert "start_date=2026-01-31" in parser._request.await_args.args[0]

    async def test_unwraps_the_data_envelope(self):
        """The endpoint wraps rows in {copyright, notes, data}."""
        parser = SeventeenLandsParser()
        parser._request = AsyncMock(
            return_value={
                "copyright": "(c) 2026 17Lands LLC",
                "notes": "…",
                "data": [
                    {"name": "Enveloped Card", "ever_drawn_win_rate": 0.55,
                     "game_count": 1000},
                ],
            }
        )

        ratings = await parser.fetch_ratings("SOS")

        assert [r.card_name for r in ratings] == ["Enveloped Card"]


class TestEmbargo:
    """
    17lands asks third-party tools to hold a new set's data for 12 days
    after its Arena release. See https://www.17lands.com/usage_guidelines
    """

    def test_day_of_release_is_embargoed(self):
        assert is_under_embargo(date(2026, 8, 1), today=date(2026, 8, 1)) is True

    def test_day_eleven_is_still_embargoed(self):
        assert is_under_embargo(date(2026, 8, 1), today=date(2026, 8, 12)) is True

    def test_day_twelve_is_clear(self):
        assert is_under_embargo(date(2026, 8, 1), today=date(2026, 8, 13)) is False

    def test_long_released_set_is_clear(self):
        assert is_under_embargo(date(2024, 2, 9), today=date(2026, 8, 14)) is False

    def test_unknown_release_date_is_not_embargoed(self):
        """
        Sets already in the DB may predate release-date tracking. Treating
        an unknown date as embargoed would silently drop their ratings.
        """
        assert is_under_embargo(None, today=date(2026, 8, 14)) is False


class TestParseRating:
    """
    Pin the 17lands JSON field mapping.

    ``_parse_rating`` is the only place the upstream response shape is
    read. It had no coverage, so when 17lands' feed stopped carrying
    statistics every test still passed and the breakage surfaced only as
    ungraded cards in production. These records use the field names and
    types the live endpoint returns.
    """

    def test_maps_a_populated_record(self):
        parser = SeventeenLandsParser()
        rating = parser._parse_rating(
            {
                "name": "Masterful Flourish",
                "color": "W",
                "rarity": "common",
                "ever_drawn_win_rate": 0.564321,
                "ever_drawn_game_count": 4200,
                "game_count": 4200,
                "url": "https://cards.scryfall.io/large/front/7/a/7a451985.jpg",
            },
            "PremierDraft",
        )

        assert rating.card_name == "Masterful Flourish"
        # Stored as a percentage, not the raw 0..1 fraction.
        assert rating.win_rate == Decimal("56.4321")
        assert rating.games_played == 4200
        assert rating.low_confidence is False
        assert rating.format == "PremierDraft"
        # Grades are assigned later, by _apply_grades over the full sample.
        assert rating.grade is None
        assert rating.rating is None

    def test_maps_a_statless_record(self):
        """
        The shape 17lands serves when it has no aggregates for a card:
        the entry exists, every statistic is null or zero.
        """
        parser = SeventeenLandsParser()
        rating = parser._parse_rating(
            {
                "name": "The Dawning Archaic",
                "color": "",
                "rarity": "mythic",
                "ever_drawn_win_rate": None,
                "ever_drawn_game_count": 0,
                "game_count": 0,
                "url": "https://cards.scryfall.io/large/front/7/a/7a451985.jpg",
            },
            "PremierDraft",
        )

        assert rating.card_name == "The Dawning Archaic"
        assert rating.win_rate is None
        assert rating.games_played == 0
        assert rating.low_confidence is True

    def test_falls_back_to_ever_drawn_game_count(self):
        """``game_count`` absent — the parser falls back to the ever-drawn count."""
        parser = SeventeenLandsParser()
        rating = parser._parse_rating(
            {
                "name": "Fallback Card",
                "ever_drawn_win_rate": 0.51,
                "ever_drawn_game_count": 900,
            },
            "PremierDraft",
        )

        assert rating.games_played == 900
        assert rating.low_confidence is False


class TestZScoreToGrade:
    """Verify the formula matches 17lands' frontend ``floor(3*(z + 11/6))``."""

    @pytest.mark.parametrize(
        "z, expected",
        [
            # C is centered at z=0 (band [-1/6, 1/6))
            (0.0, "C"),
            (0.16, "C"),
            (-0.16, "C"),
            # Boundaries (1/6 ≈ 0.1667 — flips to C+/C-)
            (0.17, "C+"),
            (-0.17, "C-"),
            # Masterful Flourish in SOS (the canonical example)
            (-0.285, "C-"),
            # C- band lower boundary at z = -0.5
            (-0.499, "C-"),
            (-0.500, "C-"),
            (-0.501, "D+"),
            # Top end: A+ requires z >= 13/6 ≈ 2.1667
            (2.0, "A"),
            (2.166, "A"),
            (2.167, "A+"),
            (10.0, "A+"),
            # Bottom end: F when index < 0, i.e. z < -1.5. The boundary at
            # exactly -1.5 lands on F due to float rounding of 11/6 — same
            # quirk as the 17lands frontend (Math.floor(3 * (-1.5 + 11/6))
            # = Math.floor(0.9999…) = 0 → uS[0] = "F").
            (-1.499, "D-"),
            (-1.500, "F"),
            (-1.501, "F"),
            (-10.0, "F"),
        ],
    )
    def test_z_to_grade_boundaries(self, z, expected):
        assert z_score_to_grade(z) == expected


class TestApplyGrades:
    """Verify ``_apply_grades`` uses a single global pool, not per-color."""

    def _make_rating(self, name: str, win_rate_pct: float, color: str = "") -> RatingData:
        return RatingData(
            card_name=name,
            source="17lands",
            win_rate=Decimal(str(win_rate_pct)),
            games_played=1000,
            format="PremierDraft",
        )

    def test_global_pool_assigns_grades_to_all_with_winrate(self):
        parser = SeventeenLandsParser()
        # 16 cards mean=55, std≈2.97 (use varying values; n>=15 so stats compute)
        ratings = [
            self._make_rating(f"Card {i}", win_rate_pct=50 + i)
            for i in range(16)
        ]
        # Add an unrated card (no win_rate) — should be skipped
        ratings.append(
            RatingData(
                card_name="No Data Card",
                source="17lands",
                win_rate=None,
                format="PremierDraft",
            )
        )

        parser._apply_grades(ratings)

        graded = [r for r in ratings if r.win_rate is not None]
        for r in graded:
            assert r.grade is not None, f"{r.card_name} missing grade"
            assert r.rating is not None
        unrated = [r for r in ratings if r.win_rate is None]
        for r in unrated:
            assert r.grade is None
            assert r.rating is None

    def test_grades_match_17lands_for_known_sample(self):
        """
        Reproduce the canonical SOS Black-color sample we used to debug the
        formula bug (n=26, mean≈55.86, std≈3.14). With global stats over
        these 26 cards, Masterful Flourish (WR=54.97%) should grade C-.
        """
        # Realistic SOS Black sample — exact win rates from 17lands API
        # default (no date filter), main-set Black cards only.
        sos_black_wrs = [
            58.62, 56.06, 55.76, 53.95, 50.84, 53.97, 55.92, 58.93, 53.79,
            54.97, 51.10, 60.85, 54.21, 56.18, 53.20, 56.78, 60.41, 56.34,
            58.51, 51.46, 56.51, 56.85, 56.99, 60.97, 55.51, 60.31,
        ]
        ratings = [
            self._make_rating(f"Card {i}", wr) for i, wr in enumerate(sos_black_wrs)
        ]
        # The 10th entry (index 9) is Masterful Flourish at 54.97
        ratings[9].card_name = "Masterful Flourish"

        parser = SeventeenLandsParser()
        parser._apply_grades(ratings)

        mf = next(r for r in ratings if r.card_name == "Masterful Flourish")
        assert mf.grade == "C-", (
            f"Expected C- to match 17lands site for Masterful Flourish, "
            f"got {mf.grade}"
        )

    def test_main_set_filter_excludes_bonus_sheet_from_stats_pool(self):
        """
        Reprints in main_set_card_names exclusion shouldn't enter the stats
        pool, but they still receive a grade based on the main-set pool.
        """
        parser = SeventeenLandsParser()
        # Main-set sample: 16 cards centered on 55%
        main_set = [self._make_rating(f"Main {i}", 55.0 + (i - 8) * 0.5)
                    for i in range(16)]
        # Bonus-sheet outlier — would massively shift mean/std if included
        bonus = self._make_rating("Bonus Outlier", 80.0)

        ratings = main_set + [bonus]
        main_set_names = {r.card_name for r in main_set}
        parser._apply_grades(ratings, main_set_card_names=main_set_names)

        # Bonus card got graded but didn't contaminate stats: with main-set
        # mean ≈ 55%, std ≈ 2.4%, z(80%) ≈ 10 → A+
        assert bonus.grade == "A+"
        # A central main-set card should land at C
        central = main_set[8]  # win_rate = 55.0 == mean
        assert central.grade == "C", f"central card grade={central.grade}"

    def test_dfc_names_rewritten_to_scryfall_form(self):
        """
        17lands returns DFC ratings under the front-face name only. The parser
        must rewrite them to Scryfall's "Front // Back" form so that
        CardRepository.upsert_ratings can match the stored card by exact name.
        """
        parser = SeventeenLandsParser()
        ratings = [
            self._make_rating("Adventurous Eater", 54.7),
            self._make_rating("Stirring Hopesinger", 64.1),
        ]
        main_set_names = {
            "Adventurous Eater // Have a Bite",
            "Adventurous Eater",
            "Stirring Hopesinger",
        }

        parser._canonicalize_dfc_names(ratings, main_set_names)

        names = {r.card_name for r in ratings}
        assert "Adventurous Eater // Have a Bite" in names
        assert "Adventurous Eater" not in names
        # Single-faced cards are untouched
        assert "Stirring Hopesinger" in names

    def test_canonicalize_no_op_without_main_set_names(self):
        parser = SeventeenLandsParser()
        ratings = [self._make_rating("Adventurous Eater", 54.7)]
        parser._canonicalize_dfc_names(ratings, None)
        assert ratings[0].card_name == "Adventurous Eater"

    def test_too_few_cards_skips_grading(self):
        parser = SeventeenLandsParser()
        ratings = [
            self._make_rating(f"Card {i}", 50 + i)
            for i in range(MIN_CARDS_FOR_STATS - 1)
        ]
        parser._apply_grades(ratings)
        assert all(r.grade is None for r in ratings)
        assert all(r.rating is None for r in ratings)
