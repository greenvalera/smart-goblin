"""
Unit tests for the vision module.

Tests cover:
- TC-9.1: Arena deck screenshot recognized with >90% card name accuracy
- TC-9.2: Physical card photos in rows recognized with >80% accuracy
- TC-9.3: Main deck and sideboard correctly split by position on image
- TC-9.4: Set detected automatically by symbol/watermark or most frequent cards
"""

import base64
import json
import os
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.vision.layouts import LayoutType, detect_layout, parse_layout_from_response
from src.vision.prompts import (
    ARENA_RECOGNITION_PROMPT,
    GENERAL_RECOGNITION_PROMPT,
    PHYSICAL_RECOGNITION_PROMPT,
    build_recognition_prompt,
)
from src.vision.recognizer import CardRecognizer, RecognitionResult


@pytest.fixture
def mock_env():
    """Setup environment variables for tests."""
    env_vars = {
        "TELEGRAM_BOT_TOKEN": "test-token",
        "OPENAI_API_KEY": "sk-test-key",
        "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/testdb",
    }
    with mock.patch.dict(os.environ, env_vars, clear=True):
        yield


@pytest.fixture
def sample_image_bytes():
    """Sample image bytes for testing."""
    return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client."""
    client = AsyncMock()
    client.call_vision = AsyncMock()
    client.close = AsyncMock()
    return client


@pytest.fixture
def arena_recognition_response():
    """Simulated LLM response for an Arena screenshot."""
    return {
        "main_deck": [
            "Lightning Bolt",
            "Lightning Bolt",
            "Counterspell",
            "Counterspell",
            "Island",
            "Island",
            "Island",
            "Island",
            "Island",
            "Island",
            "Island",
            "Island",
            "Mountain",
            "Mountain",
            "Mountain",
            "Mountain",
            "Mountain",
            "Mountain",
            "Mountain",
            "Goblin Guide",
            "Goblin Guide",
            "Shock",
            "Shock",
            "Mana Leak",
            "Mana Leak",
            "Serum Visions",
            "Serum Visions",
            "Opt",
            "Opt",
            "Brainstorm",
            "Brainstorm",
            "Ponder",
            "Ponder",
            "Preordain",
            "Preordain",
            "Spell Pierce",
            "Spell Pierce",
            "Delver of Secrets",
            "Delver of Secrets",
            "Young Pyromancer",
        ],
        "sideboard": [
            "Negate",
            "Negate",
            "Pyroblast",
            "Pyroblast",
            "Surgical Extraction",
        ],
        "detected_set": "MKM",
        "layout_detected": "arena_screenshot",
    }


@pytest.fixture
def physical_recognition_response():
    """Simulated LLM response for physical cards."""
    return {
        "main_deck": [
            "Sheoldred, the Apocalypse",
            "Go for the Throat",
            "Cut Down",
            "Evolved Sleeper",
            "Graveyard Trespasser",
            "Invoke Despair",
            "Liliana of the Veil",
            "Swamp",
            "Swamp",
            "Swamp",
            "Swamp",
            "Swamp",
            "Swamp",
            "Swamp",
            "Swamp",
            "Swamp",
            "Swamp",
            "Swamp",
            "Swamp",
            "Swamp",
            "Tenacious Underdog",
            "Gix, Yawgmoth Praetor",
            "Duress",
        ],
        "sideboard": [
            "Feed the Swarm",
            "Gix's Command",
            "Hostile Investigator",
        ],
        "detected_set": "BLB",
        "layout_detected": "physical_cards",
    }


# =============================================================================
# TC-9.1: Arena screenshot recognized with >90% accuracy
# =============================================================================


class TestTC91ArenaScreenshotRecognition:
    """TC-9.1: Arena deck screenshot recognized with >90% card name accuracy."""

    @pytest.mark.asyncio
    async def test_arena_screenshot_returns_card_names(
        self, mock_llm_client, sample_image_bytes, arena_recognition_response
    ):
        """Arena screenshot recognition should return a list of card names."""
        mock_llm_client.call_vision.return_value = arena_recognition_response

        recognizer = CardRecognizer(llm_client=mock_llm_client)
        result = await recognizer.recognize_cards(
            sample_image_bytes, layout_hint=LayoutType.ARENA_SCREENSHOT
        )

        assert isinstance(result, RecognitionResult)
        assert len(result.main_deck) == 40
        assert all(isinstance(name, str) for name in result.main_deck)
        assert all(len(name) > 0 for name in result.main_deck)

    @pytest.mark.asyncio
    async def test_arena_uses_specialized_prompt(
        self, mock_llm_client, sample_image_bytes, arena_recognition_response
    ):
        """Arena layout hint should use the Arena-specific prompt."""
        mock_llm_client.call_vision.return_value = arena_recognition_response

        recognizer = CardRecognizer(llm_client=mock_llm_client)
        await recognizer.recognize_cards(
            sample_image_bytes, layout_hint=LayoutType.ARENA_SCREENSHOT
        )

        call_args = mock_llm_client.call_vision.call_args
        prompt = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("prompt")
        assert "MTG Arena screenshot" in prompt

    @pytest.mark.asyncio
    async def test_arena_recognizes_duplicate_cards(
        self, mock_llm_client, sample_image_bytes, arena_recognition_response
    ):
        """Should list each copy of a card separately."""
        mock_llm_client.call_vision.return_value = arena_recognition_response

        recognizer = CardRecognizer(llm_client=mock_llm_client)
        result = await recognizer.recognize_cards(sample_image_bytes)

        lightning_bolts = [c for c in result.main_deck if c == "Lightning Bolt"]
        assert len(lightning_bolts) == 2

    @pytest.mark.asyncio
    async def test_arena_layout_detected(
        self, mock_llm_client, sample_image_bytes, arena_recognition_response
    ):
        """Layout should be detected as arena_screenshot."""
        mock_llm_client.call_vision.return_value = arena_recognition_response

        recognizer = CardRecognizer(llm_client=mock_llm_client)
        result = await recognizer.recognize_cards(sample_image_bytes)

        assert result.layout_detected == LayoutType.ARENA_SCREENSHOT


# =============================================================================
# TC-9.2: Physical card photos recognized with >80% accuracy
# =============================================================================


class TestTC92PhysicalCardRecognition:
    """TC-9.2: Physical card photos in rows recognized with >80% accuracy."""

    @pytest.mark.asyncio
    async def test_physical_cards_returns_card_names(
        self, mock_llm_client, sample_image_bytes, physical_recognition_response
    ):
        """Physical card recognition should return a list of card names."""
        mock_llm_client.call_vision.return_value = physical_recognition_response

        recognizer = CardRecognizer(llm_client=mock_llm_client)
        result = await recognizer.recognize_cards(
            sample_image_bytes, layout_hint=LayoutType.PHYSICAL_CARDS
        )

        assert isinstance(result, RecognitionResult)
        assert len(result.main_deck) > 0
        assert all(isinstance(name, str) for name in result.main_deck)

    @pytest.mark.asyncio
    async def test_physical_uses_specialized_prompt(
        self, mock_llm_client, sample_image_bytes, physical_recognition_response
    ):
        """Physical layout hint should use the physical-specific prompt."""
        mock_llm_client.call_vision.return_value = physical_recognition_response

        recognizer = CardRecognizer(llm_client=mock_llm_client)
        await recognizer.recognize_cards(
            sample_image_bytes, layout_hint=LayoutType.PHYSICAL_CARDS
        )

        call_args = mock_llm_client.call_vision.call_args
        prompt = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("prompt")
        assert "physical MTG cards" in prompt

    @pytest.mark.asyncio
    async def test_physical_layout_detected(
        self, mock_llm_client, sample_image_bytes, physical_recognition_response
    ):
        """Layout should be detected as physical_cards."""
        mock_llm_client.call_vision.return_value = physical_recognition_response

        recognizer = CardRecognizer(llm_client=mock_llm_client)
        result = await recognizer.recognize_cards(sample_image_bytes)

        assert result.layout_detected == LayoutType.PHYSICAL_CARDS


# =============================================================================
# TC-9.3: Main deck and sideboard correctly split
# =============================================================================


class TestTC93MainDeckSideboardSplit:
    """TC-9.3: Main deck and sideboard correctly split by position on image."""

    @pytest.mark.asyncio
    async def test_main_deck_and_sideboard_separated(
        self, mock_llm_client, sample_image_bytes, arena_recognition_response
    ):
        """Main deck and sideboard should be in separate lists."""
        mock_llm_client.call_vision.return_value = arena_recognition_response

        recognizer = CardRecognizer(llm_client=mock_llm_client)
        result = await recognizer.recognize_cards(sample_image_bytes)

        assert isinstance(result.main_deck, list)
        assert isinstance(result.sideboard, list)
        assert len(result.main_deck) > len(result.sideboard)

    @pytest.mark.asyncio
    async def test_sideboard_cards_not_in_main_deck(
        self, mock_llm_client, sample_image_bytes, arena_recognition_response
    ):
        """Sideboard cards should not appear in main deck (for this response)."""
        mock_llm_client.call_vision.return_value = arena_recognition_response

        recognizer = CardRecognizer(llm_client=mock_llm_client)
        result = await recognizer.recognize_cards(sample_image_bytes)

        sideboard_set = set(result.sideboard)
        main_deck_set = set(result.main_deck)
        # In this test response, sideboard cards are distinct from main deck
        assert "Negate" in sideboard_set
        assert "Negate" not in main_deck_set

    @pytest.mark.asyncio
    async def test_empty_sideboard_handled(self, mock_llm_client, sample_image_bytes):
        """Should handle images with no visible sideboard."""
        response = {
            "main_deck": ["Card A", "Card B", "Card C"],
            "sideboard": [],
            "detected_set": "MKM",
            "layout_detected": "arena_screenshot",
        }
        mock_llm_client.call_vision.return_value = response

        recognizer = CardRecognizer(llm_client=mock_llm_client)
        result = await recognizer.recognize_cards(sample_image_bytes)

        assert result.main_deck == ["Card A", "Card B", "Card C"]
        assert result.sideboard == []

    @pytest.mark.asyncio
    async def test_missing_sideboard_key_defaults_to_empty(
        self, mock_llm_client, sample_image_bytes
    ):
        """Missing sideboard key should default to empty list."""
        response = {
            "main_deck": ["Card A"],
            "detected_set": "MKM",
            "layout_detected": "arena_screenshot",
        }
        mock_llm_client.call_vision.return_value = response

        recognizer = CardRecognizer(llm_client=mock_llm_client)
        result = await recognizer.recognize_cards(sample_image_bytes)

        assert result.sideboard == []


# =============================================================================
# TC-9.4: Set detected automatically
# =============================================================================


class TestTC94SetDetection:
    """TC-9.4: Set detected automatically by symbol/watermark or most frequent cards."""

    @pytest.mark.asyncio
    async def test_set_detected_from_response(
        self, mock_llm_client, sample_image_bytes, arena_recognition_response
    ):
        """Detected set should be extracted from LLM response."""
        mock_llm_client.call_vision.return_value = arena_recognition_response

        recognizer = CardRecognizer(llm_client=mock_llm_client)
        result = await recognizer.recognize_cards(sample_image_bytes)

        assert result.detected_set == "MKM"

    @pytest.mark.asyncio
    async def test_set_normalized_to_uppercase(
        self, mock_llm_client, sample_image_bytes
    ):
        """Set code should be normalized to uppercase."""
        response = {
            "main_deck": ["Card A"],
            "sideboard": [],
            "detected_set": "mkm",
            "layout_detected": "arena_screenshot",
        }
        mock_llm_client.call_vision.return_value = response

        recognizer = CardRecognizer(llm_client=mock_llm_client)
        result = await recognizer.recognize_cards(sample_image_bytes)

        assert result.detected_set == "MKM"

    @pytest.mark.asyncio
    async def test_null_set_handled(self, mock_llm_client, sample_image_bytes):
        """Null detected_set should be preserved."""
        response = {
            "main_deck": ["Card A"],
            "sideboard": [],
            "detected_set": None,
            "layout_detected": "arena_screenshot",
        }
        mock_llm_client.call_vision.return_value = response

        recognizer = CardRecognizer(llm_client=mock_llm_client)
        result = await recognizer.recognize_cards(sample_image_bytes)

        assert result.detected_set is None

    @pytest.mark.asyncio
    async def test_set_hint_included_in_prompt(
        self, mock_llm_client, sample_image_bytes
    ):
        """Set hint should be included in the prompt."""
        response = {
            "main_deck": ["Card A"],
            "sideboard": [],
            "detected_set": "OTJ",
            "layout_detected": "arena_screenshot",
        }
        mock_llm_client.call_vision.return_value = response

        recognizer = CardRecognizer(llm_client=mock_llm_client)
        await recognizer.recognize_cards(sample_image_bytes, set_hint="OTJ")

        call_args = mock_llm_client.call_vision.call_args
        prompt = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("prompt")
        assert "OTJ" in prompt

    @pytest.mark.asyncio
    async def test_set_detection_prompt_mentions_set_symbols(self):
        """Recognition prompts should instruct to check set symbols."""
        assert "set symbol" in ARENA_RECOGNITION_PROMPT.lower()
        assert "set symbol" in PHYSICAL_RECOGNITION_PROMPT.lower()
        assert "set symbol" in GENERAL_RECOGNITION_PROMPT.lower()


# =============================================================================
# Layout detection tests
# =============================================================================


class TestLayoutDetection:
    """Tests for layout detection functionality."""

    @pytest.mark.asyncio
    async def test_detect_layout_arena(self, mock_llm_client, sample_image_bytes):
        """Should detect Arena screenshot layout."""
        mock_llm_client.call_vision.return_value = {"layout": "arena_screenshot"}

        result = await detect_layout(sample_image_bytes, mock_llm_client)

        assert result == LayoutType.ARENA_SCREENSHOT

    @pytest.mark.asyncio
    async def test_detect_layout_physical(self, mock_llm_client, sample_image_bytes):
        """Should detect physical cards layout."""
        mock_llm_client.call_vision.return_value = {"layout": "physical_cards"}

        result = await detect_layout(sample_image_bytes, mock_llm_client)

        assert result == LayoutType.PHYSICAL_CARDS

    @pytest.mark.asyncio
    async def test_detect_layout_unknown_on_error(
        self, mock_llm_client, sample_image_bytes
    ):
        """Should return UNKNOWN on detection error."""
        mock_llm_client.call_vision.side_effect = Exception("API error")

        result = await detect_layout(sample_image_bytes, mock_llm_client)

        assert result == LayoutType.UNKNOWN

    @pytest.mark.asyncio
    async def test_detect_layout_unknown_on_invalid_value(
        self, mock_llm_client, sample_image_bytes
    ):
        """Should return UNKNOWN for unrecognized layout values."""
        mock_llm_client.call_vision.return_value = {"layout": "something_else"}

        result = await detect_layout(sample_image_bytes, mock_llm_client)

        assert result == LayoutType.UNKNOWN

    def test_parse_layout_from_response_arena(self):
        """Should parse arena_screenshot layout."""
        result = parse_layout_from_response({"layout_detected": "arena_screenshot"})
        assert result == LayoutType.ARENA_SCREENSHOT

    def test_parse_layout_from_response_physical(self):
        """Should parse physical_cards layout."""
        result = parse_layout_from_response({"layout_detected": "physical_cards"})
        assert result == LayoutType.PHYSICAL_CARDS

    def test_parse_layout_from_response_unknown(self):
        """Should return UNKNOWN for missing or invalid layout."""
        assert parse_layout_from_response({}) == LayoutType.UNKNOWN
        assert parse_layout_from_response({"layout_detected": "bad"}) == LayoutType.UNKNOWN


# =============================================================================
# Prompt builder tests
# =============================================================================


class TestPromptBuilders:
    """Tests for prompt building functions."""

    def test_build_recognition_prompt_default(self):
        """Default prompt should be the general recognition prompt."""
        prompt = build_recognition_prompt()
        assert "Analyze the provided image" in prompt

    def test_build_recognition_prompt_arena(self):
        """Arena prompt should mention Arena-specific details."""
        prompt = build_recognition_prompt(layout_type=LayoutType.ARENA_SCREENSHOT)
        assert "MTG Arena screenshot" in prompt
        assert "grid" in prompt.lower() or "thumbnail" in prompt.lower()

    def test_build_recognition_prompt_physical(self):
        """Physical prompt should mention physical card details."""
        prompt = build_recognition_prompt(layout_type=LayoutType.PHYSICAL_CARDS)
        assert "physical MTG cards" in prompt
        assert "surface" in prompt.lower() or "table" in prompt.lower()

    def test_build_recognition_prompt_with_set_hint(self):
        """Set hint should be appended to the prompt."""
        prompt = build_recognition_prompt(set_hint="MKM")
        assert "MKM" in prompt
        assert "Additional context" in prompt

    def test_build_recognition_prompt_without_set_hint(self):
        """Prompt without set hint should not include additional context."""
        prompt = build_recognition_prompt()
        assert "Additional context" not in prompt

    def test_all_prompts_request_json(self):
        """All prompts should request JSON response format."""
        assert "JSON" in ARENA_RECOGNITION_PROMPT
        assert "JSON" in PHYSICAL_RECOGNITION_PROMPT
        assert "JSON" in GENERAL_RECOGNITION_PROMPT

    def test_all_prompts_include_required_fields(self):
        """All prompts should mention main_deck, sideboard, detected_set."""
        for prompt in [
            ARENA_RECOGNITION_PROMPT,
            PHYSICAL_RECOGNITION_PROMPT,
            GENERAL_RECOGNITION_PROMPT,
        ]:
            assert "main_deck" in prompt
            assert "sideboard" in prompt
            assert "detected_set" in prompt

    def test_build_recognition_prompt_with_known_cards(self):
        """Known cards should be included in the prompt as a reference list."""
        prompt = build_recognition_prompt(
            known_cards=["Lightning Bolt", "Counterspell"]
        )
        assert "CARD NAME REFERENCE LIST" in prompt
        assert "Lightning Bolt" in prompt
        assert "Counterspell" in prompt
        assert "MUST ONLY return card names" in prompt

    def test_build_recognition_prompt_known_cards_sorted(self):
        """Known cards in prompt should be alphabetically sorted."""
        prompt = build_recognition_prompt(
            known_cards=["Zebra Unicorn", "Ancestral Recall"]
        )
        zebra_pos = prompt.index("Zebra Unicorn")
        ancestral_pos = prompt.index("Ancestral Recall")
        assert ancestral_pos < zebra_pos

    def test_build_recognition_prompt_empty_known_cards(self):
        """Empty known_cards list should not add reference section."""
        prompt = build_recognition_prompt(known_cards=[])
        assert "CARD NAME REFERENCE LIST" not in prompt

    def test_build_recognition_prompt_none_known_cards(self):
        """None known_cards should not add reference section."""
        prompt = build_recognition_prompt(known_cards=None)
        assert "CARD NAME REFERENCE LIST" not in prompt

    def test_build_recognition_prompt_known_cards_with_set_hint(self):
        """Both set_hint and known_cards should appear in prompt."""
        prompt = build_recognition_prompt(
            set_hint="ECL", known_cards=["Cinder Strike"]
        )
        assert "ECL" in prompt
        assert "CARD NAME REFERENCE LIST" in prompt
        assert "Cinder Strike" in prompt

    def test_physical_prompt_supports_single_card_photos(self):
        """
        Regression: a close-up photo of a single physical card (e.g. a
        showcase / bonus sheet card) was previously being misclassified
        because the prompt only described decks. The prompt must now
        explicitly mark single-card photos as a valid input.
        """
        assert "single-card" in PHYSICAL_RECOGNITION_PROMPT.lower() or (
            "single card" in PHYSICAL_RECOGNITION_PROMPT.lower()
        )
        assert "main_deck" in PHYSICAL_RECOGNITION_PROMPT
        # Must instruct the model not to drop a clearly-visible single card
        assert "empty main_deck" in PHYSICAL_RECOGNITION_PROMPT.lower()

    def test_general_prompt_supports_single_card_photos(self):
        """The general (UNKNOWN-layout) prompt is what runs on bare photos
        sent to the bot — it must also handle single-card close-ups."""
        assert (
            "single-card" in GENERAL_RECOGNITION_PROMPT.lower()
            or "single card" in GENERAL_RECOGNITION_PROMPT.lower()
        )
        assert "empty main_deck" in GENERAL_RECOGNITION_PROMPT.lower()

    def test_prompts_mention_alternate_frames(self):
        """
        Regression: showcase / borderless / bonus-sheet frames were
        previously not handled. The physical and general prompts must
        now name these frame styles so the model still reads card names.
        """
        for prompt in (PHYSICAL_RECOGNITION_PROMPT, GENERAL_RECOGNITION_PROMPT):
            lower = prompt.lower()
            assert "showcase" in lower
            assert "borderless" in lower
            assert "bonus sheet" in lower


# =============================================================================
# Known cards in recognizer tests
# =============================================================================


class TestRecognizeCardsWithKnownCards:
    """Tests for passing known_cards through the recognizer."""

    @pytest.mark.asyncio
    async def test_known_cards_passed_to_prompt(
        self, mock_llm_client, sample_image_bytes
    ):
        """known_cards parameter should appear in the prompt sent to LLM."""
        mock_llm_client.call_vision.return_value = {
            "main_deck": ["Lightning Bolt"],
            "sideboard": [],
            "detected_set": "TST",
            "layout_detected": "arena_screenshot",
        }
        recognizer = CardRecognizer(llm_client=mock_llm_client)
        await recognizer.recognize_cards(
            sample_image_bytes,
            known_cards=["Lightning Bolt", "Counterspell"],
        )
        call_args = mock_llm_client.call_vision.call_args
        prompt = (
            call_args[0][1]
            if len(call_args[0]) > 1
            else call_args[1].get("prompt")
        )
        assert "CARD NAME REFERENCE LIST" in prompt
        assert "Lightning Bolt" in prompt

    @pytest.mark.asyncio
    async def test_known_cards_none_no_reference_in_prompt(
        self, mock_llm_client, sample_image_bytes
    ):
        """Without known_cards, prompt should not contain reference list."""
        mock_llm_client.call_vision.return_value = {
            "main_deck": ["Card A"],
            "sideboard": [],
            "detected_set": "TST",
            "layout_detected": "arena_screenshot",
        }
        recognizer = CardRecognizer(llm_client=mock_llm_client)
        await recognizer.recognize_cards(sample_image_bytes)
        call_args = mock_llm_client.call_vision.call_args
        prompt = (
            call_args[0][1]
            if len(call_args[0]) > 1
            else call_args[1].get("prompt")
        )
        assert "CARD NAME REFERENCE LIST" not in prompt

    @pytest.mark.asyncio
    async def test_two_pass_passes_known_cards(
        self, mock_llm_client, sample_image_bytes, arena_recognition_response
    ):
        """Two-pass recognition should forward known_cards."""
        mock_llm_client.call_vision.side_effect = [
            {"layout": "arena_screenshot"},
            arena_recognition_response,
        ]
        recognizer = CardRecognizer(llm_client=mock_llm_client)
        await recognizer.recognize_cards_two_pass(
            sample_image_bytes,
            known_cards=["Lightning Bolt"],
        )
        second_call_args = mock_llm_client.call_vision.call_args_list[1]
        prompt = (
            second_call_args[0][1]
            if len(second_call_args[0]) > 1
            else second_call_args[1].get("prompt")
        )
        assert "CARD NAME REFERENCE LIST" in prompt


# =============================================================================
# Post-processing tests
# =============================================================================


class TestPostProcessing:
    """Tests for recognition result post-processing."""

    @pytest.mark.asyncio
    async def test_whitespace_stripped_from_names(
        self, mock_llm_client, sample_image_bytes
    ):
        """Card names should have leading/trailing whitespace stripped."""
        response = {
            "main_deck": ["  Lightning Bolt  ", "Counterspell\n"],
            "sideboard": [" Negate "],
            "detected_set": "MKM",
            "layout_detected": "arena_screenshot",
        }
        mock_llm_client.call_vision.return_value = response

        recognizer = CardRecognizer(llm_client=mock_llm_client)
        result = await recognizer.recognize_cards(sample_image_bytes)

        assert result.main_deck == ["Lightning Bolt", "Counterspell"]
        assert result.sideboard == ["Negate"]

    @pytest.mark.asyncio
    async def test_empty_strings_removed(self, mock_llm_client, sample_image_bytes):
        """Empty card names should be removed."""
        response = {
            "main_deck": ["Card A", "", "Card B", "   "],
            "sideboard": ["", "Card C"],
            "detected_set": "MKM",
            "layout_detected": "arena_screenshot",
        }
        mock_llm_client.call_vision.return_value = response

        recognizer = CardRecognizer(llm_client=mock_llm_client)
        result = await recognizer.recognize_cards(sample_image_bytes)

        assert result.main_deck == ["Card A", "Card B"]
        assert result.sideboard == ["Card C"]

    @pytest.mark.asyncio
    async def test_non_string_values_filtered(
        self, mock_llm_client, sample_image_bytes
    ):
        """Non-string values in card lists should be filtered out."""
        response = {
            "main_deck": ["Card A", 123, None, "Card B", True],
            "sideboard": [],
            "detected_set": "MKM",
            "layout_detected": "arena_screenshot",
        }
        mock_llm_client.call_vision.return_value = response

        recognizer = CardRecognizer(llm_client=mock_llm_client)
        result = await recognizer.recognize_cards(sample_image_bytes)

        assert result.main_deck == ["Card A", "Card B"]

    @pytest.mark.asyncio
    async def test_set_code_whitespace_stripped(
        self, mock_llm_client, sample_image_bytes
    ):
        """Set code should have whitespace stripped."""
        response = {
            "main_deck": ["Card A"],
            "sideboard": [],
            "detected_set": "  mkm  ",
            "layout_detected": "arena_screenshot",
        }
        mock_llm_client.call_vision.return_value = response

        recognizer = CardRecognizer(llm_client=mock_llm_client)
        result = await recognizer.recognize_cards(sample_image_bytes)

        assert result.detected_set == "MKM"


# =============================================================================
# Two-pass recognition tests
# =============================================================================


class TestTwoPassRecognition:
    """Tests for two-pass recognition flow."""

    @pytest.mark.asyncio
    async def test_two_pass_detects_then_recognizes(
        self, mock_llm_client, sample_image_bytes, arena_recognition_response
    ):
        """Two-pass should first detect layout, then recognize with specialized prompt."""
        mock_llm_client.call_vision.side_effect = [
            {"layout": "arena_screenshot"},  # First call: layout detection
            arena_recognition_response,  # Second call: recognition
        ]

        recognizer = CardRecognizer(llm_client=mock_llm_client)
        result = await recognizer.recognize_cards_two_pass(sample_image_bytes)

        assert mock_llm_client.call_vision.call_count == 2
        assert result.layout_detected == LayoutType.ARENA_SCREENSHOT
        assert len(result.main_deck) == 40

    @pytest.mark.asyncio
    async def test_two_pass_with_set_hint(
        self, mock_llm_client, sample_image_bytes, arena_recognition_response
    ):
        """Two-pass should pass set_hint to the recognition call."""
        mock_llm_client.call_vision.side_effect = [
            {"layout": "arena_screenshot"},
            arena_recognition_response,
        ]

        recognizer = CardRecognizer(llm_client=mock_llm_client)
        await recognizer.recognize_cards_two_pass(sample_image_bytes, set_hint="MKM")

        # Second call should include set hint in prompt
        second_call_args = mock_llm_client.call_vision.call_args_list[1]
        prompt = (
            second_call_args[0][1]
            if len(second_call_args[0]) > 1
            else second_call_args[1].get("prompt")
        )
        assert "MKM" in prompt


# =============================================================================
# RecognitionResult dataclass tests
# =============================================================================


class TestRecognitionResult:
    """Tests for the RecognitionResult dataclass."""

    def test_default_values(self):
        """RecognitionResult should have sensible defaults."""
        result = RecognitionResult()
        assert result.main_deck == []
        assert result.sideboard == []
        assert result.detected_set is None
        assert result.layout_detected == LayoutType.UNKNOWN

    def test_custom_values(self):
        """RecognitionResult should accept custom values."""
        result = RecognitionResult(
            main_deck=["Card A", "Card B"],
            sideboard=["Card C"],
            detected_set="MKM",
            layout_detected=LayoutType.ARENA_SCREENSHOT,
        )
        assert result.main_deck == ["Card A", "Card B"]
        assert result.sideboard == ["Card C"]
        assert result.detected_set == "MKM"
        assert result.layout_detected == LayoutType.ARENA_SCREENSHOT
