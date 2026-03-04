"""
Database layer for Smart Goblin.

Provides SQLAlchemy models, async session management, and repository classes.
"""

from src.db.models import Analysis, Base, Card, CardRating, Set, User
from src.db.repository import (
    AnalysisRepository,
    CardData,
    CardRepository,
    RatingData,
    SetRepository,
    UserRepository,
)
from src.db.session import close_engine, get_engine, get_session, get_session_factory

__all__ = [
    # Models
    "Analysis",
    "Base",
    "Card",
    "CardRating",
    "Set",
    "User",
    # Repositories
    "AnalysisRepository",
    "CardData",
    "CardRepository",
    "RatingData",
    "SetRepository",
    "UserRepository",
    # Session
    "close_engine",
    "get_engine",
    "get_session",
    "get_session_factory",
]
