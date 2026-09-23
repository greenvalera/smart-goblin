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
import sys
from typing import Optional

from src.parsers.base import ParserError
from src.parsers.set_importer import SetImportError, import_set

logger = logging.getLogger(__name__)


async def add_set(
    set_code: str,
    *,
    fetch_cards: bool = True,
    parent_code: Optional[str] = None,
) -> None:
    """
    Validate a set code via Scryfall and add it to the database.

    Thin CLI wrapper around :func:`src.parsers.set_importer.import_set` that
    exits non-zero on failure.

    Args:
        set_code: MTG set code (e.g. "FDN", "MKM").
        fetch_cards: If True, also fetch cards from Scryfall and ratings from 17lands.
        parent_code: Optional parent set code (e.g. "SOS" for the bonus sheet "SOA").
            The parent must already exist in the database.
    """
    try:
        result = await import_set(set_code, fetch_cards=fetch_cards, parent_code=parent_code)
    except SetImportError as exc:
        logger.error("%s", exc)
        sys.exit(1)
    except ParserError as exc:
        logger.error("Scryfall API error: %s", exc)
        sys.exit(1)

    if result is None:
        logger.error("Set '%s' not found on Scryfall. Check the code and try again.", set_code.upper())
        sys.exit(1)

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
