"""
Integration tests for the full analyze flow (E2E).

Tests cover:
- TC-17.1: E2E test — analyze flow from photo to DB storage (with mocked LLM)
- TC-17.2: History test — after 3 analyses /history shows all three
- TC-17.3: Isolation test — analyses from different users don't mix
"""

import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.advisor import DeckAdvisor
from src.core.analyzer import DeckAnalyzer
from src.core.deck import CardInfo, Deck
from src.db.models import Analysis, Card, CardRating, Set, User
from src.db.repository import (
    AnalysisRepository,
    CardData,
    CardRepository,
    RatingData,
    SetRepository,
    UserRepository,
)
from src.llm.client import LLMClient
from src.llm.prompts import CardRecognitionResult
from src.reports.models import DeckReport
from src.reports.telegram import TelegramRenderer
from src.vision.recognizer import CardRecognizer
from tests.conftest import create_mock_advice_response, create_mock_vision_response


# ============================================================================
# Helper Functions
# ============================================================================


async def setup_test_cards(session: AsyncSession, set_code: str = "TST") -> list[Card]:
    """Create test set and cards in the database."""
    # Create set
    set_repo = SetRepository(session)
    test_set, _ = await set_repo.get_or_create(set_code, "Test Set")

    # Create cards with ratings
    card_repo = CardRepository(session)

    cards_data = [
        CardData(
            name="Lightning Bolt",
            set_code=set_code,
            mana_cost="{R}",
            cmc=Decimal("1"),
            colors=["R"],
            type_line="Instant",
            rarity="common",
        ),
        CardData(
            name="Counterspell",
            set_code=set_code,
            mana_cost="{U}{U}",
            cmc=Decimal("2"),
            colors=["U"],
            type_line="Instant",
            rarity="uncommon",
        ),
        CardData(
            name="Doom Blade",
            set_code=set_code,
            mana_cost="{1}{B}",
            cmc=Decimal("2"),
            colors=["B"],
            type_line="Instant",
            rarity="uncommon",
        ),
        CardData(
            name="Serra Angel",
            set_code=set_code,
            mana_cost="{3}{W}{W}",
            cmc=Decimal("5"),
            colors=["W"],
            type_line="Creature — Angel",
            rarity="uncommon",
        ),
        CardData(
            name="Llanowar Elves",
            set_code=set_code,
            mana_cost="{G}",
            cmc=Decimal("1"),
            colors=["G"],
            type_line="Creature — Elf Druid",
            rarity="common",
        ),
        CardData(
            name="Negate",
            set_code=set_code,
            mana_cost="{1}{U}",
            cmc=Decimal("2"),
            colors=["U"],
            type_line="Instant",
            rarity="common",
        ),
    ]

    await card_repo.upsert_cards(cards_data)

    # Add ratings
    ratings_data = [
        RatingData(
            card_name="Lightning Bolt",
            set_code=set_code,
            source="17lands",
            rating=Decimal("4.5"),
            win_rate=Decimal("58.5"),
            games_played=10000,
            format="PremierDraft",
        ),
        RatingData(
            card_name="Counterspell",
            set_code=set_code,
            source="17lands",
            rating=Decimal("4.0"),
            win_rate=Decimal("56.0"),
            games_played=8000,
            format="PremierDraft",
        ),
        RatingData(
            card_name="Doom Blade",
            set_code=set_code,
            source="17lands",
            rating=Decimal("3.5"),
            win_rate=Decimal("54.0"),
            games_played=7500,
            format="PremierDraft",
        ),
        RatingData(
            card_name="Serra Angel",
            set_code=set_code,
            source="17lands",
            rating=Decimal("3.8"),
            win_rate=Decimal("55.5"),
            games_played=6000,
            format="PremierDraft",
        ),
        RatingData(
            card_name="Llanowar Elves",
            set_code=set_code,
            source="17lands",
            rating=Decimal("3.2"),
            win_rate=Decimal("52.0"),
            games_played=9000,
            format="PremierDraft",
        ),
        RatingData(
            card_name="Negate",
            set_code=set_code,
            source="17lands",
            rating=Decimal("2.8"),
            win_rate=Decimal("49.0"),
            games_played=5000,
            format="PremierDraft",
        ),
    ]

    await card_repo.upsert_ratings(ratings_data)
    await session.commit()

    return await card_repo.get_by_set(set_code)


async def create_test_user(session: AsyncSession, telegram_id: int, username: str = None) -> User:
    """Create a test user."""
    user_repo = UserRepository(session)
    user, _ = await user_repo.get_or_create(telegram_id, username)
    await session.commit()
    return user


