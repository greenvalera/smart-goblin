"""Tests for card name fuzzy matching."""

import logging

import pytest

from src.vision.card_matcher import (
    FUZZY_MATCH_CUTOFF,
    LOW_CONFIDENCE_CUTOFF,
    MatchResult,
    fuzzy_match_cards,
)


# Sample known card names (mix of ECL-style names)
KNOWN_CARDS = [
    "Cinder Strike",
    "Impulsive Entrance",
    "Blight Rot",
    "Feed the Flames",
    "Elder Auntie",
    "Goblin Chieftain",
    "Changeling Shapeshifter",
    "Boggart Sprite-Chaser",
    "Gathering Stone",
    "Down's Light Archer",
    "Dream Seizure",
    "Lightning Bolt",
]


class TestExactMatching:
    """Tests for exact (normalized) card name matching."""

    def test_exact_match_preserves_names(self):
        result = fuzzy_match_cards(
            ["Lightning Bolt", "Blight Rot"], KNOWN_CARDS
        )
        assert result.matched == ["Lightning Bolt", "Blight Rot"]
        assert result.exact_count == 2
        assert result.unmatched == []

    def test_exact_match_case_insensitive(self):
        result = fuzzy_match_cards(
            ["lightning bolt", "BLIGHT ROT"], KNOWN_CARDS
        )
        assert result.matched == ["Lightning Bolt", "Blight Rot"]
        assert result.exact_count == 2

    def test_exact_match_with_extra_whitespace(self):
        result = fuzzy_match_cards(
            ["  Lightning Bolt  ", "Blight  Rot"], KNOWN_CARDS
        )
        # normalize_card_name strips and collapses whitespace
        assert "Lightning Bolt" in result.matched

    def test_exact_match_records_correction_when_different(self):
        result = fuzzy_match_cards(["lightning bolt"], KNOWN_CARDS)
        assert result.matched == ["Lightning Bolt"]
        assert result.corrections == {"lightning bolt": "Lightning Bolt"}

    def test_exact_match_no_correction_when_identical(self):
        result = fuzzy_match_cards(["Lightning Bolt"], KNOWN_CARDS)
        assert result.matched == ["Lightning Bolt"]
        assert result.corrections == {}


class TestFuzzyMatching:
    """Tests for fuzzy (difflib) card name matching."""

    def test_fuzzy_corrects_minor_misspelling(self):
        result = fuzzy_match_cards(["Lightining Bolt"], KNOWN_CARDS)
        assert result.matched == ["Lightning Bolt"]
        assert "Lightining Bolt" in result.corrections
        assert result.corrections["Lightining Bolt"] == "Lightning Bolt"

    def test_fuzzy_corrects_truncated_name(self):
        result = fuzzy_match_cards(["Changeling Shapeshif"], KNOWN_CARDS)
        assert result.matched == ["Changeling Shapeshifter"]

    def test_fuzzy_corrects_minor_variation(self):
        result = fuzzy_match_cards(["Boggart Sprite Chaser"], KNOWN_CARDS)
        # Missing hyphen should still match
        assert result.matched == ["Boggart Sprite-Chaser"]

    def test_fuzzy_rejects_completely_wrong_name(self):
        result = fuzzy_match_cards(
            ["Totally Fake Card Name"], KNOWN_CARDS
        )
        assert result.matched == ["Totally Fake Card Name"]  # kept as-is
        assert result.unmatched == ["Totally Fake Card Name"]
        assert result.match_count == 0

    def test_fuzzy_rejects_other_set_card(self):
        """A card from another set should not match ECL cards."""
        result = fuzzy_match_cards(
            ["Deadly Cover-Up"], KNOWN_CARDS
        )
        assert "Deadly Cover-Up" in result.unmatched


