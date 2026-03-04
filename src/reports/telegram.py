"""
Telegram message renderer for Smart Goblin.

Formats a DeckReport into a Telegram-friendly markdown message
with a compact graded card list, land recommendation, and analysis summary.
"""

from collections import Counter
from decimal import Decimal
from typing import Optional

from src.core.lands import COLOR_EMOJI, COLOR_TO_LAND, LandRecommendation
from src.reports.models import UNRATED_GRADES, CardSummary, DeckReport

# Grade sort order (best first)
_GRADE_ORDER: dict[str, int] = {
    "A+": 0, "A": 1, "A-": 2,
    "B+": 3, "B": 4, "B-": 5,
    "C+": 6, "C": 7, "C-": 8,
    "D+": 9, "D": 10, "D-": 11,
    "F": 12, "?": 13,
}


class TelegramRenderer:
    """Renders a DeckReport as a Telegram markdown message."""

    MAX_MESSAGE_LENGTH = 4000  # Telegram limit is 4096, leave margin

    def render(self, report: DeckReport) -> str:
        """
        Render the full analysis report as Telegram markdown.

        Args:
            report: A populated DeckReport.

        Returns:
            Formatted markdown string ready to send via Telegram.
        """
        sections: list[str] = []

        # Header
        set_label = f" ({report.set_name})" if report.set_name else ""
        sections.append(f"📊 *Аналіз колоди{set_label}*")

        # Compact analysis summary
        if report.analysis:
            sections.append(self._render_compact_analysis(report.analysis))

        # Main deck graded card list
        sections.append(
            self._render_graded_card_list("🃏 Main Deck", report.main_deck_cards)
        )

        # Land recommendation
        if report.land_recommendation and report.land_recommendation.lands:
            sections.append(
                self._render_land_recommendation(report.land_recommendation)
            )

        # Sideboard graded card list
        if report.sideboard_cards:
            sections.append(
                self._render_graded_card_list("📦 Sideboard", report.sideboard_cards)
            )

        # Unrated cards (compact inline list)
        unrated = report.unrated_cards
        if unrated:
            names = ", ".join(c.name for c in unrated)
            sections.append(f"🤔 *Без оцінки:* {names}")

        result = "\n\n".join(sections)

        # Truncate if still too long
        if len(result) > self.MAX_MESSAGE_LENGTH:
            result = result[: self.MAX_MESSAGE_LENGTH - 20] + "\n\n_...скорочено_"

        return result

    def _render_compact_analysis(self, analysis: "DeckAnalysis") -> str:  # noqa: F821
        """Render score, win rate, mana curve, and colors compactly."""
        lines: list[str] = []

        lines.append(
            f"📈 *Оцінка:* {analysis.score:.1f}/5.0"
            f" | 🎯 *WR:* ~{analysis.estimated_win_rate:.0f}%"
        )

        if analysis.mana_curve:
            curve = " | ".join(
                f"{cmc}:{cnt}"
                for cmc, cnt in sorted(analysis.mana_curve.items())
            )
            lines.append(f"📉 *Крива мани:* {curve}")

        if analysis.color_distribution:
            colors = ", ".join(
                f"{c}: {p:.0f}%"
                for c, p in analysis.color_distribution.items()
                if p > 0
            )
            lines.append(f"🎨 *Кольори:* {colors}")

        return "\n".join(lines)

    def _render_graded_card_list(
        self, header: str, cards: list[CardSummary]
    ) -> str:
        """
        Render a deduplicated, grade-sorted card list.

        Cards are grouped by name, counted, and sorted by grade (best first).
        """
        name_counts = Counter(c.name for c in cards)

        # Keep first occurrence of each card (for grade/WR data)
        seen: dict[str, CardSummary] = {}
        for card in cards:
            if card.name not in seen:
                seen[card.name] = card

        # Sort by grade priority (best first), then by win rate descending
        sorted_cards = sorted(
            seen.values(),
            key=lambda c: (
                _GRADE_ORDER.get(c.grade, 99),
                -(c.win_rate or Decimal(0)),
            ),
        )

        lines = [f"*{header} ({len(cards)} карт):*"]
        for card in sorted_cards:
            count = name_counts[card.name]
            count_str = f" x{count}" if count > 1 else ""

            if card.win_rate is not None:
                wr_str = f"— {card.win_rate:.1f}%"
            else:
                wr_str = "— без даних"

            grade_padded = card.grade.ljust(2)
            lines.append(f"`{grade_padded}` {card.name}{count_str} {wr_str}")

        return "\n".join(lines)

    def _render_land_recommendation(self, rec: LandRecommendation) -> str:
        """Render the recommended land composition with alternative."""
        lines: list[str] = []

        def _fmt_lands(r: LandRecommendation) -> str:
            parts: list[str] = []
            for color, count in sorted(r.lands.items(), key=lambda x: x[1], reverse=True):
                emoji = COLOR_EMOJI.get(color, "")
                land_name = COLOR_TO_LAND.get(color, color)
                parts.append(f"{emoji}{land_name} x{count}")
            return " | ".join(parts)

        # Primary recommendation only (alternative is provided in LLM advice)
        primary_str = _fmt_lands(rec)
        nb_note = f" \\+ {rec.non_basic_count} небазових" if rec.non_basic_count else ""
        lines.append(f"🏔 *Землі ({rec.total_lands}):* {primary_str}{nb_note}")

        return "\n".join(lines)
