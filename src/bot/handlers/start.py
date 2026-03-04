"""
Start and help command handlers for Smart Goblin.

Handles /start (greeting + user registration) and /help (usage instructions).
"""

import logging

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from src.bot.messages import format_help, format_start
from src.db.models import User

logger = logging.getLogger(__name__)

router = Router()


@router.message(CommandStart())
async def handle_start(message: Message, db_user: User) -> None:
    """Handle /start command — greet user and show intro."""
    logger.info("User %d issued /start", db_user.telegram_id)
    await message.answer(format_start(), parse_mode="Markdown")


@router.message(Command("help"))
async def handle_help(message: Message) -> None:
    """Handle /help command — show usage instructions."""
    await message.answer(format_help(), parse_mode="Markdown")
