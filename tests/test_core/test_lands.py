"""Tests for the land recommendation calculator."""

import pytest

from src.core.lands import LandRecommendation, count_color_pips, recommend_lands


class _FakeCard:
    """Minimal card-like object for testing."""

    def __init__(self, name="Card", mana_cost=None, colors=None):
        self.name = name
        self.mana_cost = mana_cost
        self.colors = colors


class TestCountColorPips:
    def test_none_mana_cost(self):
        assert count_color_pips(None) == {}

    def test_empty_mana_cost(self):
        assert count_color_pips("") == {}

    def test_colorless_only(self):
        assert count_color_pips("{3}") == {}

    def test_single_pip(self):
        assert count_color_pips("{W}") == {"W": 1}

    def test_multiple_same_color(self):
        assert count_color_pips("{W}{W}") == {"W": 2}

    def test_two_colors(self):
        result = count_color_pips("{2}{W}{U}")
        assert result == {"W": 1, "U": 1}

    def test_complex_cost(self):
        result = count_color_pips("{2}{W}{W}{U}")
        assert result == {"W": 2, "U": 1}

    def test_hybrid_mana(self):
        result = count_color_pips("{W/U}")
        assert result == {"W": 1, "U": 1}

    def test_phyrexian_mana(self):
        result = count_color_pips("{W/P}")
        assert result == {"W": 1}

    def test_x_cost_ignored(self):
        result = count_color_pips("{X}{R}{R}")
        assert result == {"R": 2}

    def test_all_five_colors(self):
        result = count_color_pips("{W}{U}{B}{R}{G}")
        assert result == {"W": 1, "U": 1, "B": 1, "R": 1, "G": 1}


class TestRecommendLands:
    def test_two_color_deck(self):
        """A W/U deck should get proportional land split."""
        cards = [
            _FakeCard(mana_cost="{W}"),
            _FakeCard(mana_cost="{W}"),
            _FakeCard(mana_cost="{W}{W}"),  # 2 W pips
            _FakeCard(mana_cost="{U}"),
            _FakeCard(mana_cost="{1}{U}"),
        ]
        # Total: W=4, U=2 → W gets ~11, U gets ~6
        rec = recommend_lands(cards)
        assert rec.total_lands == 17
        assert set(rec.lands.keys()) == {"W", "U"}
        assert rec.lands["W"] + rec.lands["U"] == 17
        assert rec.lands["W"] > rec.lands["U"]

    def test_mono_color(self):
        """Mono-red deck gets all mountains."""
        cards = [
            _FakeCard(mana_cost="{R}"),
            _FakeCard(mana_cost="{1}{R}"),
            _FakeCard(mana_cost="{R}{R}"),
        ]
        rec = recommend_lands(cards)
        assert rec.lands == {"R": 17}

    def test_colorless_deck_with_no_data(self):
        """Fully colorless cards with no mana_cost returns empty lands."""
        cards = [
            _FakeCard(mana_cost="{3}"),
            _FakeCard(mana_cost="{2}"),
        ]
        rec = recommend_lands(cards)
        assert rec.lands == {}
        assert rec.total_lands == 17

    def test_fallback_to_colors_field(self):
        """When mana_cost is missing, use card.colors field."""
        cards = [
            _FakeCard(colors=["W"]),
            _FakeCard(colors=["W"]),
            _FakeCard(colors=["B"]),
        ]
        rec = recommend_lands(cards)
        assert set(rec.lands.keys()) == {"W", "B"}
        assert rec.lands["W"] + rec.lands["B"] == 17
        assert rec.lands["W"] > rec.lands["B"]

    def test_empty_card_list(self):
        """No cards returns empty recommendation."""
        rec = recommend_lands([])
        assert rec.lands == {}
        assert rec.total_spells == 0

    def test_minimum_one_per_color(self):
        """Each color present gets at least 1 land."""
        cards = [
            _FakeCard(mana_cost="{R}{R}{R}{R}{R}{R}{R}{R}{R}{R}"),  # 10 R pips
            _FakeCard(mana_cost="{W}"),  # 1 W pip
        ]
        rec = recommend_lands(cards)
        assert rec.lands["W"] >= 1
        assert rec.lands["R"] + rec.lands["W"] == 17

    def test_custom_land_count(self):
        """Custom total_lands parameter works."""
        cards = [_FakeCard(mana_cost="{R}")]
        rec = recommend_lands(cards, total_lands=16)
        assert rec.total_lands == 16
        assert rec.lands == {"R": 16}

    def test_total_spells_count(self):
        """total_spells reflects the input card count."""
        cards = [_FakeCard(mana_cost="{R}") for _ in range(23)]
        rec = recommend_lands(cards)
        assert rec.total_spells == 23

    def test_five_color_deck(self):
        """Five-color deck distributes lands across all colors."""
        cards = [
            _FakeCard(mana_cost="{W}{U}{B}{R}{G}"),
        ]
        rec = recommend_lands(cards)
        assert len(rec.lands) == 5
        assert sum(rec.lands.values()) == 17
        for count in rec.lands.values():
            assert count >= 1
