"""
Unit tests for P4-5: Better Advice Generation Status Indicator.

Acceptance criteria covered:
- TC-P4-5.1: After pressing "Отримати поради", a persistent message indicator
              appears in chat (not only a disappearing popup).
- TC-P4-5.2: After advice is generated, the indicator message is replaced
              with the advice text.
- TC-P4-5.3: Cached advice → popup only, no persistent indicator sent.
- TC-P4-5.4: LLM error → indicator message updated with friendly error.
- TC-P4-5.5: message.answer is called (for indicator) BEFORE the LLM call.
"""

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from src.bot.handlers.analyze import handle_get_advice
from src.llm.exceptions import LLMError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_callback(data: str = "get_advice:42") -> MagicMock:
    """Return a mocked aiogram CallbackQuery."""
    cb = MagicMock()
    cb.data = data
    cb.answer = AsyncMock()

    # callback.message — the original report message
    report_msg = AsyncMock()
    report_msg.answer = AsyncMock()
    report_msg.edit_reply_markup = AsyncMock()
    cb.message = report_msg

    return cb


def _make_db_user(user_id: int = 1, telegram_id: int = 12345) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.telegram_id = telegram_id
    user.active_set_code = "ECL"
    return user


def _make_state() -> AsyncMock:
    """Return a mocked aiogram FSMContext."""
    state = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    state.set_state = AsyncMock()
    state.update_data = AsyncMock()
    state.clear = AsyncMock()
    return state


def _make_analysis(
    analysis_id: int = 42,
    user_id: int = 1,
    advice: str | None = None,
    main_deck: list[str] | None = None,
) -> MagicMock:
    """Return a mocked DB Analysis object."""
    analysis = MagicMock()
    analysis.id = analysis_id
    analysis.user_id = user_id
    analysis.advice = advice
    analysis.main_deck = main_deck or ["Lightning Bolt", "Counterspell", "Serra Angel"]
    analysis.sideboard = []
    analysis.set = MagicMock()
    analysis.set.code = "ECL"
    return analysis


def _patch_get_session(analysis: MagicMock):
    """Context manager that returns a session with the given analysis."""
    mock_repo = AsyncMock()
    mock_repo.get_by_id = AsyncMock(return_value=analysis)

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    return mock_cm, mock_repo


# ---------------------------------------------------------------------------
# TC-P4-5.1: Persistent indicator appears before LLM call
# TC-P4-5.5: message.answer called BEFORE LLM generate_advice
# ---------------------------------------------------------------------------


