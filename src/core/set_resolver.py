"""Infer a draft set from independent card names when Vision cannot read its symbol."""

import asyncio
import logging

from src.core.lands import BASIC_LANDS
from src.db.repository import CardRepository
from src.db.session import get_session
from src.parsers.base import ParserError
from src.parsers.scryfall import ScryfallParser

logger = logging.getLogger(__name__)
_MAX_REMOTE_NAMES = 12


def choose_set(matches: dict[str, set[str]], total: int) -> str | None:
    """Require three distinct names, 80% coverage and a clear lead over reprints."""
    ranked = sorted(((len(names), code) for code, names in matches.items()), reverse=True)
    if not ranked:
        return None
    score, code = ranked[0]
    runner_up = ranked[1][0] if len(ranked) > 1 else 0
    if score >= 3 and score >= total * 0.8 and score - runner_up >= 2:
        return code
    return None


async def infer_set_from_cards(card_names: list[str]) -> str | None:
    """Use DB evidence first, then bounded Scryfall printings for unfamiliar sets."""
    basics = {name.lower() for name in BASIC_LANDS}
    names = list(dict.fromkeys(
        name.strip().lower() for name in card_names
        if name.strip() and name.strip().lower() not in basics
    ))
    if len(names) < 3:
        return None

    async with get_session() as session:
        matches = await CardRepository(session).get_set_matches(names)
    code = choose_set(matches, len(names))
    if code:
        logger.info("Inferred set %s from DB card-name evidence (%d names)", code, len(names))
        return code

    # Spread requests across the deck instead of over-weighting one color/CMC.
    if len(names) > _MAX_REMOTE_NAMES:
        names = [names[i * (len(names) - 1) // (_MAX_REMOTE_NAMES - 1)] for i in range(_MAX_REMOTE_NAMES)]
    parser = ScryfallParser()
    remote: dict[str, set[str]] = {}
    try:
        async with asyncio.timeout(20):
            for name in names:
                for code in await parser.fetch_card_sets(name):
                    remote.setdefault(code, set()).add(name)
    except (ParserError, TimeoutError):
        logger.warning("Could not infer set from Scryfall", exc_info=True)
        return None
    finally:
        await parser.close()
    code = choose_set(remote, len(names))
    logger.info("Card-name inference from Scryfall: set=%s, sampled_names=%d", code, len(names))
    return code
