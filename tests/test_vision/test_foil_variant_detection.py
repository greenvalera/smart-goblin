"""
Tests for foil and alternate art (variant) detection in the card recognition pipeline.

Covers:
- Vision parser correctly extracts finish and variant from mock GPT-4o responses
- RecognitionResult carries finish/variant fields with proper defaults
- Handler formats display string correctly for all combinations
- Price function accepts finish/variant params without breaking
- Single-card prompt includes foil/variant detection instructions
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.vision.prompts import (
    SINGLE_CARD_RECOGNITION_PROMPT,
    build_recognition_prompt,
)
from src.vision.recognizer import CardRecognizer, RecognitionResult
from src.vision.layouts import LayoutType
from src.bot.handlers.analyze import _format_single_card_header, _fetch_card_price


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_image_bytes():
    """Minimal 1×1 PNG bytes for tests that require image data."""
    return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"


@pytest.fixture
def mock_llm_client():
    """Async mock LLM client."""
    client = AsyncMock()
    client.call_vision = AsyncMock()
    return client


def _single_card_response(
    name: str = "Blood Crypt",
    set_code: str = "ECL",
    finish: str | None = "foil",
    variant: str | None = "showcase",
    layout: str = "physical_cards",
) -> dict:
    """Build a mock single-card GPT-4o response dict."""
    return {
        "main_deck": [name],
        "sideboard": [],
        "detected_set": set_code,
        "layout_detected": layout,
        "lands_visible": False,
        "finish": finish,
        "variant": variant,
    }


# =============================================================================
# 1. Vision parser: RecognitionResult fields
# =============================================================================


class TestRecognitionResultFields:
    """RecognitionResult carries finish and variant with proper defaults."""

    def test_finish_defaults_to_none(self):
        """finish defaults to None when not set."""
        result = RecognitionResult()
        assert result.finish is None

    def test_variant_defaults_to_none(self):
        """variant defaults to None when not set."""
        result = RecognitionResult()
        assert result.variant is None

    def test_finish_and_variant_accepted_as_kwargs(self):
        """RecognitionResult accepts finish and variant in constructor."""
        result = RecognitionResult(finish="foil", variant="showcase")
        assert result.finish == "foil"
        assert result.variant == "showcase"

    def test_nonfoil_finish_stored(self):
        """nonfoil finish is stored correctly."""
        result = RecognitionResult(finish="nonfoil", variant="standard")
        assert result.finish == "nonfoil"
        assert result.variant == "standard"


# =============================================================================
# 2. Vision parser: extraction from mock GPT-4o response
# =============================================================================


class TestFinishVariantExtraction:
    """CardRecognizer._build_result correctly extracts finish and variant."""

    @pytest.mark.asyncio
    async def test_foil_showcase_extracted(self, mock_llm_client, sample_image_bytes):
        """foil + showcase are extracted from a mock GPT-4o single-card response."""
        mock_llm_client.call_vision.return_value = _single_card_response(
            finish="foil", variant="showcase"
        )
        recognizer = CardRecognizer(llm_client=mock_llm_client)
        result = await recognizer.recognize_cards(
            sample_image_bytes, single_card=True
        )
        assert result.finish == "foil"
        assert result.variant == "showcase"

    @pytest.mark.asyncio
    async def test_nonfoil_standard_extracted(self, mock_llm_client, sample_image_bytes):
        """nonfoil + standard are extracted correctly."""
        mock_llm_client.call_vision.return_value = _single_card_response(
            finish="nonfoil", variant="standard"
        )
        recognizer = CardRecognizer(llm_client=mock_llm_client)
        result = await recognizer.recognize_cards(
            sample_image_bytes, single_card=True
        )
        assert result.finish == "nonfoil"
        assert result.variant == "standard"

    @pytest.mark.asyncio
    async def test_null_finish_preserved_as_none(self, mock_llm_client, sample_image_bytes):
        """null finish (uncertain) maps to None in RecognitionResult."""
        mock_llm_client.call_vision.return_value = _single_card_response(
            finish=None, variant="borderless"
        )
        recognizer = CardRecognizer(llm_client=mock_llm_client)
        result = await recognizer.recognize_cards(
            sample_image_bytes, single_card=True
        )
        assert result.finish is None
        assert result.variant == "borderless"

    @pytest.mark.asyncio
    async def test_null_variant_preserved_as_none(self, mock_llm_client, sample_image_bytes):
        """null variant maps to None in RecognitionResult."""
        mock_llm_client.call_vision.return_value = _single_card_response(
            finish="foil", variant=None
        )
        recognizer = CardRecognizer(llm_client=mock_llm_client)
        result = await recognizer.recognize_cards(
            sample_image_bytes, single_card=True
        )
        assert result.finish == "foil"
        assert result.variant is None

    @pytest.mark.asyncio
    async def test_invalid_finish_coerced_to_none(self, mock_llm_client, sample_image_bytes):
        """An unrecognised finish value is coerced to None (not stored raw)."""
        mock_llm_client.call_vision.return_value = {
            **_single_card_response(),
            "finish": "shiny",  # not a valid value
        }
        recognizer = CardRecognizer(llm_client=mock_llm_client)
        result = await recognizer.recognize_cards(
            sample_image_bytes, single_card=True
        )
        assert result.finish is None

    @pytest.mark.asyncio
    async def test_invalid_variant_coerced_to_none(self, mock_llm_client, sample_image_bytes):
        """An unrecognised variant value is coerced to None."""
        mock_llm_client.call_vision.return_value = {
            **_single_card_response(),
            "variant": "anime",  # not a valid value
        }
        recognizer = CardRecognizer(llm_client=mock_llm_client)
        result = await recognizer.recognize_cards(
            sample_image_bytes, single_card=True
        )
        assert result.variant is None

    @pytest.mark.asyncio
    async def test_all_valid_variants_accepted(self, mock_llm_client, sample_image_bytes):
        """All five valid variant values are accepted without coercion."""
        valid_variants = ["standard", "showcase", "extended_art", "borderless", "retro"]
        for v in valid_variants:
            mock_llm_client.call_vision.return_value = _single_card_response(variant=v)
            recognizer = CardRecognizer(llm_client=mock_llm_client)
            result = await recognizer.recognize_cards(
                sample_image_bytes, single_card=True
            )
            assert result.variant == v, f"expected variant={v!r}, got {result.variant!r}"

    @pytest.mark.asyncio
    async def test_finish_absent_from_response_is_none(
        self, mock_llm_client, sample_image_bytes
    ):
        """Missing 'finish' key in response maps to None (deck recognition path)."""
        mock_llm_client.call_vision.return_value = {
            "main_deck": ["Lightning Bolt"],
            "sideboard": [],
            "detected_set": "M11",
            "layout_detected": "physical_cards",
        }
        recognizer = CardRecognizer(llm_client=mock_llm_client)
        result = await recognizer.recognize_cards(sample_image_bytes)
        assert result.finish is None
        assert result.variant is None

    @pytest.mark.asyncio
    async def test_single_card_flag_uses_single_card_prompt(
        self, mock_llm_client, sample_image_bytes
    ):
        """single_card=True causes the single-card prompt to be sent to the LLM."""
        mock_llm_client.call_vision.return_value = _single_card_response()
        recognizer = CardRecognizer(llm_client=mock_llm_client)
        await recognizer.recognize_cards(sample_image_bytes, single_card=True)

        call_args = mock_llm_client.call_vision.call_args
        prompt = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("prompt")
        assert "finish" in prompt.lower()
        assert "foil" in prompt.lower()
        assert "variant" in prompt.lower()

    @pytest.mark.asyncio
    async def test_default_call_does_not_use_single_card_prompt(
        self, mock_llm_client, sample_image_bytes
    ):
        """single_card=False (default) uses the standard deck prompt, not single-card."""
        mock_llm_client.call_vision.return_value = {
            "main_deck": ["Card A"],
            "sideboard": [],
            "detected_set": "TST",
            "layout_detected": "arena_screenshot",
        }
        recognizer = CardRecognizer(llm_client=mock_llm_client)
        await recognizer.recognize_cards(sample_image_bytes)

        call_args = mock_llm_client.call_vision.call_args
        prompt = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("prompt")
        # Single-card prompt has distinctive opening line
        assert "close-up photo of a single physical MTG card" not in prompt


# =============================================================================
# 3. Prompt content: SINGLE_CARD_RECOGNITION_PROMPT
# =============================================================================


class TestSingleCardPromptContent:
    """SINGLE_CARD_RECOGNITION_PROMPT contains necessary detection instructions."""

    def test_prompt_mentions_foil_detection_cues(self):
        """Prompt describes bottom info line approach for foil detection."""
        lower = SINGLE_CARD_RECOGNITION_PROMPT.lower()
        # New approach: read the star/diamond from the bottom info line
        assert "bottom info line" in lower or "info line" in lower
        assert "*" in SINGLE_CARD_RECOGNITION_PROMPT or "star" in lower

    def test_prompt_mentions_nonfoil(self):
        """Prompt distinguishes nonfoil (no star/diamond symbol)."""
        lower = SINGLE_CARD_RECOGNITION_PROMPT.lower()
        assert "nonfoil" in lower

    def test_prompt_lists_all_valid_variants(self):
        """Prompt explicitly lists all accepted variant values."""
        lower = SINGLE_CARD_RECOGNITION_PROMPT.lower()
        assert "showcase" in lower
        assert "extended_art" in lower or "extended art" in lower
        assert "borderless" in lower
        assert "retro" in lower
        assert "standard" in lower

    def test_prompt_includes_finish_in_json_schema(self):
        """Prompt's JSON schema example includes the 'finish' key."""
        assert '"finish"' in SINGLE_CARD_RECOGNITION_PROMPT

    def test_prompt_includes_variant_in_json_schema(self):
        """Prompt's JSON schema example includes the 'variant' key."""
        assert '"variant"' in SINGLE_CARD_RECOGNITION_PROMPT

    def test_build_recognition_prompt_single_card_flag(self):
        """build_recognition_prompt(single_card=True) returns the single-card prompt."""
        prompt = build_recognition_prompt(single_card=True)
        assert "finish" in prompt
        assert "variant" in prompt
        assert "foil" in prompt.lower()

    def test_build_recognition_prompt_default_not_single_card(self):
        """build_recognition_prompt() without single_card does not include finish field."""
        prompt = build_recognition_prompt()
        # The general prompt has 'finish' only as part of natural language
        # (e.g. "finish" as a verb) — but NOT as a JSON field name in the schema
        assert '"finish"' not in prompt
        assert '"variant"' not in prompt


