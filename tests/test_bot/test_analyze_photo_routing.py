"""
Unit tests for Smart Photo Routing — P4-1.

Acceptance criteria covered:
- TC-P4-1.1: 1 card, empty sideboard → _handle_single_card called (no deck pipeline).
- TC-P4-1.2: 3+ cards → _run_deck_pipeline called (no single card handler).
- TC-P4-1.3: 2 cards or 0 cards → clarification message sent.
- TC-P4-1.4: Single card, no active set → suggest /set <code>.
- TC-P4-1.5: Single card found in DB → grade, WR, CMC, type displayed.
- TC-P4-1.6: Single card not found in DB → "not found" message with set code.
- TC-P4-1.7: draft_router registered before analyze_router → FSM priority.
"""

from decimal import Decimal
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.handlers.analyze import (
    _handle_single_card,
    handle_photo_without_command,
)
from src.vision.recognizer import RecognitionResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message() -> MagicMock:
    """Return a mocked aiogram Message with photo support."""
    msg = MagicMock()
    msg.from_user = MagicMock(id=12345)

    photo = MagicMock()
    photo.file_id = "test_file_id"
    msg.photo = [photo]

    msg.bot = AsyncMock()
    file_obj = MagicMock()
    file_obj.file_path = "photos/test.jpg"
    msg.bot.get_file = AsyncMock(return_value=file_obj)
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    msg.bot.download_file = AsyncMock(return_value=BytesIO(png_bytes))

    reply = AsyncMock()
    reply.edit_text = AsyncMock(return_value=reply)
    msg.answer = AsyncMock(return_value=reply)
    msg.edit_text = AsyncMock(return_value=reply)
    return msg


def _make_state(data: dict | None = None) -> AsyncMock:
    """Return a mocked FSMContext."""
    state = AsyncMock()
    state.get_data = AsyncMock(return_value=data or {})
    state.set_state = AsyncMock()
    state.update_data = AsyncMock()
    state.clear = AsyncMock()
    return state


def _make_db_user(active_set_code: str | None = None) -> MagicMock:
    """Return a mocked DB User model."""
    user = MagicMock()
    user.id = 1
    user.telegram_id = 12345
    user.active_set_code = active_set_code
    return user


def _make_recognition(
    main_deck: list[str], sideboard: list[str] | None = None
) -> RecognitionResult:
    return RecognitionResult(
        main_deck=main_deck,
        sideboard=sideboard or [],
        detected_set=None,
    )


def _make_db_card(
    name: str = "Lightning Bolt",
    mana_cost: str = "{R}",
    cmc: Decimal = Decimal("1.0"),
    colors: list[str] | None = None,
    type_line: str = "Instant",
    rating: Decimal | None = Decimal("4.5"),
    win_rate: Decimal | None = Decimal("58.3"),
) -> MagicMock:
    """Return a mocked DB Card with one rating."""
    card = MagicMock()
    card.name = name
    card.mana_cost = mana_cost
    card.cmc = cmc
    card.colors = colors or ["R"]
    card.type_line = type_line
    card.rarity = "common"
    card.image_uri = None

    rating_obj = MagicMock()
    rating_obj.rating = rating
    rating_obj.win_rate = win_rate
    rating_obj.games_played = 1000
    card.ratings = [rating_obj]
    return card


# ---------------------------------------------------------------------------
# TC-P4-1.1: Single card (1 card, empty sideboard) → _handle_single_card
# ---------------------------------------------------------------------------


