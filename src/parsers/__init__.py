"""
Data source parsers for Smart Goblin.

This module provides parsers for fetching card data and ratings from external sources:
- Scryfall: Card metadata (name, mana cost, colors, rarity, image)
- 17lands: Card ratings and win rates
"""

from src.parsers.base import (
    BaseParser,
    CardData,
    NetworkError,
    NotFoundError,
    ParserError,
    RateLimitError,
    RatingData,
    SetData,
)
from src.parsers.scryfall import ScryfallParser
from src.parsers.seventeen_lands import (
    GRADE_TO_RATING,
    UNRATED_GRADES,
    SeventeenLandsParser,
    grade_to_rating,
    normalize_card_name,
)

__all__ = [
    "BaseParser",
    "CardData",
    "GRADE_TO_RATING",
    "NetworkError",
    "NotFoundError",
    "ParserError",
    "RateLimitError",
    "RatingData",
    "ScryfallParser",
    "SeventeenLandsParser",
    "SetData",
    "UNRATED_GRADES",
    "grade_to_rating",
    "normalize_card_name",
]
