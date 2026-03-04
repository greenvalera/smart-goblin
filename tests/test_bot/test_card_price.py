"""
Unit tests for Card Price Button — P4-6.

Acceptance criteria covered:
- TC-P4-6.1: Single card result shows "💰 Актуальна ціна" button.
- TC-P4-6.2: Button press → HTTP GET to Scryfall /cards/named.
- TC-P4-6.3: Response shows USD and EUR prices.
- TC-P4-6.4: Both prices null → "Ціна недоступна для цієї карти".
- TC-P4-6.5: Keyboard includes TCGPlayer and Cardmarket purchase URL buttons.
- TC-P4-6.6: Network error/timeout → friendly error message, no crash.
- TC-P4-6.7: callback_data does not exceed 64 bytes.
- TC-P4-6.8: 404 from Scryfall → "Карту не знайдено на Scryfall".
- TC-P4-6.9: Response text formatting with mock HTTP response.
"""

from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.bot.handlers.analyze import _handle_single_card, handle_card_price
from src.bot.keyboards import build_card_price_keyboard, build_single_card_keyboard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db_card(
    name: str = "Lightning Bolt",
    rating: Decimal | None = Decimal("4.5"),
    win_rate: Decimal | None = Decimal("58.3"),
    cmc: Decimal | None = Decimal("1.0"),
    colors: list[str] | None = None,
    type_line: str = "Instant",
) -> MagicMock:
    card = MagicMock()
    card.name = name
    card.mana_cost = "{R}"
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


def _make_db_user() -> MagicMock:
    user = MagicMock()
    user.id = 1
    user.telegram_id = 12345
    user.active_set_code = "ECL"
    return user


def _make_callback(data: str = "card_price:ECL:Lightning Bolt") -> MagicMock:
    callback = MagicMock()
    callback.data = data
    callback.answer = AsyncMock()
    price_msg = AsyncMock()
    price_msg.edit_text = AsyncMock()
    msg = AsyncMock()
    msg.answer = AsyncMock(return_value=price_msg)
    callback.message = msg
    return callback


def _make_scryfall_response(
    name: str = "Lightning Bolt",
    usd: str | None = "2.80",
    eur: str | None = "1.47",
    tcgplayer_url: str | None = "https://www.tcgplayer.com/product/1",
    cardmarket_url: str | None = "https://www.cardmarket.com/en/Magic/Products/1",
) -> dict:
    return {
        "object": "card",
        "name": name,
        "prices": {
            "usd": usd,
            "eur": eur,
            "usd_foil": None,
            "eur_foil": None,
        },
        "purchase_uris": {
            "tcgplayer": tcgplayer_url,
            "cardmarket": cardmarket_url,
        },
    }


