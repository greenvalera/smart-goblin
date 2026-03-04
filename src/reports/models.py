"""
Report data structures for Smart Goblin.

Defines DeckReport, CardSummary, and grading utilities used by both
the Telegram and HTML renderers.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from src.core.deck import CardInfo, Deck, DeckAnalysis
from src.core.lands import LandRecommendation
from src.parsers.seventeen_lands import win_rate_to_grade

# Grade thresholds: (min_rating, grade_label).
# Aligned with GRADE_TO_RATING in src/parsers/seventeen_lands.py
# so that rating → grade round-trips correctly.
_GRADE_THRESHOLDS: list[tuple[Decimal, str]] = [
    (Decimal("5.0"), "A+"),
    (Decimal("4.5"), "A"),
    (Decimal("4.0"), "A-"),
    (Decimal("3.5"), "B+"),
    (Decimal("3.0"), "B"),
    (Decimal("2.5"), "B-"),
    (Decimal("2.0"), "C+"),
    (Decimal("1.5"), "C"),
    (Decimal("1.0"), "C-"),
    (Decimal("0.75"), "D+"),
    (Decimal("0.5"), "D"),
    (Decimal("0.25"), "D-"),
    (Decimal("0.0"), "F"),
]

UNRATED_GRADES: frozenset[str] = frozenset({"?", "N/A"})


def rating_to_grade(rating: Optional[Decimal]) -> str:
    """
    Convert a numeric rating (1.0-5.0) to a letter grade.

    Returns "?" for cards without a rating.
    """
    if rating is None:
        return "?"
    for threshold, grade in _GRADE_THRESHOLDS:
        if rating >= threshold:
            return grade
    return "F"


@dataclass
class CardSummary:
    """Summarised card data for report rendering."""

    name: str
    rating: Optional[Decimal] = None
    win_rate: Optional[Decimal] = None
    games_played: Optional[int] = None
    mana_cost: Optional[str] = None
    cmc: Optional[Decimal] = None
    colors: Optional[list[str]] = None
    rarity: Optional[str] = None
    image_uri: Optional[str] = None
    grade: str = "?"

    @classmethod
    def from_card_info(cls, info: CardInfo) -> "CardSummary":
        """Create a CardSummary from a CardInfo object."""
        grade = rating_to_grade(info.rating)
        # Fallback: compute grade from win_rate when rating is missing
        if grade == "?" and info.win_rate is not None:
            grade = win_rate_to_grade(float(info.win_rate))
        return cls(
            name=info.name,
            rating=info.rating,
            win_rate=info.win_rate,
            games_played=info.games_played,
            mana_cost=info.mana_cost,
            cmc=info.cmc,
            colors=info.colors,
            rarity=info.rarity,
            image_uri=info.image_uri,
            grade=grade,
        )


@dataclass
class DeckReport:
    """
    Complete report data structure used by renderers.

    Contains everything needed to produce a Telegram message or HTML page:
    the deck itself, per-card summaries with grades, analysis results,
    LLM-generated advice, and a list of unrated cards.
    """

    deck: Deck
    main_deck_cards: list[CardSummary] = field(default_factory=list)
    sideboard_cards: list[CardSummary] = field(default_factory=list)
    analysis: Optional[DeckAnalysis] = None
    advice: str = ""
    set_name: Optional[str] = None
    land_recommendation: Optional[LandRecommendation] = None

    @property
    def unrated_cards(self) -> list[CardSummary]:
        """Cards whose grade is in UNRATED_GRADES (no rating data)."""
        seen: set[str] = set()
        result: list[CardSummary] = []
        for card in self.main_deck_cards + self.sideboard_cards:
            if card.grade in UNRATED_GRADES and card.name not in seen:
                seen.add(card.name)
                result.append(card)
        return result

    @classmethod
    def build(
        cls,
        deck: Deck,
        card_infos: list[CardInfo],
        analysis: DeckAnalysis,
        advice: str = "",
        set_name: Optional[str] = None,
        land_recommendation: Optional[LandRecommendation] = None,
    ) -> "DeckReport":
        """
        Build a DeckReport from raw analysis data.

        Args:
            deck: The analysed deck.
            card_infos: CardInfo objects for all known cards.
            analysis: The computed DeckAnalysis.
            advice: LLM-generated advice text (optional).
            set_name: Human-readable set name (optional).
            land_recommendation: Recommended land composition (optional).

        Returns:
            A fully populated DeckReport.
        """
        info_map = {c.name: c for c in card_infos}

        main_cards = [
            CardSummary.from_card_info(info_map[name])
            if name in info_map
            else CardSummary(name=name)
            for name in deck.main_deck
        ]
        sb_cards = [
            CardSummary.from_card_info(info_map[name])
            if name in info_map
            else CardSummary(name=name)
            for name in deck.sideboard
        ]

        return cls(
            deck=deck,
            main_deck_cards=main_cards,
            sideboard_cards=sb_cards,
            analysis=analysis,
            advice=advice,
            set_name=set_name,
            land_recommendation=land_recommendation,
        )
