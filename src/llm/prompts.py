"""
Prompt templates for LLM calls.

Contains templates for card recognition (vision) and advice generation (completion).
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class CardRecognitionResult:
    """Result structure from card recognition."""

    main_deck: list[str]
    sideboard: list[str]
    detected_set: str | None = None


CARD_RECOGNITION_PROMPT = """You are an expert Magic: The Gathering card recognition system.
Analyze the provided image and identify all visible MTG cards.

The image may be:
1. A screenshot from MTG Arena showing a deck
2. A photo of physical cards laid out in rows

For MTG Arena screenshots:
- Cards in the main area are the main deck
- Cards in the "Sideboard" section (usually on the right or bottom) are sideboard cards

For physical card photos:
- The larger group of cards (usually 40+ cards) is the main deck
- A smaller separate group (usually 0-15 cards) is the sideboard

Identify the set by looking at:
- Set symbols on the cards
- Watermarks
- If you can identify the set from specific cards, use that

Return your response as a JSON object with this exact structure:
{
    "main_deck": ["Card Name 1", "Card Name 2", ...],
    "sideboard": ["Card Name A", "Card Name B", ...],
    "detected_set": "SET_CODE"
}

Rules:
- Use EXACT English card names as they appear on the cards
- If you see multiple copies of a card, list it multiple times
- If sideboard is not visible or empty, use an empty array
- For detected_set, use the 3-letter set code (e.g., "MKM", "OTJ", "BLB")
- If you cannot determine the set, use null for detected_set
- If you cannot read a card name clearly, omit it rather than guessing

Respond ONLY with the JSON object, no additional text."""


ADVICE_SYSTEM_PROMPT = """You are an experienced Magic: The Gathering player specializing in the Limited/Draft format.
Your task is to give advice in Ukrainian on deck optimization.

Core principles:
- A draft deck has 40 cards (optimal: 17 lands + 23 spells)
- The mana curve should be balanced (peak at 2-3 mana)
- Cards with a rating < 2.5 are usually weak
- Cards with a win rate > 55% are strong

Response format:
1. Overall deck evaluation (2-3 sentences)
2. Land recommendation: ALWAYS specify the exact number of lands and color breakdown.
   If a recommendation is provided in the prompt, use it as a base and comment on it.
   If there are non-basic lands, mention their role in mana fixing.
3. Specific swap recommendations (if any)
4. Comment on the mana curve (if there are issues)
5. Synergies and deck themes

Write in plain Ukrainian, avoid technical jargon. Your advice should be understandable to a beginner."""


ADVICE_SESSION_SYSTEM_PROMPT = """You are an experienced MTG Limited/Draft player.
Task: recommend specific card swaps from the sideboard into the main deck.

For each swap, specify:
- Which card to remove from the main deck
- Which card to add from the sideboard
- A brief explanation of why

Priority: replace the weakest main deck cards with the strongest from the sideboard.
Consider the mana curve and colors. Write in Ukrainian."""


DRAFT_CHAT_SYSTEM_PROMPT = """You are an experienced Magic: The Gathering player specializing in the Limited/Draft format.
You are in a dialogue with a player about their specific draft deck. You have already seen the deck composition and provided initial advice.

