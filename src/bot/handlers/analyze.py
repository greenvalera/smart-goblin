"""
Analyze command handler for Smart Goblin.

Handles /analyze + photo: downloads the image, recognizes cards via Vision,
enriches with DB ratings, runs analysis, calculates land recommendation,
saves to DB, and sends the formatted report.

Advice is generated on demand via the "Отримати поради" callback button.

Also handles bare photo messages with smart routing:
- 1 card recognized (empty sideboard) → single card stats (grade, WR, CMC, type)
- 3+ cards recognized → full deck analysis (like /analyze)
- otherwise (0, 2, or ambiguous) → ask user to clarify with /analyze or /draft
"""

import logging
from io import BytesIO
from typing import Optional

import httpx
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.bot.handlers.draft import DraftState
from src.bot.keyboards import (
    build_analysis_actions_keyboard,
    build_card_price_keyboard,
    build_single_card_keyboard,
)
from src.bot.messages import format_error
from src.core.advisor import DeckAdvisor
from src.core.analyzer import DeckAnalyzer
from src.core.deck import CardInfo, Deck
from src.core.lands import BASIC_LANDS, STANDARD_DECK_SIZE, recommend_lands
from src.db.models import Card, User
from src.db.repository import AnalysisRepository, CardRepository, SetRepository
from src.db.session import get_session
from src.llm.client import get_llm_client
from src.llm.exceptions import LLMError
from src.reports.models import DeckReport, rating_to_grade
from src.reports.telegram import TelegramRenderer
from src.vision.card_matcher import fuzzy_match_cards
from src.vision.recognizer import CardRecognizer

logger = logging.getLogger(__name__)

router = Router()


def _card_to_card_info(card: Card) -> CardInfo:
    """Convert a DB Card model (with loaded ratings) to a CardInfo."""
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


def _is_basic_land(name: str) -> bool:
    """Check if a card name is a basic land."""
    return name in BASIC_LANDS


def _is_nonbasic_land(card_info) -> bool:
    """Return True if the card is a non-basic land (e.g. dual land, utility land)."""
    if _is_basic_land(card_info.name):
        return False
    type_line = getattr(card_info, "type_line", None) or ""
    return "Land" in type_line


async def _enrich_cards(
    session, deck: Deck
) -> tuple[list[CardInfo], Optional[str]]:
    """
    Look up cards in DB and return enriched CardInfo list + set name.

    Args:
        session: DB async session.
        deck: The deck to enrich.

    Returns:
        Tuple of (card_infos, set_name).
    """
    card_infos: list[CardInfo] = []
    set_name: Optional[str] = None

    if deck.set_code:
        card_repo = CardRepository(session)
        all_card_names = deck.main_deck + deck.sideboard
        db_cards = await card_repo.get_cards_with_ratings(
            all_card_names, deck.set_code
        )
        card_infos = [_card_to_card_info(c) for c in db_cards]

        set_repo = SetRepository(session)
        db_set = await set_repo.get_by_code(deck.set_code)
        if db_set:
            set_name = db_set.name

    return card_infos, set_name