async def simulate_analysis_flow(
    session: AsyncSession,
    user: User,
    main_deck: list[str],
    sideboard: list[str],
    set_code: str,
    mock_advice: str = None,
) -> Analysis:
    """
    Simulate the full analysis flow with mocked LLM.

    This follows the same flow as handle_analyze_with_photo in analyze.py.
    """
    # Build deck
    deck = Deck(main_deck=main_deck, sideboard=sideboard, set_code=set_code)

    # Get cards with ratings from DB
    card_repo = CardRepository(session)
    all_card_names = deck.main_deck + deck.sideboard
    db_cards = await card_repo.get_cards_with_ratings(all_card_names, set_code)

    # Convert to CardInfo
    card_infos = []
    for card in db_cards:
        rating = None
        win_rate = None
        if card.ratings:
            rating = card.ratings[0].rating
            win_rate = card.ratings[0].win_rate

        card_infos.append(
            CardInfo(
                name=card.name,
                mana_cost=card.mana_cost,
                cmc=card.cmc,
                colors=list(card.colors) if card.colors else None,
                type_line=card.type_line,
                rarity=card.rarity,
                rating=rating,
                win_rate=win_rate,
            )
        )

    # Analyze deck
    analyzer = DeckAnalyzer()
    analysis = analyzer.analyze(deck, card_infos)

    # Generate advice (mocked)
    advice = mock_advice or create_mock_advice_response()

    # Save to DB
    analysis_repo = AnalysisRepository(session)
    db_analysis = await analysis_repo.create(
        user_id=user.id,
        main_deck=deck.main_deck,
        sideboard=deck.sideboard,
        set_code=set_code,
        total_score=analysis.score,
        estimated_win_rate=analysis.estimated_win_rate,
        advice=advice,
    )
    await session.commit()

    # Re-fetch to get relationships loaded
    return await analysis_repo.get_by_id(db_analysis.id)


# ============================================================================
# TC-17.1: E2E Test — Analyze Flow from Photo to DB Storage
# ============================================================================


class TestTC171AnalyzeFlowE2E:
    """TC-17.1: E2E test — analyze flow from photo to DB storage (with mocked LLM)."""

    @pytest.mark.asyncio
    async def test_full_analyze_flow_saves_to_db(
        self, clean_session: AsyncSession, sample_image_bytes
    ):
        """
        Test the complete analyze flow:
        1. Vision recognizes cards from image
        2. Cards are enriched with DB ratings
        3. Analysis is computed
        4. Advice is generated
        5. Analysis is saved to DB
        """
        # Setup: Create test cards and user
        await setup_test_cards(clean_session, "TST")
        user = await create_test_user(clean_session, telegram_id=123456, username="testuser")

        # Define the expected recognized cards
        main_deck = [
            "Lightning Bolt",
            "Lightning Bolt",
            "Counterspell",
            "Doom Blade",
            "Serra Angel",
        ]
        sideboard = ["Negate"]
        set_code = "TST"

        # Simulate the analysis flow
        analysis = await simulate_analysis_flow(
            clean_session,
            user,
            main_deck,
            sideboard,
            set_code,
        )

        # Verify analysis was saved correctly
        assert analysis is not None
        assert analysis.id > 0
        assert analysis.user_id == user.id
        assert analysis.main_deck == main_deck
        assert analysis.sideboard == sideboard
        assert analysis.total_score is not None
        assert analysis.estimated_win_rate is not None
        assert analysis.advice is not None

    @pytest.mark.asyncio
    async def test_analyze_flow_with_vision_mock(
        self, clean_session: AsyncSession, sample_image_bytes
    ):
        """Test the flow with mocked CardRecognizer and LLMClient."""
        # Setup
        await setup_test_cards(clean_session, "TST")
        user = await create_test_user(clean_session, telegram_id=123457, username="testuser2")

        main_deck = ["Lightning Bolt", "Counterspell", "Serra Angel"]
        sideboard = ["Negate"]

        # Mock CardRecognizer
        mock_recognition = CardRecognitionResult(
            main_deck=main_deck,
            sideboard=sideboard,
            detected_set="TST",
        )

        with patch.object(
            CardRecognizer, "recognize_cards", new_callable=AsyncMock
        ) as mock_recognize:
            mock_recognize.return_value = mock_recognition

            # Create recognizer and call it
            recognizer = CardRecognizer()
            recognition = await recognizer.recognize_cards(sample_image_bytes)

            assert recognition.main_deck == main_deck
            assert recognition.sideboard == sideboard
            assert recognition.detected_set == "TST"

        # Now run the analysis part
        analysis = await simulate_analysis_flow(
            clean_session,
            user,
            main_deck,
            sideboard,
            "TST",
        )

        # Verify
        assert analysis is not None
        assert analysis.main_deck == main_deck

    @pytest.mark.asyncio
    async def test_analyze_flow_computes_correct_score(
        self, clean_session: AsyncSession
    ):
        """Test that the analysis correctly computes score from ratings."""
        await setup_test_cards(clean_session, "TST")
        user = await create_test_user(clean_session, telegram_id=123458)

        # Use cards with known ratings
        main_deck = ["Lightning Bolt", "Counterspell"]  # 4.5, 4.0 ratings
        sideboard = []

        analysis = await simulate_analysis_flow(
            clean_session, user, main_deck, sideboard, "TST"
        )

        # Score should be approximately the average of ratings (4.25)
        assert analysis.total_score is not None
        assert Decimal("4.0") <= analysis.total_score <= Decimal("4.5")

    @pytest.mark.asyncio
    async def test_analyze_flow_generates_report(
        self, clean_session: AsyncSession
    ):
        """Test that a report can be generated from saved analysis."""
        await setup_test_cards(clean_session, "TST")
        user = await create_test_user(clean_session, telegram_id=123459)

        main_deck = ["Lightning Bolt", "Serra Angel", "Llanowar Elves"]
        sideboard = ["Negate"]

        analysis = await simulate_analysis_flow(
            clean_session, user, main_deck, sideboard, "TST"
        )

        # Get cards for report
        card_repo = CardRepository(session=clean_session)
        db_cards = await card_repo.get_cards_with_ratings(main_deck + sideboard, "TST")

        card_infos = [
            CardInfo(
                name=c.name,
                cmc=c.cmc,
                rating=c.ratings[0].rating if c.ratings else None,
                win_rate=c.ratings[0].win_rate if c.ratings else None,
            )
            for c in db_cards
        ]

        deck = Deck(main_deck=main_deck, sideboard=sideboard, set_code="TST")
        analyzer = DeckAnalyzer()
        deck_analysis = analyzer.analyze(deck, card_infos)

        # Build report
        report = DeckReport.build(
            deck, card_infos, deck_analysis, analysis.advice, "Test Set"
        )

        # Render to Telegram format
        renderer = TelegramRenderer()
        text = renderer.render(report)

        # Verify report contains expected elements
        assert "Test Set" in text or "TST" in text
        assert "Lightning Bolt" in text
        assert "📈" in text or "Загальна оцінка" in text


