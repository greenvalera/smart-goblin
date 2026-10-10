"""
Land recommendation calculator for MTG draft decks.

Calculates the optimal number of basic lands per color based on
the color pips (mana symbols) in non-land card costs.
"""

import re
from dataclasses import dataclass, field
from src.core.deck import Deck, CardInfo

# Standard draft deck constants
STANDARD_DECK_SIZE = 40
DEFAULT_LAND_COUNT = 17

# Basic land names per color
COLOR_TO_LAND: dict[str, str] = {
    "W": "Plains",
    "U": "Island",
    "B": "Swamp",
    "R": "Mountain",
    "G": "Forest",
}

# Color emoji for Telegram rendering
COLOR_EMOJI: dict[str, str] = {
    "W": "\u2b1c",   # white square
    "U": "\U0001f535",  # blue circle
    "B": "\u2b1b",   # black square
    "R": "\U0001f534",  # red circle
    "G": "\U0001f7e2",  # green circle
}

BASIC_LANDS: frozenset[str] = frozenset(COLOR_TO_LAND.values())


def is_land(card: CardInfo) -> bool:
    """Classify the played/front face, rather than an optional reverse face."""
    return card.name in BASIC_LANDS or 'Land' in (card.type_line or '').split(' // ', 1)[0]


def recommend_deck_lands(deck: Deck, card_infos: list[CardInfo]) -> 'LandRecommendation':
    """Recommend a complete mana base, counting copies and existing nonbasics."""
    by_name = {card.name: card for card in card_infos}
    spells = []
    spell_count = nonbasic_count = 0
    for name in deck.main_deck:
        card = by_name.get(name)
        if name in BASIC_LANDS:
            continue
        if card and is_land(card):
            nonbasic_count += 1
        else:
            spell_count += 1
            if card:
                spells.append(card)
    total = max(nonbasic_count, STANDARD_DECK_SIZE - spell_count)
    return recommend_lands(spells, total_lands=total, non_basic_land_count=nonbasic_count)

# Regex for colored mana pips: {W}, {U}, {B}, {R}, {G}
_COLOR_PIP_RE = re.compile(r"\{([WUBRG])\}")
# Regex for hybrid mana: {W/U}, {B/G}, etc.
_HYBRID_PIP_RE = re.compile(r"\{([WUBRG])/([WUBRG])\}")
# Regex for Phyrexian mana: {W/P}, {U/P}, etc.
_PHYREXIAN_PIP_RE = re.compile(r"\{([WUBRG])/P\}")


@dataclass
class LandRecommendation:
    """Recommended land composition for a draft deck."""

    total_lands: int = DEFAULT_LAND_COUNT
    lands: dict[str, int] = field(default_factory=dict)  # color -> count of basic lands
    non_basic_count: int = 0  # non-basic lands already in the deck
    total_spells: int = 0
    alternative: "LandRecommendation | None" = None


def count_color_pips(mana_cost: str | None) -> dict[str, int]:
    """
    Count color pips in a Scryfall mana cost string.

    Handles regular pips ({W}), hybrid ({W/U}), and Phyrexian ({W/P}).

    Args:
        mana_cost: Scryfall notation like "{2}{W}{W}{U}".

    Returns:
        Dict mapping color codes to pip counts.
    """
    if not mana_cost:
        return {}

    pips: dict[str, int] = {}

    # Optional back/prepare costs do not add requirements for the played face.
    mana_cost = mana_cost.split(' // ', 1)[0]

    # Regular colored pips
    for match in _COLOR_PIP_RE.finditer(mana_cost):
        color = match.group(1)
        pips[color] = pips.get(color, 0) + 1

    # Hybrid pips — count both colors
    for match in _HYBRID_PIP_RE.finditer(mana_cost):
        for color in (match.group(1), match.group(2)):
            pips[color] = pips.get(color, 0) + 1

    # Phyrexian pips — count the color
    for match in _PHYREXIAN_PIP_RE.finditer(mana_cost):
        color = match.group(1)
        pips[color] = pips.get(color, 0) + 1

    return pips