class TestTC_P4_1_1_SingleCard:
    @patch("src.bot.handlers.analyze.CardRecognizer")
    @patch("src.bot.handlers.analyze._handle_single_card", new_callable=AsyncMock)
    async def test_single_card_calls_handle_single_card(
        self, mock_handle_single, MockRecognizer
    ):
        """TC-P4-1.1: 1 recognized card, empty sideboard → _handle_single_card called."""
        mock_rec_instance = AsyncMock()
        mock_rec_instance.recognize_cards = AsyncMock(
            return_value=_make_recognition(["Lightning Bolt"])
        )
        MockRecognizer.return_value = mock_rec_instance

        message = _make_message()
        state = _make_state()
        db_user = _make_db_user(active_set_code=None)  # no set → no get_session calls

        await handle_photo_without_command(message, db_user, state)

        mock_handle_single.assert_called_once()
        # Third positional arg is card_name
        assert mock_handle_single.call_args.args[2] == "Lightning Bolt"

    @patch("src.bot.handlers.analyze.CardRecognizer")
    @patch("src.bot.handlers.analyze._run_deck_pipeline", new_callable=AsyncMock)
    async def test_single_card_does_not_call_deck_pipeline(
        self, mock_pipeline, MockRecognizer
    ):
        """TC-P4-1.1: Single card must NOT trigger full deck pipeline."""
        mock_rec_instance = AsyncMock()
        mock_rec_instance.recognize_cards = AsyncMock(
            return_value=_make_recognition(["Lightning Bolt"])
        )
        MockRecognizer.return_value = mock_rec_instance

        message = _make_message()
        state = _make_state()
        db_user = _make_db_user(active_set_code=None)

        with patch("src.bot.handlers.analyze._handle_single_card", new_callable=AsyncMock):
            await handle_photo_without_command(message, db_user, state)

        mock_pipeline.assert_not_called()

    @patch("src.bot.handlers.analyze.CardRecognizer")
    async def test_one_card_with_nonempty_sideboard_is_ambiguous(self, MockRecognizer):
        """1 main card + non-empty sideboard → ambiguous, not single card."""
        mock_rec_instance = AsyncMock()
        mock_rec_instance.recognize_cards = AsyncMock(
            return_value=_make_recognition(["Lightning Bolt"], ["Negate"])
        )
        MockRecognizer.return_value = mock_rec_instance

        message = _make_message()
        state = _make_state()
        db_user = _make_db_user(active_set_code=None)

        with patch("src.bot.handlers.analyze._handle_single_card", new_callable=AsyncMock) as mock_single:
            await handle_photo_without_command(message, db_user, state)
            mock_single.assert_not_called()

        processing_msg = message.answer.return_value
        processing_msg.edit_text.assert_called_once()


# ---------------------------------------------------------------------------
# TC-P4-1.2: Deck (3+ cards) → _run_deck_pipeline called
# ---------------------------------------------------------------------------


class TestTC_P4_1_2_DeckPhoto:
    @patch("src.bot.handlers.analyze.CardRecognizer")
    @patch("src.bot.handlers.analyze._run_deck_pipeline", new_callable=AsyncMock)
    async def test_three_plus_cards_calls_deck_pipeline(
        self, mock_pipeline, MockRecognizer
    ):
        """TC-P4-1.2: 3+ recognized cards → _run_deck_pipeline called."""
        main_cards = ["Card A", "Card B", "Card C"]
        mock_rec_instance = AsyncMock()
        mock_rec_instance.recognize_cards = AsyncMock(
            return_value=_make_recognition(main_cards)
        )
        MockRecognizer.return_value = mock_rec_instance

        message = _make_message()
        state = _make_state()
        db_user = _make_db_user(active_set_code=None)

        await handle_photo_without_command(message, db_user, state)

        mock_pipeline.assert_called_once()
        # _run_deck_pipeline is called with positional args:
        # (message, processing_msg, db_user, main_deck, sideboard, set_code)
        call_args = mock_pipeline.call_args.args
        assert call_args[3] == main_cards  # main_deck is 4th positional arg

    @patch("src.bot.handlers.analyze.CardRecognizer")
    @patch("src.bot.handlers.analyze._handle_single_card", new_callable=AsyncMock)
    async def test_deck_does_not_call_single_card(self, mock_handle_single, MockRecognizer):
        """TC-P4-1.2: Deck photo must NOT trigger single card handler."""
        main_cards = ["A", "B", "C"]
        mock_rec_instance = AsyncMock()
        mock_rec_instance.recognize_cards = AsyncMock(
            return_value=_make_recognition(main_cards)
        )
        MockRecognizer.return_value = mock_rec_instance

        message = _make_message()
        state = _make_state()
        db_user = _make_db_user(active_set_code=None)

        with patch("src.bot.handlers.analyze._run_deck_pipeline", new_callable=AsyncMock):
            await handle_photo_without_command(message, db_user, state)

        mock_handle_single.assert_not_called()

    @patch("src.bot.handlers.analyze.CardRecognizer")
    @patch("src.bot.handlers.analyze._run_deck_pipeline", new_callable=AsyncMock)
    async def test_exactly_three_cards_triggers_pipeline(self, mock_pipeline, MockRecognizer):
        """Boundary: exactly 3 cards → deck pipeline (not ambiguous)."""
        mock_rec_instance = AsyncMock()
        mock_rec_instance.recognize_cards = AsyncMock(
            return_value=_make_recognition(["A", "B", "C"])
        )
        MockRecognizer.return_value = mock_rec_instance

        message = _make_message()
        state = _make_state()
        db_user = _make_db_user(active_set_code=None)

        await handle_photo_without_command(message, db_user, state)

        mock_pipeline.assert_called_once()