async def _run_deck_pipeline(
    message: Message,
    processing_msg: Message,
    db_user: User,
    main_deck: list[str],
    sideboard: list[str],
    set_code: Optional[str],
) -> None:
    """
    Run the full deck analysis pipeline from recognized card names.

    Handles: enrich cards with DB ratings, analyze, calculate land recommendation,
    save to DB, build and render report, send formatted response.

    Args:
        message: Original user message (for logging context).
        processing_msg: Interim "processing" message to update with result.
        db_user: The authenticated DB user.
        main_deck: Recognized/matched main deck card names.
        sideboard: Recognized/matched sideboard card names.
        set_code: Resolved set code (may be None).
    """
    deck = Deck(main_deck=main_deck, sideboard=sideboard, set_code=set_code)

    # Enrich cards with DB ratings
    async with get_session() as session:
        card_infos, set_name = await _enrich_cards(session, deck)

    # Analyze deck
    analyzer = DeckAnalyzer()
    analysis = analyzer.analyze(deck, card_infos)

    # Calculate land recommendation
    total_lands = max(1, STANDARD_DECK_SIZE - len(deck.main_deck))
    main_deck_names = set(deck.main_deck)
    non_basic_lands = [c for c in card_infos if _is_nonbasic_land(c) and c.name in main_deck_names]
    spell_infos = [
        c for c in card_infos
        if not _is_basic_land(c.name) and not _is_nonbasic_land(c) and c.name in main_deck_names
    ]
    land_rec = recommend_lands(
        spell_infos,
        total_lands=total_lands,
        non_basic_land_count=len(non_basic_lands),
    )

    # Save analysis to DB (no advice yet — on demand)
    async with get_session() as session:
        analysis_repo = AnalysisRepository(session)
        db_analysis = await analysis_repo.create(
            user_id=db_user.id,
            main_deck=deck.main_deck,
            sideboard=deck.sideboard,
            set_code=set_code,
            total_score=analysis.score,
            estimated_win_rate=analysis.estimated_win_rate,
            advice=None,
        )
        analysis_id = db_analysis.id

    # Build and render report (no advice)
    report = DeckReport.build(
        deck, card_infos, analysis,
        set_name=set_name,
        land_recommendation=land_rec,
    )
    renderer = TelegramRenderer()
    text = renderer.render(report)

    keyboard = build_analysis_actions_keyboard(analysis_id, has_advice=False)
    await processing_msg.edit_text(
        text, reply_markup=keyboard, parse_mode="Markdown"
    )

    logger.info(
        "Analysis %d completed for user %d: score=%.2f, wr=%.1f%%",
        analysis_id,
        db_user.telegram_id,
        analysis.score,
        analysis.estimated_win_rate,
    )


async def _handle_single_card(
    processing_msg: Message,
    db_user: User,
    card_name: str,
    set_code: Optional[str],
) -> None:
    """
    Handle single-card photo: look up card in DB and show grade/win rate.

    TC-P4-1.4: No active set → suggest /set <code>
    TC-P4-1.5: Card found → show grade, WR, CMC, type
    TC-P4-1.6: Card not found in DB → show not-found message with set code
    """
    if not set_code:
        await processing_msg.edit_text(
            f"🃏 Розпізнано карту: *{card_name}*\n\n"
            "Щоб побачити грейд та статистику, вкажіть активний сет:\n"
            "`/set <КОД_СЕТУ>` (наприклад, `/set ECL`)",
            parse_mode="Markdown",
        )
        return

    async with get_session() as session:
        card_repo = CardRepository(session)
        db_card = await card_repo.get_by_name(card_name, set_code)

    if not db_card:
        await processing_msg.edit_text(
            f"🃏 *{card_name}*\n\n"
            f"Карта не знайдена в базі для сету *{set_code}*.",
            parse_mode="Markdown",
        )
        return

    card_info = _card_to_card_info(db_card)
    grade = rating_to_grade(card_info.rating)

    stat_parts = [f"Грейд: {grade}"]
    if card_info.win_rate is not None:
        stat_parts.append(f"WR: {float(card_info.win_rate):.1f}%")
    if card_info.cmc is not None:
        stat_parts.append(f"CMC: {int(card_info.cmc)}")

    detail_parts = []
    if card_info.colors:
        detail_parts.append(f"Кольори: {''.join(card_info.colors)}")
    if card_info.type_line:
        detail_parts.append(f"Тип: {card_info.type_line}")

    lines = [
        f"🃏 *{card_info.name}*",
        "📊 " + " | ".join(stat_parts),
    ]
    if detail_parts:
        lines.append("🎨 " + " | ".join(detail_parts))

    keyboard = build_single_card_keyboard(card_info.name, set_code)
    await processing_msg.edit_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=keyboard
    )