def _mock_http_client(
    status_code: int = 200,
    json_data: dict | None = None,
    side_effect: Exception | None = None,
):
    """Return a patch context for httpx.AsyncClient that returns the given response."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json = MagicMock(return_value=json_data or _make_scryfall_response())
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    if side_effect is not None:
        mock_client.get = AsyncMock(side_effect=side_effect)
    else:
        mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    return patch("src.bot.handlers.analyze.httpx.AsyncClient", return_value=mock_client), mock_client


# ---------------------------------------------------------------------------
# TC-P4-6.1: Single card result shows the price button
# ---------------------------------------------------------------------------


class TestTC_P4_6_1_PriceButtonVisible:
    @patch("src.bot.handlers.analyze.CardRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_found_card_has_price_button(self, mock_get_session, MockCardRepository):
        """TC-P4-6.1: _handle_single_card attaches reply_markup with price button."""
        db_card = _make_db_card()
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
        kwargs = processing_msg.edit_text.call_args.kwargs
        assert "reply_markup" in kwargs
        assert kwargs["reply_markup"] is not None

    @patch("src.bot.handlers.analyze.CardRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_price_button_text_is_correct(self, mock_get_session, MockCardRepository):
        """TC-P4-6.1: Price button shows '💰 Актуальна ціна'."""
        db_card = _make_db_card()
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

        markup = processing_msg.edit_text.call_args.kwargs["reply_markup"]
        button = markup.inline_keyboard[0][0]
        assert button.text == "💰 Актуальна ціна"

    @patch("src.bot.handlers.analyze.CardRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_price_button_callback_data_format(self, mock_get_session, MockCardRepository):
        """TC-P4-6.1: Price button callback_data has format 'card_price:{set}:{name}'."""
        db_card = _make_db_card(name="Cryptic Command")
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
            card_name="Cryptic Command",
            set_code="ECL",
        )

        markup = processing_msg.edit_text.call_args.kwargs["reply_markup"]
        button = markup.inline_keyboard[0][0]
        assert button.callback_data == "card_price:ECL:Cryptic Command"

    @patch("src.bot.handlers.analyze.CardRepository")
    @patch("src.bot.handlers.analyze.get_session")
    async def test_card_not_found_has_no_price_button(self, mock_get_session, MockCardRepository):
        """TC-P4-6.1: Card not found → no price button in response."""
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

        kwargs = processing_msg.edit_text.call_args.kwargs
        assert kwargs.get("reply_markup") is None


# ---------------------------------------------------------------------------
# TC-P4-6.2: Button press → HTTP GET to Scryfall
# ---------------------------------------------------------------------------


class TestTC_P4_6_2_HttpRequest:
    async def test_button_press_makes_scryfall_request(self):
        """TC-P4-6.2: handle_card_price makes GET to Scryfall /cards/named."""
        patch_ctx, mock_client = _mock_http_client(
            json_data=_make_scryfall_response()
        )
        with patch_ctx:
            callback = _make_callback("card_price:ECL:Lightning Bolt")
            await handle_card_price(callback)

        mock_client.get.assert_called_once()
        call_kwargs = mock_client.get.call_args
        url = call_kwargs.args[0] if call_kwargs.args else ""
        params = call_kwargs.kwargs.get("params", {})
        assert "cards/named" in url
        assert params.get("exact") == "Lightning Bolt"
        assert params.get("set") == "ecl"

    async def test_answer_called_with_loading_text(self):
        """TC-P4-6.2: callback.answer called immediately to acknowledge button press."""
        patch_ctx, _ = _mock_http_client(json_data=_make_scryfall_response())
        with patch_ctx:
            callback = _make_callback()
            await handle_card_price(callback)

        callback.answer.assert_called_once()
        assert "Отримую" in callback.answer.call_args.args[0]


# ---------------------------------------------------------------------------
# TC-P4-6.3: USD and EUR prices shown
# ---------------------------------------------------------------------------


class TestTC_P4_6_3_PricesDisplayed:
    async def test_usd_price_shown(self):
        """TC-P4-6.3: USD price ($2.80) is shown in response."""
        patch_ctx, _ = _mock_http_client(
            json_data=_make_scryfall_response(usd="2.80")
        )
        with patch_ctx:
            callback = _make_callback()
            price_msg = callback.message.answer.return_value
            await handle_card_price(callback)

        text = price_msg.edit_text.call_args.args[0]
        assert "$2.80" in text

    async def test_eur_price_shown(self):
        """TC-P4-6.3: EUR price (€1.47) is shown in response."""
        patch_ctx, _ = _mock_http_client(
            json_data=_make_scryfall_response(eur="1.47")
        )
        with patch_ctx:
            callback = _make_callback()
            price_msg = callback.message.answer.return_value
            await handle_card_price(callback)

        text = price_msg.edit_text.call_args.args[0]
        assert "€1.47" in text

    async def test_response_shows_card_name_and_set(self):
        """TC-P4-6.3: Response header includes card name and set code."""
        patch_ctx, _ = _mock_http_client(
            json_data=_make_scryfall_response(name="Lightning Bolt")
        )
        with patch_ctx:
            callback = _make_callback("card_price:ECL:Lightning Bolt")
            price_msg = callback.message.answer.return_value
            await handle_card_price(callback)

        text = price_msg.edit_text.call_args.args[0]
        assert "Lightning Bolt" in text
        assert "ECL" in text


# ---------------------------------------------------------------------------
# TC-P4-6.4: Both prices null → "Ціна недоступна"
# ---------------------------------------------------------------------------


class TestTC_P4_6_4_BothPricesNull:
    async def test_both_null_shows_unavailable_message(self):
        """TC-P4-6.4: Both USD and EUR null → 'Ціна недоступна для цієї карти'."""
        patch_ctx, _ = _mock_http_client(
            json_data=_make_scryfall_response(usd=None, eur=None)
        )
        with patch_ctx:
            callback = _make_callback()
            price_msg = callback.message.answer.return_value
            await handle_card_price(callback)

        text = price_msg.edit_text.call_args.args[0]
        assert "недоступна" in text

    async def test_both_null_no_purchase_keyboard(self):
        """TC-P4-6.4: Both prices null → no purchase keyboard (None)."""
        patch_ctx, _ = _mock_http_client(
            json_data=_make_scryfall_response(
                usd=None, eur=None, tcgplayer_url=None, cardmarket_url=None
            )
        )
        with patch_ctx:
            callback = _make_callback()
            price_msg = callback.message.answer.return_value
            await handle_card_price(callback)

        kwargs = price_msg.edit_text.call_args.kwargs
        assert kwargs.get("reply_markup") is None


# ---------------------------------------------------------------------------
# TC-P4-6.5: Purchase links in keyboard
# ---------------------------------------------------------------------------


class TestTC_P4_6_5_PurchaseLinks:
    async def test_tcgplayer_url_in_keyboard(self):
        """TC-P4-6.5: TCGPlayer URL is present as keyboard button."""
        tcg_url = "https://www.tcgplayer.com/product/12345"
        patch_ctx, _ = _mock_http_client(
            json_data=_make_scryfall_response(tcgplayer_url=tcg_url)
        )
        with patch_ctx:
            callback = _make_callback()
            price_msg = callback.message.answer.return_value
            await handle_card_price(callback)

        markup = price_msg.edit_text.call_args.kwargs.get("reply_markup")
        assert markup is not None
        all_urls = [btn.url for row in markup.inline_keyboard for btn in row]
        assert tcg_url in all_urls

    async def test_cardmarket_url_in_keyboard(self):
        """TC-P4-6.5: Cardmarket URL is present as keyboard button."""
        cm_url = "https://www.cardmarket.com/en/Magic/Products/67890"
        patch_ctx, _ = _mock_http_client(
            json_data=_make_scryfall_response(cardmarket_url=cm_url)
        )
        with patch_ctx:
            callback = _make_callback()
            price_msg = callback.message.answer.return_value
            await handle_card_price(callback)

        markup = price_msg.edit_text.call_args.kwargs.get("reply_markup")
        assert markup is not None
        all_urls = [btn.url for row in markup.inline_keyboard for btn in row]
        assert cm_url in all_urls

    def test_build_card_price_keyboard_both_none_returns_none(self):
        """TC-P4-6.5: build_card_price_keyboard(None, None) → None."""
        result = build_card_price_keyboard(None, None)
        assert result is None

    def test_build_card_price_keyboard_one_url(self):
        """TC-P4-6.5: build_card_price_keyboard with only TCGPlayer URL."""
        markup = build_card_price_keyboard("https://tcgplayer.com/1", None)
        assert markup is not None
        buttons = markup.inline_keyboard[0]
        assert len(buttons) == 1
        assert buttons[0].url == "https://tcgplayer.com/1"


# ---------------------------------------------------------------------------
# TC-P4-6.6: Network error → friendly message
# ---------------------------------------------------------------------------


class TestTC_P4_6_6_NetworkError:
    async def test_timeout_shows_friendly_message(self):
        """TC-P4-6.6: Timeout → friendly message, no crash."""
        patch_ctx, _ = _mock_http_client(
            side_effect=httpx.TimeoutException("")
        )
        with patch_ctx:
            callback = _make_callback()
            price_msg = callback.message.answer.return_value
            await handle_card_price(callback)

        text = price_msg.edit_text.call_args.args[0]
        assert "Scryfall" in text or "Timeout" in text or "Спробуйте" in text

    async def test_network_error_shows_friendly_message(self):
        """TC-P4-6.6: Network error → friendly message, no crash."""
        patch_ctx, _ = _mock_http_client(
            side_effect=httpx.ConnectError("Connection refused")
        )
        with patch_ctx:
            callback = _make_callback()
            price_msg = callback.message.answer.return_value
            await handle_card_price(callback)

        text = price_msg.edit_text.call_args.args[0]
        assert "мережі" in text or "Спробуйте" in text


# ---------------------------------------------------------------------------
# TC-P4-6.7: callback_data ≤ 64 bytes
# ---------------------------------------------------------------------------


class TestTC_P4_6_7_CallbackDataLength:
    def test_normal_card_name_fits_64_bytes(self):
        """TC-P4-6.7: Typical card name produces callback_data ≤ 64 bytes."""
        markup = build_single_card_keyboard("Lightning Bolt", "ECL")
        cd = markup.inline_keyboard[0][0].callback_data
        assert len(cd.encode("utf-8")) <= 64

    def test_long_card_name_truncated_to_fit(self):
        """TC-P4-6.7: Very long card name is truncated to fit 64-byte limit."""
        long_name = "A" * 100  # 100-char name, far exceeds 64 bytes total
        markup = build_single_card_keyboard(long_name, "ECL")
        cd = markup.inline_keyboard[0][0].callback_data
        assert len(cd.encode("utf-8")) <= 64

    def test_common_set_code_cards_fit(self):
        """TC-P4-6.7: Real card names with real set codes fit in 64 bytes."""
        test_cases = [
            ("Emrakul, the Promised End", "EMN"),
            ("Teferi, Hero of Dominaria", "DOM"),
            ("Nicol Bolas, Planeswalker", "M13"),
            ("Thraximundar", "CMD"),
        ]
        for card_name, set_code in test_cases:
            markup = build_single_card_keyboard(card_name, set_code)
            cd = markup.inline_keyboard[0][0].callback_data
            assert len(cd.encode("utf-8")) <= 64, (
                f"callback_data for '{card_name}'/'{set_code}' "
                f"exceeds 64 bytes: {len(cd.encode())}"
            )


# ---------------------------------------------------------------------------
# TC-P4-6.8: 404 → "Карту не знайдено на Scryfall"
# ---------------------------------------------------------------------------


class TestTC_P4_6_8_NotFound:
    async def test_404_shows_not_found_message(self):
        """TC-P4-6.8: Scryfall returns 404 → 'Карту не знайдено на Scryfall'."""
        patch_ctx, _ = _mock_http_client(
            status_code=404,
            json_data={"object": "error", "code": "not_found"},
        )
        with patch_ctx:
            callback = _make_callback("card_price:ECL:Nonexistent Card")
            price_msg = callback.message.answer.return_value
            await handle_card_price(callback)

        text = price_msg.edit_text.call_args.args[0]
        assert "не знайдено" in text and "Scryfall" in text

    async def test_404_no_crash(self):
        """TC-P4-6.8: 404 response is handled gracefully (no exception raised)."""
        patch_ctx, _ = _mock_http_client(
            status_code=404,
            json_data={"object": "error"},
        )
        with patch_ctx:
            callback = _make_callback()
            # Should not raise
            await handle_card_price(callback)


# ---------------------------------------------------------------------------
# TC-P4-6.9: Response text formatting (mock HTTP)
# ---------------------------------------------------------------------------


class TestTC_P4_6_9_TextFormatting:
    async def test_full_response_format(self):
        """TC-P4-6.9: Response text matches expected format with USD, EUR, header."""
        patch_ctx, _ = _mock_http_client(
            json_data=_make_scryfall_response(
                name="Lightning Bolt",
                usd="2.80",
                eur="1.47",
            )
        )
        with patch_ctx:
            callback = _make_callback("card_price:ECL:Lightning Bolt")
            price_msg = callback.message.answer.return_value
            await handle_card_price(callback)

        text = price_msg.edit_text.call_args.args[0]
        assert "Lightning Bolt" in text
        assert "ECL" in text
        assert "$2.80" in text
        assert "€1.47" in text
        assert "TCGPlayer" in text
        assert "Cardmarket" in text

    async def test_only_usd_available(self):
        """TC-P4-6.9: Only USD available → shows USD, mentions Cardmarket."""
        patch_ctx, _ = _mock_http_client(
            json_data=_make_scryfall_response(usd="5.00", eur=None)
        )
        with patch_ctx:
            callback = _make_callback()
            price_msg = callback.message.answer.return_value
            await handle_card_price(callback)

        text = price_msg.edit_text.call_args.args[0]
        assert "$5.00" in text
        assert "Cardmarket" in text

    async def test_parse_mode_is_markdown(self):
        """TC-P4-6.9: Response is sent with Markdown parse mode."""
        patch_ctx, _ = _mock_http_client(json_data=_make_scryfall_response())
        with patch_ctx:
            callback = _make_callback()
            price_msg = callback.message.answer.return_value
            await handle_card_price(callback)

        kwargs = price_msg.edit_text.call_args.kwargs
        assert kwargs.get("parse_mode") == "Markdown"
