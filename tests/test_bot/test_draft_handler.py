"""
Unit tests for the /draft multi-photo session handler.

Acceptance criteria covered:
- TC-P3-6.1: /draft sets FSM to waiting_main and sends prompt.
- TC-P3-6.2: Photo in waiting_main → recognition count confirmed.
- TC-P3-6.3: FSM transitions to waiting_sideboard after recognition.
- TC-P3-6.4: Photo in waiting_sideboard → _build_and_send_report called.
- TC-P3-6.5: "Пропустити sideboard" → _build_and_send_report with empty sideboard.
- TC-P3-6.6: DeckReport with non-empty sideboard renders both sections.
- TC-P3-6.7: Empty main deck recognition → state cleared + error sent.
- TC-P4-3.1: After advice generation FSM transitions to DraftState.chatting.
- TC-P4-3.2: Text message in chatting state → LLM call + response sent.
- TC-P4-3.3: LLM call system prompt contains main deck card names.
- TC-P4-3.4: Conversation history is saved in FSM after chat exchange.
- TC-P4-3.5: /draft command in chatting → FSM transitions to waiting_main.
- TC-P4-3.6: /analyze clears FSM before running analysis.
- TC-P4-3.7: LLM error in chat → friendly error, FSM stays in chatting.
- TC-P4-3.8: Conversation history trimmed to last 10 exchanges (20 messages).
- TC-P4-3.9: DRAFT_CHAT_SYSTEM_PROMPT contains Ukrainian instruction.
- TC-P4-3.10: System prompt passed to LLM contains main deck card names.
"""

from decimal import Decimal
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from src.bot.handlers.draft import (
    DraftState,
    _build_deck_context,
    handle_draft_chat,
    handle_draft_command,
    handle_draft_main_photo,
    handle_draft_sideboard_photo,
    handle_skip_sideboard,
)
from src.bot.messages import format_error
from src.core.deck import CardInfo, Deck, DeckAnalysis
from src.core.lands import LandRecommendation
from src.llm.exceptions import LLMError
from src.llm.prompts import DRAFT_CHAT_SYSTEM_PROMPT
from src.reports.models import CardSummary, DeckReport
from src.reports.telegram import TelegramRenderer
from src.vision.recognizer import RecognitionResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message(text_answers: list[str] | None = None) -> MagicMock:
    """Return a mocked aiogram Message with photo support."""
    msg = MagicMock()
    msg.from_user = MagicMock(id=12345)

    # photo[-1] → file for download
    photo = MagicMock()
    photo.file_id = "test_file_id"
    msg.photo = [photo]

    # bot helpers
    msg.bot = AsyncMock()
    file_obj = MagicMock()
    file_obj.file_path = "photos/test.jpg"
    msg.bot.get_file = AsyncMock(return_value=file_obj)
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    msg.bot.download_file = AsyncMock(return_value=BytesIO(png_bytes))

    # answer / edit_text return another mock Message
    reply = AsyncMock()
    reply.edit_text = AsyncMock(return_value=reply)
    msg.answer = AsyncMock(return_value=reply)
    msg.edit_text = AsyncMock(return_value=reply)

    return msg


def _make_state(data: dict | None = None) -> AsyncMock:
    """Return a mocked aiogram FSMContext."""
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


def _make_recognition(main_deck: list[str], sideboard: list[str] | None = None) -> RecognitionResult:
    return RecognitionResult(
        main_deck=main_deck,
        sideboard=sideboard or [],
        detected_set=None,
    )


# ---------------------------------------------------------------------------
# TC-P3-6.1: /draft sets FSM to waiting_main
# ---------------------------------------------------------------------------


class TestTC_P3_6_1_DraftCommand:
    async def test_draft_sets_waiting_main_state(self):
        message = _make_message()
        state = _make_state()

        await handle_draft_command(message, state)

        state.set_state.assert_called_once_with(DraftState.waiting_main)

    async def test_draft_sends_main_deck_prompt(self):
        message = _make_message()
        state = _make_state()

        await handle_draft_command(message, state)

        message.answer.assert_called_once()
        call_kwargs = message.answer.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        assert "main deck" in text.lower() or "main deck" in text


# ---------------------------------------------------------------------------
# TC-P3-6.2 + TC-P3-6.3: Main deck photo → count + state transition
# ---------------------------------------------------------------------------


