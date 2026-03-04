"""
HTML report renderer for Smart Goblin.

Generates a self-contained HTML page (inline CSS, no external dependencies)
that can be opened directly in a browser.
"""

import html as html_lib
from decimal import Decimal
from pathlib import Path
from typing import Optional

from src.core.lands import COLOR_TO_LAND, LandRecommendation
from src.reports.models import UNRATED_GRADES, CardSummary, DeckReport

# Scryfall card search URL template
_SCRYFALL_CARD_URL = "https://scryfall.com/search?q=%21%22{name}%22"

# Color code mapping for visual display
_COLOR_HEX: dict[str, str] = {
    "W": "#f9faf4",
    "U": "#0e68ab",
    "B": "#150b00",
    "R": "#d3202a",
    "G": "#00733e",
    "C": "#ccc2c0",
}

_COLOR_NAMES: dict[str, str] = {
    "W": "White",
    "U": "Blue",
    "B": "Black",
    "R": "Red",
    "G": "Green",
    "C": "Colorless",
}


def _esc(text: str) -> str:
    """HTML-escape a string."""
    return html_lib.escape(text, quote=True)


def _scryfall_link(card_name: str) -> str:
    """Build a Scryfall search link for the given card name."""
    encoded = card_name.replace('"', "").replace(" ", "+")
    return f"https://scryfall.com/search?q=%21%22{encoded}%22"


def _grade_class(grade: str) -> str:
    """CSS class name for a grade badge."""
    return f"grade-{grade.replace('+', 'plus').lower()}"


def _rating_display(rating: Optional[Decimal]) -> str:
    if rating is None:
        return "—"
    return f"{rating:.1f}"


def _wr_display(win_rate: Optional[Decimal]) -> str:
    if win_rate is None:
        return "—"
    return f"{win_rate:.1f}%"


# ---------------------------------------------------------------------------
# CSS (inline, no external deps)
# ---------------------------------------------------------------------------

_CSS = """\
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#1a1a2e;color:#e0e0e0;padding:20px;max-width:900px;margin:0 auto}
h1{color:#e94560;margin-bottom:6px;font-size:1.6rem}
h2{color:#0f3460;background:#16213e;padding:8px 14px;border-radius:6px;margin-top:24px;margin-bottom:10px;font-size:1.1rem;color:#e0e0e0}
.subtitle{color:#888;margin-bottom:18px;font-size:.9rem}
.summary{display:flex;gap:18px;flex-wrap:wrap;margin:14px 0}
.summary .stat{background:#16213e;border-radius:8px;padding:12px 18px;flex:1;min-width:140px;text-align:center}
.stat .value{font-size:1.5rem;font-weight:700;color:#e94560}
.stat .label{font-size:.75rem;color:#888;margin-top:2px}
table{width:100%;border-collapse:collapse;margin-bottom:10px}
th{text-align:left;padding:6px 10px;background:#16213e;color:#aaa;font-size:.8rem;font-weight:600}
td{padding:6px 10px;border-bottom:1px solid #222}
tr:hover td{background:#16213e}
a{color:#539bf5;text-decoration:none}
a:hover{text-decoration:underline}
.grade{display:inline-block;padding:2px 7px;border-radius:4px;font-weight:700;font-size:.8rem;color:#fff;min-width:30px;text-align:center}
.grade-aplus{background:#1b8a2d}
.grade-a{background:#2ea043}
.grade-bplus{background:#57ab5a}
.grade-b{background:#8b949e}
.grade-c{background:#d29922}
.grade-d{background:#db6d28}
.grade-f{background:#f85149}
.grade-\\?{background:#555}
.advice{background:#16213e;border-left:3px solid #e94560;padding:14px 18px;border-radius:0 8px 8px 0;margin:14px 0;white-space:pre-wrap;line-height:1.6}
.unrated{background:#1e1e3a;border:1px dashed #555;border-radius:8px;padding:14px 18px;margin:14px 0}
.unrated h3{color:#d29922;margin-bottom:8px}
.mana-curve{display:flex;align-items:flex-end;gap:4px;height:80px;margin:10px 0}
.mana-bar{background:#0f3460;border-radius:3px 3px 0 0;min-width:28px;text-align:center;position:relative;font-size:.7rem;color:#aaa}
.mana-bar .bar-count{position:absolute;top:-16px;width:100%;text-align:center}
.mana-bar .bar-cmc{margin-top:4px}
.color-dots{display:flex;gap:6px;margin:6px 0}
.color-dot{width:20px;height:20px;border-radius:50%;border:2px solid #333;display:inline-block}
footer{margin-top:30px;text-align:center;color:#555;font-size:.75rem}
"""