async def _run_analysis(
    message: Message,
    db_user: User,
    state: FSMContext,
    set_arg: Optional[str] = None,
) -> None:
    """Core analysis logic — download image, recognize, analyze, respond."""
    processing_msg = await message.answer("⏳ Аналізую вашу колоду...")

    try:
        # Download photo (largest available size)
        photo = message.photo[-1]
        file_obj = await message.bot.get_file(photo.file_id)
        downloaded: BytesIO = await message.bot.download_file(file_obj.file_path)
        image_bytes = downloaded.read()

        # Determine set override priority:
        # (1) command arg (e.g. /analyze MKM) → (2) FSM state → (3) DB active_set_code → (4) auto-detect
        fsm_data = await state.get_data()
        if set_arg:
            set_override: Optional[str] = set_arg.strip().upper()
        else:
            set_override = fsm_data.get("set_override") or db_user.active_set_code

        # Pre-fetch known card names for prompt enhancement
        known_cards: list[str] | None = None
        if set_override:
            async with get_session() as session:
                card_repo = CardRepository(session)
                names = await card_repo.get_card_names_by_set(set_override)
                if names:
                    known_cards = names
                    logger.info(
                        "Loaded %d known card names for set %s",
                        len(known_cards), set_override,
                    )

        # Recognize cards from image
        recognizer = CardRecognizer()
        recognition = await recognizer.recognize_cards(
            image_bytes, set_hint=set_override, known_cards=known_cards
        )

        if not recognition.main_deck:
            await processing_msg.edit_text(format_error("no_cards"))
            return

        # Build deck
        set_code = set_override or recognition.detected_set
        deck = Deck(
            main_deck=recognition.main_deck,
            sideboard=recognition.sideboard,
            set_code=set_code,
        )

        # Fuzzy-match recognized names against known cards
        if set_code:
            if not known_cards:
                # Set was auto-detected — fetch card names now
                async with get_session() as session:
                    card_repo = CardRepository(session)
                    known_cards = await card_repo.get_card_names_by_set(set_code)

            if known_cards:
                main_result = fuzzy_match_cards(deck.main_deck, known_cards)
                deck.main_deck = main_result.matched

                sb_result = fuzzy_match_cards(deck.sideboard, known_cards)
                deck.sideboard = sb_result.matched

                total_corrections = len(main_result.corrections) + len(sb_result.corrections)
                total_unmatched = len(main_result.unmatched) + len(sb_result.unmatched)
                if total_corrections:
                    logger.info("Fuzzy matching corrected %d card names", total_corrections)
                if total_unmatched:
                    logger.warning(
                        "Fuzzy matching: %d unmatched names",
                        total_unmatched,
                    )

        await _run_deck_pipeline(
            message, processing_msg, db_user,
            deck.main_deck, deck.sideboard, set_code,
        )

    except LLMError:
        logger.exception("LLM error during analysis for user %d", db_user.telegram_id)
        await processing_msg.edit_text(format_error("llm"))

    except Exception:
        logger.exception(
            "Unexpected error during analysis for user %d", db_user.telegram_id
        )
        await processing_msg.edit_text(format_error("general"))


@router.message(Command("analyze"), F.photo)
async def handle_analyze_with_photo(
    message: Message,
    db_user: User,
    command: CommandObject,
    state: FSMContext,
) -> None:
    """Handle /analyze command with an attached photo — run full analysis."""
    # Reset any active draft chatting session so it doesn't persist (TC-P4-3.6)
    await state.clear()
    await _run_analysis(message, db_user, state, set_arg=command.args)


@router.message(Command("analyze"))
async def handle_analyze_no_photo(message: Message) -> None:
    """Handle /analyze command without a photo — prompt user to attach one."""
    await message.answer(format_error("no_photo"))


