"""
Integration tests for photo-based deck analysis.

Tests the full pipeline:
  photo → CardRecognizer → fuzzy matching → DB enrichment → analysis → report

Place test photos in tests/fixtures/:
  - ecl_deck.jpg — photo of an ECL draft deck

To run with real LLM calls (requires OPENAI_API_KEY in env):
  pytest tests/integration/test_photo_analysis.py -k real_llm -s
"""

import os
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.analyzer import DeckAnalyzer
from src.core.deck import CardInfo, Deck
from src.core.lands import recommend_lands
from src.db.models import Card
from src.db.repository import (
    CardData,
    CardRepository,
    RatingData,
    SetRepository,
)
from src.parsers.scryfall import ScryfallParser
from src.parsers.seventeen_lands import SeventeenLandsParser
from src.reports.models import DeckReport, UNRATED_GRADES
from src.reports.telegram import TelegramRenderer
from src.vision.card_matcher import fuzzy_match_cards
from src.vision.recognizer import CardRecognizer

# Path to test fixtures
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"

# Realistic ECL card names that GPT-4o Vision might return from a deck photo.
MOCK_ECL_MAIN_DECK = [
    "Boggart Sprite-Chaser",
    "Boggart Sprite-Chaser",
    "Cinder Strike",
    "Cinder Strike",
    "Elder Auntie",
    "Feed the Flames",
    "Goblin Chieftain",
    "Goblin Chieftain",
    "Impulsive Entrance",
    "Rooftop Percher",
    "Rooftop Percher",
    "Rooftop Percher",
    "Changeling Shapeshifter",
    "Down's Light Archer",
    "Dream Seizure",
    "Dream Seizure",
    "Gathering Stone",
    "Blight Rot",
    "Blight Rot",
    "Lightning Bolt",
    "Lightning Bolt",
    "Lightning Bolt",
    "Adept Watershaper",
]

MOCK_ECL_SIDEBOARD = [
    "Appeal to Eirdu",
    "Changeling Wayfinder",
]

# Representative ECL cards with metadata and ratings for the test DB.
_ECL_TEST_CARDS = [
    ("Boggart Sprite-Chaser", "{1}{R}", Decimal("2"), ["R"], "Creature — Goblin", "common", Decimal("2.5"), Decimal("53.10"), 80000),
    ("Cinder Strike", "{2}{R}", Decimal("3"), ["R"], "Instant", "common", Decimal("2.0"), Decimal("51.40"), 70000),
    ("Elder Auntie", "{2}{B}{R}", Decimal("4"), ["B", "R"], "Creature — Goblin Shaman", "rare", Decimal("2.0"), Decimal("51.93"), 86184),
    ("Feed the Flames", "{1}{R}", Decimal("2"), ["R"], "Instant", "uncommon", Decimal("3.0"), Decimal("55.80"), 40000),
    ("Goblin Chieftain", "{1}{R}{R}", Decimal("3"), ["R"], "Creature — Goblin", "rare", Decimal("3.5"), Decimal("57.20"), 30000),
    ("Impulsive Entrance", "{R}", Decimal("1"), ["R"], "Sorcery", "common", Decimal("1.5"), Decimal("49.50"), 60000),
    ("Rooftop Percher", "{1}{B}", Decimal("2"), ["B"], "Creature — Faerie Rogue", "common", Decimal("3.0"), Decimal("55.19"), 99690),
    ("Changeling Shapeshifter", "{2}{U}", Decimal("3"), ["U"], "Creature — Shapeshifter", "uncommon", Decimal("2.5"), Decimal("53.00"), 50000),
    ("Down's Light Archer", "{1}{G}", Decimal("2"), ["G"], "Creature — Elf Archer", "common", Decimal("2.5"), Decimal("54.10"), 75000),
    ("Dream Seizure", "{1}{B}", Decimal("2"), ["B"], "Sorcery", "common", Decimal("1.5"), Decimal("50.20"), 45000),
    ("Gathering Stone", "{3}", Decimal("3"), [], "Artifact", "uncommon", Decimal("2.0"), Decimal("51.00"), 35000),
    ("Blight Rot", "{B}", Decimal("1"), ["B"], "Enchantment", "common", Decimal("1.5"), Decimal("49.80"), 55000),
    ("Lightning Bolt", "{R}", Decimal("1"), ["R"], "Instant", "common", Decimal("4.5"), Decimal("60.50"), 120000),
    ("Adept Watershaper", "{1}{W}", Decimal("2"), ["W"], "Creature — Merfolk Wizard", "rare", Decimal("4.0"), Decimal("58.25"), 30779),
    ("Appeal to Eirdu", "{W}", Decimal("1"), ["W"], "Instant", "common", Decimal("1.5"), Decimal("50.36"), 19468),
    ("Changeling Wayfinder", "{1}{G}", Decimal("2"), ["G"], "Creature — Shapeshifter", "common", Decimal("2.5"), Decimal("53.77"), 164075),
]



