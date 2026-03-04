"""
Aiogram middlewares for Smart Goblin Telegram bot.

Provides user auto-registration middleware that ensures every
interacting user has a record in the database.
"""

import logging

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from src.db.repository import UserRepository
from src.db.session import get_session

logger = logging.getLogger(__name__)


class UserRegistrationMiddleware(BaseMiddleware):
    """
    Middleware that auto-registers Telegram users in the database.

    For every incoming event (message, callback query, etc.), this middleware
    checks whether the user exists in the DB and creates a record if not.
    The resulting User model instance is injected into handler data as ``db_user``.
    """

    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = data.get("event_from_user")
        if user is not None:
            async with get_session() as session:
                user_repo = UserRepository(session)
                db_user, created = await user_repo.get_or_create(
                    telegram_id=user.id,
                    username=user.username,
                )
                data["db_user"] = db_user

                if created:
                    logger.info(
                        "New user registered: telegram_id=%d, username=%s",
                        user.id,
                        user.username,
                    )

        return await handler(event, data)
