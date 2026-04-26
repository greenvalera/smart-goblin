"""
Grade validator for Smart Goblin.

After every DB ratings update, re-fetches live 17lands data and compares the
freshly computed letter grade for each card against what's stored in the DB
(via the ``rating → letter grade`` round-trip used everywhere on display).

The validator never writes to the DB and never raises — it returns a
``ValidationReport`` that the scheduler logs. A non-zero ``mismatched`` count
means our DB grade for at least one card no longer matches the site.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import CardRating
from src.db.repository import CardRepository
from src.parsers.base import NotFoundError, RatingData
from src.parsers.seventeen_lands import (
    SeventeenLandsParser,
    normalize_card_name,
)
from src.reports.models import rating_to_grade

logger = logging.getLogger(__name__)

# How many per-card mismatch lines to log before truncating with "...and N more".
# Avoids flooding the daily scheduler log when a formula change diverges every
# card in a set.
MAX_DIFFS_LOGGED = 50


@dataclass
class GradeDiff:
    """A single per-card grade discrepancy."""

    card_name: str
    expected_grade: Optional[str]   # from a fresh 17lands fetch
    actual_grade: str               # rating_to_grade(db_rating)
    win_rate: Optional[Decimal]
    games_played: Optional[int]


@dataclass
class ValidationReport:
    """Per-set summary of a grade validation pass."""

    set_code: str
    total: int = 0
    matched: int = 0
    mismatched: int = 0
    missing_in_db: list[str] = field(default_factory=list)
    missing_on_17lands: list[str] = field(default_factory=list)
    diffs: list[GradeDiff] = field(default_factory=list)
    skipped: bool = False
    skip_reason: Optional[str] = None


def _db_grade(rating: Optional[Decimal]) -> str:
    """DB-side rating → letter grade. Mirrors what reports show users."""
    return rating_to_grade(rating)


def _select_db_rating(
    ratings: list[CardRating], format_name: str
) -> Optional[CardRating]:
    """Pick the 17lands/{format} rating row, if any, from a card's ratings."""
    for r in ratings:
        if r.source == SeventeenLandsParser.SOURCE_NAME and r.format == format_name:
            return r
    return None


async def validate_set_grades(
    session: AsyncSession,
    set_code: str,
    parser: SeventeenLandsParser,
    main_set_card_names: set[str],
    format_name: str = "PremierDraft",
) -> ValidationReport:
    """
    Compare DB-side grades for ``set_code`` against a fresh 17lands fetch.

    Args:
        session: Active DB session (read-only use).
        set_code: Set code to validate (e.g. ``"TLA"``).
        parser: Reusable ``SeventeenLandsParser`` (the same instance the
            scheduler already created).
        main_set_card_names: Names of the set's main-set cards. Passed to
            ``fetch_ratings`` so bonus-sheet reprints are excluded from the
            stats pool the same way they were on upsert.
        format_name: Format to validate (defaults to PremierDraft, matching
            the scheduler).

    Returns:
        ``ValidationReport`` describing the comparison. ``skipped=True`` when
        17lands has no data for this set (e.g. just-released set with no API
        coverage yet).
    """
    report = ValidationReport(set_code=set_code)

    try:
        fresh: list[RatingData] = await parser.fetch_ratings(
            set_code,
            format_name=format_name,
            main_set_card_names=main_set_card_names or None,
        )
    except NotFoundError:
        report.skipped = True
        report.skip_reason = "17lands returned 404"
        return report

    if not fresh:
        report.skipped = True
        report.skip_reason = "17lands returned no data"
        return report

    # Build {normalized_name: RatingData} for lookup. Use the same
    # normalization used elsewhere so Jötun ≡ Jotun, etc.
    fresh_by_norm: dict[str, RatingData] = {
        normalize_card_name(r.card_name): r for r in fresh
    }

    card_repo = CardRepository(session)
    db_cards = await card_repo.get_by_set(set_code)

    db_by_norm: dict[str, "Card"] = {  # noqa: F821 - forward type only
        normalize_card_name(c.name): c for c in db_cards
    }

    seen_db_keys: set[str] = set()

    for norm_name, fresh_rating in fresh_by_norm.items():
        card = db_by_norm.get(norm_name)
        if card is None:
            # 17lands knows this card but our cards table doesn't — usually a
            # bonus-sheet reprint we never imported, or a name normalization
            # gap. Worth surfacing but not a grade mismatch.
            report.missing_in_db.append(fresh_rating.card_name)
            continue

        seen_db_keys.add(norm_name)
        report.total += 1

        db_rating_row = _select_db_rating(card.ratings, format_name)
        db_rating_value = db_rating_row.rating if db_rating_row else None

        expected = fresh_rating.grade            # str | None (None when stats pool too small)
        actual = _db_grade(db_rating_value)      # always a str ("?" for None)

        # Both sides "no grade" → matched. (Scheduler stored None, fresh fetch
        # also computed no grade.)
        if expected is None and db_rating_value is None:
            report.matched += 1
            continue

        # Normalise: when fresh fetch has no grade, use "?" to align with
        # rating_to_grade's None sentinel. This way the diff line is readable.
        expected_str = expected if expected is not None else "?"

        if expected_str == actual:
            report.matched += 1
        else:
            report.mismatched += 1
            report.diffs.append(
                GradeDiff(
                    card_name=card.name,
                    expected_grade=expected_str,
                    actual_grade=actual,
                    win_rate=fresh_rating.win_rate,
                    games_played=fresh_rating.games_played,
                )
            )

    # Cards in our DB that 17lands didn't return at all this run. Often
    # benign (low-play cards filtered by 17lands' own threshold) but worth
    # surfacing because their stored rating is now stale.
    for norm_name, card in db_by_norm.items():
        if norm_name in seen_db_keys:
            continue
        db_rating_row = _select_db_rating(card.ratings, format_name)
        if db_rating_row is None or db_rating_row.rating is None:
            # Never had a 17lands rating to begin with — nothing to flag.
            continue
        report.missing_on_17lands.append(card.name)

    return report


def log_validation_report(report: ValidationReport) -> None:
    """
    Emit a ``ValidationReport`` through the standard logger.

    INFO for the per-set summary, WARNING for each grade diff (capped at
    ``MAX_DIFFS_LOGGED``), INFO for skip reasons.
    """
    if report.skipped:
        logger.info(
            "Grade validation skipped for %s: %s",
            report.set_code,
            report.skip_reason,
        )
        return

    logger.info(
        "Grade validation for %s: %d/%d matched, %d mismatched, "
        "%d unknown to DB, %d stale in DB",
        report.set_code,
        report.matched,
        report.total,
        report.mismatched,
        len(report.missing_in_db),
        len(report.missing_on_17lands),
    )

    for diff in report.diffs[:MAX_DIFFS_LOGGED]:
        logger.warning(
            "Grade mismatch for %s: expected %s, got %s (wr=%s, n=%s)",
            diff.card_name,
            diff.expected_grade,
            diff.actual_grade,
            diff.win_rate,
            diff.games_played,
        )

    extra = len(report.diffs) - MAX_DIFFS_LOGGED
    if extra > 0:
        logger.warning(
            "...and %d more grade mismatch(es) for %s not shown",
            extra,
            report.set_code,
        )
