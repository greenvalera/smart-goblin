"""
Stats and set command handlers for Smart Goblin.

Handles /stats {card_name} (card statistics) and /set {code} (set override).
"""

import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from src.bot.messages import format_card_stats, format_error
from src.db.models import User
from src.db.repository import CardRepository, UserRepository
from src.db.session import get_session

logger = logging.getLogger(__name__)

router = Router()


@router.message(Command("stats"))
async def handle_stats(message: Message, command: CommandObject) -> None:
    """Handle /stats {card_name} — show statistics for a card."""
    card_name = command.args
    if not card_name or not card_name.strip():
        await message.answer(
            "Вкажіть назву карти, наприклад: /stats Lightning Bolt"
        )
        return

    card_name = card_name.strip()

    async with get_session() as session:
        card_repo = CardRepository(session)
        cards = await card_repo.search_by_name(card_name, limit=1)

    if not cards:
        await message.answer(format_error("not_found"))
        return

    card = cards[0]
    text = format_card_stats(card, list(card.ratings) if card.ratings else [])
    await message.answer(text, parse_mode="Markdown")


@router.message(Command("set"))
async def handle_set(
    message: Message, command: CommandObject, state: FSMContext, db_user: User
) -> None:
    """Handle /set {code} — manually override the set for next analysis."""
    set_code = command.args
    if not set_code or not set_code.strip():
        # Show current override: FSM state takes priority, fallback to DB
        data = await state.get_data()
        current = data.get("set_override") or db_user.active_set_code
        if current:
            await message.answer(
                f"Поточний сет: *{current}*\n"
                "Щоб змінити: /set КОД\n"
                "Щоб скинути: /set reset",
                parse_mode="Markdown",
            )
        else:
            await message.answer(
                "Вкажіть код сету, наприклад: /set MKM\n"
                "Це перевизначить автоматичне визначення сету для наступних аналізів."
            )
        return

    set_code = set_code.strip().upper()

    if set_code == "RESET":
        await state.update_data(set_override=None)
        async with get_session() as session:
            await UserRepository(session).update_active_set(message.from_user.id, None)
        await message.answer("Сет скинуто. Буде визначатися автоматично.")
        return

    await state.update_data(set_override=set_code)
    async with get_session() as session:
        await UserRepository(session).update_active_set(message.from_user.id, set_code)
    await message.answer(
        f"Сет встановлено: *{set_code}*\n"
        "Цей сет буде використано для наступного аналізу.",
        parse_mode="Markdown",
    )
    logger.info(
        "User %d set override to %s", message.from_user.id, set_code
    )
