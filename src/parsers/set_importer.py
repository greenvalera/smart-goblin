"""
Import an MTG set into the database by its code.

Shared by the ``scripts.add_set`` CLI and the bot (auto-import of a set that
was detected on a deck photo but is missing from the DB). Validates the code
via Scryfall, creates the set record, then fetches cards from Scryfall and
ratings from 17lands.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from src.db.models import Set as SetModel
from src.db.repository import CardData as RepoCardData
from src.db.repository import CardRepository, SetRepository
from src.db.repository import RatingData as RepoRatingData
from src.db.session import get_session
from src.parsers.base import ParserError
from src.parsers.scryfall import ScryfallParser
from src.parsers.seventeen_lands import SeventeenLandsParser

logger = logging.getLogger(__name__)

# One lock per set code so concurrent imports of the same set (e.g. two users
# sending photos of a brand-new set at once) don't race on the INSERT.
_import_locks: dict[str, asyncio.Lock] = {}


class SetImportError(Exception):
    """Invalid import request (e.g. bad or missing parent set)."""


@dataclass
class SetImportResult:
    """Outcome of a successful set import."""

    set_code: str
    set_name: str
    created: bool
    cards_count: int = 0
    ratings_count: int = 0


def get_import_lock(set_code: str) -> asyncio.Lock:
    """Return the per-set-code import lock."""
    return _import_locks.setdefault(set_code.upper(), asyncio.Lock())


async def import_set(
    set_code: str,
    *,
    fetch_cards: bool = True,
    parent_code: Optional[str] = None,
) -> Optional[SetImportResult]:
    """
    Validate a set code via Scryfall and add it (with cards and ratings) to the DB.

    Args:
        set_code: MTG set code (e.g. "FDN", "MKM").
        fetch_cards: If True, also fetch cards from Scryfall and ratings from 17lands.
        parent_code: Optional parent set code (e.g. "SOS" for the bonus sheet "SOA").
            The parent must already exist in the database.

    Returns:
        SetImportResult, or None if the set does not exist on Scryfall.

    Raises:
        SetImportError: If ``parent_code`` is invalid or missing from the DB.
        ParserError: If the Scryfall API fails.
    """
    set_code = set_code.upper()
    parent_code = parent_code.upper() if parent_code else None

    if parent_code and parent_code == set_code:
        raise SetImportError(f"Parent set code '{parent_code}' cannot equal the set code itself.")

    scryfall = ScryfallParser()

    try:
        # 1. Validate set exists on Scryfall
        logger.info("Validating set '%s' via Scryfall API...", set_code)
        set_info = await scryfall.fetch_set_info(set_code)

        if set_info is None:
            logger.error("Set '%s' not found on Scryfall.", set_code)
            return None

        logger.info(
            "Found set: %s (%s), released %s",
            set_info.name,
            set_info.code,
            set_info.release_date or "N/A",
        )
        result = SetImportResult(set_code=set_code, set_name=set_info.name, created=False)

        # 2. Add set to database
        async with get_session() as session:
            set_repo = SetRepository(session)

            # Validate parent exists in DB before creating/updating the child.
            if parent_code:
                parent_set = await set_repo.get_by_code(parent_code)
                if parent_set is None:
                    raise SetImportError(
                        f"Parent set '{parent_code}' not found in database. "
                        f"Add the parent first: python -m scripts.add_set {parent_code}"
                    )

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
                new_set = SetModel(
                    code=set_info.code.upper(),
                    name=set_info.name,
                    release_date=set_info.release_date,
                    parent_set_code=parent_code,
                )
                session.add(new_set)
                await session.flush()
                result.created = True
                logger.info("Created set '%s' — %s (id=%d).", new_set.code, new_set.name, new_set.id)
                if parent_code:
                    logger.info("Linked '%s' → parent '%s'.", set_code, parent_code)

            if not fetch_cards:
                logger.info("Skipping card/rating fetch.")
                return result

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
                result.cards_count = await card_repo.upsert_cards(repo_cards)
                logger.info("Upserted %d cards for '%s'.", result.cards_count, set_code)
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
                    result.ratings_count = await card_repo.upsert_ratings(repo_ratings)
                    logger.info("Upserted %d ratings for '%s'.", result.ratings_count, set_code)
                else:
                    logger.warning("No ratings returned from 17lands for '%s' (set may be too new).", set_code)
            except ParserError as exc:
                logger.warning("Could not fetch 17lands ratings: %s", exc)
            finally:
                await seventeen.close()

    finally:
        await scryfall.close()

    logger.info("Import of '%s' done.", set_code)
    return result