def _load_photo(filename: str) -> bytes:
    """Load a test photo from the fixtures directory."""
    photo_path = FIXTURES_DIR / filename
    if not photo_path.exists():
        pytest.skip(
            f"Test photo not found: {photo_path}. "
            f"Place a deck photo at {photo_path} to run this test."
        )
    return photo_path.read_bytes()


def _card_to_card_info(card: Card) -> CardInfo:
    """Convert a DB Card model to a CardInfo (same logic as analyze.py)."""
    rating = None
    win_rate = None
    games_played = None

    if card.ratings:
        best = card.ratings[0]
        rating = best.rating
        win_rate = best.win_rate
        games_played = best.games_played

    return CardInfo(
        name=card.name,
        mana_cost=card.mana_cost,
        cmc=card.cmc,
        colors=list(card.colors) if card.colors else None,
        type_line=card.type_line,
        rarity=card.rarity,
        image_uri=card.image_uri,
        rating=rating,
        win_rate=win_rate,
        games_played=games_played,
    )


async def _seed_ecl_data(
    session: AsyncSession,
    card_lists: list[list[tuple]] | None = None,
) -> None:
    """
    Seed the test database with ECL set, cards, and ratings.

    Args:
        session: DB session.
        card_lists: Card data lists to seed. Defaults to [_ECL_TEST_CARDS].
            Each list contains tuples of:
            (name, mana_cost, cmc, colors, type_line, rarity, rating, win_rate, games_played)
    """
    if card_lists is None:
        card_lists = [_ECL_TEST_CARDS]

    set_repo = SetRepository(session)
    await set_repo.get_or_create("ECL", "Lorwyn: Eclipsed")

    card_repo = CardRepository(session)

    all_cards_data: list[tuple] = []
    for card_list in card_lists:
        all_cards_data.extend(card_list)

    cards = [
        CardData(
            name=name,
            set_code="ECL",
            mana_cost=mana_cost,
            cmc=cmc,
            colors=colors,
            type_line=type_line,
            rarity=rarity,
        )
        for name, mana_cost, cmc, colors, type_line, rarity, _rating, _wr, _gp in all_cards_data
    ]
    await card_repo.upsert_cards(cards)

    ratings = [
        RatingData(
            card_name=name,
            set_code="ECL",
            source="17lands",
            rating=rating,
            win_rate=win_rate,
            games_played=games_played,
            format="PremierDraft",
        )
        for name, _mc, _cmc, _colors, _tl, _rarity, rating, win_rate, games_played in all_cards_data
        if rating is not None  # skip cards without ratings (e.g. mythics with no data)
    ]
    await card_repo.upsert_ratings(ratings)
    await session.commit()


