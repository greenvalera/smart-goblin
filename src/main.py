"""
Entry point for the Smart Goblin Telegram bot.

Initializes logging, database, scheduler, and starts aiogram polling.
Usage: python -m src.main
"""

import asyncio
import logging
import signal
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from sqlalchemy import text

from src.config import get_settings
from src.bot.handlers import get_handlers_router
from src.bot.middlewares import UserRegistrationMiddleware
from src.db.session import close_engine, get_engine
from src.parsers.scheduler import create_scheduler

logger = logging.getLogger(__name__)


def setup_logging(level: str) -> None:
    """Configure root logger with a consistent format."""
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    # Silence noisy third-party loggers
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.INFO)


async def main() -> None:
    """Run the bot with scheduler and graceful shutdown."""
    settings = get_settings()
    setup_logging(settings.log_level)

    logger.info("Starting Smart Goblin bot...")

    # Verify DB connectivity early
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("Database connection OK.")

    # Create bot and dispatcher
    bot = Bot(
        token=settings.telegram.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Register middleware
    dp.message.middleware(UserRegistrationMiddleware())
    dp.callback_query.middleware(UserRegistrationMiddleware())

    # Register handlers
    dp.include_router(get_handlers_router())

    # Start scheduler (if enabled)
    scheduler = None
    if settings.parser.parser_schedule_enabled:
        scheduler = create_scheduler()
        scheduler.start()
        logger.info("Scheduler started.")
    else:
        logger.info("Scheduler disabled via PARSER_SCHEDULE_ENABLED=false.")

    # Register SIGTERM handler for graceful shutdown (Unix only)
    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(
            signal.SIGTERM,
            lambda: asyncio.ensure_future(dp.stop_polling()),
        )
        logger.info("SIGTERM handler registered.")

    # Register bot commands for Telegram menu
    await bot.set_my_commands([
        BotCommand(command="start", description="Розпочати роботу"),
        BotCommand(command="help", description="Довідка та команди"),
        BotCommand(command="analyze", description="Аналіз колоди (надіслати з фото)"),
        BotCommand(command="draft", description="Режим драфту: main deck + sideboard"),
        BotCommand(command="history", description="Мої попередні аналізи"),
        BotCommand(command="stats", description="Статистика карти: /stats назва"),
        BotCommand(command="set", description="Встановити активний сет: /set ECL"),
    ])
    logger.info("Bot commands registered.")

    try:
        logger.info("Bot is now polling for updates...")
        await dp.start_polling(bot)
    finally:
        logger.info("Shutting down...")
        if scheduler is not None:
            scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped.")
        await close_engine()
        logger.info("Database connections closed.")
        await bot.session.close()
        logger.info("Bot session closed. Goodbye!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
