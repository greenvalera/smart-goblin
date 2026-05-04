"""
Periodic update scheduler for Smart Goblin.

Uses APScheduler to run parser updates daily (Scryfall cards + 17lands ratings).

Can also be run manually::

    python -m src.parsers.scheduler
"""

import asyncio
import logging
import re
import sys
from uuid import UUID

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import get_settings
from src.db.repository import CardRepository, SetRepository
from src.db.session import get_session
from src.parsers.base import ParserError
from src.parsers.grade_validator import (
    ValidationReport,
    log_validation_report,
    validate_set_grades,
)
from src.parsers.scryfall import ScryfallParser
from src.parsers.seventeen_lands import SeventeenLandsParser
from src.db.repository import CardData as RepoCardData, RatingData as RepoRatingData

logger = logging.getLogger(__name__)

# Matches the Scryfall UUID embedded in 17lands image URLs, e.g.:
# https://cards.scryfall.io/large/front/a/b/<uuid>.jpg?version=...
_SCRYFALL_UUID_RE = re.compile(
    r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\."
)


async def run_updates() -> list[ValidationReport]:
    """
    Run all parser updates for sets stored in the database.

    Fetches card metadata from Scryfall and ratings from 17lands
    for every set present in the DB. After each set's ratings are
    upserted, runs a grade validation pass that re-fetches 17lands
    and compares against the freshly persisted DB grades; mismatches
    are logged at WARNING but never raise.

    Errors are logged but never propagated so that a single failing
    parser cannot crash the bot.

    Returns:
        Per-set ``ValidationReport`` list. Used by the manual
        ``--strict`` CLI invocation to gate its exit code; the daily
        APScheduler trigger ignores the return value.
    """
    logger.info("Starting scheduled parser update...")

    scryfall = ScryfallParser()
    seventeen = SeventeenLandsParser()
    reports: list[ValidationReport] = []

    try:
        async with get_session() as session:
            set_repo = SetRepository(session)
            card_repo = CardRepository(session)

            # Fetch all known sets from the database
            from sqlalchemy import select
            from src.db.models import Set as SetModel

            result = await session.execute(select(SetModel))
            sets = list(result.scalars().all())

            if not sets:
                logger.info("No sets in database, skipping update.")
                return reports

            for set_obj in sets:
                set_code = set_obj.code
                logger.info("Updating set %s (%s)...", set_code, set_obj.name)

                # --- Scryfall: card metadata ---
                main_set_card_names: set[str] = set()
                try:
                    cards = await scryfall.fetch_set_cards(set_code)
                    if cards:
                        # Include both full name and front-face name for
                        # split / prepare layout cards: Scryfall stores them
                        # as "Front // Back" but 17lands uses only the front.
                        for c in cards:
                            main_set_card_names.add(c.name)
                            if " // " in c.name:
                                main_set_card_names.add(c.name.split(" // ", 1)[0])
                        repo_cards = [
                            RepoCardData(
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
                            for c in cards
                        ]
                        count = await card_repo.upsert_cards(repo_cards)
                        logger.info("Upserted %d cards for %s from Scryfall.", count, set_code)
                except ParserError as exc:
                    logger.error("Scryfall error for %s: %s", set_code, exc)
                except Exception as exc:
                    logger.error("Unexpected error fetching Scryfall data for %s: %s", set_code, exc)

                # --- 17lands: ratings ---
                # Pass main-set card names so the global stats pool excludes
                # bonus-sheet reprints that 17lands mixes into the same feed.
                #
                # We deliberately do NOT pass start_date: Scryfall's
                # release_date is the *paper* release, but 17lands' format
                # actually starts ~3 days earlier on Arena (early access).
                # Passing Scryfall's date would chop those 3 days from the
                # sample and shift grades. The API default (no date filter)
                # returns the full format history, which matches the site's
                # default for newly released sets exactly.
                try:
                    ratings = await seventeen.fetch_ratings(
                        set_code,
                        main_set_card_names=main_set_card_names or None,
                    )
                    if ratings:
                        # --- Seed bonus/Special Guest cards ---
                        # 17lands mixes bonus-sheet cards (e.g. Special Guests in SOS)
                        # into the ratings feed. These have a different Scryfall set code
                        # and were never seeded by the Scryfall pass above, so upsert_ratings
                        # would silently skip them. We identify them as cards whose name is
                        # absent from main_set_card_names and fetch their metadata by the
                        # Scryfall UUID embedded in the 17lands image URL.
                        if main_set_card_names:
                            bonus_cards: list[RepoCardData] = []
                            seen_bonus_names: set[str] = set()
                            for r in ratings:
                                if r.card_name in main_set_card_names:
                                    continue
                                if r.card_name in seen_bonus_names or not r.url:
                                    continue
                                m = _SCRYFALL_UUID_RE.search(r.url)
                                if not m:
                                    continue
                                try:
                                    scryfall_id = UUID(m.group(1))
                                except ValueError:
                                    continue
                                card_data = await scryfall.fetch_card_by_id(scryfall_id)
                                if card_data is None:
                                    logger.warning(
                                        "Could not fetch Scryfall data for bonus card %s (id=%s)",
                                        r.card_name, scryfall_id,
                                    )
                                    continue
                                seen_bonus_names.add(r.card_name)
                                # scryfall_id is intentionally None: the same
                                # SPG printing can appear in multiple formats
                                # (ECL, SOS, …) and cards.scryfall_id must be
                                # globally unique. image_uri still carries the
                                # URL so card images display correctly.
                                bonus_cards.append(RepoCardData(
                                    name=card_data.name,
                                    set_code=set_code,
                                    scryfall_id=None,
                                    mana_cost=card_data.mana_cost,
                                    cmc=card_data.cmc,
                                    colors=card_data.colors,
                                    type_line=card_data.type_line,
                                    rarity=card_data.rarity,
                                    image_uri=card_data.image_uri,
                                ))
                            if bonus_cards:
                                seeded = await card_repo.upsert_cards(bonus_cards)
                                logger.info(
                                    "Seeded %d bonus/Special Guest card(s) for %s.",
                                    seeded, set_code,
                                )

                        repo_ratings = [
                            RepoRatingData(
                                card_name=r.card_name,
                                set_code=set_code,
                                source=r.source,
                                rating=r.rating,
                                win_rate=r.win_rate,
                                games_played=r.games_played,
                                format=r.format,
                            )
                            for r in ratings
                        ]
                        count = await card_repo.upsert_ratings(repo_ratings)
                        logger.info("Upserted %d ratings for %s from 17lands.", count, set_code)
                except ParserError as exc:
                    logger.error("17lands error for %s: %s", set_code, exc)
                except Exception as exc:
                    logger.error("Unexpected error fetching 17lands data for %s: %s", set_code, exc)

                # --- Validation: compare fresh 17lands grades vs DB ---
                # Re-fetches 17lands with the same params used above and
                # checks every card's stored grade still matches what the
                # site computes. Failures here are warnings, not hard errors.
                try:
                    report = await validate_set_grades(
                        session,
                        set_code,
                        seventeen,
                        main_set_card_names or set(),
                    )
                    log_validation_report(report)
                    reports.append(report)
                except Exception as exc:
                    logger.error("Grade validation failed for %s: %s", set_code, exc)

    except Exception as exc:
        logger.error("Scheduler update failed: %s", exc)
    finally:
        await scryfall.close()
        await seventeen.close()

    logger.info("Scheduled parser update finished.")
    return reports


def create_scheduler() -> AsyncIOScheduler:
    """
    Create and configure the APScheduler instance.

    The scheduler runs ``run_updates`` every day at the hour specified
    by ``PARSER_SCHEDULE_HOUR`` in the configuration (default 03:00 UTC).

    Returns:
        Configured (but not started) AsyncIOScheduler.
    """
    settings = get_settings()
    hour = settings.parser.parser_schedule_hour

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_updates,
        trigger=CronTrigger(hour=hour, minute=0, timezone="UTC"),
        id="parser_daily_update",
        name="Daily parser update (Scryfall + 17lands)",
        replace_existing=True,
    )

    logger.info("Scheduler configured: daily update at %02d:00 UTC", hour)
    return scheduler


if __name__ == "__main__":
    # Manual run: python -m src.parsers.scheduler [--strict]
    #
    # ``--strict`` exits 1 if any set has grade mismatches. Useful as a
    # post-update gate; the daily APScheduler trigger ignores this flag.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    strict = "--strict" in sys.argv[1:]
    logger.info("Running parser update manually (strict=%s)...", strict)
    reports = asyncio.run(run_updates())
    if strict:
        total_mismatches = sum(r.mismatched for r in reports)
        if total_mismatches > 0:
            logger.error(
                "Strict mode: %d grade mismatch(es) across %d set(s).",
                total_mismatches,
                sum(1 for r in reports if r.mismatched > 0),
            )
            sys.exit(1)