async def _seed_from_apis(session: AsyncSession, set_code: str) -> str:
    """
    Seed the test database with real card data from Scryfall and 17lands.

    Fetches set info, all cards, and ratings — no manual fixture data needed.
    Mirrors the logic in scripts/add_set.py.

    Args:
        session: DB session.
        set_code: MTG set code to fetch (e.g. "LRW", "MKM").

    Returns:
        Set name as returned by Scryfall.

    Raises:
        pytest.skip: If set not found on Scryfall.
    """
    scryfall = ScryfallParser()
    seventeen = SeventeenLandsParser()

    try:
        set_info = await scryfall.fetch_set_info(set_code)
        if set_info is None:
            pytest.skip(f"Set '{set_code}' not found on Scryfall — check E2E_SET_CODE")

        set_repo = SetRepository(session)
        await set_repo.get_or_create(set_info.code, set_info.name)

        cards = await scryfall.fetch_set_cards(set_code)
        card_repo = CardRepository(session)
        repo_cards = [
            CardData(
                name=c.name,
                set_code=set_code,
                scryfall_id=c.scryfall_id,
                mana_cost=c.mana_cost,
                cmc=c.cmc,
                colors=c.colors,
                type_line=c.type_line,
                rarity=c.rarity,
                image_uri=c.image_uri,
            )
            for c in cards
        ]
        await card_repo.upsert_cards(repo_cards)
        print(f"  Scryfall: {len(repo_cards)} cards seeded for '{set_code}'")

        try:
            ratings = await seventeen.fetch_ratings(set_code)
            if ratings:
                repo_ratings = [
                    RatingData(
                        card_name=r.card_name,
                        set_code=set_code,
                        source=r.source,
                        rating=r.rating,
                        win_rate=r.win_rate,
                        games_played=r.games_played,
                        format=r.format,
                    )
                    for r in ratings
                ]
                await card_repo.upsert_ratings(repo_ratings)
                print(f"  17lands: {len(repo_ratings)} ratings seeded for '{set_code}'")
            else:
                print(f"  17lands: no ratings available for '{set_code}' (set may be too new)")
        except Exception as exc:
            print(f"  17lands: skipped — {exc}")

        await session.commit()
        return set_info.name

    finally:
        await scryfall.close()
        await seventeen.close()


async def run_analysis_pipeline(
    session: AsyncSession,
    main_deck: list[str],
    sideboard: list[str],
    set_code: str,
) -> tuple[DeckReport, str]:
    """
    Run the full analysis pipeline (matching the flow in analyze.py).

    Returns:
        Tuple of (DeckReport, rendered_text).
    """
    card_repo = CardRepository(session)
    known_cards = await card_repo.get_card_names_by_set(set_code)

    if known_cards:
        main_result = fuzzy_match_cards(main_deck, known_cards)
        main_deck = main_result.matched

        sb_result = fuzzy_match_cards(sideboard, known_cards)
        sideboard = sb_result.matched

    deck = Deck(main_deck=main_deck, sideboard=sideboard, set_code=set_code)

    all_card_names = deck.main_deck + deck.sideboard
    db_cards = await card_repo.get_cards_with_ratings(all_card_names, set_code)
    card_infos = [_card_to_card_info(c) for c in db_cards]

    analyzer = DeckAnalyzer()
    analysis = analyzer.analyze(deck, card_infos)

    set_repo = SetRepository(session)
    db_set = await set_repo.get_by_code(set_code)
    set_name = db_set.name if db_set else None

    main_deck_names = set(deck.main_deck)
    non_land_infos = [
        c for c in card_infos
        if c.name not in {"Plains", "Island", "Swamp", "Mountain", "Forest"}
        and c.name in main_deck_names
    ]
    land_rec = recommend_lands(non_land_infos)

    report = DeckReport.build(
        deck, card_infos, analysis,
        set_name=set_name,
        land_recommendation=land_rec,
    )
    renderer = TelegramRenderer()
    text = renderer.render(report)

    return report, text


# ============================================================================
# Tests with mocked LLM (always runnable — seeds its own DB data)
# ============================================================================


