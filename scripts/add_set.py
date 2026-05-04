"""
Add an MTG set to the database by its code.

Validates the set code against Scryfall API, creates the set record,
and optionally fetches all cards and ratings.

Usage::

    python -m scripts.add_set FDN
    python -m scripts.add_set FDN --no-fetch
    python -m scripts.add_set SOA --parent SOS  # link bonus-sheet to its main set
"""

import argparse
import asyncio
import logging
import re
import sys
from typing import Optional
from uuid import UUID

from src.db.repository import CardRepository, SetRepository
from src.db.repository import CardData as RepoCardData, RatingData as RepoRatingData
from src.db.session import get_session
from src.parsers.base import ParserError
from src.parsers.scryfall import ScryfallParser
from src.parsers.seventeen_lands import SeventeenLandsParser

logger = logging.getLogger(__name__)

_SCRYFALL_UUID_RE = re.compile(
    r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\."
)


async def add_set(
    set_code: str,
    *,
    fetch_cards: bool = True,
    parent_code: Optional[str] = None,
) -> None:
    """
    Validate a set code via Scryfall and add it to the database.

    Args:
        set_code: MTG set code (e.g. "FDN", "MKM").
        fetch_cards: If True, also fetch cards from Scryfall and ratings from 17lands.
        parent_code: Optional parent set code (e.g. "SOS" for the bonus sheet "SOA").
            The parent must already exist in the database.
    """
    set_code = set_code.upper()
    parent_code = parent_code.upper() if parent_code else None

    if parent_code and parent_code == set_code:
        logger.error("Parent set code '%s' cannot equal the set code itself.", parent_code)
        sys.exit(1)

    scryfall = ScryfallParser()

    try:
        # 1. Validate set exists on Scryfall
        logger.info("Validating set '%s' via Scryfall API...", set_code)
        set_info = await scryfall.fetch_set_info(set_code)

        if set_info is None:
            logger.error("Set '%s' not found on Scryfall. Check the code and try again.", set_code)
            sys.exit(1)

        logger.info(
            "Found set: %s (%s), released %s",
            set_info.name,
            set_info.code,
            set_info.release_date or "N/A",
        )

        # 2. Add set to database
        async with get_session() as session:
            set_repo = SetRepository(session)

            # Validate parent exists in DB before creating/updating the child.
            if parent_code:
                parent_set = await set_repo.get_by_code(parent_code)
                if parent_set is None:
                    logger.error(
                        "Parent set '%s' not found in database. "
                        "Add the parent first: python -m scripts.add_set %s",
                        parent_code,
                        parent_code,
                    )
                    sys.exit(1)

            existing = await set_repo.get_by_code(set_code)

            if existing:
                logger.info("Set '%s' already exists in database (id=%d).", set_code, existing.id)
                if parent_code and existing.parent_set_code != parent_code:
                    existing.parent_set_code = parent_code
                    await session.flush()
                    logger.info("Linked '%s' → parent '%s'.", set_code, parent_code)
                elif parent_code:
                    logger.info("'%s' already linked to parent '%s'.", set_code, parent_code)
            else:
                from src.db.models import Set as SetModel

                new_set = SetModel(
                    code=set_info.code,
                    name=set_info.name,
                    release_date=set_info.release_date,
                    parent_set_code=parent_code,
                )
                session.add(new_set)
                await session.flush()
                logger.info("Created set '%s' — %s (id=%d).", new_set.code, new_set.name, new_set.id)
                if parent_code:
                    logger.info("Linked '%s' → parent '%s'.", set_code, parent_code)

            if not fetch_cards:
                logger.info("Skipping card/rating fetch (--no-fetch).")
                return

            # 3. Fetch cards from Scryfall
            logger.info("Fetching cards for '%s' from Scryfall...", set_code)
            cards = await scryfall.fetch_set_cards(set_code)
            main_set_card_names: set[str] = set()
            if cards:
                # Include both the full Scryfall name and the front-face form
                # for split / DFC / adventure / prepare layouts. 17lands returns
                # those ratings under the front face only; passing both forms
                # lets _canonicalize_dfc_names rewrite them to the full
                # "Front // Back" name so upsert_ratings finds the card.
                for c in cards:
                    main_set_card_names.add(c.name)
                    if " // " in c.name:
                        main_set_card_names.add(c.name.split(" // ", 1)[0])

                card_repo = CardRepository(session)
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
                logger.info("Upserted %d cards for '%s'.", count, set_code)
            else:
                logger.warning("No cards returned from Scryfall for '%s'.", set_code)

            # 4. Fetch ratings from 17lands
            logger.info("Fetching ratings for '%s' from 17lands...", set_code)
            seventeen = SeventeenLandsParser()
            try:
                ratings = await seventeen.fetch_ratings(
                    set_code,
                    main_set_card_names=main_set_card_names or None,
                )
                if ratings:
                    card_repo = CardRepository(session)

                    # Seed bonus/Special Guest cards not in the main Scryfall set
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
                                "Seeded %d bonus/Special Guest card(s) for '%s'.",
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
                    logger.info("Upserted %d ratings for '%s'.", count, set_code)
                else:
                    logger.warning("No ratings returned from 17lands for '%s' (set may be too new).", set_code)
            except ParserError as exc:
                logger.warning("Could not fetch 17lands ratings: %s", exc)
            finally:
                await seventeen.close()

    except ParserError as exc:
        logger.error("Scryfall API error: %s", exc)
        sys.exit(1)
    finally:
        await scryfall.close()

    logger.info("Done!")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add an MTG set to Smart Goblin database by its code.",
    )
    parser.add_argument(
        "set_code",
        type=str,
        help="MTG set code, e.g. FDN, MKM, OTJ",
    )
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        default=False,
        help="Only create the set record, skip fetching cards and ratings",
    )
    parser.add_argument(
        "--parent",
        type=str,
        default=None,
        metavar="CODE",
        help=(
            "Link this set as a bonus-sheet child of the given parent set code "
            "(e.g. --parent SOS for SOA). Parent must already exist in the database."
        ),
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    asyncio.run(
        add_set(
            args.set_code,
            fetch_cards=not args.no_fetch,
            parent_code=args.parent,
        )
    )


if __name__ == "__main__":
    main()
