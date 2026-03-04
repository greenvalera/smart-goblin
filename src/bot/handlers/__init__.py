"""
Bot handlers package for Smart Goblin.

Aggregates all handler routers into a single router for use
by the Dispatcher.
"""

from aiogram import Router

from src.bot.handlers.analyze import router as analyze_router
from src.bot.handlers.draft import router as draft_router
from src.bot.handlers.history import router as history_router
from src.bot.handlers.start import router as start_router
from src.bot.handlers.stats import router as stats_router


def get_handlers_router() -> Router:
    """
    Create and return a router that includes all handler sub-routers.

    The order of inclusion matters: more specific handlers (e.g., /draft with
    FSM state filters) must be registered before generic ones (e.g., bare photo).
    """
    router = Router()
    router.include_router(start_router)
    router.include_router(draft_router)   # must precede analyze_router (FSM priority)
    router.include_router(analyze_router)
    router.include_router(history_router)
    router.include_router(stats_router)
    return router