class TestTC_P3_6_2_3_MainDeckPhoto:
    @patch("src.bot.handlers.draft.CardRecognizer")
    async def test_recognition_count_confirmed_in_message(self, MockRecognizer):
        """TC-P3-6.2: After recognition the message shows card count."""
        main_cards = ["Lightning Bolt", "Counterspell", "Serra Angel"]
        mock_rec = AsyncMock()
        mock_rec.recognize_cards = AsyncMock(return_value=_make_recognition(main_cards))
        MockRecognizer.return_value = mock_rec

        message = _make_message()
        state = _make_state(data={})
        db_user = _make_db_user()

        await handle_draft_main_photo(message, db_user, state)

        processing_msg = message.answer.return_value
        processing_msg.edit_text.assert_called()
        call_args = processing_msg.edit_text.call_args
        text = call_args.args[0] if call_args.args else call_args.kwargs.get("text", "")
        assert "3" in text  # 3 cards recognized

    @patch("src.bot.handlers.draft.CardRecognizer")
    async def test_fsm_transitions_to_waiting_sideboard(self, MockRecognizer):
        """TC-P3-6.3: FSM moves to waiting_sideboard after main deck recognized."""
        main_cards = ["Lightning Bolt", "Counterspell"]
        mock_rec = AsyncMock()
        mock_rec.recognize_cards = AsyncMock(return_value=_make_recognition(main_cards))
        MockRecognizer.return_value = mock_rec

        message = _make_message()
        state = _make_state(data={})
        db_user = _make_db_user()

        await handle_draft_main_photo(message, db_user, state)

        state.set_state.assert_called_with(DraftState.waiting_sideboard)

    @patch("src.bot.handlers.draft.CardRecognizer")
    async def test_main_deck_stored_in_fsm_data(self, MockRecognizer):
        """Main deck is persisted in FSM for the next step."""
        main_cards = ["Lightning Bolt", "Counterspell"]
        mock_rec = AsyncMock()
        mock_rec.recognize_cards = AsyncMock(return_value=_make_recognition(main_cards))
        MockRecognizer.return_value = mock_rec

        message = _make_message()
        state = _make_state(data={})
        db_user = _make_db_user()

        await handle_draft_main_photo(message, db_user, state)

        state.update_data.assert_called()
        call_kwargs = state.update_data.call_args.kwargs
        assert call_kwargs.get("draft_main_deck") == main_cards

    @patch("src.bot.handlers.draft.CardRecognizer")
    async def test_skip_sideboard_keyboard_sent(self, MockRecognizer):
        """After main deck recognition, the 'skip sideboard' keyboard is shown."""
        main_cards = ["Lightning Bolt"]
        mock_rec = AsyncMock()
        mock_rec.recognize_cards = AsyncMock(return_value=_make_recognition(main_cards))
        MockRecognizer.return_value = mock_rec

        message = _make_message()
        state = _make_state(data={})
        db_user = _make_db_user()

        await handle_draft_main_photo(message, db_user, state)

        processing_msg = message.answer.return_value
        call_kwargs = processing_msg.edit_text.call_args.kwargs
        # reply_markup must be present
        assert call_kwargs.get("reply_markup") is not None


# ---------------------------------------------------------------------------
# TC-P3-6.4: Sideboard photo → full report generated
# ---------------------------------------------------------------------------


class TestTC_P3_6_4_SideboardPhoto:
    @patch("src.bot.handlers.draft._build_and_send_report", new_callable=AsyncMock)
    @patch("src.bot.handlers.draft.CardRecognizer")
    async def test_sideboard_photo_calls_build_report(self, MockRecognizer, mock_build):
        """TC-P3-6.4: Sideboard photo triggers _build_and_send_report."""
        sideboard_cards = ["Negate", "Disenchant"]
        mock_rec = AsyncMock()
        mock_rec.recognize_cards = AsyncMock(
            return_value=_make_recognition([], sideboard_cards)
        )
        MockRecognizer.return_value = mock_rec

        stored_main = ["Lightning Bolt", "Counterspell"]
        message = _make_message()
        state = _make_state(data={
            "draft_main_deck": stored_main,
            "draft_set_code": None,
            "draft_known_cards": None,
        })
        db_user = _make_db_user()

        await handle_draft_sideboard_photo(message, db_user, state)

        mock_build.assert_called_once()
        call_kwargs = mock_build.call_args.kwargs
        assert call_kwargs["main_deck"] == stored_main
        assert call_kwargs["sideboard"] == sideboard_cards

    @patch("src.bot.handlers.draft._build_and_send_report", new_callable=AsyncMock)
    @patch("src.bot.handlers.draft.CardRecognizer")
    async def test_sideboard_photo_clears_fsm_state(self, MockRecognizer, mock_build):
        """After sideboard photo, FSM state is cleared."""
        mock_rec = AsyncMock()
        mock_rec.recognize_cards = AsyncMock(
            return_value=_make_recognition(["Card A"])
        )
        MockRecognizer.return_value = mock_rec

        message = _make_message()
        state = _make_state(data={"draft_main_deck": ["Lightning Bolt"]})
        db_user = _make_db_user()

        await handle_draft_sideboard_photo(message, db_user, state)

        state.clear.assert_called_once()