@router.message(F.photo)
async def handle_photo_without_command(
    message: Message,
    db_user: User,
    state: FSMContext,
) -> None:
    """
    Handle any photo without a command — smart routing.

    Classification logic (TC-P4-1):
    - 1 card recognized, empty sideboard → single card stats (grade, WR, CMC, type)
    - 3+ cards recognized → full deck analysis (like /analyze)
    - otherwise (0, 2 cards, or 1 card with sideboard) → ask user to clarify

    FSM handlers (e.g. DraftState.waiting_main) have higher priority via
    router registration order — draft_router is included before analyze_router.
    """
    processing_msg = await message.answer("⏳ Аналізую фото...")

    try:
        # Download photo (largest available size)
        photo = message.photo[-1]
        file_obj = await message.bot.get_file(photo.file_id)
        downloaded: BytesIO = await message.bot.download_file(file_obj.file_path)
        image_bytes = downloaded.read()

        # Use active set code as recognition hint
        fsm_data = await state.get_data()
        set_override: Optional[str] = fsm_data.get("set_override") or db_user.active_set_code

        # Pre-fetch known card names for recognition quality
        known_cards: list[str] | None = None
        if set_override:
            async with get_session() as session:
                card_repo = CardRepository(session)
                names = await card_repo.get_card_names_by_set(set_override)
                if names:
                    known_cards = names

        # Recognize cards from image
        recognizer = CardRecognizer()
        recognition = await recognizer.recognize_cards(
            image_bytes, set_hint=set_override, known_cards=known_cards
        )

        # Resolve final set code
        resolved_set = set_override or recognition.detected_set

        # Fuzzy-match recognized names against known cards
        if resolved_set:
            if not known_cards:
                async with get_session() as session:
                    card_repo = CardRepository(session)
                    known_cards = await card_repo.get_card_names_by_set(resolved_set)

            if known_cards:
                main_result = fuzzy_match_cards(recognition.main_deck, known_cards)
                recognition.main_deck = main_result.matched

                sb_result = fuzzy_match_cards(recognition.sideboard, known_cards)
                recognition.sideboard = sb_result.matched

        # Route based on recognized card count
        main_count = len(recognition.main_deck)
        sb_empty = len(recognition.sideboard) == 0

        if main_count == 1 and sb_empty:
            # Single card photo — show grade and stats
            await _handle_single_card(
                processing_msg, db_user, recognition.main_deck[0], resolved_set
            )

        elif main_count >= 3:
            # Deck photo — run full analysis pipeline
            await _run_deck_pipeline(
                message, processing_msg, db_user,
                recognition.main_deck, recognition.sideboard, resolved_set,
            )

        else:
            # Ambiguous: 0 cards, 2 cards, or 1 card with non-empty sideboard
            await processing_msg.edit_text(
                "🤔 Не вдалося визначити тип фото.\n\n"
                "Спробуйте надіслати фото з командою `/analyze` або `/draft`.",
                parse_mode="Markdown",
            )

    except LLMError:
        logger.exception("LLM error during photo routing for user %d", db_user.telegram_id)
        await processing_msg.edit_text(format_error("llm"))

    except Exception:
        logger.exception(
            "Unexpected error during photo routing for user %d", db_user.telegram_id
        )
        await processing_msg.edit_text(format_error("general"))


# --- On-demand advice callbacks ---


