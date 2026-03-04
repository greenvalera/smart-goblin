"""
Unit tests for the DeckAdvisor module.

Tests cover:
- TC-11.1: Advice contains specific card names for replacement (min 2 if weak cards exist)
- TC-11.2: If sideboard is empty, the "add from sideboard" section is absent
- TC-11.3: Advice text in Ukrainian, without technical jargon
- TC-11.4: Advice considers mana curve (too many expensive/cheap cards)
"""

import os
from decimal import Decimal
from unittest import mock
from unittest.mock import AsyncMock, patch

import pytest

from src.core.advisor import (
    DeckAdvisor,
    WEAK_CARD_THRESHOLD,
    STRONG_CARD_THRESHOLD,
)
from src.core.deck import CardInfo, Deck, DeckAnalysis
from src.llm.client import LLMClient


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
def llm_client(mock_env):
    """Create an LLMClient instance for testing."""
    return LLMClient()


@pytest.fixture
def advisor(llm_client):
    """Create a DeckAdvisor instance for testing."""
    return DeckAdvisor(llm_client)


def make_card_info(
    name: str,
    rating: float | None = None,
    win_rate: float | None = None,
    cmc: float | None = None,
    colors: list[str] | None = None,
) -> CardInfo:
    """Helper to create CardInfo with Decimal fields."""
    return CardInfo(
        name=name,
        rating=Decimal(str(rating)) if rating is not None else None,
        win_rate=Decimal(str(win_rate)) if win_rate is not None else None,
        cmc=Decimal(str(cmc)) if cmc is not None else None,
        colors=colors,
    )


def build_deck_with_weak_and_strong() -> tuple[Deck, list[CardInfo], DeckAnalysis]:
    """Build a test deck with weak main deck cards and strong sideboard cards."""
    main_cards = [
        "Lightning Bolt", "Counterspell", "Doom Blade",
        "Weak Creature A", "Weak Creature B", "Weak Spell C",
        "Llanowar Elves", "Serra Angel",
    ]
    sideboard_cards = [
        "Strong Sideboard Card", "Another Strong Card", "Mediocre Card",
    ]

    deck = Deck(main_deck=main_cards, sideboard=sideboard_cards, set_code="TST")

    card_infos = [
        # Strong main deck cards
        make_card_info("Lightning Bolt", rating=4.5, win_rate=58.0, cmc=1, colors=["R"]),
        make_card_info("Counterspell", rating=4.0, win_rate=56.0, cmc=2, colors=["U"]),
        make_card_info("Doom Blade", rating=3.5, win_rate=54.0, cmc=2, colors=["B"]),
        # Weak main deck cards (rating < 2.5)
        make_card_info("Weak Creature A", rating=1.5, win_rate=42.0, cmc=3),
        make_card_info("Weak Creature B", rating=2.0, win_rate=44.0, cmc=4),
        make_card_info("Weak Spell C", rating=2.2, win_rate=45.0, cmc=5),
        # Decent cards
        make_card_info("Llanowar Elves", rating=3.0, win_rate=52.0, cmc=1, colors=["G"]),
        make_card_info("Serra Angel", rating=3.8, win_rate=55.0, cmc=5, colors=["W"]),
        # Strong sideboard
        make_card_info("Strong Sideboard Card", rating=4.0, win_rate=57.0, cmc=3, colors=["R"]),
        make_card_info("Another Strong Card", rating=3.5, win_rate=55.5, cmc=2, colors=["U"]),
        # Weak sideboard
        make_card_info("Mediocre Card", rating=2.0, win_rate=45.0, cmc=4),
    ]

    analysis = DeckAnalysis(
        score=Decimal("3.10"),
        estimated_win_rate=Decimal("51.50"),
        mana_curve={1: 2, 2: 2, 3: 1, 4: 1, 5: 2},
        color_distribution={"R": 25.0, "U": 25.0, "B": 12.5, "G": 12.5, "W": 12.5, "C": 12.5},
        cards_with_ratings=8,
        total_cards=8,
    )

    return deck, card_infos, analysis