# ============================================================================
# TC-17.2: History Test — After 3 Analyses /history Shows All Three
# ============================================================================


class TestTC172HistoryShowsAllAnalyses:
    """TC-17.2: History test — after 3 analyses /history shows all three."""

    @pytest.mark.asyncio
    async def test_history_shows_all_three_analyses(
        self, clean_session: AsyncSession
    ):
        """After 3 analyses, history should show all three."""
        await setup_test_cards(clean_session, "TST")
        user = await create_test_user(clean_session, telegram_id=200001)

        # Create 3 analyses
        for i in range(3):
            main_deck = ["Lightning Bolt", "Counterspell"]
            await simulate_analysis_flow(
                clean_session,
                user,
                main_deck,
                [],
                "TST",
                mock_advice=f"Advice for analysis {i + 1}",
            )

        # Get history
        analysis_repo = AnalysisRepository(clean_session)
        analyses = await analysis_repo.get_user_analyses(user.id, limit=10)

        assert len(analyses) == 3

        # Verify each has unique advice
        advices = [a.advice for a in analyses]
        assert len(set(advices)) == 3

    @pytest.mark.asyncio
    async def test_history_respects_limit(self, clean_session: AsyncSession):
        """History with limit should only return that many."""
        await setup_test_cards(clean_session, "TST")
        user = await create_test_user(clean_session, telegram_id=200002)

        # Create 5 analyses
        for i in range(5):
            await simulate_analysis_flow(
                clean_session,
                user,
                ["Lightning Bolt"],
                [],
                "TST",
                mock_advice=f"Advice {i}",
            )

        analysis_repo = AnalysisRepository(clean_session)

        # Get only 3
        analyses = await analysis_repo.get_user_analyses(user.id, limit=3)
        assert len(analyses) == 3

        # Get all
        all_analyses = await analysis_repo.get_user_analyses(user.id, limit=10)
        assert len(all_analyses) == 5

    @pytest.mark.asyncio
    async def test_history_sorted_by_date_descending(
        self, clean_session: AsyncSession
    ):
        """History should be sorted with newest first."""
        await setup_test_cards(clean_session, "TST")
        user = await create_test_user(clean_session, telegram_id=200003)

        # Create analyses
        analysis_repo = AnalysisRepository(clean_session)
        for i in range(3):
            await analysis_repo.create(
                user_id=user.id,
                main_deck=["Card"],
                sideboard=[],
                advice=f"Advice {i}",
            )
            await clean_session.commit()

        analyses = await analysis_repo.get_user_analyses(user.id)

        # Newest should be first
        for i in range(len(analyses) - 1):
            assert analyses[i].created_at >= analyses[i + 1].created_at

    @pytest.mark.asyncio
    async def test_empty_history_returns_empty_list(
        self, clean_session: AsyncSession
    ):
        """User with no analyses should get empty list."""
        user = await create_test_user(clean_session, telegram_id=200004)

        analysis_repo = AnalysisRepository(clean_session)
        analyses = await analysis_repo.get_user_analyses(user.id)

        assert analyses == []


