"""
Multi-photo draft session handler for Smart Goblin.

Handles /draft command: collects main deck photo, then optionally a sideboard
photo (or "Пропустити sideboard"), and generates a full deck report.

FSM flow:
  /draft → waiting_main → (photo) → waiting_sideboard → (photo | skip) → chatting
  chatting → (text message) → LLM response in deck context
"""

import logging
from io import BytesIO
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from src.bot.keyboards import build_analysis_actions_keyboard, build_skip_sideboard_keyboard
from src.bot.messages import format_error
from src.core.analyzer import DeckAnalyzer
from src.core.deck import CardInfo, Deck
from src.core.lands import BASIC_LANDS, recommend_lands
from src.db.models import Card, User
from src.db.repository import AnalysisRepository, CardRepository, SetRepository
from src.db.session import get_session
from src.llm.client import get_llm_client
from src.llm.exceptions import LLMError
from src.llm.prompts import DRAFT_CHAT_SYSTEM_PROMPT
from src.reports.models import DeckReport
from src.reports.telegram import TelegramRenderer
from src.vision.card_matcher import fuzzy_match_cards
from src.vision.recognizer import CardRecognizer

logger = logging.getLogger(__name__)

router = Router()

# Maximum number of conversation exchanges (each = 1 user + 1 assistant message)
_MAX_CHAT_EXCHANGES = 10


class DraftState(StatesGroup):
    """FSM states for the multi-photo draft session."""

    waiting_main = State()
    waiting_sideboard = State()
    chatting = State()  # conversation mode after advice is generated


# --- Private helpers ---


def _card_to_card_info(card: Card) -> CardInfo:
    """Convert a DB Card (with loaded ratings) to a CardInfo."""
    rating = win_rate = games_played = None
    if card.ratings:
        best = card.ratings[0]
        rating, win_rate, games_played = best.rating, best.win_rate, best.games_played
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


def _is_basic_land(name: str) -> bool:
    return name in BASIC_LANDS


async def _download_image(message: Message) -> bytes:
    """Download the highest-resolution photo from a message."""
    photo = message.photo[-1]
    file_obj = await message.bot.get_file(photo.file_id)
    downloaded: BytesIO = await message.bot.download_file(file_obj.file_path)
    return downloaded.read()


async def _fetch_known_cards(set_code: str) -> list[str]:
    """Return known card names for a set from DB (empty list if none)."""
    async with get_session() as session:
        names = await CardRepository(session).get_card_names_by_set(set_code)
        return names or []


async def _recognize_and_match(
    image_bytes: bytes,
    set_override: Optional[str],
    known_cards: Optional[list[str]],
) -> tuple[list[str], list[str], Optional[str]]:
    """
    Run GPT-4o Vision recognition and fuzzy-match result against known cards.

    Returns:
        Tuple of (main_deck, sideboard, resolved_set_code).
    """
    recognizer = CardRecognizer()
    recognition = await recognizer.recognize_cards(
        image_bytes, set_hint=set_override, known_cards=known_cards
    )

    resolved_set = set_override or recognition.detected_set

    if resolved_set and known_cards:
        main_result = fuzzy_match_cards(recognition.main_deck, known_cards)
        sb_result = fuzzy_match_cards(recognition.sideboard, known_cards)

        corrections = len(main_result.corrections) + len(sb_result.corrections)
        unmatched = len(main_result.unmatched) + len(sb_result.unmatched)
        if corrections:
            logger.info("Fuzzy matching corrected %d card names", corrections)
        if unmatched:
            logger.warning("Fuzzy matching: %d unmatched names", unmatched)

        return main_result.matched, sb_result.matched, resolved_set

    return recognition.main_deck, recognition.sideboard, resolved_set


async def _build_and_send_report(
    db_user: User,
    main_deck: list[str],
    sideboard: list[str],
    set_code: Optional[str],
    processing_msg: Message,
) -> None:
    """
    Enrich cards with DB ratings, analyze, save to DB, and send the report.

    Edits processing_msg with the final rendered report.
    """
    deck = Deck(main_deck=main_deck, sideboard=sideboard, set_code=set_code)

    card_infos: list[CardInfo] = []
    set_name: Optional[str] = None

    if set_code:
        async with get_session() as session:
            db_cards = await CardRepository(session).get_cards_with_ratings(
                deck.main_deck + deck.sideboard, set_code
            )
            card_infos = [_card_to_card_info(c) for c in db_cards]

            db_set = await SetRepository(session).get_by_code(set_code)
            if db_set:
                set_name = db_set.name

    analyzer = DeckAnalyzer()
    analysis = analyzer.analyze(deck, card_infos)

    main_deck_names = set(deck.main_deck)
    non_land_infos = [c for c in card_infos if not _is_basic_land(c.name) and c.name in main_deck_names]
    land_rec = recommend_lands(non_land_infos)

    async with get_session() as session:
        db_analysis = await AnalysisRepository(session).create(
            user_id=db_user.id,
            main_deck=deck.main_deck,
            sideboard=deck.sideboard,
            set_code=set_code,
            total_score=analysis.score,
            estimated_win_rate=analysis.estimated_win_rate,
            advice=None,
        )
        analysis_id = db_analysis.id

    report = DeckReport.build(
        deck, card_infos, analysis,
        set_name=set_name,
        land_recommendation=land_rec,
    )
    text = TelegramRenderer().render(report)

    keyboard = build_analysis_actions_keyboard(analysis_id, has_advice=False)
    await processing_msg.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")

    logger.info(
        "Draft analysis %d for user %d: main=%d, sb=%d, score=%.2f",
        analysis_id,
        db_user.telegram_id,
        len(deck.main_deck),
        len(deck.sideboard),
        analysis.score,
    )