class TestPhotoAnalysisMocked:
    """Tests using mocked LLM vision response with realistic ECL cards."""

    @pytest.mark.asyncio
    async def test_full_pipeline_with_mock_vision(self, clean_session: AsyncSession):
        """
        Full pipeline from mock vision response to rendered report.

        Verifies cards are fuzzy-matched, enriched, and graded.
        """
        await _seed_ecl_data(clean_session)

        report, text = await run_analysis_pipeline(
            clean_session,
            list(MOCK_ECL_MAIN_DECK),
            list(MOCK_ECL_SIDEBOARD),
            "ECL",
        )

        assert len(report.main_deck_cards) > 0
        assert report.analysis is not None
        assert report.analysis.score > Decimal("0")
        assert report.analysis.estimated_win_rate > Decimal("0")

    @pytest.mark.asyncio
    async def test_cards_have_grades_and_win_rates(self, clean_session: AsyncSession):
        """Cards with win_rate must get proper grades (not '?')."""
        await _seed_ecl_data(clean_session)

        report, _ = await run_analysis_pipeline(
            clean_session,
            list(MOCK_ECL_MAIN_DECK),
            list(MOCK_ECL_SIDEBOARD),
            "ECL",
        )

        graded = [c for c in report.main_deck_cards if c.grade not in UNRATED_GRADES]
        assert len(graded) > 0, "No cards received grades"

        for card in report.main_deck_cards:
            if card.win_rate is not None:
                assert card.grade not in UNRATED_GRADES, (
                    f"{card.name} has win_rate={card.win_rate} but grade='{card.grade}'"
                )

    @pytest.mark.asyncio
    async def test_win_rate_shown_in_report(self, clean_session: AsyncSession):
        """win_rate must appear in rendered text for every rated card."""
        await _seed_ecl_data(clean_session)

        report, text = await run_analysis_pipeline(
            clean_session,
            list(MOCK_ECL_MAIN_DECK),
            list(MOCK_ECL_SIDEBOARD),
            "ECL",
        )

        for card in report.main_deck_cards:
            if card.win_rate is not None:
                wr_str = f"{card.win_rate:.1f}%"
                assert wr_str in text, (
                    f"{card.name} win_rate={card.win_rate} not found in report"
                )

    @pytest.mark.asyncio
    async def test_no_bez_danyh_for_rated_cards(self, clean_session: AsyncSession):
        """Cards with ratings must NOT show 'без даних'."""
        await _seed_ecl_data(clean_session)

        report, text = await run_analysis_pipeline(
            clean_session,
            list(MOCK_ECL_MAIN_DECK),
            list(MOCK_ECL_SIDEBOARD),
            "ECL",
        )

        # All our test cards have ratings — none should be unrated
        assert len(report.unrated_cards) == 0, (
            f"Unrated cards: {[c.name for c in report.unrated_cards]}"
        )

    @pytest.mark.asyncio
    async def test_report_contains_set_name(self, clean_session: AsyncSession):
        """Report should display the set name."""
        await _seed_ecl_data(clean_session)

        report, text = await run_analysis_pipeline(
            clean_session,
            list(MOCK_ECL_MAIN_DECK),
            list(MOCK_ECL_SIDEBOARD),
            "ECL",
        )

        assert report.set_name == "Lorwyn: Eclipsed"
        assert "Lorwyn: Eclipsed" in text

    @pytest.mark.asyncio
    async def test_mana_curve_not_all_zeros(self, clean_session: AsyncSession):
        """Mana curve should reflect actual card CMC distribution."""
        await _seed_ecl_data(clean_session)

        report, _ = await run_analysis_pipeline(
            clean_session,
            list(MOCK_ECL_MAIN_DECK),
            list(MOCK_ECL_SIDEBOARD),
            "ECL",
        )

        assert report.analysis is not None
        curve = report.analysis.mana_curve
        non_zero = sum(1 for cmc, cnt in curve.items() if cmc > 0 and cnt > 0)
        assert non_zero > 0, "Mana curve has no non-zero entries above CMC 0"

    @pytest.mark.asyncio
    async def test_color_distribution_not_all_colorless(self, clean_session: AsyncSession):
        """Color distribution should reflect actual card colors."""
        await _seed_ecl_data(clean_session)

        report, _ = await run_analysis_pipeline(
            clean_session,
            list(MOCK_ECL_MAIN_DECK),
            list(MOCK_ECL_SIDEBOARD),
            "ECL",
        )

        assert report.analysis is not None
        dist = report.analysis.color_distribution
        non_colorless = {c: p for c, p in dist.items() if c != "C" and p > 0}
        assert len(non_colorless) > 0, "All cards are colorless — enrichment failed"
        assert "R" in non_colorless, "Red should be present in this deck"

    @pytest.mark.asyncio
    async def test_fuzzy_matching_corrects_misspellings(self, clean_session: AsyncSession):
        """Fuzzy matching should correct minor OCR-like errors."""
        await _seed_ecl_data(clean_session)

        misspelled_deck = [
            "Boggart Sprite Chaser",   # missing hyphen
            "Lightning Bolt",          # correct
            "Changeling Shapeshiftr",  # truncated
        ]

        card_repo = CardRepository(clean_session)
        known_cards = await card_repo.get_card_names_by_set("ECL")

        result = fuzzy_match_cards(misspelled_deck, known_cards)

        assert "Boggart Sprite-Chaser" in result.matched
        assert "Lightning Bolt" in result.matched
        assert "Changeling Shapeshifter" in result.matched

    @pytest.mark.asyncio
    async def test_recognizer_passes_known_cards_to_prompt(self, clean_session: AsyncSession):
        """CardRecognizer should inject known_cards into the LLM prompt."""
        await _seed_ecl_data(clean_session)

        card_repo = CardRepository(clean_session)
        known_cards = await card_repo.get_card_names_by_set("ECL")

        mock_llm = AsyncMock()
        mock_llm.call_vision = AsyncMock(return_value={
            "main_deck": MOCK_ECL_MAIN_DECK[:5],
            "sideboard": [],
            "detected_set": "ECL",
            "layout_detected": "physical_cards",
            "lands_visible": False,
        })

        recognizer = CardRecognizer(llm_client=mock_llm)
        result = await recognizer.recognize_cards(
            b"fake_image_bytes",
            set_hint="ECL",
            known_cards=known_cards,
        )

        call_args = mock_llm.call_vision.call_args
        prompt = call_args[0][1]
        assert "CARD NAME REFERENCE LIST" in prompt
        assert "Lightning Bolt" in prompt
        assert len(result.main_deck) == 5

    @pytest.mark.asyncio
    async def test_grade_calculation_from_win_rate(self, clean_session: AsyncSession):
        """Verify grade mapping: high WR → high grade, low WR → low grade."""
        await _seed_ecl_data(clean_session)

        report, _ = await run_analysis_pipeline(
            clean_session,
            list(MOCK_ECL_MAIN_DECK),
            list(MOCK_ECL_SIDEBOARD),
            "ECL",
        )

        card_by_name = {c.name: c for c in report.main_deck_cards}

        # Lightning Bolt: 60.50% WR → A grade
        bolt = card_by_name.get("Lightning Bolt")
        assert bolt is not None
        assert bolt.grade in ("A+", "A"), f"Lightning Bolt grade={bolt.grade}"

        # Impulsive Entrance: 49.50% WR → C grade
        entrance = card_by_name.get("Impulsive Entrance")
        assert entrance is not None
        assert entrance.grade in ("C", "C-"), f"Impulsive Entrance grade={entrance.grade}"


