"""
DeckAdvisor module for Smart Goblin.

Generates LLM-based advice for MTG draft deck optimization.
Identifies weak cards, strong sideboard candidates, and mana curve issues,
then calls the LLM to produce human-friendly advice in Ukrainian.
"""

import logging
from decimal import Decimal
from typing import Any

from src.core.deck import CardInfo, Deck, DeckAnalysis
from src.core.lands import COLOR_EMOJI, COLOR_TO_LAND, LandRecommendation
from src.llm.client import LLMClient
from src.llm.prompts import (
    ADVICE_SESSION_SYSTEM_PROMPT,
    build_advice_prompt,
    build_session_advice_prompt,
)

logger = logging.getLogger(__name__)

# Thresholds for card quality classification
WEAK_CARD_THRESHOLD = Decimal("2.5")
STRONG_CARD_THRESHOLD = Decimal("3.0")
STRONG_WIN_RATE_THRESHOLD = Decimal("55.0")

# Mana curve balance thresholds
IDEAL_CURVE_PEAK_LOW = 2
IDEAL_CURVE_PEAK_HIGH = 3
HIGH_CMC_THRESHOLD = 5
LOW_CMC_RATIO_WARN = 0.15  # warn if <15% of cards are CMC 1-2
HIGH_CMC_RATIO_WARN = 0.25  # warn if >25% of cards are CMC 5+