# --- Handlers ---


@router.message(Command("draft"))
async def handle_draft_command(message: Message, state: FSMContext) -> None:
    """/draft — start multi-photo draft session, ask for main deck photo."""
    await state.set_state(DraftState.waiting_main)
    await message.answer(
        "🃏 *Режим драфт-сесії*\n\n"
        "Надішліть фото або скріншот *main deck* (основна колода).",
        parse_mode="Markdown",
    )


@router.message(DraftState.waiting_main, F.photo)
async def handle_draft_main_photo(
    message: Message,
    db_user: User,
    state: FSMContext,
) -> None:
    """Recognize main deck photo and transition to waiting_sideboard."""
    processing_msg = await message.answer("⏳ Розпізнаю main deck...")

    try:
        image_bytes = await _download_image(message)

        fsm_data = await state.get_data()
        set_override: Optional[str] = fsm_data.get("set_override") or db_user.active_set_code

        known_cards: Optional[list[str]] = None
        if set_override:
            names = await _fetch_known_cards(set_override)
            if names:
                known_cards = names
                logger.info(
                    "Loaded %d known cards for set %s", len(known_cards), set_override
                )

        main_deck, _sb_from_img, detected_set = await _recognize_and_match(
            image_bytes, set_override, known_cards
        )

        if not main_deck:
            await state.clear()
            await processing_msg.edit_text(format_error("no_cards"))
            return

        resolved_set = set_override or detected_set

        # Persist recognition result for the next step
        await state.update_data(
            draft_main_deck=main_deck,
            draft_set_code=resolved_set,
            draft_known_cards=known_cards,
        )
        await state.set_state(DraftState.waiting_sideboard)

        await processing_msg.edit_text(
            f"✅ Розпізнано *{len(main_deck)}* карт у main deck.\n\n"
            "Надішліть фото *sideboard* або пропустіть.",
            parse_mode="Markdown",
            reply_markup=build_skip_sideboard_keyboard(),
        )

        logger.info(
            "Draft main deck recognized for user %d: %d cards, set=%s",
            db_user.telegram_id,
            len(main_deck),
            resolved_set,
        )

    except LLMError:
        logger.exception("LLM error in draft main recognition for user %d", db_user.telegram_id)
        await state.clear()
        await processing_msg.edit_text(format_error("llm"))

    except Exception:
        logger.exception("Error in draft main recognition for user %d", db_user.telegram_id)
        await state.clear()
        await processing_msg.edit_text(format_error("general"))


@router.message(DraftState.waiting_sideboard, F.photo)
async def handle_draft_sideboard_photo(
    message: Message,
    db_user: User,
    state: FSMContext,
) -> None:
    """Recognize sideboard photo, merge with stored main deck, send full report."""
    processing_msg = await message.answer("⏳ Розпізнаю sideboard та генерую звіт...")

    try:
        fsm_data = await state.get_data()
        main_deck: list[str] = fsm_data.get("draft_main_deck", [])
        set_code: Optional[str] = fsm_data.get("draft_set_code")
        known_cards: Optional[list[str]] = fsm_data.get("draft_known_cards")

        image_bytes = await _download_image(message)

        # Recognize sideboard image — treat all recognized cards as sideboard
        recognizer = CardRecognizer()
        recognition = await recognizer.recognize_cards(
            image_bytes, set_hint=set_code, known_cards=known_cards
        )
        all_sideboard = recognition.main_deck + recognition.sideboard

        if all_sideboard and known_cards:
            sb_result = fuzzy_match_cards(all_sideboard, known_cards)
            all_sideboard = sb_result.matched

        await state.clear()

        await _build_and_send_report(
            db_user=db_user,
            main_deck=main_deck,
            sideboard=all_sideboard,
            set_code=set_code,
            processing_msg=processing_msg,
        )

    except LLMError:
        logger.exception(
            "LLM error in draft sideboard recognition for user %d", db_user.telegram_id
        )
        await state.clear()
        await processing_msg.edit_text(format_error("llm"))

    except Exception:
        logger.exception(
            "Error in draft sideboard recognition for user %d", db_user.telegram_id
        )
        await state.clear()
        await processing_msg.edit_text(format_error("general"))