# ============================================================================
# Tests with real photo from disk
# ============================================================================


class TestPhotoFromDisk:
    """Tests that load a real photo from tests/fixtures/ and run the pipeline."""

    @pytest.mark.asyncio
    async def test_photo_loads_and_pipeline_runs(self, clean_session: AsyncSession):
        """
        Load ecl_deck.jpg and run full pipeline with mocked vision.

        Place your deck photo at: tests/fixtures/ecl_deck.jpg
        """
        image_bytes = _load_photo("ecl_deck.jpg")
        assert len(image_bytes) > 100, "Photo file seems too small"

        await _seed_ecl_data(clean_session)

        mock_llm = AsyncMock()
        mock_llm.call_vision = AsyncMock(return_value={
            "main_deck": MOCK_ECL_MAIN_DECK,
            "sideboard": MOCK_ECL_SIDEBOARD,
            "detected_set": "ECL",
            "layout_detected": "physical_cards",
            "lands_visible": False,
        })

        recognizer = CardRecognizer(llm_client=mock_llm)
        recognition = await recognizer.recognize_cards(
            image_bytes, set_hint="ECL",
        )

        report, text = await run_analysis_pipeline(
            clean_session,
            recognition.main_deck,
            recognition.sideboard,
            "ECL",
        )

        assert len(report.main_deck_cards) > 0
        assert len(report.unrated_cards) == 0

    @pytest.mark.asyncio
    async def test_e2e_real_llm_full_validation(self, clean_session: AsyncSession):
        """
        E2E test: real LLM vision recognition + real Scryfall + real 17lands data.

        No manual fixture data — card metadata and ratings are fetched from
        Scryfall and 17lands APIs at test runtime.

        Requires:
          - OPENAI_API_KEY in .env
          - E2E_SET_CODE in .env or environment (e.g. E2E_SET_CODE=LRW)
          - Photo at tests/fixtures/ecl_deck.jpg showing cards from that set

        Run with:
          E2E_SET_CODE=LRW pytest tests/integration/test_photo_analysis.py -k real_llm -s
        """
        import sys
        from dotenv import dotenv_values
        from src.llm.client import LLMClient

        # --- Skip conditions ---
        env_path = Path(__file__).parent.parent.parent / ".env"
        env = dotenv_values(env_path)

        api_key = env.get("OPENAI_API_KEY", "")
        if not api_key or api_key.startswith("sk-test"):
            pytest.skip(f"Real OPENAI_API_KEY not found in {env_path}")

        set_code = (env.get("E2E_SET_CODE") or os.environ.get("E2E_SET_CODE", "")).upper()
        if not set_code:
            pytest.skip("Set E2E_SET_CODE=<set_code> in .env or environment (e.g. E2E_SET_CODE=LRW)")

        photo_path = FIXTURES_DIR / "ecl_deck.jpg"
        if not photo_path.exists():
            pytest.skip(f"Test photo not found: {photo_path}")

        image_bytes = photo_path.read_bytes()
        model = env.get("OPENAI_MODEL") or "gpt-4o"
        vision_model = env.get("OPENAI_VISION_MODEL") or model

        # --- Step 1: Seed DB from real Scryfall + 17lands ---
        print(f"\n=== Seeding DB from Scryfall + 17lands for '{set_code}' ===")
        set_name = await _seed_from_apis(clean_session, set_code)
        print(f"  Set: {set_name}")

        card_repo = CardRepository(clean_session)
        known_cards = await card_repo.get_card_names_by_set(set_code)
        print(f"  Known cards in DB: {len(known_cards)}")

        # --- Step 2: Real vision recognition ---
        llm_client = LLMClient(api_key=api_key, model=model, vision_model=vision_model)
        recognizer = CardRecognizer(llm_client=llm_client)

        try:
            recognition = await recognizer.recognize_cards(
                image_bytes,
                set_hint=set_code,
                known_cards=known_cards,
            )

            print(f"\n=== Real LLM Recognition Results ===")
            print(f"Main deck ({len(recognition.main_deck)} cards):")
            for card in recognition.main_deck:
                print(f"  - {card}")
            print(f"Sideboard ({len(recognition.sideboard)} cards):")
            for card in recognition.sideboard:
                print(f"  - {card}")
            print(f"Detected set: {recognition.detected_set}")
            print(f"Layout: {recognition.layout_detected.value}")

            assert len(recognition.main_deck) > 0, "No cards recognized from photo"

            # --- Step 3: Full analysis pipeline ---
            report, text = await run_analysis_pipeline(
                clean_session,
                recognition.main_deck,
                recognition.sideboard,
                set_code,
            )

            sys.stdout.buffer.write(b"\n=== Rendered Report ===\n")
            sys.stdout.buffer.write(text.encode("utf-8"))
            sys.stdout.buffer.write(b"\n")

            assert len(report.main_deck_cards) > 0, "Report has no main deck cards"

            # --- Step 4: Grade validation ---
            rated_with_bad_grade = [
                f"{c.name} (win_rate={c.win_rate}, grade={c.grade})"
                for c in report.main_deck_cards + report.sideboard_cards
                if c.win_rate is not None and c.grade in UNRATED_GRADES
            ]

            graded = [c for c in report.main_deck_cards if c.grade not in UNRATED_GRADES]
            print(f"\nGraded cards: {len(graded)}/{len(report.main_deck_cards)}")

            assert not rated_with_bad_grade, (
                f"Cards with win_rate should have a valid grade, "
                f"but found: {rated_with_bad_grade}"
            )
        finally:
            await llm_client.close()
            from src.config import get_settings
            get_settings.cache_clear()