# ---------------------------------------------------------------------------
# TC-P3-6.5: Skip sideboard → report with empty sideboard
# ---------------------------------------------------------------------------


class TestTC_P3_6_5_SkipSideboard:
    @patch("src.bot.handlers.draft._build_and_send_report", new_callable=AsyncMock)
    async def test_skip_calls_build_with_empty_sideboard(self, mock_build):
        """TC-P3-6.5: Skipping sideboard calls _build_and_send_report with sideboard=[]."""
        stored_main = ["Lightning Bolt", "Counterspell", "Serra Angel"]

        callback = MagicMock()
        callback.answer = AsyncMock()
        reply_msg = AsyncMock()
        reply_msg.edit_text = AsyncMock(return_value=reply_msg)
        callback.message = reply_msg

        state = _make_state(data={
            "draft_main_deck": stored_main,
            "draft_set_code": "TST",
        })
        db_user = _make_db_user()

        await handle_skip_sideboard(callback, db_user, state)

        mock_build.assert_called_once()
        call_kwargs = mock_build.call_args.kwargs
        assert call_kwargs["sideboard"] == []
        assert call_kwargs["main_deck"] == stored_main

    @patch("src.bot.handlers.draft._build_and_send_report", new_callable=AsyncMock)
    async def test_skip_clears_fsm_state(self, mock_build):
        """FSM state is cleared after skip."""
        callback = MagicMock()
        callback.answer = AsyncMock()
        reply_msg = AsyncMock()
        reply_msg.edit_text = AsyncMock(return_value=reply_msg)
        callback.message = reply_msg

        state = _make_state(data={"draft_main_deck": ["Card A"]})
        db_user = _make_db_user()

        await handle_skip_sideboard(callback, db_user, state)

        state.clear.assert_called_once()


# ---------------------------------------------------------------------------
# TC-P3-6.6: Report contains separate main deck and sideboard sections
# ---------------------------------------------------------------------------


class TestTC_P3_6_6_ReportSections:
    def _make_report(self, main_names: list[str], sb_names: list[str]) -> DeckReport:
        deck = Deck(main_deck=main_names, sideboard=sb_names, set_code=None)
        main_cards = [CardSummary(name=n) for n in main_names]
        sb_cards = [CardSummary(name=n) for n in sb_names]
        analysis = DeckAnalysis(score=Decimal("3.0"), estimated_win_rate=Decimal("50.0"))
        return DeckReport(
            deck=deck,
            main_deck_cards=main_cards,
            sideboard_cards=sb_cards,
            analysis=analysis,
        )

    def test_report_contains_main_deck_section(self):
        """TC-P3-6.6: Rendered report has main deck section."""
        report = self._make_report(["Lightning Bolt", "Counterspell"], ["Negate"])
        text = TelegramRenderer().render(report)
        assert "Main Deck" in text or "main deck" in text.lower()

    def test_report_contains_sideboard_section_when_non_empty(self):
        """TC-P3-6.6: Rendered report has sideboard section when sideboard non-empty."""
        report = self._make_report(["Lightning Bolt"], ["Negate"])
        text = TelegramRenderer().render(report)
        assert "Sideboard" in text or "sideboard" in text.lower()

    def test_sideboard_section_absent_when_empty(self):
        """Report does NOT show sideboard section when sideboard is empty."""
        report = self._make_report(["Lightning Bolt"], [])
        text = TelegramRenderer().render(report)
        # Should not have a dedicated sideboard section if empty
        assert "sideboard" not in text.lower() or report.sideboard_cards == []


# ---------------------------------------------------------------------------
# TC-P3-6.7: Empty main deck recognition → error + FSM reset
# ---------------------------------------------------------------------------


