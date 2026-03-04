"""
Card recognition module using GPT-4o Vision.

Orchestrates layout detection, prompt selection, LLM vision calls,
and post-processing of recognized card lists.
"""

import logging
from collections import Counter
from dataclasses import dataclass, field

from src.llm.client import LLMClient, get_llm_client
from src.vision.layouts import LayoutType, detect_layout, parse_layout_from_response
from src.vision.prompts import build_recognition_prompt

logger = logging.getLogger(__name__)


@dataclass
class RecognitionResult:
    """Result of card recognition from an image."""

    main_deck: list[str] = field(default_factory=list)
    sideboard: list[str] = field(default_factory=list)
    detected_set: str | None = None
    layout_detected: LayoutType = LayoutType.UNKNOWN
    lands_visible: bool | None = None


class CardRecognizer:
    """
    Recognizes MTG cards from images using GPT-4o Vision.

    Supports both Arena screenshots and physical card photos.
    Automatically detects layout type and uses optimized prompts.
    """

    def __init__(self, llm_client: LLMClient | None = None):
        """
        Initialize the card recognizer.

        Args:
            llm_client: Optional LLM client. Uses shared instance if not provided.
        """
        self._llm_client = llm_client

    @property
    def llm_client(self) -> LLMClient:
        """Get the LLM client, creating a shared instance if needed."""
        if self._llm_client is None:
            self._llm_client = get_llm_client()
        return self._llm_client

    async def recognize_cards(
        self,
        image: bytes | str,
        layout_hint: LayoutType | None = None,
        set_hint: str | None = None,
        known_cards: list[str] | None = None,
    ) -> RecognitionResult:
        """
        Recognize MTG cards from an image.

        Uses GPT-4o Vision to identify cards in the image. Optionally accepts
        hints for layout type and set code to improve accuracy.

        Args:
            image: Image as bytes or base64-encoded string.
            layout_hint: Optional hint about the image layout type.
                If provided, a specialized prompt is used.
                If None, the general prompt handles both detection and recognition.
            set_hint: Optional set code hint (e.g., "MKM") to improve accuracy.
            known_cards: Optional list of valid card names for this set.
                When provided, the prompt constrains the model to only return
                names from this list.

        Returns:
            RecognitionResult with main_deck, sideboard, detected_set, and layout.
        """
        layout_type = layout_hint or LayoutType.UNKNOWN
        prompt = build_recognition_prompt(
            layout_type=layout_type, set_hint=set_hint, known_cards=known_cards
        )

        logger.info(
            "Recognizing cards (layout_hint=%s, set_hint=%s, known_cards=%s)",
            layout_hint, set_hint,
            f"yes ({len(known_cards)})" if known_cards else "no",
        )

        raw_result = await self.llm_client.call_vision(image, prompt)

        result = self._build_result(raw_result)
        result = self._post_process(result)

        logger.info(
            f"Recognized {len(result.main_deck)} main deck cards, "
            f"{len(result.sideboard)} sideboard cards, "
            f"set={result.detected_set}, layout={result.layout_detected.value}"
        )

        return result

    async def detect_layout(self, image: bytes | str) -> LayoutType:
        """
        Detect the layout type of an image without full recognition.

        Makes a lightweight LLM call to determine if the image is an
        Arena screenshot or physical card photo.

        Args:
            image: Image as bytes or base64-encoded string.

        Returns:
            The detected LayoutType.
        """
        return await detect_layout(image, self.llm_client)

    def _build_result(self, raw: dict) -> RecognitionResult:
        """
        Build a RecognitionResult from the raw LLM response.

        Args:
            raw: Parsed JSON dict from the LLM.

        Returns:
            RecognitionResult populated from the response.
        """
        layout = parse_layout_from_response(raw)

        return RecognitionResult(
            main_deck=raw.get("main_deck", []),
            sideboard=raw.get("sideboard", []),
            detected_set=raw.get("detected_set"),
            layout_detected=layout,
            lands_visible=raw.get("lands_visible"),
        )

    def _post_process(self, result: RecognitionResult) -> RecognitionResult:
        """
        Post-process recognition results for quality.

        Applies the following cleanup:
        - Strip whitespace from card names
        - Remove empty strings
        - Normalize set code to uppercase

        Args:
            result: The raw recognition result.

        Returns:
            Cleaned-up RecognitionResult.
        """
        result.main_deck = self._clean_card_list(result.main_deck)
        result.sideboard = self._clean_card_list(result.sideboard)

        if result.detected_set:
            result.detected_set = result.detected_set.strip().upper()

        # If set was not detected, try to infer from most common cards
        # (This is a placeholder — real inference would cross-reference a card DB)
        if not result.detected_set:
            logger.debug("Set not detected by LLM, no automatic inference available")

        return result

    @staticmethod
    def _clean_card_list(cards: list) -> list[str]:
        """
        Clean a list of card names.

        Args:
            cards: Raw list of card names (may contain non-strings).

        Returns:
            Cleaned list with stripped, non-empty string names.
        """
        cleaned = []
        for card in cards:
            if not isinstance(card, str):
                continue
            name = card.strip()
            if name:
                cleaned.append(name)
        return cleaned

    async def recognize_cards_two_pass(
        self,
        image: bytes | str,
        set_hint: str | None = None,
        known_cards: list[str] | None = None,
    ) -> RecognitionResult:
        """
        Two-pass recognition: detect layout first, then use specialized prompt.

        This approach makes two LLM calls but may improve accuracy by using
        a prompt specifically optimized for the detected layout type.

        Args:
            image: Image as bytes or base64-encoded string.
            set_hint: Optional set code hint.
            known_cards: Optional list of valid card names for this set.

        Returns:
            RecognitionResult with main_deck, sideboard, detected_set, and layout.
        """
        logger.info("Starting two-pass recognition")

        layout = await self.detect_layout(image)
        logger.info(f"Layout detected: {layout.value}")

        return await self.recognize_cards(
            image, layout_hint=layout, set_hint=set_hint, known_cards=known_cards
        )
