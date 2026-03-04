"""
Layout detection for MTG card images.

Detects whether an image is an Arena screenshot or a photo of physical cards.
"""

import logging
from typing import Any

from src.vision.prompts import LayoutType

logger = logging.getLogger(__name__)

LAYOUT_DETECTION_PROMPT = """Analyze this image and determine what type of Magic: The Gathering card display it shows.

Options:
1. "arena_screenshot" — A screenshot from MTG Arena (digital client) showing cards as thumbnails in a grid interface
2. "physical_cards" — A photo of real physical cards laid out on a surface (table, mat, etc.)

Return ONLY a JSON object:
{"layout": "arena_screenshot"} or {"layout": "physical_cards"}"""


def parse_layout_from_response(response: dict[str, Any]) -> LayoutType:
    """
    Parse the layout type from LLM recognition response.

    The recognition response includes a "layout_detected" field that indicates
    what type of image was analyzed.

    Args:
        response: The parsed JSON response from the LLM.

    Returns:
        The detected LayoutType.
    """
    layout_str = response.get("layout_detected", "")
    try:
        return LayoutType(layout_str)
    except ValueError:
        logger.warning(f"Unknown layout type in response: {layout_str!r}")
        return LayoutType.UNKNOWN


async def detect_layout(
    image: bytes | str,
    llm_client: Any,
) -> LayoutType:
    """
    Detect the layout type of a card image using an LLM vision call.

    This makes a lightweight LLM call to determine whether the image is
    an Arena screenshot or a photo of physical cards. Use this when you
    want to select a specialized prompt before full recognition.

    For most cases, prefer using the general recognition prompt which
    detects layout and recognizes cards in a single call.

    Args:
        image: Image as bytes or base64-encoded string.
        llm_client: An LLMClient instance with call_vision method.

    Returns:
        The detected LayoutType.
    """
    try:
        result = await llm_client.call_vision(image, LAYOUT_DETECTION_PROMPT)
        layout_str = result.get("layout", "")
        try:
            return LayoutType(layout_str)
        except ValueError:
            logger.warning(f"LLM returned unknown layout: {layout_str!r}")
            return LayoutType.UNKNOWN
    except Exception:
        logger.warning("Layout detection failed, falling back to UNKNOWN", exc_info=True)
        return LayoutType.UNKNOWN
