"""
Vision-specific prompt templates for card recognition.

Contains layout-aware prompts optimized for Arena screenshots and physical card photos.
"""

from enum import Enum


class LayoutType(str, Enum):
    """Type of card layout detected in the image."""

    ARENA_SCREENSHOT = "arena_screenshot"
    PHYSICAL_CARDS = "physical_cards"
    UNKNOWN = "unknown"


ARENA_RECOGNITION_PROMPT = """You are an expert Magic: The Gathering card recognition system.
You are analyzing an MTG Arena screenshot showing a deck.

Arena Layout Rules:
- The main deck is displayed as a grid of card thumbnails, typically sorted by mana cost
- Cards are shown with their name visible at the top of each thumbnail
- The sideboard section is usually separated visually (to the right or below the main deck)
- The sideboard may be labeled "Sideboard" or separated by a divider
- Card quantities may be indicated by a number overlay or by repeated cards stacked
- The set symbol is visible on each card (small icon on the right side of the card)

Identification Rules:
- Read card names EXACTLY as displayed — do not guess or autocorrect
- If a card appears stacked or shows a quantity number (e.g., "x2"), list it that many times
- Pay attention to the divider between main deck and sideboard sections
- Cards in the main section are main deck, cards after the divider are sideboard
- If no sideboard section is visible, return an empty sideboard array

Important — Lands:
- Basic lands (Plains, Island, Swamp, Mountain, Forest) may NOT be visible in the image
- If lands are not visible, that is completely normal — do NOT add them
- Only list lands you can clearly see in the image
- The system will calculate recommended lands automatically

Set Detection:
- Look at set symbols on the cards (small icon between art and text box)
- Identify the 3-letter set code (e.g., "MKM", "OTJ", "BLB", "DSK", "FDN")
- If multiple sets are present, use the most frequently occurring one

Return your response as a JSON object:
{
    "main_deck": ["Card Name 1", "Card Name 1", "Card Name 2", ...],
    "sideboard": ["Card Name A", "Card Name B", ...],
    "detected_set": "SET_CODE",
    "layout_detected": "arena_screenshot",
    "lands_visible": true
}

Rules:
- Use EXACT English card names as printed on the cards
- List each copy separately (e.g., if 3 copies of "Lightning Bolt", list it 3 times)
- If sideboard is not visible, use an empty array []
- Use null for detected_set if you cannot determine the set
- Set lands_visible to true if basic lands are visible in the image, false otherwise
- Omit cards you cannot read clearly rather than guessing

Respond ONLY with the JSON object."""


PHYSICAL_RECOGNITION_PROMPT = """You are an expert Magic: The Gathering card recognition system.
You are analyzing a photo of physical MTG cards laid out on a surface.

Physical Card Layout Rules:
- Cards are typically laid out in rows on a table or mat
- The larger group of cards (usually 23+ non-land cards + lands) is the main deck
- A smaller separate group (typically 0-15 cards, often to the side) is the sideboard
- Cards may be partially overlapping in a fan/spread arrangement
- Some cards may be at angles or partially obscured
- Lands may be grouped separately from non-land cards within the main deck

Identification Rules:
- Read the card name from the title bar at the top of each card
- For overlapping cards, focus on the visible portion of the card name
- If a card is face-down or completely obscured, skip it
- Card art and type line can help confirm identification
- If multiple copies are visible, count each physical card separately

Important — Lands:
- Basic lands (Plains, Island, Swamp, Mountain, Forest) may NOT be visible in the photo
- If lands are not visible, that is completely normal — do NOT add them
- Only list lands you can clearly see in the image
- The system will calculate recommended lands automatically

Set Detection:
- Look at set symbols (icon on the right side between art and text box)
- Check card frame style which varies by era/set
- Watermarks in the text box may indicate the set
- Use the most common set if cards are from multiple sets

Return your response as a JSON object:
{
    "main_deck": ["Card Name 1", "Card Name 2", ...],
    "sideboard": ["Card Name A", "Card Name B", ...],
    "detected_set": "SET_CODE",
    "layout_detected": "physical_cards",
    "lands_visible": true
}

Rules:
- Use EXACT English card names as printed on the cards
- List each physical card separately
- If you cannot distinguish main deck from sideboard, put all cards in main_deck
- Use null for detected_set if you cannot determine the set
- Set lands_visible to true if basic lands are visible in the photo, false otherwise
- Omit cards you cannot identify rather than guessing

Respond ONLY with the JSON object."""


