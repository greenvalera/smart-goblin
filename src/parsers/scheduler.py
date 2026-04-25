"""
Periodic update scheduler for Smart Goblin.

Uses APScheduler to run parser updates daily (Scryfall cards + 17lands ratings).

Can also be run manually::

    python -m src.parsers.scheduler
"""

import asyncio
import logging
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import get_settings
from src.db.repository import CardRepository, SetRepository
from src.db.session import get_session
from src.parsers.base import ParserError
from src.parsers.scryfall import ScryfallParser
from src.parsers.seventeen_lands import SeventeenLandsParser
from src.db.repository import CardData as RepoCardData, RatingData as RepoRatingData

logger = logging.getLogger(__name__)


async def run_updates() -> None:
    """
    Run all parser updates for sets stored in the database.

    Fetches card metadata from Scryfall and ratings from 17lands
    for every set present in the DB. Errors are logged but never
    propagated so that a single failing parser cannot crash the bot.
    """
    logger.info("Starting scheduled parser update...")

    scryfall = ScryfallParser()
    seventeen = SeventeenLandsParser()

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
                return

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
                # Pass main-set card names so per-color stats exclude bonus-sheet
                # reprints that 17lands mixes into the same feed.
                try:
                    ratings = await seventeen.fetch_ratings(
                        set_code,
                        main_set_card_names=main_set_card_names or None,
                    )
                    if ratings:
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

    except Exception as exc:
        logger.error("Scheduler update failed: %s", exc)
    finally:
        await scryfall.close()
        await seventeen.close()

    logger.info("Scheduled parser update finished.")


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
    # Manual run: python -m src.parsers.scheduler
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logger.info("Running parser update manually...")
    asyncio.run(run_updates())