# ---------------------------------------------------------------------------
# TC-P4-1.3: Ambiguous (2 cards or 0 cards) → clarification message
# ---------------------------------------------------------------------------


class TestTC_P4_1_3_Ambiguous:
    @patch("src.bot.handlers.analyze.CardRecognizer")
    async def test_two_cards_shows_ambiguous_message(self, MockRecognizer):
        """TC-P4-1.3: 2 recognized cards → clarification message shown."""
        mock_rec_instance = AsyncMock()
        mock_rec_instance.recognize_cards = AsyncMock(
            return_value=_make_recognition(["Card A", "Card B"])
        )
        MockRecognizer.return_value = mock_rec_instance

        message = _make_message()
        state = _make_state()
        db_user = _make_db_user(active_set_code=None)

        await handle_photo_without_command(message, db_user, state)

        processing_msg = message.answer.return_value
        processing_msg.edit_text.assert_called_once()
        text = processing_msg.edit_text.call_args.args[0]
        assert "визначити" in text or "analyze" in text or "draft" in text.lower()

    @patch("src.bot.handlers.analyze.CardRecognizer")
    async def test_zero_cards_shows_ambiguous_message(self, MockRecognizer):
        """TC-P4-1.3: 0 recognized cards → clarification message shown."""
        mock_rec_instance = AsyncMock()
        mock_rec_instance.recognize_cards = AsyncMock(
            return_value=_make_recognition([])
        )
        MockRecognizer.return_value = mock_rec_instance

        message = _make_message()
        state = _make_state()
        db_user = _make_db_user(active_set_code=None)

        await handle_photo_without_command(message, db_user, state)

        processing_msg = message.answer.return_value
        processing_msg.edit_text.assert_called_once()
        text = processing_msg.edit_text.call_args.args[0]
        assert "визначити" in text or "analyze" in text

    @patch("src.bot.handlers.analyze.CardRecognizer")
    async def test_two_cards_does_not_call_single_or_pipeline(self, MockRecognizer):
        """TC-P4-1.3: 2 cards → neither single card nor deck pipeline called."""
        mock_rec_instance = AsyncMock()
        mock_rec_instance.recognize_cards = AsyncMock(
            return_value=_make_recognition(["A", "B"])
        )
        MockRecognizer.return_value = mock_rec_instance

        message = _make_message()
        state = _make_state()
        db_user = _make_db_user(active_set_code=None)

        with (
            patch("src.bot.handlers.analyze._handle_single_card", new_callable=AsyncMock) as ms,
            patch("src.bot.handlers.analyze._run_deck_pipeline", new_callable=AsyncMock) as mp,
        ):
            await handle_photo_without_command(message, db_user, state)
            ms.assert_not_called()
            mp.assert_not_called()