class TestTC_P4_5_1_and_5_5_IndicatorBeforeLLM:
    @patch("src.bot.handlers.analyze.DeckAdvisor")
    @patch("src.bot.handlers.analyze.DeckAnalyzer")
    @patch("src.bot.handlers.analyze._enrich_cards", new_callable=AsyncMock)
    @patch("src.bot.handlers.analyze.AnalysisRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_indicator_message_sent_before_llm(
        self,
        mock_get_session,
        MockAnalysisRepo,
        mock_enrich,
        MockAnalyzer,
        MockAdvisor,
    ):
        """TC-P4-5.1 + TC-P4-5.5: persistent indicator is sent before LLM call."""
        analysis = _make_analysis(advice=None)
        mock_cm, mock_repo = _patch_get_session(analysis)
        mock_get_session.return_value = mock_cm
        MockAnalysisRepo.return_value = mock_repo

        mock_enrich.return_value = ([], None)
        MockAnalyzer.return_value.analyze = MagicMock(return_value=MagicMock())

        call_order: list[str] = []

        # Track when indicator is sent
        indicator_msg = AsyncMock()
        indicator_msg.edit_text = AsyncMock()

        async def fake_answer(text, **kwargs):
            call_order.append("indicator_sent")
            return indicator_msg

        # Track when LLM is called
        async def fake_generate_advice(*args, **kwargs):
            call_order.append("llm_called")
            return "Тестові рекомендації"

        callback = _make_callback()
        callback.message.answer = AsyncMock(side_effect=fake_answer)

        mock_advisor = AsyncMock()
        mock_advisor.generate_advice = AsyncMock(side_effect=fake_generate_advice)
        MockAdvisor.return_value = mock_advisor

        db_user = _make_db_user()

        with patch("src.bot.handlers.analyze.recommend_lands", return_value=MagicMock()):
            with patch("src.bot.handlers.analyze.get_llm_client"):
                await handle_get_advice(callback, db_user, _make_state())

        assert "indicator_sent" in call_order, "Indicator message was never sent"
        assert "llm_called" in call_order, "LLM was never called"
        indicator_idx = call_order.index("indicator_sent")
        llm_idx = call_order.index("llm_called")
        assert indicator_idx < llm_idx, (
            "message.answer (indicator) must be called BEFORE LLM generate_advice"
        )

    @patch("src.bot.handlers.analyze.DeckAdvisor")
    @patch("src.bot.handlers.analyze.DeckAnalyzer")
    @patch("src.bot.handlers.analyze._enrich_cards", new_callable=AsyncMock)
    @patch("src.bot.handlers.analyze.AnalysisRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_indicator_text_contains_loading_hint(
        self,
        mock_get_session,
        MockAnalysisRepo,
        mock_enrich,
        MockAnalyzer,
        MockAdvisor,
    ):
        """TC-P4-5.1: The indicator message text conveys loading / processing."""
        analysis = _make_analysis(advice=None)
        mock_cm, mock_repo = _patch_get_session(analysis)
        mock_get_session.return_value = mock_cm
        MockAnalysisRepo.return_value = mock_repo

        mock_enrich.return_value = ([], None)
        MockAnalyzer.return_value.analyze = MagicMock(return_value=MagicMock())

        indicator_msg = AsyncMock()
        indicator_msg.edit_text = AsyncMock()
        callback = _make_callback()
        callback.message.answer = AsyncMock(return_value=indicator_msg)

        mock_advisor = AsyncMock()
        mock_advisor.generate_advice = AsyncMock(return_value="Поради")
        MockAdvisor.return_value = mock_advisor

        db_user = _make_db_user()

        with patch("src.bot.handlers.analyze.recommend_lands", return_value=MagicMock()):
            with patch("src.bot.handlers.analyze.get_llm_client"):
                await handle_get_advice(callback, db_user, _make_state())

        callback.message.answer.assert_called_once()
        indicator_text = callback.message.answer.call_args.args[0]
        assert "⏳" in indicator_text or "Генерую" in indicator_text


# ---------------------------------------------------------------------------
# TC-P4-5.2: Indicator replaced with advice after generation
# ---------------------------------------------------------------------------