class DeckAdvisor:
    """
    LLM-based deck advice generator.

    Analyzes deck composition, identifies weak/strong cards,
    detects mana curve issues, and calls the LLM to produce
    optimization advice in Ukrainian.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        """
        Initialize the advisor.

        Args:
            llm_client: LLM client for generating advice text.
        """
        self._llm = llm_client

    async def generate_advice(
        self,
        deck: Deck,
        card_infos: list[CardInfo],
        analysis: DeckAnalysis,
        session_mode: bool = False,
        land_recommendation: LandRecommendation | None = None,
    ) -> str:
        """
        Generate deck optimization advice in Ukrainian.

        Builds a rich context from deck data, card ratings, and analysis,
        then calls the LLM to produce actionable advice.

        Args:
            deck: The deck with main_deck and sideboard card names.
            card_infos: CardInfo objects for all cards (main + sideboard).
            analysis: Pre-computed DeckAnalysis with score, win rate, etc.
            session_mode: If True and sideboard is non-empty, focus on
                specific sideboard swap recommendations.

        Returns:
            Advice text in Ukrainian.
        """
        card_map = {c.name: c for c in card_infos}

        main_deck_dicts = self._build_card_dicts(deck.main_deck, card_map)
        sideboard_dicts = self._build_card_dicts(deck.sideboard, card_map)
        analysis_dict = self._build_analysis_dict(analysis)

        # Pre-compute structured analysis for the LLM
        weak_cards = self._find_weak_cards(deck.main_deck, card_map)
        strong_sideboard = self._find_strong_sideboard_cards(deck.sideboard, card_map)
        curve_issues = self._analyze_mana_curve(analysis.mana_curve)

        land_rec_dict = self._build_land_rec_dict(land_recommendation)
        use_session = session_mode and len(deck.sideboard) > 0

        if use_session:
            # Session mode: focus on specific sideboard swaps
            weak_dicts = self._build_card_dicts(
                [c.name for c in weak_cards], card_map
            )
            strong_sb_dicts = self._build_card_dicts(
                [c.name for c in strong_sideboard], card_map
            )
            full_prompt = build_session_advice_prompt(
                main_deck_dicts,
                sideboard_dicts,
                analysis_dict,
                weak_cards=weak_dicts,
                strong_sideboard=strong_sb_dicts,
                land_rec=land_rec_dict,
            )
            system_prompt = ADVICE_SESSION_SYSTEM_PROMPT
        else:
            # Standard mode: general advice
            base_prompt = build_advice_prompt(
                main_deck_dicts, sideboard_dicts, analysis_dict,
                land_rec=land_rec_dict,
            )
            extra_context = self._build_extra_context(
                weak_cards, strong_sideboard, curve_issues
            )
            if extra_context:
                full_prompt = base_prompt + "\n" + extra_context
            else:
                full_prompt = base_prompt
            system_prompt = None

        logger.info(
            f"Generating advice: {len(deck.main_deck)} main, "
            f"{len(deck.sideboard)} sideboard, "
            f"{len(weak_cards)} weak, {len(strong_sideboard)} strong sb"
            f"{', session_mode' if use_session else ''}"
        )

        messages = [{"role": "user", "content": full_prompt}]
        advice = await self._llm.call_completion(
            messages, system_prompt=system_prompt
        )

        return advice

    def _build_card_dicts(
        self,
        card_names: list[str],
        card_map: dict[str, CardInfo],
    ) -> list[dict[str, Any]]:
        """Convert card names to dicts for the prompt builder."""
        result = []
        for name in card_names:
            info = card_map.get(name)
            card_dict: dict[str, Any] = {"name": name}
            if info:
                if info.rating is not None:
                    card_dict["rating"] = float(info.rating)
                if info.win_rate is not None:
                    card_dict["win_rate"] = float(info.win_rate)
                if info.cmc is not None:
                    card_dict["cmc"] = float(info.cmc)
                else:
                    card_dict["cmc"] = "?"
            else:
                card_dict["cmc"] = "?"
            result.append(card_dict)
        return result

    def _build_analysis_dict(self, analysis: DeckAnalysis) -> dict[str, Any]:
        """Convert DeckAnalysis to dict for the prompt builder."""
        return {
            "total_score": float(analysis.score),
            "estimated_win_rate": float(analysis.estimated_win_rate),
            "mana_curve": analysis.mana_curve,
            "color_distribution": analysis.color_distribution,
        }

    def _find_weak_cards(
        self,
        card_names: list[str],
        card_map: dict[str, CardInfo],
    ) -> list[CardInfo]:
        """
        Find weak cards in the main deck.

        A card is considered weak if its rating is below WEAK_CARD_THRESHOLD.
        Returns cards sorted by rating (weakest first).
        """
        weak = []
        for name in card_names:
            info = card_map.get(name)
            if info and info.rating is not None and info.rating < WEAK_CARD_THRESHOLD:
                weak.append(info)

        # Sort by rating ascending (weakest first), deduplicate by name
        seen = set()
        unique_weak = []
        for card in sorted(weak, key=lambda c: c.rating):
            if card.name not in seen:
                seen.add(card.name)
                unique_weak.append(card)

        return unique_weak

    def _find_strong_sideboard_cards(
        self,
        sideboard_names: list[str],
        card_map: dict[str, CardInfo],
    ) -> list[CardInfo]:
        """
        Find strong cards in the sideboard that could improve the deck.

        A sideboard card is considered strong if its rating >= STRONG_CARD_THRESHOLD
        or win_rate >= STRONG_WIN_RATE_THRESHOLD.
        Returns cards sorted by rating (strongest first).
        """
        strong = []
        for name in sideboard_names:
            info = card_map.get(name)
            if not info:
                continue
            is_strong = (
                (info.rating is not None and info.rating >= STRONG_CARD_THRESHOLD)
                or (info.win_rate is not None and info.win_rate >= STRONG_WIN_RATE_THRESHOLD)
            )
            if is_strong:
                strong.append(info)

        # Sort by rating descending (strongest first), deduplicate by name
        seen = set()
        unique_strong = []
        for card in sorted(
            strong,
            key=lambda c: c.rating if c.rating is not None else Decimal("0"),
            reverse=True,
        ):
            if card.name not in seen:
                seen.add(card.name)
                unique_strong.append(card)

        return unique_strong

    def _analyze_mana_curve(self, mana_curve: dict[int, int]) -> list[str]:
        """
        Analyze mana curve for common issues.

        Returns a list of issue descriptions (in Ukrainian) for the LLM context.
        """
        if not mana_curve:
            return []

        total = sum(mana_curve.values())
        if total == 0:
            return []

        issues = []

        # Check for too many expensive cards (CMC >= 5)
        high_cmc_count = sum(
            count for cmc, count in mana_curve.items() if cmc >= HIGH_CMC_THRESHOLD
        )
        high_ratio = high_cmc_count / total
        if high_ratio > HIGH_CMC_RATIO_WARN:
            issues.append(
                f"Забагато дорогих карт: {high_cmc_count} карт з вартістю {HIGH_CMC_THRESHOLD}+ мани "
                f"({high_ratio:.0%} колоди)"
            )

        # Check for too few early game cards (CMC 1-2)
        low_cmc_count = sum(
            count for cmc, count in mana_curve.items() if cmc in (1, 2)
        )
        low_ratio = low_cmc_count / total
        if low_ratio < LOW_CMC_RATIO_WARN:
            issues.append(
                f"Замало ранніх карт: лише {low_cmc_count} карт з вартістю 1-2 мани "
                f"({low_ratio:.0%} колоди)"
            )

        # Check curve peak
        if mana_curve:
            peak_cmc = max(mana_curve, key=mana_curve.get)
            if peak_cmc < IDEAL_CURVE_PEAK_LOW:
                issues.append(
                    f"Пік кривої мани на {peak_cmc} — занадто агресивно, "
                    f"може не вистачити потужних карт у пізній грі"
                )
            elif peak_cmc > IDEAL_CURVE_PEAK_HIGH:
                issues.append(
                    f"Пік кривої мани на {peak_cmc} — колода занадто повільна, "
                    f"може програти до агресивних опонентів"
                )

        return issues

    def _build_land_rec_dict(
        self, rec: LandRecommendation | None
    ) -> dict[str, Any] | None:
        """Convert LandRecommendation to a dict for the prompt builder."""
        if rec is None or not rec.lands:
            return None

        def _fmt(r: LandRecommendation) -> dict[str, Any]:
            parts = []
            for color, count in sorted(r.lands.items(), key=lambda x: x[1], reverse=True):
                emoji = COLOR_EMOJI.get(color, "")
                name = COLOR_TO_LAND.get(color, color)
                parts.append(f"{emoji}{name} x{count}")
            return {
                "total": r.total_lands,
                "basic_breakdown": " | ".join(parts),
                "non_basic_count": r.non_basic_count,
            }

        result: dict[str, Any] = {"primary": _fmt(rec)}
        if rec.alternative and rec.alternative.lands:
            result["alternative"] = _fmt(rec.alternative)
        return result

    def _build_extra_context(
        self,
        weak_cards: list[CardInfo],
        strong_sideboard: list[CardInfo],
        curve_issues: list[str],
    ) -> str:
        """Build additional context sections for the LLM prompt."""
        sections = []

        if weak_cards:
            lines = ["\n## Слабкі карти для заміни"]
            for card in weak_cards:
                rating_str = f"⭐{card.rating:.1f}" if card.rating is not None else ""
                wr_str = f", {card.win_rate:.1f}% WR" if card.win_rate is not None else ""
                lines.append(f"- {card.name} ({rating_str}{wr_str})")
            sections.append("\n".join(lines))

        if strong_sideboard:
            lines = ["\n## Сильні карти з sideboard для додавання"]
            for card in strong_sideboard:
                rating_str = f"⭐{card.rating:.1f}" if card.rating is not None else ""
                wr_str = f", {card.win_rate:.1f}% WR" if card.win_rate is not None else ""
                lines.append(f"- {card.name} ({rating_str}{wr_str})")
            sections.append("\n".join(lines))

        if curve_issues:
            lines = ["\n## Проблеми з кривою мани"]
            for issue in curve_issues:
                lines.append(f"- {issue}")
            sections.append("\n".join(lines))

        if sections:
            sections.insert(0, "\n---\nДодатковий аналіз для контексту:")

        return "\n".join(sections)