class TestTC111AdviceContainsCardNames:
    """TC-11.1: Advice contains specific card names for replacement (min 2 if weak cards exist)."""

    @pytest.mark.asyncio
    async def test_prompt_includes_weak_card_names(self, advisor, llm_client):
        """The prompt sent to LLM should contain weak card names for replacement."""
        deck, card_infos, analysis = build_deck_with_weak_and_strong()

        captured_messages = []

        async def mock_completion(messages, system_prompt=None):
            captured_messages.extend(messages)
            return (
                "Загальна оцінка: Колода має потенціал, але потребує оптимізації.\n\n"
                "Рекомендую замінити:\n"
                "- Weak Creature A — слабка карта, краще прибрати\n"
                "- Weak Creature B — не варта місця в колоді\n"
                "Додайте з сайдборду:\n"
                "- Strong Sideboard Card — значно краща альтернатива"
            )

        with patch.object(llm_client, "call_completion", side_effect=mock_completion):
            advice = await advisor.generate_advice(deck, card_infos, analysis)

        # Verify the prompt includes weak card names
        prompt_text = captured_messages[0]["content"]
        assert "Weak Creature A" in prompt_text
        assert "Weak Creature B" in prompt_text
        assert "Weak Spell C" in prompt_text

    @pytest.mark.asyncio
    async def test_finds_at_least_2_weak_cards(self, advisor):
        """Should identify at least 2 weak cards when they exist."""
        deck, card_infos, _ = build_deck_with_weak_and_strong()
        card_map = {c.name: c for c in card_infos}

        weak = advisor._find_weak_cards(deck.main_deck, card_map)

        # We have 3 weak cards (rating < 2.5)
        assert len(weak) >= 2
        # All should be below threshold
        for card in weak:
            assert card.rating < WEAK_CARD_THRESHOLD

    @pytest.mark.asyncio
    async def test_strong_sideboard_cards_included_in_prompt(self, advisor, llm_client):
        """Strong sideboard cards should be included in the prompt."""
        deck, card_infos, analysis = build_deck_with_weak_and_strong()

        captured_messages = []

        async def mock_completion(messages, system_prompt=None):
            captured_messages.extend(messages)
            return "Порада українською."

        with patch.object(llm_client, "call_completion", side_effect=mock_completion):
            await advisor.generate_advice(deck, card_infos, analysis)

        prompt_text = captured_messages[0]["content"]
        assert "Strong Sideboard Card" in prompt_text
        assert "Another Strong Card" in prompt_text


class TestTC112EmptySideboardNoSection:
    """TC-11.2: If sideboard is empty, the 'add from sideboard' section is absent."""

    @pytest.mark.asyncio
    async def test_empty_sideboard_no_add_section(self, advisor, llm_client):
        """When sideboard is empty, prompt should not have 'strong sideboard' section."""
        deck = Deck(
            main_deck=["Card A", "Card B", "Card C"],
            sideboard=[],
            set_code="TST",
        )
        card_infos = [
            make_card_info("Card A", rating=3.5, win_rate=54.0, cmc=2),
            make_card_info("Card B", rating=2.0, win_rate=44.0, cmc=3),
            make_card_info("Card C", rating=3.0, win_rate=50.0, cmc=4),
        ]
        analysis = DeckAnalysis(
            score=Decimal("2.83"),
            estimated_win_rate=Decimal("49.33"),
            mana_curve={2: 1, 3: 1, 4: 1},
            color_distribution={},
            cards_with_ratings=3,
            total_cards=3,
        )

        captured_messages = []

        async def mock_completion(messages, system_prompt=None):
            captured_messages.extend(messages)
            return "Порада без сайдборду."

        with patch.object(llm_client, "call_completion", side_effect=mock_completion):
            await advisor.generate_advice(deck, card_infos, analysis)

        prompt_text = captured_messages[0]["content"]
        # The prompt should indicate empty sideboard
        assert "порожній" in prompt_text
        # Should NOT have the "strong sideboard cards" section
        assert "Сильні карти з sideboard для додавання" not in prompt_text

    @pytest.mark.asyncio
    async def test_no_strong_sideboard_cards_found(self, advisor):
        """With empty sideboard, no strong sideboard cards should be found."""
        card_map: dict[str, CardInfo] = {}
        strong = advisor._find_strong_sideboard_cards([], card_map)
        assert strong == []