# =============================================================================
# 4. Handler display formatting: _format_single_card_header
# =============================================================================


class TestFormatSingleCardHeader:
    """_format_single_card_header produces correct display strings."""

    def test_foil_and_variant_showcase(self):
        """Foil + Showcase: ✨ after name, • Showcase after set code."""
        header = _format_single_card_header(
            "Blood Crypt", "ECL", finish="foil", variant="showcase"
        )
        assert "✨" in header
        assert "Blood Crypt" in header
        assert "ECL" in header
        assert "Showcase" in header

    def test_foil_only_no_variant_suffix(self):
        """Foil with standard variant: ✨ present, no variant suffix."""
        header = _format_single_card_header(
            "Lightning Bolt", "M11", finish="foil", variant="standard"
        )
        assert "✨" in header
        assert "Lightning Bolt" in header
        assert "M11" in header
        # 'Standard' should NOT appear as a variant label
        assert "Standard" not in header
        assert "•" not in header

    def test_nonfoil_standard_no_extras(self):
        """Nonfoil standard: no ✨, no variant suffix."""
        header = _format_single_card_header(
            "Lightning Bolt", "M11", finish="nonfoil", variant="standard"
        )
        assert "✨" not in header
        assert "•" not in header
        assert "🃏" in header
        assert "Lightning Bolt" in header
        assert "M11" in header

    def test_nonfoil_borderless(self):
        """Nonfoil borderless: no ✨, shows • Borderless."""
        header = _format_single_card_header(
            "Liliana of the Veil", "MOM", finish="nonfoil", variant="borderless"
        )
        assert "✨" not in header
        assert "Borderless" in header
        assert "•" in header

    def test_foil_borderless(self):
        """Foil borderless: ✨ present + • Borderless."""
        header = _format_single_card_header(
            "Liliana of the Veil", "MOM", finish="foil", variant="borderless"
        )
        assert "✨" in header
        assert "Borderless" in header

    def test_foil_extended_art(self):
        """Foil extended_art: ✨ present + • Extended Art."""
        header = _format_single_card_header(
            "Sheoldred", "ONE", finish="foil", variant="extended_art"
        )
        assert "✨" in header
        assert "Extended Art" in header

    def test_foil_retro(self):
        """Foil retro: ✨ present + • Retro."""
        header = _format_single_card_header(
            "Dark Ritual", "TSP", finish="foil", variant="retro"
        )
        assert "✨" in header
        assert "Retro" in header

    def test_no_finish_no_variant(self):
        """No finish/variant (None, None): plain header with no extras."""
        header = _format_single_card_header("Goblin Guide", "ZEN")
        assert "✨" not in header
        assert "•" not in header
        assert "🃏" in header
        assert "Goblin Guide" in header
        assert "ZEN" in header

    def test_no_finish_with_variant(self):
        """finish=None, variant=showcase: no ✨ but variant label shown."""
        header = _format_single_card_header(
            "Atraxa", "ONE", finish=None, variant="showcase"
        )
        assert "✨" not in header
        assert "Showcase" in header

    def test_foil_no_variant(self):
        """finish=foil, variant=None: ✨ shown, no variant label."""
        header = _format_single_card_header("Atraxa", "ONE", finish="foil", variant=None)
        assert "✨" in header
        assert "•" not in header

    def test_header_uses_markdown_bold(self):
        """Card name should be wrapped in markdown bold (*...*) for Telegram."""
        header = _format_single_card_header("Test Card", "TST")
        assert "*Test Card" in header

    def test_header_contains_card_emoji(self):
        """Header always starts with the 🃏 emoji."""
        header = _format_single_card_header("Test Card", "TST")
        assert header.startswith("🃏")


