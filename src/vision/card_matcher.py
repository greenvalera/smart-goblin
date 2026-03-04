"""
Fuzzy card name matching for post-processing vision recognition results.

Uses difflib from stdlib — no external dependencies required.
"""

import difflib
import logging
from dataclasses import dataclass, field

from src.parsers.seventeen_lands import normalize_card_name

logger = logging.getLogger(__name__)

# Similarity threshold for difflib.get_close_matches().
# 0.75 catches OCR-type errors ("Lightining Bolt" -> "Lightning Bolt")
# while rejecting unrelated names ("Bitter Triumph" vs "Blight Rot").
FUZZY_MATCH_CUTOFF = 0.75

# Matches below this score produce a warning log.
LOW_CONFIDENCE_CUTOFF = 0.8


@dataclass
class MatchResult:
    """Result of fuzzy matching a card list against known cards."""

    matched: list[str] = field(default_factory=list)
    corrections: dict[str, str] = field(default_factory=dict)
    unmatched: list[str] = field(default_factory=list)
    match_count: int = 0
    exact_count: int = 0


def fuzzy_match_cards(
    recognized_names: list[str],
    known_names: list[str],
    cutoff: float = FUZZY_MATCH_CUTOFF,
) -> MatchResult:
    """
    Match recognized card names against a known card list using fuzzy matching.

    For each recognized name:
    1. Try exact match (case-insensitive via normalize_card_name)
    2. If no exact match, use difflib.get_close_matches
    3. If still no match, keep original name and add to unmatched list

    Args:
        recognized_names: Card names returned by vision recognition.
        known_names: Valid card names from the database for this set.
        cutoff: Minimum similarity ratio (0.0-1.0). Default 0.75.

    Returns:
        MatchResult with corrected names, corrections dict, and unmatched list.
    """
    if not known_names:
        return MatchResult(matched=list(recognized_names))

    # Build normalized -> original lookup for exact matching
    normalized_lookup: dict[str, str] = {}
    for name in known_names:
        normalized_lookup[normalize_card_name(name)] = name

    # Lowercase list for difflib + reverse map
    known_lower = [name.lower() for name in known_names]
    lower_to_original = {name.lower(): name for name in known_names}

    matched: list[str] = []
    corrections: dict[str, str] = {}
    unmatched: list[str] = []
    exact_count = 0
    match_count = 0

    for recognized in recognized_names:
        # Step 1: exact match via normalized comparison
        norm = normalize_card_name(recognized)
        if norm in normalized_lookup:
            correct_name = normalized_lookup[norm]
            matched.append(correct_name)
            exact_count += 1
            match_count += 1
            if recognized != correct_name:
                corrections[recognized] = correct_name
            continue

        # Step 2: fuzzy match via difflib
        close = difflib.get_close_matches(
            recognized.lower(), known_lower, n=1, cutoff=cutoff
        )
        if close:
            correct_name = lower_to_original[close[0]]
            matched.append(correct_name)
            corrections[recognized] = correct_name
            match_count += 1

            ratio = difflib.SequenceMatcher(
                None, recognized.lower(), close[0]
            ).ratio()
            if ratio < LOW_CONFIDENCE_CUTOFF:
                logger.warning(
                    "Low-confidence fuzzy match: '%s' -> '%s' (similarity=%.2f)",
                    recognized, correct_name, ratio,
                )
            else:
                logger.info(
                    "Fuzzy match: '%s' -> '%s' (similarity=%.2f)",
                    recognized, correct_name, ratio,
                )
            continue

        # Step 3: no match found — keep original
        matched.append(recognized)
        unmatched.append(recognized)
        logger.warning("No match found for '%s' in known card list", recognized)

    if corrections:
        logger.info(
            "Card matching: %d/%d matched (%d exact, %d fuzzy), %d unmatched",
            match_count, len(recognized_names),
            exact_count, match_count - exact_count,
            len(unmatched),
        )

    return MatchResult(
        matched=matched,
        corrections=corrections,
        unmatched=unmatched,
        match_count=match_count,
        exact_count=exact_count,
    )
