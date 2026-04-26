"""
Abstract base parser interface for Smart Goblin.

Defines the contract that all data source parsers must implement.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID


@dataclass
class CardData:
    """Data structure for card metadata from external sources."""

    name: str
    scryfall_id: Optional[UUID] = None
    mana_cost: Optional[str] = None
    cmc: Optional[Decimal] = None
    colors: Optional[list[str]] = None
    type_line: Optional[str] = None
    rarity: Optional[str] = None
    image_uri: Optional[str] = None


@dataclass
class SetData:
    """Data structure for set metadata."""

    code: str
    name: str
    release_date: Optional[date] = None


@dataclass
class RatingData:
    """Data structure for card rating from external sources."""

    card_name: str
    source: str
    rating: Optional[Decimal] = None
    win_rate: Optional[Decimal] = None
    games_played: Optional[int] = None
    format: Optional[str] = None
    low_confidence: bool = False
    grade: Optional[str] = None  # Letter grade from 17lands (A+, A, A-, B+, etc.)


class BaseParser(ABC):
    """
    Abstract base class for data source parsers.

    All parsers must implement methods for fetching card and set data
    from their respective sources.
    """

    @abstractmethod
    async def fetch_set_cards(self, set_code: str) -> list[CardData]:
        """
        Fetch all cards for a given set.

        Args:
            set_code: The set code (e.g., "MKM", "OTJ").

        Returns:
            List of CardData objects for all cards in the set.

        Raises:
            ParserError: If fetching fails.
        """
        pass

    @abstractmethod
    async def fetch_set_info(self, set_code: str) -> Optional[SetData]:
        """
        Fetch metadata for a given set.

        Args:
            set_code: The set code (e.g., "MKM", "OTJ").

        Returns:
            SetData object with set metadata, or None if not found.

        Raises:
            ParserError: If fetching fails.
        """
        pass

    async def close(self) -> None:
        """
        Clean up resources (e.g., close HTTP client).

        Override this method if the parser needs cleanup.
        """
        pass


class ParserError(Exception):
    """Base exception for parser errors."""

    pass


class RateLimitError(ParserError):
    """Raised when rate limit is exceeded."""

    pass


class NetworkError(ParserError):
    """Raised when network request fails."""

    pass


class NotFoundError(ParserError):
    """Raised when requested resource is not found."""

    pass
