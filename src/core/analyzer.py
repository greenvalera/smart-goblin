"""
Deck analysis module for Smart Goblin.

Provides DeckAnalyzer that calculates deck score, estimated win rate,
mana curve, and color distribution from card data and ratings.
"""

import logging
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from src.core.deck import CardInfo, Deck, DeckAnalysis

logger = logging.getLogger(__name__)

# Default values when no rating data is available
DEFAULT_RATING = Decimal("3.0")
DEFAULT_WIN_RATE = Decimal("50.0")
DEFAULT_GAMES_PLAYED = 0

# Minimum games for a rating to be considered high-confidence
MIN_GAMES_HIGH_CONFIDENCE = 200


class DeckAnalyzer:
    """
    Analyzes MTG draft decks based on card ratings and statistics.

    Calculates overall deck score, estimated win rate, mana curve,
    and color distribution using weighted averages from rating data.
    """

    def analyze(
        self,
        deck: Deck,
        card_infos: list[CardInfo],
    ) -> DeckAnalysis:
        """
        Analyze a deck and produce a DeckAnalysis result.

        The analysis combines card ratings (weighted by sample size)
        to produce an overall score and estimated win rate.

        Args:
            deck: The deck with card names.
            card_infos: List of CardInfo objects with enriched data
                for cards in the main deck.

        Returns:
            DeckAnalysis with score, win rate, mana curve, and colors.
        """
        card_map = {c.name: c for c in card_infos}

        score = self._calculate_score(deck.main_deck, card_map)
        win_rate = self._calculate_win_rate(deck.main_deck, card_map)
        mana_curve = self._calculate_mana_curve(deck.main_deck, card_map)
        color_dist = self._calculate_color_distribution(deck.main_deck, card_map)

        rated_count = sum(
            1 for name in deck.main_deck if card_map.get(name) and card_map[name].rating is not None
        )

        logger.info(
            f"Deck analysis: score={score}, win_rate={win_rate}%, "
            f"rated={rated_count}/{len(deck.main_deck)}"
        )

        return DeckAnalysis(
            score=score,
            estimated_win_rate=win_rate,
            mana_curve=dict(mana_curve),
            color_distribution=color_dist,
            cards_with_ratings=rated_count,
            total_cards=len(deck.main_deck),
        )

    def _calculate_score(
        self,
        card_names: list[str],
        card_map: dict[str, CardInfo],
    ) -> Decimal:
        """
        Calculate overall deck score as weighted average of card ratings.

        Cards with more games played carry more weight in the average.
        Cards without ratings use a default rating of 3.0.

        Args:
            card_names: List of card names in the deck.
            card_map: Mapping of card name to CardInfo.

        Returns:
            Weighted average score (1.0-5.0 scale).
        """
        if not card_names:
            return DEFAULT_RATING

        total_weighted_rating = Decimal("0")
        total_weight = Decimal("0")

        for name in card_names:
            info = card_map.get(name)
            rating = self._get_rating(info)
            weight = self._get_weight(info)

            total_weighted_rating += rating * weight
            total_weight += weight

        if total_weight == 0:
            return DEFAULT_RATING

        result = total_weighted_rating / total_weight
        return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def _calculate_win_rate(
        self,
        card_names: list[str],
        card_map: dict[str, CardInfo],
    ) -> Decimal:
        """
        Calculate estimated win rate as weighted average of card win rates.

        Weight is based on games_played (sample size). Cards with more games
        have higher confidence and thus more weight.

        Args:
            card_names: List of card names in the deck.
            card_map: Mapping of card name to CardInfo.

        Returns:
            Estimated win rate as a percentage (e.g., 54.50).
        """
        if not card_names:
            return DEFAULT_WIN_RATE

        total_weighted_wr = Decimal("0")
        total_weight = Decimal("0")

        for name in card_names:
            info = card_map.get(name)
            win_rate = self._get_win_rate(info)
            weight = self._get_weight(info)

            total_weighted_wr += win_rate * weight
            total_weight += weight

        if total_weight == 0:
            return DEFAULT_WIN_RATE

        result = total_weighted_wr / total_weight
        return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def _calculate_mana_curve(
        self,
        card_names: list[str],
        card_map: dict[str, CardInfo],
    ) -> dict[int, int]:
        """
        Calculate mana curve — distribution of cards by converted mana cost.

        Args:
            card_names: List of card names in the deck.
            card_map: Mapping of card name to CardInfo.

        Returns:
            Dict mapping CMC (int) to number of cards.
        """
        curve: dict[int, int] = defaultdict(int)

        for name in card_names:
            info = card_map.get(name)
            if info and info.cmc is not None:
                cmc_int = int(info.cmc)
            else:
                # Unknown CMC, count as 0
                cmc_int = 0
            curve[cmc_int] += 1

        return dict(sorted(curve.items()))

    def _calculate_color_distribution(
        self,
        card_names: list[str],
        card_map: dict[str, CardInfo],
    ) -> dict[str, float]:
        """
        Calculate color distribution — percentage of cards per color.

        Multi-colored cards count toward each of their colors.
        Cards without color data are counted as "C" (colorless).

        Args:
            card_names: List of card names in the deck.
            card_map: Mapping of card name to CardInfo.

        Returns:
            Dict mapping color code (W/U/B/R/G/C) to percentage (0-100).
        """
        if not card_names:
            return {}

        color_counts: dict[str, int] = defaultdict(int)
        total_cards = len(card_names)

        for name in card_names:
            info = card_map.get(name)
            if info and info.colors:
                for color in info.colors:
                    color_counts[color] += 1
            else:
                color_counts["C"] += 1

        # Convert counts to percentages
        result = {}
        for color, count in sorted(color_counts.items()):
            pct = (count / total_cards) * 100
            result[color] = round(pct, 1)

        return result

    @staticmethod
    def _get_rating(info: Optional[CardInfo]) -> Decimal:
        """Get rating from CardInfo, or default if unavailable."""
        if info and info.rating is not None:
            return info.rating
        return DEFAULT_RATING

    @staticmethod
    def _get_win_rate(info: Optional[CardInfo]) -> Decimal:
        """Get win rate from CardInfo, or default if unavailable."""
        if info and info.win_rate is not None:
            return info.win_rate
        return DEFAULT_WIN_RATE

    @staticmethod
    def _get_weight(info: Optional[CardInfo]) -> Decimal:
        """
        Calculate weight for a card based on its sample size.

        Cards with more games played get more weight. Cards without
        data get a weight of 1 (minimal influence).

        The weight formula: max(1, games_played / MIN_GAMES_HIGH_CONFIDENCE)
        capped at a maximum of 10 to prevent any single card from
        dominating the average.
        """
        if info and info.games_played is not None and info.games_played > 0:
            weight = Decimal(info.games_played) / Decimal(MIN_GAMES_HIGH_CONFIDENCE)
            return min(max(weight, Decimal("1")), Decimal("10"))
        return Decimal("1")