# =============================================================================
# 5. Price function signature: accepts finish/variant without breaking
# =============================================================================


class TestFetchCardPriceSignature:
    """_fetch_card_price accepts finish and variant params without error."""

    @pytest.mark.asyncio
    async def test_called_with_finish_and_variant(self):
        """_fetch_card_price can be called with finish='foil' and variant='showcase'."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"name": "Blood Crypt", "prices": {}, "purchase_uris": {}})
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.bot.handlers.analyze.httpx.AsyncClient", return_value=mock_client):
            # Should not raise — finish/variant are accepted silently
            resp = await _fetch_card_price(
                "Blood Crypt",
                "ECL",
                finish="foil",
                variant="showcase",
            )
        assert resp is not None

    @pytest.mark.asyncio
    async def test_called_without_finish_variant(self):
        """_fetch_card_price works when called without finish/variant (default None)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"name": "Lightning Bolt", "prices": {}, "purchase_uris": {}})
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.bot.handlers.analyze.httpx.AsyncClient", return_value=mock_client):
            resp = await _fetch_card_price("Lightning Bolt", "M11")
        assert resp is not None

    @pytest.mark.asyncio
    async def test_called_with_nonfoil_standard(self):
        """_fetch_card_price works with finish='nonfoil' and variant='standard'."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"name": "Counterspell", "prices": {}, "purchase_uris": {}})
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.bot.handlers.analyze.httpx.AsyncClient", return_value=mock_client):
            resp = await _fetch_card_price(
                "Counterspell", "MM3", finish="nonfoil", variant="standard"
            )
        assert resp is not None