class TestTC_P4_5_2_IndicatorReplacedWithAdvice:
    @patch("src.bot.handlers.analyze.DeckAdvisor")
    @patch("src.bot.handlers.analyze.DeckAnalyzer")
    @patch("src.bot.handlers.analyze._enrich_cards", new_callable=AsyncMock)
    @patch("src.bot.handlers.analyze.AnalysisRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_indicator_edited_with_advice_text(
        self,
        mock_get_session,
        MockAnalysisRepo,
        mock_enrich,
        MockAnalyzer,
        MockAdvisor,
    ):
        """TC-P4-5.2: After LLM generates advice, indicator.edit_text is called with it."""
        advice_text = "Ця дека дуже сильна, але забракує вінрейту."
        analysis = _make_analysis(advice=None)
        mock_cm, mock_repo = _patch_get_session(analysis)
        mock_get_session.return_value = mock_cm
        MockAnalysisRepo.return_value = mock_repo

        mock_enrich.return_value = ([], None)
        MockAnalyzer.return_value.analyze = MagicMock(return_value=MagicMock())

        indicator_msg = AsyncMock()
        indicator_msg.edit_text = AsyncMock()
        callback = _make_callback()
        callback.message.answer = AsyncMock(return_value=indicator_msg)

        mock_advisor = AsyncMock()
        mock_advisor.generate_advice = AsyncMock(return_value=advice_text)
        MockAdvisor.return_value = mock_advisor

        db_user = _make_db_user()

        with patch("src.bot.handlers.analyze.recommend_lands", return_value=MagicMock()):
            with patch("src.bot.handlers.analyze.get_llm_client"):
                await handle_get_advice(callback, db_user, _make_state())

        indicator_msg.edit_text.assert_called_once()
        edited_text = indicator_msg.edit_text.call_args.args[0]
        assert advice_text in edited_text

    @patch("src.bot.handlers.analyze.DeckAdvisor")
    @patch("src.bot.handlers.analyze.DeckAnalyzer")
    @patch("src.bot.handlers.analyze._enrich_cards", new_callable=AsyncMock)
    @patch("src.bot.handlers.analyze.AnalysisRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_keyboard_updated_after_advice(
        self,
        mock_get_session,
        MockAnalysisRepo,
        mock_enrich,
        MockAnalyzer,
        MockAdvisor,
    ):
        """TC-P4-5.2: After advice generated, report keyboard is updated."""
        analysis = _make_analysis(advice=None)
        mock_cm, mock_repo = _patch_get_session(analysis)
        mock_get_session.return_value = mock_cm
        MockAnalysisRepo.return_value = mock_repo

        mock_enrich.return_value = ([], None)
        MockAnalyzer.return_value.analyze = MagicMock(return_value=MagicMock())

        indicator_msg = AsyncMock()
        indicator_msg.edit_text = AsyncMock()
        callback = _make_callback()
        callback.message.answer = AsyncMock(return_value=indicator_msg)

        mock_advisor = AsyncMock()
        mock_advisor.generate_advice = AsyncMock(return_value="Поради")
        MockAdvisor.return_value = mock_advisor

        db_user = _make_db_user()

        with patch("src.bot.handlers.analyze.recommend_lands", return_value=MagicMock()):
            with patch("src.bot.handlers.analyze.get_llm_client"):
                await handle_get_advice(callback, db_user, _make_state())

        callback.message.edit_reply_markup.assert_called_once()


# ---------------------------------------------------------------------------
# TC-P4-5.3: Cached advice → popup only, no persistent indicator
# ---------------------------------------------------------------------------


class TestTC_P4_5_3_CachedAdvice:
    @patch("src.bot.handlers.analyze.AnalysisRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_cached_advice_no_indicator_message(
        self, mock_get_session, MockAnalysisRepo
    ):
        """TC-P4-5.3: Cached advice → no loading indicator sent.

        _send_advice still calls callback.message.answer to deliver the advice,
        but it must NOT be called first with a loading indicator text.
        The answer should be the advice itself (single call, no ⏳ prefix).
        """
        cached_advice = "Вже згенеровані поради."
        analysis = _make_analysis(advice=cached_advice)
        mock_cm, mock_repo = _patch_get_session(analysis)
        mock_get_session.return_value = mock_cm
        MockAnalysisRepo.return_value = mock_repo

        callback = _make_callback()
        db_user = _make_db_user()

        await handle_get_advice(callback, db_user, _make_state())

        # answer is called exactly once — to deliver advice, not a loading indicator
        callback.message.answer.assert_called_once()
        advice_call_text = callback.message.answer.call_args.args[0]
        assert "⏳" not in advice_call_text, "Indicator '⏳' must not appear for cached advice"
        assert "Генерую" not in advice_call_text, "Loading text must not appear for cached advice"
        assert cached_advice in advice_call_text

    @patch("src.bot.handlers.analyze.AnalysisRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_cached_advice_uses_popup(
        self, mock_get_session, MockAnalysisRepo
    ):
        """TC-P4-5.3: Cached advice → callback.answer called (popup)."""
        cached_advice = "Вже згенеровані поради."
        analysis = _make_analysis(advice=cached_advice)
        mock_cm, mock_repo = _patch_get_session(analysis)
        mock_get_session.return_value = mock_cm
        MockAnalysisRepo.return_value = mock_repo

        callback = _make_callback()
        db_user = _make_db_user()

        await handle_get_advice(callback, db_user, _make_state())

        callback.answer.assert_called_once()