class HTMLRenderer:
    """Renders a DeckReport as a self-contained HTML page."""

    def render(self, report: DeckReport) -> str:
        """
        Render the report as a complete HTML document.

        Args:
            report: A populated DeckReport.

        Returns:
            HTML string that can be written to a file and opened in a browser.
        """
        parts: list[str] = [
            "<!DOCTYPE html>",
            '<html lang="uk">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width,initial-scale=1">',
            f"<title>Smart Goblin — Аналіз колоди{self._set_suffix(report)}</title>",
            f"<style>{_CSS}</style>",
            "</head>",
            "<body>",
            f"<h1>📊 Аналіз колоди{self._set_suffix(report)}</h1>",
        ]

        # Summary stats
        if report.analysis:
            parts.append(self._render_summary(report.analysis))

        # Main deck table
        parts.append("<h2>🃏 Main Deck</h2>")
        parts.append(self._render_card_table(report.main_deck_cards))

        # Land recommendation
        if report.land_recommendation and report.land_recommendation.lands:
            parts.append("<h2>🏔 Рекомендовані землі</h2>")
            parts.append(self._render_lands(report.land_recommendation))
            # Alternative recommendation
            alt = report.land_recommendation.alternative
            if alt and alt.lands:
                parts.append("<h2>🔄 Альтернативний розподіл</h2>")
                parts.append(self._render_lands(alt))

        # Sideboard table
        if report.sideboard_cards:
            parts.append("<h2>📦 Sideboard</h2>")
            parts.append(self._render_card_table(report.sideboard_cards))

        # Mana curve
        if report.analysis and report.analysis.mana_curve:
            parts.append("<h2>📉 Крива мани</h2>")
            parts.append(self._render_mana_curve(report.analysis.mana_curve))

        # Color distribution
        if report.analysis and report.analysis.color_distribution:
            parts.append("<h2>🎨 Розподіл кольорів</h2>")
            parts.append(self._render_colors(report.analysis.color_distribution))

        # Advice
        if report.advice:
            parts.append("<h2>💡 Рекомендації</h2>")
            parts.append(f'<div class="advice">{_esc(report.advice)}</div>')

        # Unrated cards
        unrated = report.unrated_cards
        if unrated:
            parts.append(self._render_unrated(unrated))

        parts.append('<footer>Smart Goblin — AI-помічник для MTG Draft</footer>')
        parts.append("</body></html>")

        return "\n".join(parts)

    def render_to_file(self, report: DeckReport, path: str | Path) -> Path:
        """
        Render the report and write it to an HTML file.

        Args:
            report: A populated DeckReport.
            path: Destination file path.

        Returns:
            The resolved Path of the written file.
        """
        dest = Path(path)
        dest.write_text(self.render(report), encoding="utf-8")
        return dest.resolve()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _set_suffix(self, report: DeckReport) -> str:
        if report.set_name:
            return f" ({_esc(report.set_name)})"
        return ""

    def _render_summary(self, analysis: "DeckAnalysis") -> str:  # noqa: F821
        return (
            '<div class="summary">'
            '<div class="stat">'
            f'<div class="value">{analysis.score:.1f}</div>'
            '<div class="label">Оцінка / 5.0</div></div>'
            '<div class="stat">'
            f'<div class="value">~{analysis.estimated_win_rate:.0f}%</div>'
            '<div class="label">Win Rate</div></div>'
            '<div class="stat">'
            f'<div class="value">{analysis.total_cards}</div>'
            '<div class="label">Карт в колоді</div></div>'
            '<div class="stat">'
            f'<div class="value">{analysis.cards_with_ratings}</div>'
            '<div class="label">З оцінкою</div></div>'
            "</div>"
        )

    def _render_card_table(self, cards: list[CardSummary]) -> str:
        rows: list[str] = []
        rows.append("<table>")
        rows.append(
            "<tr><th>Карта</th><th>Оцінка</th><th>Grade</th>"
            "<th>Win Rate</th><th>Mana</th><th>Рідкісність</th></tr>"
        )
        for card in cards:
            link = f'<a href="{_scryfall_link(card.name)}" target="_blank">{_esc(card.name)}</a>'
            grade_cls = _grade_class(card.grade)
            rows.append(
                f"<tr>"
                f"<td>{link}</td>"
                f"<td>{_rating_display(card.rating)}</td>"
                f'<td><span class="grade {grade_cls}">{_esc(card.grade)}</span></td>'
                f"<td>{_wr_display(card.win_rate)}</td>"
                f"<td>{_esc(card.mana_cost or '—')}</td>"
                f"<td>{_esc(card.rarity or '—')}</td>"
                f"</tr>"
            )
        rows.append("</table>")
        return "\n".join(rows)

    def _render_lands(self, rec: LandRecommendation) -> str:
        """Render recommended land composition as a simple table."""
        rows: list[str] = ['<table>', '<tr><th>Колір</th><th>Земля</th><th>К-сть</th></tr>']
        for color, count in sorted(rec.lands.items(), key=lambda x: x[1], reverse=True):
            color_name = _COLOR_NAMES.get(color, color)
            land_name = COLOR_TO_LAND.get(color, color)
            hex_color = _COLOR_HEX.get(color, "#888")
            rows.append(
                f'<tr><td><span class="color-dot" style="background:{hex_color};'
                f'width:14px;height:14px;vertical-align:middle;display:inline-block">'
                f'</span> {_esc(color_name)}</td>'
                f'<td>{_esc(land_name)}</td><td>{count}</td></tr>'
            )
        rows.append(f'<tr style="font-weight:bold"><td colspan="2">Всього</td><td>{rec.total_lands}</td></tr>')
        rows.append('</table>')
        return "\n".join(rows)

    def _render_mana_curve(self, curve: dict[int, int]) -> str:
        if not curve:
            return ""
        max_count = max(curve.values()) or 1
        bars: list[str] = []
        for cmc in range(max(curve.keys()) + 1):
            count = curve.get(cmc, 0)
            height = max(4, int((count / max_count) * 70))
            bars.append(
                f'<div class="mana-bar" style="height:{height}px">'
                f'<span class="bar-count">{count}</span>'
                f'<span class="bar-cmc">{cmc}</span>'
                f"</div>"
            )
        return f'<div class="mana-curve">{"".join(bars)}</div>'

    def _render_colors(self, dist: dict[str, float]) -> str:
        parts: list[str] = ['<div class="color-dots">']
        for color, pct in dist.items():
            if pct <= 0:
                continue
            hex_color = _COLOR_HEX.get(color, "#888")
            name = _COLOR_NAMES.get(color, color)
            parts.append(
                f'<div class="color-dot" style="background:{hex_color}" '
                f'title="{_esc(name)}: {pct:.0f}%"></div>'
            )
        parts.append("</div>")

        # Text fallback
        text_parts = [
            f"{_COLOR_NAMES.get(c, c)}: {p:.0f}%"
            for c, p in dist.items()
            if p > 0
        ]
        parts.append(f"<p>{', '.join(text_parts)}</p>")

        return "\n".join(parts)

    def _render_unrated(self, cards: list[CardSummary]) -> str:
        lines = [
            '<div class="unrated">',
            "<h3>🤔 Оціни сам</h3>",
            "<p>Для цих карт немає статистики — оціни їх самостійно:</p>",
            "<ul>",
        ]
        for card in cards:
            link = f'<a href="{_scryfall_link(card.name)}" target="_blank">{_esc(card.name)}</a>'
            lines.append(f"<li>{link}</li>")
        lines.append("</ul></div>")
        return "\n".join(lines)