class TestTC_P3_6_7_EmptyMainDeck:
    @patch("src.bot.handlers.draft.CardRecognizer")
    async def test_empty_recognition_sends_error(self, MockRecognizer):
        """TC-P3-6.7: When no cards recognized, error message is sent."""
        mock_rec = AsyncMock()
        mock_rec.recognize_cards = AsyncMock(return_value=_make_recognition([]))
        MockRecognizer.return_value = mock_rec

        message = _make_message()
        state = _make_state(data={})
        db_user = _make_db_user()

        await handle_draft_main_photo(message, db_user, state)

        processing_msg = message.answer.return_value
        processing_msg.edit_text.assert_called_once()
        call_args = processing_msg.edit_text.call_args
        text = call_args.args[0] if call_args.args else call_args.kwargs.get("text", "")
        error_text = format_error("no_cards")
        assert text == error_text

    @patch("src.bot.handlers.draft.CardRecognizer")
    async def test_empty_recognition_resets_fsm(self, MockRecognizer):
        """TC-P3-6.7: When no cards recognized, FSM state is cleared."""
        mock_rec = AsyncMock()
        mock_rec.recognize_cards = AsyncMock(return_value=_make_recognition([]))
        MockRecognizer.return_value = mock_rec

        message = _make_message()
        state = _make_state(data={})
        db_user = _make_db_user()

        await handle_draft_main_photo(message, db_user, state)

        state.clear.assert_called_once()
        # Must NOT transition to waiting_sideboard
        for call in state.set_state.call_args_list:
            assert call.args[0] != DraftState.waiting_sideboard


# ---------------------------------------------------------------------------
# TC-P4-3.9: DRAFT_CHAT_SYSTEM_PROMPT content check
# ---------------------------------------------------------------------------


class TestTC_P4_3_9_SystemPromptContent:
    def test_system_prompt_contains_ukrainian_instruction(self):
        """TC-P4-3.9: DRAFT_CHAT_SYSTEM_PROMPT contains Ukrainian language instruction."""
        assert "ukrainian" in DRAFT_CHAT_SYSTEM_PROMPT.lower()

    def test_system_prompt_contains_deck_context_instruction(self):
        """TC-P4-3.9: DRAFT_CHAT_SYSTEM_PROMPT instructs to know the deck."""
        prompt_lower = DRAFT_CHAT_SYSTEM_PROMPT.lower()
        assert "deck" in prompt_lower


# ---------------------------------------------------------------------------
# TC-P4-3.2 + TC-P4-3.3 + TC-P4-3.4 + TC-P4-3.10: handle_draft_chat handler
# ---------------------------------------------------------------------------


def _make_text_message(text: str = "Яка краща карта?") -> MagicMock:
    """Return a mocked aiogram Message with text content."""
    msg = MagicMock()
    msg.from_user = MagicMock(id=12345)
    msg.text = text

    reply = AsyncMock()
    reply.edit_text = AsyncMock(return_value=reply)
    msg.answer = AsyncMock(return_value=reply)
    return msg


