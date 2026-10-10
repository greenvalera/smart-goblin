"""Shared on-demand set loading for all photo and /set entry points."""

import logging
import re
from time import monotonic
from dataclasses import dataclass, field
from typing import Optional

from aiogram.types import Message
from src.core.lands import BASIC_LANDS
from src.db.repository import CardRepository
from src.db.session import get_session
from src.parsers.set_importer import get_import_lock, import_set

logger = logging.getLogger(__name__)

async def fetch_known_cards(set_code: str) -> list[str]:
    """Return known card names for a set from DB (empty list if none)."""
    async with get_session() as session:
        names = await CardRepository(session).get_card_names_by_set(set_code)
        return names or []


_SET_CODE_RE = re.compile(r"^[A-Za-z0-9]{2,6}$")
_rating_attempts: dict[str, float] = {}
_RATING_RETRY_SECONDS = 300


def set_mismatch_text(names: list[str], known: list[str], code: str) -> Optional[str]:
    """Reject a deck from a different set before producing fabricated defaults."""
    nonlands = {n.casefold() for n in names if n not in BASIC_LANDS}
    valid = {n.casefold() for n in known}
    valid.update(n.split(" // ", 1)[0] for n in valid.copy())
    if len(nonlands) >= 3 and len(nonlands & valid) / len(nonlands) < 0.5:
        return (
            f"⚠️ Більшість карт не відповідає вибраному сету *{code}*.\n\n"
            "Вкажіть правильний сет: /set КОД або увімкніть автоматичне "
            "визначення: /set reset. Потім надішліть фото ще раз."
        )
    return None


@dataclass
class SetStatus:
    """Availability of a set's data in the DB (after optional auto-import)."""

    known_cards: list[str] = field(default_factory=list)
    has_ratings: bool = False
    available: bool = False  # set exists in DB with cards
    imported: bool = False  # set was auto-imported during this request


async def ensure_set_data(set_code: str, processing_msg: Message) -> SetStatus:
    """
    Make sure a set's cards and ratings are in the DB, importing it if missing.

    Import missing cards, and retry missing ratings at most once per five
    minutes per process. Concurrent requests share the same import lock.
    """
    set_code = set_code.strip().upper()
    if not _SET_CODE_RE.fullmatch(set_code):
        logger.warning("Refusing to import set with invalid code %r", set_code)
        return SetStatus()

    imported = False
    known = await fetch_known_cards(set_code)
    async def has_ratings() -> bool:
        async with get_session() as session:
            return await CardRepository(session).has_ratings_for_set(set_code)

    async def needs_import() -> bool:
        if not known:
            return True
        return (
            not await has_ratings()
            and monotonic() - _rating_attempts.get(set_code, float('-inf')) >= _RATING_RETRY_SECONDS
        )

    if await needs_import():
        async with get_import_lock(set_code):
            # Another request may have imported the set while we waited.
            known = await fetch_known_cards(set_code)
            if await needs_import():
                await processing_msg.edit_text(
                    f"🔄 Дані сету *{set_code}* неповні. "
                    "Оновлюю дані сету (карти та рейтинги 17lands), "
                    "це може зайняти до хвилини...",
                    parse_mode="Markdown",
                )
                _rating_attempts[set_code] = monotonic()
                try:
                    result = await import_set(set_code)
                except Exception:
                    logger.exception("Auto-import of set %s failed", set_code)
                    return SetStatus(known_cards=known, available=bool(known))
                if result is None:
                    logger.warning("Auto-import: set %s not found on Scryfall", set_code)
                    return SetStatus(known_cards=known, available=bool(known))
                logger.info(
                    "Auto-imported set %s: %d cards, %d ratings",
                    set_code, result.cards_count, result.ratings_count,
                )
                known = await fetch_known_cards(set_code)
                imported = True

    if not known:
        return SetStatus()

    return SetStatus(
        known_cards=known, has_ratings=await has_ratings(), available=True, imported=imported
    )


def set_unavailable_text(set_code: str, status: SetStatus) -> Optional[str]:
    """Return the user-facing message if the set can't be analyzed, else None."""
    code = set_code.upper()
    if not status.available:
        return (
            f"⚠️ Не вдалося знайти або завантажити дані сету *{code}*.\n\n"
            "Спробуйте пізніше або вкажіть сет вручну: /set КОД"
        )
    if not status.has_ratings:
        return (
            f"📭 Рейтингів по сету *{code}* у базі поки немає. "
            "Карти завантажені, але статистика 17lands ще недоступна "
            "або її не вдалося завантажити.\n\n"
            "Рейтинги оновлюються щодня, спробуйте пізніше."
        )
    return None