Rules:
- Respond ONLY in Ukrainian
- Consider the specific cards from the player's deck (listed below in the context)
- Give specific advice referencing the specific cards in the player's deck
- If the player asks about swaps, consider both the main deck and sideboard
- Respond concisely (3–6 sentences, unless the question requires a more detailed answer)
- Do not repeat already provided advice without an explicit request from the player"""


def _render_land_rec_section(land_rec: dict[str, Any] | None) -> str:
    """Build the land recommendation section for LLM prompts."""
    if not land_rec:
        return ""
    primary = land_rec.get("primary", {})
    lines = ["\n## Land Recommendation"]
    non_basic = primary.get("non_basic_count", 0)
    lines.append(
        f"Primary plan ({primary['total']} lands): {primary['basic_breakdown']}"
        + (f" + {non_basic} non-basic" if non_basic else "")
    )
    alt = land_rec.get("alternative")
    if alt:
        non_basic_alt = alt.get("non_basic_count", 0)
        lines.append(
            f"Alternative ({alt['total']} lands): {alt['basic_breakdown']}"
            + (f" + {non_basic_alt} non-basic" if non_basic_alt else "")
        )
    return "\n".join(lines)


def build_session_advice_prompt(
    main_deck: list[dict[str, Any]],
    sideboard: list[dict[str, Any]],
    analysis: dict[str, Any],
    weak_cards: list[dict[str, Any]] | None = None,
    strong_sideboard: list[dict[str, Any]] | None = None,
    land_rec: dict[str, Any] | None = None,
) -> str:
    """
    Build the user prompt for session-mode advice (sideboard swap recommendations).

    Args:
        main_deck: List of card dicts with name, rating, win_rate.
        sideboard: List of card dicts with name, rating, win_rate.
        analysis: Dict with total_score, estimated_win_rate, mana_curve, colors.
        weak_cards: Pre-identified weak main deck cards for swap candidates.
        strong_sideboard: Pre-identified strong sideboard cards for swap candidates.

    Returns:
        Formatted prompt string focused on sideboard swap recommendations.
    """
    lines = ["Suggest specific card swaps from the sideboard into the main deck.\n"]

    # Main deck
    lines.append("## Main Deck ({} cards)".format(len(main_deck)))
    for card in main_deck:
        name = card.get("name", "Unknown")
        rating = card.get("rating")
        win_rate = card.get("win_rate")
        cmc = card.get("cmc", "?")

        rating_str = f"⭐{rating:.1f}" if rating else "no rating"
        wr_str = f"{win_rate:.1f}% WR" if win_rate else ""

        parts = [f"- {name} (CMC {cmc})"]
        parts.append(f"— {rating_str}")
        if wr_str:
            parts.append(f"({wr_str})")
        lines.append(" ".join(parts))

    # Sideboard
    lines.append("\n## Sideboard ({} cards)".format(len(sideboard)))
    for card in sideboard:
        name = card.get("name", "Unknown")
        rating = card.get("rating")
        win_rate = card.get("win_rate")

        rating_str = f"⭐{rating:.1f}" if rating else "no rating"
        wr_str = f"{win_rate:.1f}% WR" if win_rate else ""

        parts = [f"- {name}"]
        parts.append(f"— {rating_str}")
        if wr_str:
            parts.append(f"({wr_str})")
        lines.append(" ".join(parts))

    # Swap candidates section
    if weak_cards or strong_sideboard:
        lines.append("\n## Swap Candidates")
        if weak_cards:
            lines.append("Weak main deck cards (OUT candidates):")
            for card in weak_cards:
                name = card.get("name", "Unknown")
                rating = card.get("rating")
                rating_str = f"⭐{rating:.1f}" if rating else ""
                lines.append(f"  OUT: {name} {rating_str}")
        if strong_sideboard:
            lines.append("Strong sideboard cards (IN candidates):")
            for card in strong_sideboard:
                name = card.get("name", "Unknown")
                rating = card.get("rating")
                rating_str = f"⭐{rating:.1f}" if rating else ""
                lines.append(f"  IN: {name} {rating_str}")

    # Analysis summary
    lines.append("\n## Analysis")
    if analysis.get("total_score"):
        lines.append(f"- Overall score: {analysis['total_score']:.2f}/5.0")
    if analysis.get("estimated_win_rate"):
        lines.append(f"- Expected win rate: {analysis['estimated_win_rate']:.1f}%")

    if analysis.get("mana_curve"):
        curve = analysis["mana_curve"]
        curve_str = " | ".join(f"{cmc}: {count}" for cmc, count in sorted(curve.items()))
        lines.append(f"- Mana curve: {curve_str}")

    if analysis.get("color_distribution"):
        colors = analysis["color_distribution"]
        color_str = ", ".join(f"{c}: {p:.0f}%" for c, p in colors.items() if p > 0)
        lines.append(f"- Color distribution: {color_str}")

    land_section = _render_land_rec_section(land_rec)
    if land_section:
        lines.append(land_section)

    lines.append("\nSuggest swaps in the format: OUT: card_name → IN: card_name with an explanation.")
    lines.append("Write in Ukrainian.")
    return "\n".join(lines)


def build_advice_prompt(
    main_deck: list[dict[str, Any]],
    sideboard: list[dict[str, Any]],
    analysis: dict[str, Any],
    land_rec: dict[str, Any] | None = None,
) -> str:
    """
    Build the user prompt for advice generation.

    Args:
        main_deck: List of card dicts with name, rating, win_rate.
        sideboard: List of card dicts with name, rating, win_rate.
        analysis: Dict with total_score, estimated_win_rate, mana_curve, colors.

    Returns:
        Formatted prompt string for the LLM.
    """
    lines = ["Analyze this draft deck and provide optimization advice.\n"]

    # Main deck
    lines.append("## Main Deck ({} cards)".format(len(main_deck)))
    for card in main_deck:
        name = card.get("name", "Unknown")
        rating = card.get("rating")
        win_rate = card.get("win_rate")
        cmc = card.get("cmc", "?")

        rating_str = f"⭐{rating:.1f}" if rating else "no rating"
        wr_str = f"{win_rate:.1f}% WR" if win_rate else ""

        parts = [f"- {name} (CMC {cmc})"]
        parts.append(f"— {rating_str}")
        if wr_str:
            parts.append(f"({wr_str})")
        lines.append(" ".join(parts))

    # Sideboard
    if sideboard:
        lines.append("\n## Sideboard ({} cards)".format(len(sideboard)))
        for card in sideboard:
            name = card.get("name", "Unknown")
            rating = card.get("rating")
            win_rate = card.get("win_rate")

            rating_str = f"⭐{rating:.1f}" if rating else "no rating"
            wr_str = f"{win_rate:.1f}% WR" if win_rate else ""

            parts = [f"- {name}"]
            parts.append(f"— {rating_str}")
            if wr_str:
                parts.append(f"({wr_str})")
            lines.append(" ".join(parts))
    else:
        lines.append("\n## Sideboard: empty")

    # Analysis summary
    lines.append("\n## Analysis")
    if analysis.get("total_score"):
        lines.append(f"- Overall score: {analysis['total_score']:.2f}/5.0")
    if analysis.get("estimated_win_rate"):
        lines.append(f"- Expected win rate: {analysis['estimated_win_rate']:.1f}%")

    # Mana curve
    if analysis.get("mana_curve"):
        curve = analysis["mana_curve"]
        curve_str = " | ".join(f"{cmc}: {count}" for cmc, count in sorted(curve.items()))
        lines.append(f"- Mana curve: {curve_str}")

    # Colors
    if analysis.get("color_distribution"):
        colors = analysis["color_distribution"]
        color_str = ", ".join(f"{c}: {p:.0f}%" for c, p in colors.items() if p > 0)
        lines.append(f"- Color distribution: {color_str}")

    land_section = _render_land_rec_section(land_rec)
    if land_section:
        lines.append(land_section)

    lines.append("\nProvide advice in Ukrainian.")
    return "\n".join(lines)


def build_vision_prompt(additional_context: str | None = None) -> str:
    """
    Build the prompt for card recognition.

    Args:
        additional_context: Optional additional instructions for recognition.

    Returns:
        The full prompt string.
    """
    prompt = CARD_RECOGNITION_PROMPT
    if additional_context:
        prompt += f"\n\nAdditional context: {additional_context}"
    return prompt
