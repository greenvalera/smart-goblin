"""
Vision module for Smart Goblin.

Provides card recognition from images using GPT-4o Vision.
"""

from src.vision.layouts import LayoutType, detect_layout, parse_layout_from_response
from src.vision.prompts import (
    ARENA_RECOGNITION_PROMPT,
    GENERAL_RECOGNITION_PROMPT,
    PHYSICAL_RECOGNITION_PROMPT,
    build_recognition_prompt,
)
from src.vision.card_matcher import MatchResult, fuzzy_match_cards
from src.vision.recognizer import CardRecognizer, RecognitionResult

__all__ = [
    # Recognizer
    "CardRecognizer",
    "RecognitionResult",
    # Card matching
    "MatchResult",
    "fuzzy_match_cards",
    # Layouts
    "LayoutType",
    "detect_layout",
    "parse_layout_from_response",
    # Prompts
    "ARENA_RECOGNITION_PROMPT",
    "PHYSICAL_RECOGNITION_PROMPT",
    "GENERAL_RECOGNITION_PROMPT",
    "build_recognition_prompt",
]