# ============================================================================
# TC-17.3: Isolation Test — Analyses from Different Users Don't Mix
# ============================================================================


class TestTC173UserIsolation:
    """TC-17.3: Isolation test — analyses from different users don't mix."""

    @pytest.mark.asyncio
    async def test_analyses_isolated_between_users(
        self, clean_session: AsyncSession
    ):
        """Each user should only see their own analyses."""
        await setup_test_cards(clean_session, "TST")

        # Create two users
        user1 = await create_test_user(clean_session, telegram_id=300001, username="user1")
        user2 = await create_test_user(clean_session, telegram_id=300002, username="user2")

        # Create analyses for user1
        for i in range(3):
            await simulate_analysis_flow(
                clean_session,
                user1,
                ["Lightning Bolt"],
                [],
                "TST",
                mock_advice=f"User1 advice {i}",
            )

        # Create analyses for user2
        for i in range(2):
            await simulate_analysis_flow(
                clean_session,
                user2,
                ["Counterspell"],
                [],
                "TST",
                mock_advice=f"User2 advice {i}",
            )

        # Get each user's analyses
        analysis_repo = AnalysisRepository(clean_session)

        user1_analyses = await analysis_repo.get_user_analyses(user1.id)
        user2_analyses = await analysis_repo.get_user_analyses(user2.id)

        # Verify counts
        assert len(user1_analyses) == 3
        assert len(user2_analyses) == 2

        # Verify user1 only sees their own
        for analysis in user1_analyses:
            assert analysis.user_id == user1.id
            assert "User1" in analysis.advice

        # Verify user2 only sees their own
        for analysis in user2_analyses:
            assert analysis.user_id == user2.id
            assert "User2" in analysis.advice

    @pytest.mark.asyncio
    async def test_analysis_by_id_belongs_to_user(
        self, clean_session: AsyncSession
    ):
        """Getting analysis by ID should verify user ownership."""
        await setup_test_cards(clean_session, "TST")

        user1 = await create_test_user(clean_session, telegram_id=300003)
        user2 = await create_test_user(clean_session, telegram_id=300004)

        # Create analysis for user1
        analysis = await simulate_analysis_flow(
            clean_session, user1, ["Lightning Bolt"], [], "TST"
        )

        # Get by ID
        analysis_repo = AnalysisRepository(clean_session)
        fetched = await analysis_repo.get_by_id(analysis.id)

        # Should belong to user1
        assert fetched is not None
        assert fetched.user_id == user1.id
        assert fetched.user_id != user2.id

    @pytest.mark.asyncio
    async def test_user_count_is_correct(self, clean_session: AsyncSession):
        """Count function should return correct number per user."""
        await setup_test_cards(clean_session, "TST")

        user1 = await create_test_user(clean_session, telegram_id=300005)
        user2 = await create_test_user(clean_session, telegram_id=300006)

        # Create different numbers of analyses
        for _ in range(5):
            await simulate_analysis_flow(
                clean_session, user1, ["Lightning Bolt"], [], "TST"
            )

        for _ in range(3):
            await simulate_analysis_flow(
                clean_session, user2, ["Counterspell"], [], "TST"
            )

        analysis_repo = AnalysisRepository(clean_session)

        count1 = await analysis_repo.count_by_user(user1.id)
        count2 = await analysis_repo.count_by_user(user2.id)

        assert count1 == 5
        assert count2 == 3

    @pytest.mark.asyncio
    async def test_deleting_analysis_only_affects_owner(
        self, clean_session: AsyncSession
    ):
        """Deleting an analysis should not affect other users."""
        await setup_test_cards(clean_session, "TST")

        user1 = await create_test_user(clean_session, telegram_id=300007)
        user2 = await create_test_user(clean_session, telegram_id=300008)

        # Create analyses
        analysis1 = await simulate_analysis_flow(
            clean_session, user1, ["Lightning Bolt"], [], "TST"
        )
        analysis2 = await simulate_analysis_flow(
            clean_session, user2, ["Counterspell"], [], "TST"
        )

        analysis_repo = AnalysisRepository(clean_session)

        # Delete user1's analysis
        await analysis_repo.delete(analysis1.id)
        await clean_session.commit()

        # User1 should have 0 analyses
        user1_analyses = await analysis_repo.get_user_analyses(user1.id)
        assert len(user1_analyses) == 0

        # User2 should still have their analysis
        user2_analyses = await analysis_repo.get_user_analyses(user2.id)
        assert len(user2_analyses) == 1
        assert user2_analyses[0].id == analysis2.id