@router.callback_query(DraftState.waiting_sideboard, F.data == "skip_sideboard")
async def handle_skip_sideboard(
    callback: CallbackQuery,
    db_user: User,
    state: FSMContext,
) -> None:
    """Generate report with empty sideboard when user skips the sideboard step."""
    await callback.answer()

    processing_msg = await callback.message.edit_text("⏳ Генерую звіт...")

    try:
        fsm_data = await state.get_data()
        main_deck: list[str] = fsm_data.get("draft_main_deck", [])
        set_code: Optional[str] = fsm_data.get("draft_set_code")

        await state.clear()

        await _build_and_send_report(
            db_user=db_user,
            main_deck=main_deck,
            sideboard=[],
            set_code=set_code,
            processing_msg=processing_msg,
        )

    except LLMError:
        logger.exception(
            "LLM error generating draft report for user %d", db_user.telegram_id
        )
        await state.clear()
        await processing_msg.edit_text(format_error("llm"))

    except Exception:
        logger.exception(
            "Error generating draft report for user %d", db_user.telegram_id
        )
        await state.clear()
        await processing_msg.edit_text(format_error("general"))


# --- Chatting mode helpers and handler ---


def _build_deck_context(
    main_deck: list[str],
    sideboard: list[str],
    set_code: Optional[str],
    advice: str,
) -> str:
    """Build a deck context string to include in the LLM system prompt."""
    set_info = f"Сет: {set_code}" if set_code else "Сет не вказаний"
    main_str = ", ".join(main_deck) if main_deck else "невідомо"
    sb_str = ", ".join(sideboard) if sideboard else "порожній"

    lines = [
        "## Поточна колода гравця",
        set_info,
        f"Main Deck ({len(main_deck)} карт): {main_str}",
        f"Sideboard ({len(sideboard)} карт): {sb_str}",
    ]

    if advice:
        trimmed = advice[:600]
        if len(advice) > 600:
            trimmed += "..."
        lines.append(f"\n## Поради що вже були надані:\n{trimmed}")

    return "\n".join(lines)


@router.message(DraftState.chatting, F.text, ~F.text.startswith("/"))
async def handle_draft_chat(
    message: Message,
    db_user: User,
    state: FSMContext,
) -> None:
    """
    Handle user text questions in draft conversation mode.

    Maintains conversation history in FSM, trims to last MAX_CHAT_EXCHANGES
    exchanges, and responds using LLM with full deck context.

    TC-P4-3.2: Text message in chatting state → LLM response.
    TC-P4-3.3: Deck context (card names) is included in LLM prompt.
    TC-P4-3.4: Conversation history is saved to FSM.
    TC-P4-3.7: LLM error → friendly error, FSM stays in chatting.
    TC-P4-3.8: History trimmed to last 10 exchanges (20 messages).
    """
    fsm_data = await state.get_data()
    main_deck: list[str] = fsm_data.get("draft_main_deck", [])
    sideboard: list[str] = fsm_data.get("draft_sideboard", [])
    set_code: Optional[str] = fsm_data.get("draft_set_code")
    advice: str = fsm_data.get("draft_advice", "")
    conversation: list[dict] = fsm_data.get("draft_conversation", [])

    user_text = message.text or ""

    deck_context = _build_deck_context(main_deck, sideboard, set_code, advice)
    full_system_prompt = DRAFT_CHAT_SYSTEM_PROMPT + "\n\n" + deck_context

    # Build messages: trimmed history + new user message
    messages = list(conversation[-(2 * _MAX_CHAT_EXCHANGES):])
    messages.append({"role": "user", "content": user_text})

    processing_msg = await message.answer("⏳ Думаю...")

    try:
        llm = get_llm_client()
        response = await llm.call_completion(messages, system_prompt=full_system_prompt)

        # Append exchange and trim to max history
        updated = conversation + [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": response},
        ]
        if len(updated) > 2 * _MAX_CHAT_EXCHANGES:
            updated = updated[-(2 * _MAX_CHAT_EXCHANGES):]

        await state.update_data(draft_conversation=updated)

        text = response
        if len(text) > 4000:
            text = text[:3980] + "\n\n_...скорочено_"

        await processing_msg.edit_text(text, parse_mode="Markdown")

        logger.info(
            "Draft chat reply for user %d: %d exchanges in history",
            db_user.telegram_id,
            len(updated) // 2,
        )

    except LLMError:
        logger.exception("LLM error in draft chat for user %d", db_user.telegram_id)
        await processing_msg.edit_text(format_error("llm"))
        # FSM stays in chatting state — user can retry (TC-P4-3.7)

    except Exception:
        logger.exception("Error in draft chat for user %d", db_user.telegram_id)
        await processing_msg.edit_text(format_error("general"))
        # FSM stays in chatting state