# ---------------------------------------------------------------------------
# TC-P4-1.4: Single card, no active set → suggest /set
# ---------------------------------------------------------------------------


class TestTC_P4_1_4_NoActiveSet:
    async def test_no_set_suggests_set_command(self):
        """TC-P4-1.4: _handle_single_card with no set_code → suggest /set."""
        processing_msg = AsyncMock()
        db_user = _make_db_user(active_set_code=None)

        await _handle_single_card(
            processing_msg=processing_msg,
            db_user=db_user,
            card_name="Lightning Bolt",
            set_code=None,
        )

        processing_msg.edit_text.assert_called_once()
        text = processing_msg.edit_text.call_args.args[0]
        assert "/set" in text

    async def test_no_set_includes_card_name(self):
        """TC-P4-1.4: No-set message mentions the recognized card name."""
        processing_msg = AsyncMock()
        db_user = _make_db_user(active_set_code=None)

        await _handle_single_card(
            processing_msg=processing_msg,
            db_user=db_user,
            card_name="Cryptic Command",
            set_code=None,
        )

        text = processing_msg.edit_text.call_args.args[0]
        assert "Cryptic Command" in text


# ---------------------------------------------------------------------------
# TC-P4-1.5: Single card found in DB → grade, WR, CMC, type displayed
# ---------------------------------------------------------------------------


