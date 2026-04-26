"""
Unit tests for the 17lands parser's grade calculation.

Focus on the two pieces of logic that determine the final letter grade:
- ``z_score_to_grade``: the formula extracted from the 17lands frontend bundle.
- ``SeventeenLandsParser._apply_grades``: assigning grades from a global pool.
"""

from decimal import Decimal

import pytest

from src.parsers.base import RatingData
from src.parsers.seventeen_lands import (
    MIN_CARDS_FOR_STATS,
    SeventeenLandsParser,
    z_score_to_grade,
)


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

    def test_too_few_cards_skips_grading(self):
        parser = SeventeenLandsParser()
        ratings = [
            self._make_rating(f"Card {i}", 50 + i)
            for i in range(MIN_CARDS_FOR_STATS - 1)
        ]
        parser._apply_grades(ratings)
        assert all(r.grade is None for r in ratings)
        assert all(r.rating is None for r in ratings)