# ============================================================================
# E2E test for /draft flow with two photos
# ============================================================================


class TestDraftE2E:
    """
    E2E test for /draft command flow with two real photos.

    Mirrors the bot's draft handler flow:
      ecl_deck.jpg → main deck recognition
      ecl_sideboard.jpg → sideboard recognition
      fuzzy matching → analysis pipeline → advice

    Run with:
      E2E_SET_CODE=ECL pytest tests/integration/test_photo_analysis.py -k draft_e2e -s
    """

    @pytest.mark.asyncio
    async def test_draft_e2e_two_photos(self, clean_session: AsyncSession):
        """
        E2E test: /draft flow with ecl_deck.jpg (main deck) + ecl_sideboard.jpg (sideboard).

        Uses real GPT-4o Vision recognition, real Scryfall + 17lands data.
        Verifies full pipeline from two photos to report and advice generation.

        Requires:
          - OPENAI_API_KEY in .env (not sk-test)
          - E2E_SET_CODE in .env or environment (e.g. E2E_SET_CODE=ECL)
          - tests/fixtures/ecl_deck.jpg — main deck photo
          - tests/fixtures/ecl_sideboard.jpg — sideboard photo

        Run with:
          E2E_SET_CODE=ECL pytest tests/integration/test_photo_analysis.py -k draft_e2e -s
        """
        import sys
        from dotenv import dotenv_values
        from src.llm.client import LLMClient
        from src.core.advisor import DeckAdvisor
        from src.core.deck import Deck as _Deck

        # --- Step 1: Skip conditions ---
        env_path = Path(__file__).parent.parent.parent / ".env"
        env = dotenv_values(env_path)

        api_key = env.get("OPENAI_API_KEY", "")
        if not api_key or api_key.startswith("sk-test"):
            pytest.skip(f"Real OPENAI_API_KEY not found in {env_path}")

        set_code = (env.get("E2E_SET_CODE") or os.environ.get("E2E_SET_CODE", "")).upper()
        if not set_code:
            pytest.skip("Set E2E_SET_CODE=<set_code> in .env or environment (e.g. E2E_SET_CODE=ECL)")

        deck_photo_path = FIXTURES_DIR / "ecl_deck.jpg"
        sideboard_photo_path = FIXTURES_DIR / "ecl_sideboard.jpg"

        if not deck_photo_path.exists():
            pytest.skip(f"Deck photo not found: {deck_photo_path}")
        if not sideboard_photo_path.exists():
            pytest.skip(f"Sideboard photo not found: {sideboard_photo_path}")

        deck_bytes = deck_photo_path.read_bytes()
        sideboard_bytes = sideboard_photo_path.read_bytes()
        model = env.get("OPENAI_MODEL") or "gpt-4o"
        vision_model = env.get("OPENAI_VISION_MODEL") or model

        # --- Step 2: Seed DB from real Scryfall + 17lands ---
        print(f"\n=== [Draft E2E] Seeding DB from Scryfall + 17lands for '{set_code}' ===")
        set_name = await _seed_from_apis(clean_session, set_code)
        print(f"  Set: {set_name}")

        card_repo = CardRepository(clean_session)
        known_cards = await card_repo.get_card_names_by_set(set_code)
        print(f"  Known cards in DB: {len(known_cards)}")

        llm_client = LLMClient(api_key=api_key, model=model, vision_model=vision_model)

        try:
            recognizer = CardRecognizer(llm_client=llm_client)

            # --- Step 3: Recognize ecl_deck.jpg → main deck ---
            print("\n=== [Draft E2E] Recognizing ecl_deck.jpg (main deck) ===")
            main_recognition = await recognizer.recognize_cards(
                deck_bytes,
                set_hint=set_code,
                known_cards=known_cards,
            )
            raw_main_deck = main_recognition.main_deck

            print(f"Main deck ({len(raw_main_deck)} cards):")
            for card in raw_main_deck:
                print(f"  - {card}")

            assert len(raw_main_deck) > 0, "No cards recognized from main deck photo"

            # --- Step 4: Recognize ecl_sideboard.jpg → sideboard ---
            print("\n=== [Draft E2E] Recognizing ecl_sideboard.jpg (sideboard) ===")
            sb_recognition = await recognizer.recognize_cards(
                sideboard_bytes,
                set_hint=set_code,
                known_cards=known_cards,
            )
            # Treat all recognized cards as sideboard (mirrors bot's draft handler)
            raw_sideboard = sb_recognition.main_deck + sb_recognition.sideboard

            print(f"Sideboard ({len(raw_sideboard)} cards):")
            for card in raw_sideboard:
                print(f"  - {card}")

            assert len(raw_sideboard) > 0, "No cards recognized from sideboard photo"

            # --- Step 5: Fuzzy matching to known_cards ---
            if known_cards:
                main_result = fuzzy_match_cards(raw_main_deck, known_cards)
                matched_main = main_result.matched

                sb_result = fuzzy_match_cards(raw_sideboard, known_cards)
                matched_sideboard = sb_result.matched
            else:
                matched_main = raw_main_deck
                matched_sideboard = raw_sideboard

            # --- Step 6: run_analysis_pipeline → report + rendered_text ---
            print("\n=== [Draft E2E] Running analysis pipeline ===")
            report, rendered_text = await run_analysis_pipeline(
                clean_session,
                list(matched_main),
                list(matched_sideboard),
                set_code,
            )

            sys.stdout.buffer.write(b"\n=== [Draft E2E] Rendered Report ===\n")
            sys.stdout.buffer.write(rendered_text.encode("utf-8"))
            sys.stdout.buffer.write(b"\n")

            assert len(report.main_deck_cards) > 0, "Report has no main deck cards"

            # --- Step 7: DeckAdvisor.generate_advice(session_mode=True) ---
            print("\n=== [Draft E2E] Generating advice (session_mode=True) ===")

            deck = _Deck(
                main_deck=list(matched_main),
                sideboard=list(matched_sideboard),
                set_code=set_code,
            )
            db_cards = await card_repo.get_cards_with_ratings(
                deck.main_deck + deck.sideboard, set_code
            )
            card_infos = [_card_to_card_info(c) for c in db_cards]

            analyzer = DeckAnalyzer()
            analysis = analyzer.analyze(deck, card_infos)

            main_deck_names = set(deck.main_deck)
            non_land_infos = [
                c for c in card_infos
                if c.name not in {"Plains", "Island", "Swamp", "Mountain", "Forest"}
                and c.name in main_deck_names
            ]
            land_rec = recommend_lands(non_land_infos)

            advisor = DeckAdvisor(llm_client=llm_client)
            advice_text = await advisor.generate_advice(
                deck,
                card_infos,
                analysis,
                session_mode=True,
                land_recommendation=land_rec,
            )

            assert advice_text, "Advice text is empty"

            # --- Step 8: Print advice to stdout ---
            sys.stdout.buffer.write(b"\n=== [Draft E2E] Advice ===\n")
            sys.stdout.buffer.write(advice_text.encode("utf-8"))
            sys.stdout.buffer.write(b"\n")

            # --- Step 9: Assertions ---
            rated_with_bad_grade = [
                f"{c.name} (win_rate={c.win_rate}, grade={c.grade})"
                for c in report.main_deck_cards + report.sideboard_cards
                if c.win_rate is not None and c.grade in UNRATED_GRADES
            ]

            graded = [c for c in report.main_deck_cards if c.grade not in UNRATED_GRADES]
            print(f"\nGraded main deck cards: {len(graded)}/{len(report.main_deck_cards)}")

            assert not rated_with_bad_grade, (
                f"Cards with win_rate should have a valid grade, "
                f"but found: {rated_with_bad_grade}"
            )

        finally:
            await llm_client.close()
            from src.config import get_settings
            get_settings.cache_clear()