def recommend_lands(
    card_infos: list,
    total_lands: int = DEFAULT_LAND_COUNT,
    non_basic_land_count: int = 0,
) -> LandRecommendation:
    """
    Calculate recommended land distribution for a draft deck.

    Uses color pip counts from mana costs to determine the proportion
    of each basic land type. Falls back to the colors field if
    mana_cost is unavailable. Non-basic lands already in the deck
    reduce the number of basic lands needed.

    Args:
        card_infos: List of CardInfo objects (non-land spell cards only).
        total_lands: Total number of lands to recommend (default 17).
        non_basic_land_count: Number of non-basic lands already in the deck.

    Returns:
        LandRecommendation with per-color basic land counts.
    """
    total_pips: dict[str, int] = {}

    hybrids: list[tuple[str, str]] = []
    for card in card_infos:
        cost = (getattr(card, 'mana_cost', None) or '').split(' // ', 1)[0]
        hybrids.extend(_HYBRID_PIP_RE.findall(cost))
        # Hybrid pips are alternatives, not simultaneous color requirements.
        pips = count_color_pips(_HYBRID_PIP_RE.sub('', cost))
        for color, count in pips.items():
            total_pips[color] = total_pips.get(color, 0) + count

    for options in hybrids:
        color = max(options, key=lambda c: (total_pips.get(c, 0), -'WUBRG'.index(c)))
        total_pips[color] = total_pips.get(color, 0) + 1

    pip_sum = sum(total_pips.values())

    # Fallback: use card.colors if no mana_cost data
    if pip_sum == 0:
        color_counts: dict[str, int] = {}
        for card in card_infos:
            colors = getattr(card, "colors", None)
            if colors:
                for c in colors:
                    color_counts[c] = color_counts.get(c, 0) + 1
        if color_counts:
            total_pips = color_counts
            pip_sum = sum(total_pips.values())

    # Non-basic lands in the deck reduce the number of basic lands needed
    total_lands = max(0, total_lands)
    non_basic_land_count = min(total_lands, max(0, non_basic_land_count))
    total_basic = total_lands - non_basic_land_count

    # If still no color info, return empty recommendation
    if pip_sum == 0:
        return LandRecommendation(
            total_lands=total_lands,
            lands={},
            non_basic_count=non_basic_land_count,
            total_spells=len(card_infos),
        )

    def _distribute(n_lands: int) -> dict[str, int]:
        """Distribute n_lands proportionally by pip counts."""
        result: dict[str, int] = {}
        remaining = n_lands
        # When there are fewer slots than colors, allocate to the strongest
        # requirements; never create negative counts to reserve extra colors.
        active_colors = sorted_colors[:n_lands]
        for i, (color, pips) in enumerate(active_colors):
            if i == len(active_colors) - 1:
                result[color] = remaining
            else:
                share = round(n_lands * pips / pip_sum)
                share = max(share, 1)
                share = min(share, remaining - (len(active_colors) - i - 1))
                result[color] = share
                remaining -= share
        return result

    # Sort by pip count descending for fair rounding
    sorted_colors = sorted(total_pips.items(), key=lambda x: x[1], reverse=True)

    lands = _distribute(total_basic)

    rec = LandRecommendation(
        total_lands=total_lands,
        lands=lands,
        non_basic_count=non_basic_land_count,
        total_spells=len(card_infos),
    )

    # Compute alternative with one fewer total land (e.g. 16 instead of 17)
    if total_basic > 1:
        alt_basic = total_basic - 1
        alt_total = alt_basic + non_basic_land_count
        rec.alternative = LandRecommendation(
            total_lands=alt_total,
            lands=_distribute(alt_basic),
            non_basic_count=non_basic_land_count,
            total_spells=len(card_infos),
        )

    return rec
