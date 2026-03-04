"""
History command handler for Smart Goblin.

Handles /history (list of past analyses) and callback queries
for viewing analysis details from the inline keyboard.
"""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from src.bot.keyboards import build_analysis_actions_keyboard, build_history_keyboard
from src.bot.messages import format_error, format_history_list
from src.db.models import User
from src.db.repository import AnalysisRepository
from src.db.session import get_session
from src.reports.telegram import TelegramRenderer

logger = logging.getLogger(__name__)

router = Router()


@router.message(Command("history"))
async def handle_history(message: Message, db_user: User) -> None:
    """Handle /history command — list recent analyses."""
    async with get_session() as session:
        analysis_repo = AnalysisRepository(session)
        analyses = await analysis_repo.get_user_analyses(db_user.id, limit=10)

    text = format_history_list(analyses)

    if analyses:
        keyboard = build_history_keyboard(analyses)
        await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
    else:
        await message.answer(text, parse_mode="Markdown")


@router.callback_query(F.data.startswith("history:"))
async def handle_history_detail(callback: CallbackQuery, db_user: User) -> None:
    """Handle callback from history keyboard — show analysis details."""
    await callback.answer()

    try:
        analysis_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return

    async with get_session() as session:
        analysis_repo = AnalysisRepository(session)
        analysis = await analysis_repo.get_by_id(analysis_id)

    if not analysis or analysis.user_id != db_user.id:
        await callback.message.edit_text(format_error("not_found"))
        return

    # Build a simple detail view from the stored analysis
    text = _format_analysis_detail(analysis)
    has_advice = bool(analysis.advice)
    keyboard = build_analysis_actions_keyboard(analysis_id, has_advice=has_advice)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(F.data.startswith("details:"))
async def handle_details(callback: CallbackQuery, db_user: User) -> None:
    """Handle 'Details' action button — same as history detail."""
    await callback.answer()

    try:
        analysis_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return

    async with get_session() as session:
        analysis_repo = AnalysisRepository(session)
        analysis = await analysis_repo.get_by_id(analysis_id)

    if not analysis or analysis.user_id != db_user.id:
        await callback.message.edit_text(format_error("not_found"))
        return

    text = _format_analysis_detail(analysis)
    has_advice = bool(analysis.advice)
    keyboard = build_analysis_actions_keyboard(analysis_id, has_advice=has_advice)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(F.data.startswith("delete:"))
async def handle_delete(callback: CallbackQuery, db_user: User) -> None:
    """Handle 'Delete' action button — remove an analysis."""
    await callback.answer()

    try:
        analysis_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return

    async with get_session() as session:
        analysis_repo = AnalysisRepository(session)
        analysis = await analysis_repo.get_by_id(analysis_id)

        if not analysis or analysis.user_id != db_user.id:
            await callback.message.edit_text(format_error("not_found"))
            return

        await analysis_repo.delete(analysis_id)

    await callback.message.edit_text("🗑 Аналіз видалено.")


def _format_analysis_detail(analysis) -> str:
    """Format a stored analysis as a readable Telegram message."""
    lines = []

    set_label = ""
    if analysis.set and analysis.set.code:
        set_label = f" ({analysis.set.name or analysis.set.code})"

    date_str = analysis.created_at.strftime("%d.%m.%Y %H:%M")
    lines.append(f"📊 *Аналіз #{analysis.id}{set_label}*")
    lines.append(f"📅 {date_str}")

    if analysis.total_score is not None:
        lines.append(f"📈 *Загальна оцінка:* {analysis.total_score:.1f}/5.0")
    if analysis.estimated_win_rate is not None:
        lines.append(
            f"🎯 *Очікуваний win rate:* ~{analysis.estimated_win_rate:.0f}%"
        )

    card_count = len(analysis.main_deck) if analysis.main_deck else 0
    sb_count = len(analysis.sideboard) if analysis.sideboard else 0
    lines.append(f"🃏 Main Deck: {card_count} карт")
    if sb_count:
        lines.append(f"📦 Sideboard: {sb_count} карт")

    return "\n".join(lines)