class TestTC113UkrainianNoJargon:
    """TC-11.3: Advice text in Ukrainian, without technical jargon."""

    @pytest.mark.asyncio
    async def test_system_prompt_requests_ukrainian(self, advisor, llm_client):
        """The LLM should receive a system prompt requesting Ukrainian output."""
        deck = Deck(main_deck=["Card A"], sideboard=[], set_code="TST")
        card_infos = [make_card_info("Card A", rating=3.0, cmc=2)]
        analysis = DeckAnalysis(
            score=Decimal("3.0"),
            estimated_win_rate=Decimal("50.0"),
            mana_curve={2: 1},
            color_distribution={},
        )

        captured_messages = []

        async def mock_completion(messages, system_prompt=None):
            captured_messages.extend(messages)
            return "Гарна колода!"

        with patch.object(llm_client, "call_completion", side_effect=mock_completion):
            await advisor.generate_advice(deck, card_infos, analysis)

        prompt_text = captured_messages[0]["content"]
        # The prompt should explicitly request Ukrainian
        assert "українською" in prompt_text

    @pytest.mark.asyncio
    async def test_extra_context_in_ukrainian(self, advisor):
        """Extra context sections should use Ukrainian text."""
        weak_cards = [
            make_card_info("Bad Card", rating=1.5, win_rate=40.0),
        ]
        curve_issues = advisor._analyze_mana_curve({1: 1, 5: 5, 6: 4})

        context = advisor._build_extra_context(weak_cards, [], curve_issues)

        # Context should be in Ukrainian
        assert "Слабкі карти для заміни" in context
        assert "Проблеми з кривою мани" in context
        # Should contain Ukrainian words
        assert "дорогих" in context or "мани" in context


class TestTC114ManaCurveConsideration:
    """TC-11.4: Advice considers mana curve (too many expensive/cheap cards)."""

    def test_detects_too_many_expensive_cards(self, advisor):
        """Should flag when >25% of cards have CMC 5+."""
        # 4 out of 10 cards are CMC 5+ (40%)
        mana_curve = {1: 1, 2: 2, 3: 2, 4: 1, 5: 2, 6: 1, 7: 1}
        issues = advisor._analyze_mana_curve(mana_curve)

        expensive_issue = [i for i in issues if "дорогих" in i]
        assert len(expensive_issue) > 0

    def test_detects_too_few_early_cards(self, advisor):
        """Should flag when <15% of cards are CMC 1-2."""
        # 1 out of 10 cards is CMC 1-2 (10%)
        mana_curve = {1: 1, 3: 3, 4: 3, 5: 2, 6: 1}
        issues = advisor._analyze_mana_curve(mana_curve)

        early_issue = [i for i in issues if "ранніх" in i]
        assert len(early_issue) > 0

    def test_detects_curve_peak_too_high(self, advisor):
        """Should flag when curve peaks at CMC 4+."""
        mana_curve = {1: 1, 2: 2, 3: 3, 4: 5, 5: 2}
        issues = advisor._analyze_mana_curve(mana_curve)

        peak_issue = [i for i in issues if "повільна" in i]
        assert len(peak_issue) > 0

    def test_detects_curve_peak_too_low(self, advisor):
        """Should flag when curve peaks at CMC 0-1."""
        mana_curve = {0: 5, 1: 8, 2: 3, 3: 1}
        issues = advisor._analyze_mana_curve(mana_curve)

        peak_issue = [i for i in issues if "агресивно" in i]
        assert len(peak_issue) > 0

    def test_no_issues_with_balanced_curve(self, advisor):
        """Should not flag a well-balanced mana curve."""
        # Ideal curve: peak at 2-3, reasonable distribution
        mana_curve = {1: 3, 2: 6, 3: 6, 4: 4, 5: 1}
        issues = advisor._analyze_mana_curve(mana_curve)

        assert len(issues) == 0

    @pytest.mark.asyncio
    async def test_curve_issues_included_in_prompt(self, advisor, llm_client):
        """Mana curve issues should be included in the prompt to the LLM."""
        # Deck with too many expensive cards
        main_cards = [f"Card {i}" for i in range(10)]
        deck = Deck(main_deck=main_cards, sideboard=[], set_code="TST")

        card_infos = [
            make_card_info(f"Card {i}", rating=3.0, win_rate=50.0, cmc=5 + (i % 3))
            for i in range(10)
        ]
        analysis = DeckAnalysis(
            score=Decimal("3.0"),
            estimated_win_rate=Decimal("50.0"),
            # Terrible curve: all expensive
            mana_curve={5: 4, 6: 3, 7: 3},
            color_distribution={},
            cards_with_ratings=10,
            total_cards=10,
        )

        captured_messages = []

        async def mock_completion(messages, system_prompt=None):
            captured_messages.extend(messages)
            return "Крива мани потребує коригування."

        with patch.object(llm_client, "call_completion", side_effect=mock_completion):
            await advisor.generate_advice(deck, card_infos, analysis)

        prompt_text = captured_messages[0]["content"]
        assert "кривою мани" in prompt_text or "дорогих" in prompt_text

    def test_empty_curve_no_issues(self, advisor):
        """Empty mana curve should produce no issues."""
        issues = advisor._analyze_mana_curve({})
        assert issues == []