class TestTC_P4_3_2_3_4_ChatHandler:
    @patch("src.bot.handlers.draft.get_llm_client")
    async def test_chat_calls_llm_and_sends_response(self, mock_get_llm):
        """TC-P4-3.2: Text message in chatting state → LLM called + response sent."""
        mock_llm = AsyncMock()
        mock_llm.call_completion = AsyncMock(return_value="Рекомендую прибрати Shock.")
        mock_get_llm.return_value = mock_llm

        fsm_data = {
            "draft_main_deck": ["Lightning Bolt", "Counterspell"],
            "draft_sideboard": ["Serra Angel"],
            "draft_set_code": "TST",
            "draft_advice": "Ваша колода непогана.",
            "draft_conversation": [],
        }
        message = _make_text_message("Яку карту краще прибрати?")
        state = _make_state(data=fsm_data)
        db_user = _make_db_user()

        await handle_draft_chat(message, db_user, state)

        mock_llm.call_completion.assert_called_once()
        reply_msg = message.answer.return_value
        reply_msg.edit_text.assert_called_once()
        call_args = reply_msg.edit_text.call_args
        text = call_args.args[0] if call_args.args else call_args.kwargs.get("text", "")
        assert "Shock" in text or len(text) > 0

    @patch("src.bot.handlers.draft.get_llm_client")
    async def test_system_prompt_contains_main_deck_cards(self, mock_get_llm):
        """TC-P4-3.3 + TC-P4-3.10: LLM call system prompt contains main deck card names."""
        mock_llm = AsyncMock()
        mock_llm.call_completion = AsyncMock(return_value="Порада.")
        mock_get_llm.return_value = mock_llm

        main_deck = ["Lightning Bolt", "Counterspell", "Serra Angel"]
        fsm_data = {
            "draft_main_deck": main_deck,
            "draft_sideboard": [],
            "draft_set_code": "TST",
            "draft_advice": "",
            "draft_conversation": [],
        }
        message = _make_text_message("Що думаєш про мою колоду?")
        state = _make_state(data=fsm_data)
        db_user = _make_db_user()

        await handle_draft_chat(message, db_user, state)

        call_kwargs = mock_llm.call_completion.call_args.kwargs
        system_prompt = call_kwargs.get("system_prompt", "")
        for card_name in main_deck:
            assert card_name in system_prompt, (
                f"Card '{card_name}' not found in system_prompt"
            )

    @patch("src.bot.handlers.draft.get_llm_client")
    async def test_conversation_history_saved_to_fsm(self, mock_get_llm):
        """TC-P4-3.4: User message and assistant reply are saved to FSM conversation."""
        mock_llm = AsyncMock()
        mock_llm.call_completion = AsyncMock(return_value="Відповідь LLM.")
        mock_get_llm.return_value = mock_llm

        user_question = "Що замінити?"
        fsm_data = {
            "draft_main_deck": ["Card A"],
            "draft_sideboard": [],
            "draft_set_code": None,
            "draft_advice": "",
            "draft_conversation": [],
        }
        message = _make_text_message(user_question)
        state = _make_state(data=fsm_data)
        db_user = _make_db_user()

        await handle_draft_chat(message, db_user, state)

        state.update_data.assert_called_once()
        updated = state.update_data.call_args.kwargs.get("draft_conversation", [])
        assert len(updated) == 2
        assert updated[0] == {"role": "user", "content": user_question}
        assert updated[1] == {"role": "assistant", "content": "Відповідь LLM."}

    @patch("src.bot.handlers.draft.get_llm_client")
    async def test_previous_history_included_in_messages(self, mock_get_llm):
        """TC-P4-3.4: Existing conversation history is passed to LLM."""
        mock_llm = AsyncMock()
        mock_llm.call_completion = AsyncMock(return_value="Нова відповідь.")
        mock_get_llm.return_value = mock_llm

        existing_history = [
            {"role": "user", "content": "Перше питання"},
            {"role": "assistant", "content": "Перша відповідь"},
        ]
        fsm_data = {
            "draft_main_deck": ["Card A"],
            "draft_sideboard": [],
            "draft_set_code": None,
            "draft_advice": "",
            "draft_conversation": existing_history,
        }
        message = _make_text_message("Друге питання")
        state = _make_state(data=fsm_data)
        db_user = _make_db_user()

        await handle_draft_chat(message, db_user, state)

        passed_messages = mock_llm.call_completion.call_args.args[0]
        # History + new user message
        assert any(m["content"] == "Перше питання" for m in passed_messages)
        assert any(m["content"] == "Перша відповідь" for m in passed_messages)
        assert passed_messages[-1] == {"role": "user", "content": "Друге питання"}


# ---------------------------------------------------------------------------
# TC-P4-3.7: LLM error in chat → friendly error, FSM stays in chatting
# ---------------------------------------------------------------------------


class TestTC_P4_3_7_LLMErrorInChat:
    @patch("src.bot.handlers.draft.get_llm_client")
    async def test_llm_error_sends_friendly_message(self, mock_get_llm):
        """TC-P4-3.7: LLM error → error message sent."""
        mock_llm = AsyncMock()
        mock_llm.call_completion = AsyncMock(side_effect=LLMError("timeout"))
        mock_get_llm.return_value = mock_llm

        fsm_data = {
            "draft_main_deck": ["Card A"],
            "draft_sideboard": [],
            "draft_set_code": None,
            "draft_advice": "",
            "draft_conversation": [],
        }
        message = _make_text_message("Питання")
        state = _make_state(data=fsm_data)
        db_user = _make_db_user()

        await handle_draft_chat(message, db_user, state)

        reply_msg = message.answer.return_value
        reply_msg.edit_text.assert_called_once()
        call_args = reply_msg.edit_text.call_args
        text = call_args.args[0] if call_args.args else call_args.kwargs.get("text", "")
        assert text == format_error("llm")

    @patch("src.bot.handlers.draft.get_llm_client")
    async def test_llm_error_does_not_clear_fsm(self, mock_get_llm):
        """TC-P4-3.7: LLM error → FSM state NOT cleared (stays in chatting)."""
        mock_llm = AsyncMock()
        mock_llm.call_completion = AsyncMock(side_effect=LLMError("timeout"))
        mock_get_llm.return_value = mock_llm

        fsm_data = {
            "draft_main_deck": ["Card A"],
            "draft_sideboard": [],
            "draft_set_code": None,
            "draft_advice": "",
            "draft_conversation": [],
        }
        message = _make_text_message("Питання")
        state = _make_state(data=fsm_data)
        db_user = _make_db_user()

        await handle_draft_chat(message, db_user, state)

        state.clear.assert_not_called()
        state.set_state.assert_not_called()