@router.callback_query(F.data.startswith("get_advice:"))
async def handle_get_advice(callback: CallbackQuery, db_user: User, state: FSMContext) -> None:
    """Generate LLM advice on demand when the user presses the button."""
    try:
        analysis_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer()
        return

    processing_msg: Optional[Message] = None

    try:
        async with get_session() as session:
            analysis_repo = AnalysisRepository(session)
            analysis = await analysis_repo.get_by_id(analysis_id)

            if not analysis or analysis.user_id != db_user.id:
                await callback.answer()
                await callback.message.answer(format_error("not_found"))
                return

            # Cached advice — instant response via popup, no persistent indicator (TC-P4-5.3)
            if analysis.advice:
                await callback.answer("⏳ Відображаю поради...")
                await _send_advice(callback, analysis_id, analysis.advice)
                # Enter chatting mode with cached context (TC-P4-3.1)
                cached_set_code = analysis.set.code if analysis.set else None
                await state.update_data(
                    draft_main_deck=analysis.main_deck,
                    draft_sideboard=analysis.sideboard or [],
                    draft_set_code=cached_set_code,
                    draft_advice=analysis.advice,
                    draft_conversation=[],
                )
                await state.set_state(DraftState.chatting)
                return

            # Not cached — acknowledge callback and show persistent loading indicator (TC-P4-5.1)
            await callback.answer()
            processing_msg = await callback.message.answer(
                "⏳ Генерую рекомендації...\n\nЦе може зайняти 10–20 секунд."
            )

            # Rebuild deck and card_infos from stored data
            set_code = analysis.set.code if analysis.set else None
            deck = Deck(
                main_deck=analysis.main_deck,
                sideboard=analysis.sideboard or [],
                set_code=set_code,
            )

            card_infos, _ = await _enrich_cards(session, deck)

            # Re-analyze for DeckAnalysis
            analyzer = DeckAnalyzer()
            deck_analysis = analyzer.analyze(deck, card_infos)

            # Recompute land recommendation for the advice prompt
            adv_total_lands = max(1, STANDARD_DECK_SIZE - len(deck.main_deck))
            main_deck_names = set(deck.main_deck)
            non_basic_lands = [c for c in card_infos if _is_nonbasic_land(c) and c.name in main_deck_names]
            spell_infos = [
                c for c in card_infos
                if not _is_basic_land(c.name) and not _is_nonbasic_land(c) and c.name in main_deck_names
            ]
            land_rec = recommend_lands(
                spell_infos,
                total_lands=adv_total_lands,
                non_basic_land_count=len(non_basic_lands),
            )

            # Generate advice via LLM
            advisor = DeckAdvisor(get_llm_client())
            advice = await advisor.generate_advice(
                deck, card_infos, deck_analysis, land_recommendation=land_rec
            )

            # Cache advice in DB
            analysis.advice = advice
            await session.commit()

        # Replace loading indicator with advice (TC-P4-5.2)
        text = f"💡 *Рекомендації:*\n\n{advice}"
        if len(text) > 4000:
            text = text[:3980] + "\n\n_...скорочено_"
        await processing_msg.edit_text(text, parse_mode="Markdown")

        # Update keyboard on the report message
        keyboard = build_analysis_actions_keyboard(analysis_id, has_advice=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=keyboard)
        except Exception:
            pass  # message may be too old to edit

        # Enter chatting mode with deck context (TC-P4-3.1)
        await state.update_data(
            draft_main_deck=deck.main_deck,
            draft_sideboard=deck.sideboard,
            draft_set_code=deck.set_code,
            draft_advice=advice,
            draft_conversation=[],
        )
        await state.set_state(DraftState.chatting)

    except LLMError:
        logger.exception("LLM error generating advice for analysis %d", analysis_id)
        if processing_msg:
            await processing_msg.edit_text(format_error("llm"))  # TC-P4-5.4
        else:
            await callback.message.answer(format_error("llm"))

    except Exception:
        logger.exception("Error generating advice for analysis %d", analysis_id)
        if processing_msg:
            await processing_msg.edit_text(format_error("general"))
        else:
            await callback.message.answer(format_error("general"))


@router.callback_query(F.data.startswith("view_advice:"))
async def handle_view_advice(callback: CallbackQuery, db_user: User) -> None:
    """View previously generated (cached) advice."""
    await callback.answer()

    try:
        analysis_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return

    async with get_session() as session:
        analysis_repo = AnalysisRepository(session)
        analysis = await analysis_repo.get_by_id(analysis_id)

    if not analysis or analysis.user_id != db_user.id:
        await callback.message.answer(format_error("not_found"))
        return

    if analysis.advice:
        await _send_advice(callback, analysis_id, analysis.advice)
    else:
        await callback.message.answer("Поради ще не згенеровано.")


