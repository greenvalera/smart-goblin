"""
Deck data structures for Smart Goblin.

Defines the Deck dataclass and related types used throughout the core module.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional


@dataclass
class CardInfo:
    """Card information enriched with rating data from the database."""

    name: str
    mana_cost: Optional[str] = None
    cmc: Optional[Decimal] = None
    colors: Optional[list[str]] = None
    type_line: Optional[str] = None
    rarity: Optional[str] = None
    image_uri: Optional[str] = None
    rating: Optional[Decimal] = None
    win_rate: Optional[Decimal] = None
    games_played: Optional[int] = None


@dataclass
class Deck:
    """
    Represents an MTG draft deck.

    Attributes:
        main_deck: List of card names in the main deck.
        sideboard: List of card names in the sideboard.
        set_code: The set code (e.g., "MKM", "OTJ").
    """

    main_deck: list[str] = field(default_factory=list)
    sideboard: list[str] = field(default_factory=list)
    set_code: Optional[str] = None

    @property
    def total_cards(self) -> int:
        """Total number of cards in the main deck."""
        return len(self.main_deck)


@dataclass
class DeckAnalysis:
    """
    Result of deck analysis.

    Attributes:
        score: Overall deck quality score (1.0-5.0).
        estimated_win_rate: Estimated win rate as a percentage.
        mana_curve: Distribution of cards by converted mana cost.
        color_distribution: Percentage of cards per color.
        cards_with_ratings: Number of cards that had rating data.
        total_cards: Total number of cards analyzed.
    """

    score: Decimal
    estimated_win_rate: Decimal
    mana_curve: dict[int, int] = field(default_factory=dict)
    color_distribution: dict[str, float] = field(default_factory=dict)
    cards_with_ratings: int = 0
    total_cards: int = 0