class TestDeckAdvisorHelpers:
    """Tests for DeckAdvisor helper methods."""

    def test_build_card_dicts_with_full_info(self, advisor):
        """Card dicts should contain all available info."""
        card_map = {
            "Bolt": make_card_info("Bolt", rating=4.5, win_rate=58.0, cmc=1),
        }
        result = advisor._build_card_dicts(["Bolt"], card_map)

        assert len(result) == 1
        assert result[0]["name"] == "Bolt"
        assert result[0]["rating"] == 4.5
        assert result[0]["win_rate"] == 58.0
        assert result[0]["cmc"] == 1.0

    def test_build_card_dicts_with_unknown_card(self, advisor):
        """Unknown cards should have cmc='?' and no rating."""
        result = advisor._build_card_dicts(["Unknown Card"], {})

        assert len(result) == 1
        assert result[0]["name"] == "Unknown Card"
        assert result[0]["cmc"] == "?"
        assert "rating" not in result[0]

    def test_build_analysis_dict(self, advisor):
        """Analysis dict should contain all fields."""
        analysis = DeckAnalysis(
            score=Decimal("3.50"),
            estimated_win_rate=Decimal("54.25"),
            mana_curve={1: 3, 2: 5},
            color_distribution={"R": 60.0, "U": 40.0},
        )
        result = advisor._build_analysis_dict(analysis)

        assert result["total_score"] == 3.50
        assert result["estimated_win_rate"] == 54.25
        assert result["mana_curve"] == {1: 3, 2: 5}
        assert result["color_distribution"] == {"R": 60.0, "U": 40.0}

    def test_weak_cards_sorted_by_rating(self, advisor):
        """Weak cards should be sorted by rating ascending."""
        card_map = {
            "A": make_card_info("A", rating=2.4),
            "B": make_card_info("B", rating=1.0),
            "C": make_card_info("C", rating=2.0),
        }
        weak = advisor._find_weak_cards(["A", "B", "C"], card_map)

        assert [c.name for c in weak] == ["B", "C", "A"]

    def test_weak_cards_deduplicated(self, advisor):
        """Duplicate card names should appear only once in weak list."""
        card_map = {
            "Dup": make_card_info("Dup", rating=1.5),
        }
        weak = advisor._find_weak_cards(["Dup", "Dup", "Dup"], card_map)

        assert len(weak) == 1
        assert weak[0].name == "Dup"

    def test_strong_sideboard_sorted_by_rating(self, advisor):
        """Strong sideboard cards should be sorted by rating descending."""
        card_map = {
            "X": make_card_info("X", rating=3.5, win_rate=53.0),
            "Y": make_card_info("Y", rating=4.5, win_rate=58.0),
            "Z": make_card_info("Z", rating=3.0, win_rate=56.0),
        }
        strong = advisor._find_strong_sideboard_cards(["X", "Y", "Z"], card_map)

        assert strong[0].name == "Y"
        assert strong[1].name == "X"

    def test_no_extra_context_when_no_issues(self, advisor):
        """Extra context should be empty when no issues found."""
        context = advisor._build_extra_context([], [], [])
        assert context == ""