@router.callback_query(F.data.startswith("card_price:"))
async def handle_card_price(callback: CallbackQuery) -> None:
    """
    Fetch and display the current price for a single recognized card.

    Callback data format: "card_price:{set_code}:{card_name}"
    Uses Scryfall /cards/named API (no auth required).

    TC-P4-6.2: HTTP GET to Scryfall /cards/named?exact={name}&set={code}
    TC-P4-6.3: Shows USD (TCGPlayer) and EUR (Cardmarket) prices
    TC-P4-6.4: Both prices null → "Ціна недоступна для цієї карти"
    TC-P4-6.5: Keyboard with TCGPlayer and Cardmarket purchase links
    TC-P4-6.6: Network error/timeout → friendly error message
    TC-P4-6.8: 404 → "Карту не знайдено на Scryfall"
    """
    _, set_code, card_name = callback.data.split(":", 2)
    await callback.answer("⏳ Отримую ціну...")
    price_msg = await callback.message.answer("⏳ Отримую актуальну ціну...")

    try:
        from src.config import get_settings
        base_url = get_settings().parser.scryfall_api_base.rstrip("/")
        async with httpx.AsyncClient(
            timeout=10.0,
            headers={"User-Agent": "SmartGoblin/1.0 (MTG Draft Analyzer Bot)"},
        ) as client:
            resp = await client.get(
                f"{base_url}/cards/named",
                params={"exact": card_name, "set": set_code.lower()},
            )

        if resp.status_code == 404:
            await price_msg.edit_text("Карту не знайдено на Scryfall.")
            return

        resp.raise_for_status()
        data = resp.json()

        prices = data.get("prices") or {}
        purchase_uris = data.get("purchase_uris") or {}
        display_name = data.get("name", card_name)

        usd = prices.get("usd")
        eur = prices.get("eur")
        tcgplayer_url = purchase_uris.get("tcgplayer")
        cardmarket_url = purchase_uris.get("cardmarket")

        lines = [f"💰 *{display_name}* ({set_code})"]
        lines.append("")

        if usd is None and eur is None:
            lines.append("Ціна недоступна для цієї карти.")
            keyboard = None
        else:
            lines.append(f"🇺🇸 TCGPlayer: ${usd}" if usd is not None else "🇺🇸 TCGPlayer: Ціна недоступна")
            lines.append(f"🇪🇺 Cardmarket: €{eur}" if eur is not None else "🇪🇺 Cardmarket: Ціна недоступна")
            keyboard = build_card_price_keyboard(tcgplayer_url, cardmarket_url)

        await price_msg.edit_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

    except httpx.TimeoutException:
        logger.warning("Timeout fetching price for %s/%s", set_code, card_name)
        await price_msg.edit_text("⏱ Scryfall не відповідає. Спробуйте пізніше.")

    except httpx.RequestError as exc:
        logger.warning("Network error fetching price for %s/%s: %s", set_code, card_name, exc)
        await price_msg.edit_text("🌐 Помилка мережі. Спробуйте пізніше.")

    except Exception:
        logger.exception("Unexpected error fetching price for %s/%s", set_code, card_name)
        await price_msg.edit_text("❌ Не вдалося отримати ціну. Спробуйте пізніше.")


async def _send_advice(
    callback: CallbackQuery, analysis_id: int, advice: str
) -> None:
    """Send advice as a new message and update the keyboard."""
    text = f"💡 *Рекомендації:*\n\n{advice}"
    if len(text) > 4000:
        text = text[:3980] + "\n\n_...скорочено_"

    await callback.message.answer(text, parse_mode="Markdown")

    # Update keyboard to show "view advice" instead of "get advice"
    keyboard = build_analysis_actions_keyboard(analysis_id, has_advice=True)
    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    except Exception:
        pass  # message may be too old to edit