class TestTC_P4_1_5_CardFound:
    @patch("src.bot.handlers.analyze.CardRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_found_card_shows_grade_and_wr(
        self, mock_get_session, MockCardRepository
    ):
        """TC-P4-1.5: Found card shows Грейд and WR."""
        db_card = _make_db_card(
            name="Lightning Bolt",
            rating=Decimal("4.5"),
            win_rate=Decimal("58.3"),
            cmc=Decimal("1.0"),
            colors=["R"],
            type_line="Instant",
        )

        mock_repo = AsyncMock()
        mock_repo.get_by_name = AsyncMock(return_value=db_card)
        MockCardRepository.return_value = mock_repo

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = mock_cm

        processing_msg = AsyncMock()
        db_user = _make_db_user()

        await _handle_single_card(
            processing_msg=processing_msg,
            db_user=db_user,
            card_name="Lightning Bolt",
            set_code="ECL",
        )

        processing_msg.edit_text.assert_called_once()
        text = processing_msg.edit_text.call_args.args[0]
        assert "Грейд:" in text
        assert "WR:" in text

    @patch("src.bot.handlers.analyze.CardRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_found_card_shows_cmc(self, mock_get_session, MockCardRepository):
        """TC-P4-1.5: Found card shows CMC."""
        db_card = _make_db_card(cmc=Decimal("3.0"))

        mock_repo = AsyncMock()
        mock_repo.get_by_name = AsyncMock(return_value=db_card)
        MockCardRepository.return_value = mock_repo

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = mock_cm

        processing_msg = AsyncMock()
        db_user = _make_db_user()

        await _handle_single_card(
            processing_msg=processing_msg,
            db_user=db_user,
            card_name="Some Card",
            set_code="ECL",
        )

        text = processing_msg.edit_text.call_args.args[0]
        assert "CMC: 3" in text

    @patch("src.bot.handlers.analyze.CardRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_found_card_shows_type_and_colors(
        self, mock_get_session, MockCardRepository
    ):
        """TC-P4-1.5: Found card shows type line and colors."""
        db_card = _make_db_card(
            colors=["U"],
            type_line="Creature — Merfolk",
        )

        mock_repo = AsyncMock()
        mock_repo.get_by_name = AsyncMock(return_value=db_card)
        MockCardRepository.return_value = mock_repo

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = mock_cm

        processing_msg = AsyncMock()
        db_user = _make_db_user()

        await _handle_single_card(
            processing_msg=processing_msg,
            db_user=db_user,
            card_name="Some Merfolk",
            set_code="ECL",
        )

        text = processing_msg.edit_text.call_args.args[0]
        assert "Тип:" in text
        assert "Кольори:" in text
        assert "Creature" in text

    @patch("src.bot.handlers.analyze.CardRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_found_card_grade_computed_from_rating(
        self, mock_get_session, MockCardRepository
    ):
        """TC-P4-1.5: Grade is computed from rating via rating_to_grade."""
        # rating 4.5 → grade "A"
        db_card = _make_db_card(rating=Decimal("4.5"))

        mock_repo = AsyncMock()
        mock_repo.get_by_name = AsyncMock(return_value=db_card)
        MockCardRepository.return_value = mock_repo

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = mock_cm

        processing_msg = AsyncMock()
        db_user = _make_db_user()

        await _handle_single_card(
            processing_msg=processing_msg,
            db_user=db_user,
            card_name="Good Card",
            set_code="ECL",
        )

        text = processing_msg.edit_text.call_args.args[0]
        assert "Грейд: A" in text


# ---------------------------------------------------------------------------
# TC-P4-1.6: Single card not found in DB → "not found" message with set code
# ---------------------------------------------------------------------------


class TestTC_P4_1_6_CardNotFound:
    @patch("src.bot.handlers.analyze.CardRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_missing_card_shows_not_found_message(
        self, mock_get_session, MockCardRepository
    ):
        """TC-P4-1.6: Card not in DB → not-found message."""
        mock_repo = AsyncMock()
        mock_repo.get_by_name = AsyncMock(return_value=None)
        MockCardRepository.return_value = mock_repo

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = mock_cm

        processing_msg = AsyncMock()
        db_user = _make_db_user()

        await _handle_single_card(
            processing_msg=processing_msg,
            db_user=db_user,
            card_name="Unknown Card",
            set_code="ECL",
        )

        processing_msg.edit_text.assert_called_once()
        text = processing_msg.edit_text.call_args.args[0]
        assert "не знайдена" in text
        assert "ECL" in text

    @patch("src.bot.handlers.analyze.CardRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_missing_card_message_includes_card_name(
        self, mock_get_session, MockCardRepository
    ):
        """TC-P4-1.6: Not-found message includes the unrecognized card name."""
        mock_repo = AsyncMock()
        mock_repo.get_by_name = AsyncMock(return_value=None)
        MockCardRepository.return_value = mock_repo

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = mock_cm

        processing_msg = AsyncMock()
        db_user = _make_db_user()

        await _handle_single_card(
            processing_msg=processing_msg,
            db_user=db_user,
            card_name="Mystery Card",
            set_code="ECL",
        )

        text = processing_msg.edit_text.call_args.args[0]
        assert "Mystery Card" in text


# ---------------------------------------------------------------------------
# TC-P4-1.7: FSM handlers have priority over bare photo handler
# ---------------------------------------------------------------------------


class TestTC_P4_1_7_FSMPriority:
    def test_draft_router_registered_before_analyze_router(self):
        """
        TC-P4-1.7: draft_router is included before analyze_router in the root
        router, so DraftState FSM handlers intercept photos before the generic
        handle_photo_without_command.
        """
        from src.bot.handlers import get_handlers_router
        from src.bot.handlers.analyze import router as analyze_router
        from src.bot.handlers.draft import router as draft_router

        root_router = get_handlers_router()
        sub_routers = root_router.sub_routers

        draft_idx = None
        analyze_idx = None
        for i, sr in enumerate(sub_routers):
            if sr is draft_router:
                draft_idx = i
            elif sr is analyze_router:
                analyze_idx = i

        assert draft_idx is not None, "draft_router not found in root router"
        assert analyze_idx is not None, "analyze_router not found in root router"
        assert draft_idx < analyze_idx, (
            "draft_router must be registered before analyze_router "
            "so FSM handlers have higher priority"
        )