class TestP37SessionMode:
    """P3-7: Session mode — sideboard swap recommendations."""

    @pytest.mark.asyncio
    async def test_session_mode_accepted_without_error(self, advisor, llm_client):
        """TC-P3-7.1: generate_advice() accepts session_mode=True without errors."""
        deck, card_infos, analysis = build_deck_with_weak_and_strong()

        async def mock_completion(messages, system_prompt=None):
            return "OUT: Weak Creature A → IN: Strong Sideboard Card"

        with patch.object(llm_client, "call_completion", side_effect=mock_completion):
            advice = await advisor.generate_advice(
                deck, card_infos, analysis, session_mode=True
            )

        assert advice  # non-empty response

    @pytest.mark.asyncio
    async def test_session_mode_prompt_contains_swap_instructions(self, advisor, llm_client):
        """TC-P3-7.2: session_mode=True with non-empty sideboard produces swap-focused prompt."""
        deck, card_infos, analysis = build_deck_with_weak_and_strong()

        captured_messages = []

        async def mock_completion(messages, system_prompt=None):
            captured_messages.extend(messages)
            return "Заміни карт."

        with patch.object(llm_client, "call_completion", side_effect=mock_completion):
            await advisor.generate_advice(
                deck, card_infos, analysis, session_mode=True
            )

        prompt_text = captured_messages[0]["content"]
        # Session prompt should contain swap-related keywords
        assert "заміни" in prompt_text.lower()
        assert "sideboard" in prompt_text.lower()
        assert "OUT:" in prompt_text
        assert "IN:" in prompt_text

    @pytest.mark.asyncio
    async def test_session_mode_empty_sideboard_falls_back(self, advisor, llm_client):
        """TC-P3-7.3: session_mode=True with empty sideboard falls back to standard prompt."""
        deck = Deck(
            main_deck=["Card A", "Card B", "Card C"],
            sideboard=[],
            set_code="TST",
        )
        card_infos = [
            make_card_info("Card A", rating=3.5, win_rate=54.0, cmc=2),
            make_card_info("Card B", rating=2.0, win_rate=44.0, cmc=3),
            make_card_info("Card C", rating=3.0, win_rate=50.0, cmc=4),
        ]
        analysis = DeckAnalysis(
            score=Decimal("2.83"),
            estimated_win_rate=Decimal("49.33"),
            mana_curve={2: 1, 3: 1, 4: 1},
            color_distribution={},
            cards_with_ratings=3,
            total_cards=3,
        )

        captured_session = []
        captured_standard = []

        async def mock_session(messages, system_prompt=None):
            captured_session.extend(messages)
            return "Порада."

        async def mock_standard(messages, system_prompt=None):
            captured_standard.extend(messages)
            return "Порада."

        # Get standard prompt for comparison
        with patch.object(llm_client, "call_completion", side_effect=mock_standard):
            await advisor.generate_advice(deck, card_infos, analysis, session_mode=False)

        # Get session mode prompt with empty sideboard
        with patch.object(llm_client, "call_completion", side_effect=mock_session):
            await advisor.generate_advice(deck, card_infos, analysis, session_mode=True)

        # Both should produce the same prompt (fallback)
        assert captured_session[0]["content"] == captured_standard[0]["content"]

    @pytest.mark.asyncio
    async def test_session_system_prompt_passed_to_completion(self, advisor, llm_client):
        """TC-P3-7.4: session_mode=True passes ADVICE_SESSION_SYSTEM_PROMPT to call_completion."""
        from src.llm.prompts import ADVICE_SESSION_SYSTEM_PROMPT

        deck, card_infos, analysis = build_deck_with_weak_and_strong()

        captured_system_prompt = []

        async def mock_completion(messages, system_prompt=None):
            captured_system_prompt.append(system_prompt)
            return "Заміни."

        with patch.object(llm_client, "call_completion", side_effect=mock_completion):
            await advisor.generate_advice(
                deck, card_infos, analysis, session_mode=True
            )

        assert captured_system_prompt[0] == ADVICE_SESSION_SYSTEM_PROMPT