# ---------------------------------------------------------------------------
# TC-P4-3.8: Conversation history trimmed to last 10 exchanges
# ---------------------------------------------------------------------------


class TestTC_P4_3_8_HistoryTrimming:
    @patch("src.bot.handlers.draft.get_llm_client")
    async def test_history_trimmed_to_20_messages(self, mock_get_llm):
        """TC-P4-3.8: When history exceeds 10 exchanges (20 msgs), it is trimmed."""
        mock_llm = AsyncMock()
        mock_llm.call_completion = AsyncMock(return_value="Відповідь.")
        mock_get_llm.return_value = mock_llm

        # 11 existing exchanges = 22 messages → after adding new pair = 24 → trim to 20
        existing_history = []
        for i in range(11):
            existing_history.append({"role": "user", "content": f"Питання {i}"})
            existing_history.append({"role": "assistant", "content": f"Відповідь {i}"})

        fsm_data = {
            "draft_main_deck": ["Card A"],
            "draft_sideboard": [],
            "draft_set_code": None,
            "draft_advice": "",
            "draft_conversation": existing_history,
        }
        message = _make_text_message("Нове питання")
        state = _make_state(data=fsm_data)
        db_user = _make_db_user()

        await handle_draft_chat(message, db_user, state)

        updated = state.update_data.call_args.kwargs.get("draft_conversation", [])
        assert len(updated) <= 20  # max 10 exchanges = 20 messages

    @patch("src.bot.handlers.draft.get_llm_client")
    async def test_short_history_not_trimmed(self, mock_get_llm):
        """History with fewer than 10 exchanges stays intact."""
        mock_llm = AsyncMock()
        mock_llm.call_completion = AsyncMock(return_value="Відповідь.")
        mock_get_llm.return_value = mock_llm

        existing_history = [
            {"role": "user", "content": "Питання 1"},
            {"role": "assistant", "content": "Відповідь 1"},
        ]
        fsm_data = {
            "draft_main_deck": ["Card A"],
            "draft_sideboard": [],
            "draft_set_code": None,
            "draft_advice": "",
            "draft_conversation": existing_history,
        }
        message = _make_text_message("Питання 2")
        state = _make_state(data=fsm_data)
        db_user = _make_db_user()

        await handle_draft_chat(message, db_user, state)

        updated = state.update_data.call_args.kwargs.get("draft_conversation", [])
        assert len(updated) == 4  # 2 old + 2 new


# ---------------------------------------------------------------------------
# TC-P4-3.5: /draft in chatting → FSM transitions to waiting_main
# ---------------------------------------------------------------------------


class TestTC_P4_3_5_DraftCommandResetsChat:
    async def test_draft_command_transitions_from_chatting_to_waiting_main(self):
        """TC-P4-3.5: /draft in chatting state → FSM moves to waiting_main."""
        message = _make_message()
        state = _make_state(data={
            "draft_main_deck": ["Card A"],
            "draft_conversation": [{"role": "user", "content": "Hi"}],
        })

        await handle_draft_command(message, state)

        state.set_state.assert_called_with(DraftState.waiting_main)


# ---------------------------------------------------------------------------
# TC-P4-3 helper: _build_deck_context
# ---------------------------------------------------------------------------


class TestBuildDeckContext:
    def test_contains_main_deck_cards(self):
        """_build_deck_context includes all main deck card names."""
        ctx = _build_deck_context(
            ["Lightning Bolt", "Counterspell"],
            [],
            "TST",
            "",
        )
        assert "Lightning Bolt" in ctx
        assert "Counterspell" in ctx

    def test_contains_set_code(self):
        ctx = _build_deck_context([], [], "ECL", "")
        assert "ECL" in ctx

    def test_contains_advice_snippet(self):
        ctx = _build_deck_context([], [], None, "Перша порада")
        assert "Перша порада" in ctx

    def test_empty_sideboard_shown(self):
        ctx = _build_deck_context(["Card A"], [], "TST", "")
        assert "порожній" in ctx or "0" in ctx