# ---------------------------------------------------------------------------
# TC-P4-5.4: LLM error → indicator updated with error message
# ---------------------------------------------------------------------------


class TestTC_P4_5_4_LLMError:
    @patch("src.bot.handlers.analyze.DeckAdvisor")
    @patch("src.bot.handlers.analyze.DeckAnalyzer")
    @patch("src.bot.handlers.analyze._enrich_cards", new_callable=AsyncMock)
    @patch("src.bot.handlers.analyze.AnalysisRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_llm_error_updates_indicator(
        self,
        mock_get_session,
        MockAnalysisRepo,
        mock_enrich,
        MockAnalyzer,
        MockAdvisor,
    ):
        """TC-P4-5.4: On LLMError, indicator message is updated with error text."""
        analysis = _make_analysis(advice=None)
        mock_cm, mock_repo = _patch_get_session(analysis)
        mock_get_session.return_value = mock_cm
        MockAnalysisRepo.return_value = mock_repo

        mock_enrich.return_value = ([], None)
        MockAnalyzer.return_value.analyze = MagicMock(return_value=MagicMock())

        indicator_msg = AsyncMock()
        indicator_msg.edit_text = AsyncMock()
        callback = _make_callback()
        callback.message.answer = AsyncMock(return_value=indicator_msg)

        mock_advisor = AsyncMock()
        mock_advisor.generate_advice = AsyncMock(side_effect=LLMError("API error"))
        MockAdvisor.return_value = mock_advisor

        db_user = _make_db_user()

        with patch("src.bot.handlers.analyze.recommend_lands", return_value=MagicMock()):
            with patch("src.bot.handlers.analyze.get_llm_client"):
                await handle_get_advice(callback, db_user, _make_state())

        # Indicator must be edited with an error message (not a new answer)
        indicator_msg.edit_text.assert_called_once()
        # callback.message.answer was called once for the indicator, not again for error
        callback.message.answer.assert_called_once()

    @patch("src.bot.handlers.analyze.DeckAdvisor")
    @patch("src.bot.handlers.analyze.DeckAnalyzer")
    @patch("src.bot.handlers.analyze._enrich_cards", new_callable=AsyncMock)
    @patch("src.bot.handlers.analyze.AnalysisRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_llm_error_indicator_not_left_as_loading(
        self,
        mock_get_session,
        MockAnalysisRepo,
        mock_enrich,
        MockAnalyzer,
        MockAdvisor,
    ):
        """TC-P4-5.4: Indicator not left as '⏳ Генерую...' after error."""
        analysis = _make_analysis(advice=None)
        mock_cm, mock_repo = _patch_get_session(analysis)
        mock_get_session.return_value = mock_cm
        MockAnalysisRepo.return_value = mock_repo

        mock_enrich.return_value = ([], None)
        MockAnalyzer.return_value.analyze = MagicMock(return_value=MagicMock())

        indicator_msg = AsyncMock()
        indicator_msg.edit_text = AsyncMock()
        callback = _make_callback()
        callback.message.answer = AsyncMock(return_value=indicator_msg)

        mock_advisor = AsyncMock()
        mock_advisor.generate_advice = AsyncMock(side_effect=LLMError("quota exceeded"))
        MockAdvisor.return_value = mock_advisor

        db_user = _make_db_user()

        with patch("src.bot.handlers.analyze.recommend_lands", return_value=MagicMock()):
            with patch("src.bot.handlers.analyze.get_llm_client"):
                await handle_get_advice(callback, db_user, _make_state())

        error_text = indicator_msg.edit_text.call_args.args[0]
        assert "⏳" not in error_text, "Indicator must not remain as loading on error"