GENERAL_RECOGNITION_PROMPT = """You are an expert Magic: The Gathering card recognition system.
Analyze the provided image and identify all visible MTG cards.

First, determine the image type:
1. **MTG Arena screenshot** — digital interface showing a deck as card thumbnails in a grid
2. **Physical card photo** — photo of real cards laid out on a surface

For MTG Arena screenshots:
- Cards in the main grid area are the main deck
- Cards in the "Sideboard" section (usually separated by a divider) are sideboard cards
- Pay attention to card quantities (stacked cards or "x2" indicators)
- Read card names from the thumbnail text

For physical card photos:
- The larger group of cards (23+ spells + lands, ~40 total) is the main deck
- A smaller separate group (0-15 cards) is the sideboard
- Read card names from the title bar at the top of each card
- Skip face-down or completely unreadable cards

Important — Lands:
- Basic lands (Plains, Island, Swamp, Mountain, Forest) may NOT be visible in the image
- If lands are not visible, that is completely normal — do NOT add them
- Only list lands you can clearly see in the image
- The system will calculate recommended lands automatically

Set Detection:
- Look at set symbols on the cards
- Check watermarks or frame styles
- Use the 3-letter set code (e.g., "MKM", "OTJ", "BLB", "DSK", "FDN")
- Use the most frequently occurring set if multiple are present

Return your response as a JSON object:
{
    "main_deck": ["Card Name 1", "Card Name 2", ...],
    "sideboard": ["Card Name A", "Card Name B", ...],
    "detected_set": "SET_CODE",
    "layout_detected": "arena_screenshot" or "physical_cards",
    "lands_visible": true
}

Rules:
- Use EXACT English card names as printed on the cards
- List each copy separately (don't group — list "Lightning Bolt" 3 times if 3 copies)
- If sideboard is not visible or distinguishable, use an empty array []
- Use null for detected_set if you cannot determine the set
- Set lands_visible to true if basic lands are visible in the image, false otherwise
- Omit cards you cannot read clearly rather than guessing

Respond ONLY with the JSON object."""


_PROMPTS = {
    LayoutType.ARENA_SCREENSHOT: ARENA_RECOGNITION_PROMPT,
    LayoutType.PHYSICAL_CARDS: PHYSICAL_RECOGNITION_PROMPT,
    LayoutType.UNKNOWN: GENERAL_RECOGNITION_PROMPT,
}


def build_recognition_prompt(
    layout_type: LayoutType = LayoutType.UNKNOWN,
    set_hint: str | None = None,
    known_cards: list[str] | None = None,
) -> str:
    """
    Build the recognition prompt based on layout type.

    Args:
        layout_type: Detected or hinted layout type.
        set_hint: Optional set code hint to include in the prompt.
        known_cards: Optional list of valid card names for this set.
            When provided, the prompt constrains GPT-4o to only return
            names from this list, significantly reducing hallucinations.

    Returns:
        The full prompt string for card recognition.
    """
    prompt = _PROMPTS[layout_type]

    if set_hint:
        prompt += (
            f"\n\nAdditional context: The cards are likely from the set "
            f'"{set_hint}". Use this as a hint but verify against what you see.'
        )

    if known_cards:
        card_list = "\n".join(sorted(known_cards))
        prompt += (
            f"\n\n=== CARD NAME REFERENCE LIST ===\n"
            f"The following is the COMPLETE list of valid card names for this set. "
            f"You MUST ONLY return card names that appear in this list. "
            f"Do NOT invent card names or use names from other sets. "
            f"If you cannot match a visible card to a name on this list, skip it.\n\n"
            f"{card_list}\n"
            f"=== END REFERENCE LIST ==="
        )

    return prompt
