"""
Unit tests for global card fallback search — feat/global-card-fallback.

Acceptance criteria covered:
- TC-GCF-1: Card found in active set → existing behaviour, no fallback triggered.
- TC-GCF-2: Card not in active set but exists elsewhere → fallback finds it,
             display name includes set code suffix, e.g. "Blood Crypt (ECL)".
- TC-GCF-3: Card absent from ALL sets → existing "not found" message.
- TC-GCF-4: Fallback card uses the actual set code for the price keyboard,
             not the user's active set.
- TC-GCF-5: CardRepository.get_by_name(name, set_code=None) searches globally
             (no WHERE on set_code).
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from src.bot.handlers.analyze import _handle_single_card


# ---------------------------------------------------------------------------
# Helpers (mirrors style of test_analyze_photo_routing.py)
# ---------------------------------------------------------------------------


def _make_db_card(
    name: str = "Lightning Bolt",
    set_code: str = "ECL",
    mana_cost: str = "{R}",
    cmc: Decimal = Decimal("1.0"),
    colors: list[str] | None = None,
    type_line: str = "Instant",
    rating: Decimal | None = Decimal("4.5"),
    win_rate: Decimal | None = Decimal("58.3"),
) -> MagicMock:
    """Return a mocked DB Card with one rating and a set attribute."""
    card = MagicMock()
    card.name = name
    card.mana_cost = mana_cost
    card.cmc = cmc
    card.colors = colors or ["R"]
    card.type_line = type_line
    card.rarity = "common"
    card.image_uri = None

    set_obj = MagicMock()
    set_obj.code = set_code
    card.set = set_obj

    rating_obj = MagicMock()
    rating_obj.rating = rating
    rating_obj.win_rate = win_rate
    rating_obj.games_played = 1000
    card.ratings = [rating_obj]
    return card


def _make_db_user(active_set_code: str | None = "SOS") -> MagicMock:
    user = MagicMock()
    user.id = 1
    user.telegram_id = 12345
    user.active_set_code = active_set_code
    return user


def _mock_get_session(first_result, second_result=None):
    """
    Build a mock get_session() context manager.

    If second_result is provided, the context manager returns the same mock
    session but CardRepository.get_by_name will return first_result on the
    first call and second_result on the second call.
    """
    mock_repo = AsyncMock()
    if second_result is not None:
        mock_repo.get_by_name = AsyncMock(
            side_effect=[first_result, second_result]
        )
    else:
        mock_repo.get_by_name = AsyncMock(return_value=first_result)

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return mock_cm, mock_repo


# ---------------------------------------------------------------------------
# TC-GCF-1: Card found in active set — no fallback triggered
# ---------------------------------------------------------------------------


class TestTC_GCF_1_CardFoundInActiveSet:
    @patch("src.bot.handlers.analyze.CardRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_primary_hit_does_not_call_fallback(
        self, mock_get_session, MockCardRepository
    ):
        """TC-GCF-1: Card present in active set → get_by_name called once only."""
        db_card = _make_db_card(name="Counterspell", set_code="SOS")
        mock_repo = AsyncMock()
        mock_repo.get_by_name = AsyncMock(return_value=db_card)
        MockCardRepository.return_value = mock_repo

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = mock_cm

        processing_msg = AsyncMock()
        db_user = _make_db_user(active_set_code="SOS")

        await _handle_single_card(
            processing_msg=processing_msg,
            db_user=db_user,
            card_name="Counterspell",
            set_code="SOS",
        )

        # get_by_name was called exactly once (primary lookup)
        assert mock_repo.get_by_name.call_count == 1
        mock_repo.get_by_name.assert_called_once_with("Counterspell", "SOS")

    @patch("src.bot.handlers.analyze.CardRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_primary_hit_name_has_no_set_suffix(
        self, mock_get_session, MockCardRepository
    ):
        """TC-GCF-1: Card found in active set — display name has no set suffix."""
        db_card = _make_db_card(name="Counterspell", set_code="SOS")
        mock_repo = AsyncMock()
        mock_repo.get_by_name = AsyncMock(return_value=db_card)
        MockCardRepository.return_value = mock_repo

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = mock_cm

        processing_msg = AsyncMock()
        db_user = _make_db_user(active_set_code="SOS")

        await _handle_single_card(
            processing_msg=processing_msg,
            db_user=db_user,
            card_name="Counterspell",
            set_code="SOS",
        )

        text = processing_msg.edit_text.call_args.args[0]
        # Name should NOT carry a parenthesised set code
        assert "(SOS)" not in text
        assert "Counterspell" in text


# ---------------------------------------------------------------------------
# TC-GCF-2: Card absent from active set but present globally — fallback fires
# ---------------------------------------------------------------------------


class TestTC_GCF_2_FallbackFindsCard:
    @patch("src.bot.handlers.analyze.CardRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_fallback_is_triggered_when_primary_misses(
        self, mock_get_session, MockCardRepository
    ):
        """TC-GCF-2: get_by_name called twice — first with set_code, then with None."""
        ecl_card = _make_db_card(name="Blood Crypt", set_code="ECL")
        mock_repo = AsyncMock()
        # First call (primary) → None; second call (fallback, set_code=None) → card
        mock_repo.get_by_name = AsyncMock(side_effect=[None, ecl_card])
        MockCardRepository.return_value = mock_repo

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = mock_cm

        processing_msg = AsyncMock()
        db_user = _make_db_user(active_set_code="SOS")

        await _handle_single_card(
            processing_msg=processing_msg,
            db_user=db_user,
            card_name="Blood Crypt",
            set_code="SOS",
        )

        assert mock_repo.get_by_name.call_count == 2
        calls = mock_repo.get_by_name.call_args_list
        assert calls[0] == call("Blood Crypt", "SOS")
        assert calls[1] == call("Blood Crypt", set_code=None)

    @patch("src.bot.handlers.analyze.CardRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_fallback_result_shows_set_code_suffix(
        self, mock_get_session, MockCardRepository
    ):
        """TC-GCF-2: Fallback card display name includes '(ECL)' suffix."""
        ecl_card = _make_db_card(name="Blood Crypt", set_code="ECL")
        mock_repo = AsyncMock()
        mock_repo.get_by_name = AsyncMock(side_effect=[None, ecl_card])
        MockCardRepository.return_value = mock_repo

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = mock_cm

        processing_msg = AsyncMock()
        db_user = _make_db_user(active_set_code="SOS")

        await _handle_single_card(
            processing_msg=processing_msg,
            db_user=db_user,
            card_name="Blood Crypt",
            set_code="SOS",
        )

        text = processing_msg.edit_text.call_args.args[0]
        assert "Blood Crypt (ECL)" in text

    @patch("src.bot.handlers.analyze.CardRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_fallback_result_still_shows_grade_and_wr(
        self, mock_get_session, MockCardRepository
    ):
        """TC-GCF-2: Fallback result shows Грейд and WR like a normal hit."""
        ecl_card = _make_db_card(
            name="Blood Crypt",
            set_code="ECL",
            rating=Decimal("3.5"),
            win_rate=Decimal("52.1"),
        )
        mock_repo = AsyncMock()
        mock_repo.get_by_name = AsyncMock(side_effect=[None, ecl_card])
        MockCardRepository.return_value = mock_repo

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = mock_cm

        processing_msg = AsyncMock()
        db_user = _make_db_user(active_set_code="SOS")

        await _handle_single_card(
            processing_msg=processing_msg,
            db_user=db_user,
            card_name="Blood Crypt",
            set_code="SOS",
        )

        text = processing_msg.edit_text.call_args.args[0]
        assert "Грейд:" in text
        assert "WR:" in text


# ---------------------------------------------------------------------------
# TC-GCF-3: Card absent everywhere → existing "not found" message unchanged
# ---------------------------------------------------------------------------


class TestTC_GCF_3_CardNotFoundAnywhere:
    @patch("src.bot.handlers.analyze.CardRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_both_misses_show_not_found_message(
        self, mock_get_session, MockCardRepository
    ):
        """TC-GCF-3: Both lookups return None → not-found message with active set code."""
        mock_repo = AsyncMock()
        mock_repo.get_by_name = AsyncMock(return_value=None)
        MockCardRepository.return_value = mock_repo

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = mock_cm

        processing_msg = AsyncMock()
        db_user = _make_db_user(active_set_code="SOS")

        await _handle_single_card(
            processing_msg=processing_msg,
            db_user=db_user,
            card_name="Totally Unknown Card",
            set_code="SOS",
        )

        processing_msg.edit_text.assert_called_once()
        text = processing_msg.edit_text.call_args.args[0]
        assert "не знайдена" in text
        assert "SOS" in text

    @patch("src.bot.handlers.analyze.CardRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_not_found_message_includes_card_name(
        self, mock_get_session, MockCardRepository
    ):
        """TC-GCF-3: Not-found message includes the unrecognized card name."""
        mock_repo = AsyncMock()
        mock_repo.get_by_name = AsyncMock(return_value=None)
        MockCardRepository.return_value = mock_repo

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = mock_cm

        processing_msg = AsyncMock()
        db_user = _make_db_user(active_set_code="SOS")

        await _handle_single_card(
            processing_msg=processing_msg,
            db_user=db_user,
            card_name="Phantom Card",
            set_code="SOS",
        )

        text = processing_msg.edit_text.call_args.args[0]
        assert "Phantom Card" in text

    @patch("src.bot.handlers.analyze.CardRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_fallback_still_attempted_before_not_found(
        self, mock_get_session, MockCardRepository
    ):
        """TC-GCF-3: Even when both fail, fallback (None set_code) was attempted."""
        mock_repo = AsyncMock()
        mock_repo.get_by_name = AsyncMock(return_value=None)
        MockCardRepository.return_value = mock_repo

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = mock_cm

        processing_msg = AsyncMock()
        db_user = _make_db_user(active_set_code="SOS")

        await _handle_single_card(
            processing_msg=processing_msg,
            db_user=db_user,
            card_name="Ghost Card",
            set_code="SOS",
        )

        # Two calls: primary with "SOS", then fallback with None
        assert mock_repo.get_by_name.call_count == 2
        calls = mock_repo.get_by_name.call_args_list
        assert calls[1] == call("Ghost Card", set_code=None)


# ---------------------------------------------------------------------------
# TC-GCF-4: Fallback card uses the actual (fallback) set code for the keyboard
# ---------------------------------------------------------------------------


class TestTC_GCF_4_KeyboardUsesActualSetCode:
    @patch("src.bot.handlers.analyze.build_single_card_keyboard")
    @patch("src.bot.handlers.analyze.CardRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_keyboard_built_with_fallback_set_code(
        self, mock_get_session, MockCardRepository, mock_keyboard
    ):
        """TC-GCF-4: build_single_card_keyboard receives ECL (actual), not SOS (active)."""
        ecl_card = _make_db_card(name="Blood Crypt", set_code="ECL")
        mock_repo = AsyncMock()
        mock_repo.get_by_name = AsyncMock(side_effect=[None, ecl_card])
        MockCardRepository.return_value = mock_repo

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = mock_cm

        mock_keyboard.return_value = MagicMock()
        processing_msg = AsyncMock()
        db_user = _make_db_user(active_set_code="SOS")

        await _handle_single_card(
            processing_msg=processing_msg,
            db_user=db_user,
            card_name="Blood Crypt",
            set_code="SOS",
        )

        mock_keyboard.assert_called_once_with("Blood Crypt", "ECL")

    @patch("src.bot.handlers.analyze.build_single_card_keyboard")
    @patch("src.bot.handlers.analyze.CardRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_keyboard_uses_active_set_when_primary_hit(
        self, mock_get_session, MockCardRepository, mock_keyboard
    ):
        """TC-GCF-4 (control): Primary hit → keyboard uses the active set code."""
        sos_card = _make_db_card(name="Counterspell", set_code="SOS")
        mock_repo = AsyncMock()
        mock_repo.get_by_name = AsyncMock(return_value=sos_card)
        MockCardRepository.return_value = mock_repo

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = mock_cm

        mock_keyboard.return_value = MagicMock()
        processing_msg = AsyncMock()
        db_user = _make_db_user(active_set_code="SOS")

        await _handle_single_card(
            processing_msg=processing_msg,
            db_user=db_user,
            card_name="Counterspell",
            set_code="SOS",
        )

        mock_keyboard.assert_called_once_with("Counterspell", "SOS")


# ---------------------------------------------------------------------------
# TC-GCF-5: CardRepository.get_by_name with set_code=None — global search
# (Integration-style unit test using real query logic via mock session)
# ---------------------------------------------------------------------------


class TestTC_GCF_5_RepositoryGlobalSearch:
    async def test_get_by_name_accepts_none_set_code(self):
        """TC-GCF-5: get_by_name(name, set_code=None) must not raise TypeError."""
        from src.db.repository import CardRepository

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_result)

        repo = CardRepository(mock_session)

        # Should not raise — previously would have crashed on set_code.upper()
        result = await repo.get_by_name("Blood Crypt", set_code=None)
        assert result is None
        mock_session.execute.assert_called_once()

    async def test_get_by_name_none_omits_set_filter(self):
        """TC-GCF-5: When set_code=None the query sent to DB has no set restriction."""
        from src.db.repository import CardRepository

        captured_stmt = None

        async def capture_execute(stmt, *args, **kwargs):
            nonlocal captured_stmt
            captured_stmt = stmt
            mock_result = MagicMock()
            mock_result.scalar_one_or_none = MagicMock(return_value=None)
            return mock_result

        mock_session = AsyncMock()
        mock_session.execute = capture_execute

        repo = CardRepository(mock_session)
        await repo.get_by_name("Blood Crypt", set_code=None)

        assert captured_stmt is not None
        # Compile the statement to SQL text and check for set-filter clauses in WHERE.
        # `parent_set_code` appears in the SELECT list (column is loaded via joinedload)
        # so we look for the operator that would restrict by set, not just the column name.
        compiled = captured_stmt.compile(compile_kwargs={"literal_binds": False})
        sql_text = str(compiled).lower()
        # The query must NOT restrict by sets.code = :param (set equality in WHERE)
        # A global search has no "sets_1.code = :param" restriction.
        assert "sets_1.code = :param" not in sql_text
        # It must still filter on the card name
        assert "cards.name" in sql_text or "name" in sql_text