class TestDuplicateHandling:
    """Tests for handling duplicate card names."""

    def test_duplicates_preserved_in_matched(self):
        result = fuzzy_match_cards(
            ["Lightning Bolt", "Lightning Bolt", "Lightning Bolt"],
            KNOWN_CARDS,
        )
        assert result.matched == [
            "Lightning Bolt", "Lightning Bolt", "Lightning Bolt"
        ]
        assert result.match_count == 3
        assert result.exact_count == 3

    def test_duplicates_with_fuzzy(self):
        result = fuzzy_match_cards(
            ["Lightining Bolt", "Lightining Bolt"],
            KNOWN_CARDS,
        )
        assert result.matched == ["Lightning Bolt", "Lightning Bolt"]
        assert result.match_count == 2


class TestEdgeCases:
    """Tests for edge cases and empty inputs."""

    def test_empty_recognized_list(self):
        result = fuzzy_match_cards([], KNOWN_CARDS)
        assert result.matched == []
        assert result.corrections == {}
        assert result.unmatched == []

    def test_empty_known_list(self):
        result = fuzzy_match_cards(["Lightning Bolt"], [])
        assert result.matched == ["Lightning Bolt"]
        assert result.match_count == 0

    def test_none_like_empty_known_list(self):
        """Empty known_cards returns all recognized names unchanged."""
        names = ["Card A", "Card B"]
        result = fuzzy_match_cards(names, [])
        assert result.matched == names
        assert result.unmatched == []

    def test_single_card(self):
        result = fuzzy_match_cards(["Cinder Strike"], KNOWN_CARDS)
        assert result.matched == ["Cinder Strike"]
        assert result.exact_count == 1


class TestMatchResultCounts:
    """Tests for MatchResult count accuracy."""

    def test_all_exact(self):
        result = fuzzy_match_cards(
            ["Lightning Bolt", "Blight Rot"], KNOWN_CARDS
        )
        assert result.match_count == 2
        assert result.exact_count == 2
        assert len(result.unmatched) == 0

    def test_mixed_exact_fuzzy_unmatched(self):
        result = fuzzy_match_cards(
            ["Lightning Bolt", "Lightining Bolt", "Totally Fake"],
            KNOWN_CARDS,
        )
        assert result.exact_count == 1  # Lightning Bolt
        assert result.match_count == 2  # exact + fuzzy
        assert len(result.unmatched) == 1  # Totally Fake

    def test_match_result_defaults(self):
        r = MatchResult()
        assert r.matched == []
        assert r.corrections == {}
        assert r.unmatched == []
        assert r.match_count == 0
        assert r.exact_count == 0


class TestCustomCutoff:
    """Tests for custom similarity threshold."""

    def test_higher_cutoff_rejects_more(self):
        # "Feed Flames" vs "Feed the Flames" — similarity ~0.83, rejected at 0.95
        result = fuzzy_match_cards(
            ["Feed Flames"], KNOWN_CARDS, cutoff=0.95
        )
        assert result.unmatched == ["Feed Flames"]

    def test_lower_cutoff_accepts_more(self):
        result = fuzzy_match_cards(
            ["Lightining Bolt"], KNOWN_CARDS, cutoff=0.5
        )
        assert result.matched == ["Lightning Bolt"]


class TestLogging:
    """Tests for logging behavior."""

    def test_low_confidence_match_logs_warning(self, caplog):
        # "Feed Flam" vs "Feed the Flames" — similarity 0.75, below LOW_CONFIDENCE_CUTOFF (0.8)
        with caplog.at_level(logging.WARNING, logger="src.vision.card_matcher"):
            fuzzy_match_cards(["Feed Flam"], KNOWN_CARDS, cutoff=0.7)
        warning_msgs = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("Low-confidence" in r.message for r in warning_msgs)

    def test_unmatched_logs_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="src.vision.card_matcher"):
            fuzzy_match_cards(["Completely Unknown Card"], KNOWN_CARDS)
        warning_msgs = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("No match found" in r.message for r in warning_msgs)

    def test_corrections_log_summary(self, caplog):
        with caplog.at_level(logging.INFO, logger="src.vision.card_matcher"):
            fuzzy_match_cards(
                ["lightning bolt", "Lightining Bolt"], KNOWN_CARDS
            )
        info_msgs = [r for r in caplog.records if r.levelno == logging.INFO]
        assert any("Card matching" in r.message for r in info_msgs)
