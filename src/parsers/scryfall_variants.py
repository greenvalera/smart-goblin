"""
Scryfall variant lookup for card frame detection.

Provides helpers to query all printings of a card in a given set and to
cross-reference a GPT-4o visual hint with Scryfall frame_effects data to
produce a reliable variant classification.
"""

import httpx
from typing import Optional

SCRYFALL_SEARCH = "https://api.scryfall.com/cards/search"


async def get_card_variants(card_name: str, set_code: str) -> list[dict]:
    """
    Return all printings of *card_name* in *set_code* with their frame data.

    Each item in the returned list is a dict with keys:
        - ``scryfall_id`` (str)
        - ``frame_effects`` (list[str]) — e.g. ["borderless", "showcase"]
        - ``border_color`` (str) — e.g. "black", "borderless"

    Returns an empty list on any error so that callers can fall back
    gracefully without disrupting the main recognition flow.

    Args:
        card_name: Exact card name (case-insensitive for Scryfall).
        set_code: 3-letter set code (e.g. "ECL").

    Returns:
        List of printing dicts, possibly empty.
    """
    params = {
        "q": f'!"{card_name}" set:{set_code} unique:prints',
        "order": "released",
    }
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(SCRYFALL_SEARCH, params=params)
        if resp.status_code != 200:
            return []
        data = resp.json()
        results = []
        for card in data.get("data", []):
            results.append(
                {
                    "scryfall_id": card.get("id", ""),
                    "frame_effects": card.get("frame_effects", []),
                    "border_color": card.get("border_color", "black"),
                }
            )
        return results
    except Exception:
        return []


def resolve_variant(
    visual_hint: Optional[str],
    scryfall_variants: list[dict],
) -> Optional[str]:
    """
    Cross-reference a GPT-4o visual hint with Scryfall data to pick the
    correct frame variant.

    ``visual_hint`` accepted values (as emitted by the single-card prompt):
        - ``"no_border"``      → art fills all four edges, no border strip
        - ``"decorative_frame"`` → unusual/themed decorated border
        - ``"extended"``       → normal frame, art bleeds into side borders
        - ``"standard"``       → plain coloured border on all sides
        - ``None``             → model could not determine

    Returns one of:
        ``"borderless"`` | ``"showcase"`` | ``"extended_art"`` |
        ``"retro"`` | ``"standard"`` | ``None``

    Args:
        visual_hint: Visual hint string returned by GPT-4o.
        scryfall_variants: List of printing dicts from :func:`get_card_variants`.

    Returns:
        Resolved variant string, or ``None`` if undetermined.
    """
    if not scryfall_variants:
        # No Scryfall data — map hint directly
        hint_map: dict[str, str] = {
            "no_border": "borderless",
            "decorative_frame": "showcase",
            "extended": "extended_art",
        }
        return hint_map.get(visual_hint)  # None for "standard" or unknown

    # Only one printing: use its effects directly, ignore visual hint
    if len(scryfall_variants) == 1:
        v = scryfall_variants[0]
        effects = v.get("frame_effects", []) or []
        if v.get("border_color") == "borderless" or "borderless" in effects:
            return "borderless"
        for effect in ("showcase", "extended_art", "retro", "inverted"):
            if effect in effects:
                # "inverted" is Scryfall's frame_effect for some borderless cards
                return "borderless" if effect == "inverted" else effect
        return None  # standard

    # Multiple printings — use visual hint to disambiguate
    borderless_variants = [
        v for v in scryfall_variants if v.get("border_color") == "borderless"
    ]

    if visual_hint == "no_border" and borderless_variants:
        return "borderless"
    elif visual_hint == "decorative_frame":
        for v in scryfall_variants:
            if "showcase" in (v.get("frame_effects") or []):
                return "showcase"
    elif visual_hint == "extended":
        for v in scryfall_variants:
            if "extended_art" in (v.get("frame_effects") or []):
                return "extended_art"

    # No clear visual hint — can't reliably distinguish
    return None
