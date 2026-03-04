"""
Inline keyboards for Smart Goblin Telegram bot.

Provides keyboard builders for history navigation and analysis actions.
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.db.models import Analysis


def build_history_keyboard(analyses: list[Analysis]) -> InlineKeyboardMarkup:
    """
    Build an inline keyboard for the analysis history list.

    Each button shows the analysis date and ID. Pressing it triggers
    a callback to display that analysis in detail.

    Args:
        analyses: List of Analysis objects sorted by date descending.

    Returns:
        InlineKeyboardMarkup with one button per analysis.
    """
    builder = InlineKeyboardBuilder()

    for analysis in analyses:
        date_str = analysis.created_at.strftime("%d.%m.%Y")
        set_label = ""
        if analysis.set and analysis.set.code:
            set_label = f" [{analysis.set.code}]"

        builder.row(
            InlineKeyboardButton(
                text=f"Аналіз #{analysis.id} — {date_str}{set_label}",
                callback_data=f"history:{analysis.id}",
            )
        )

    return builder.as_markup()


def build_skip_sideboard_keyboard() -> InlineKeyboardMarkup:
    """
    Build a keyboard with a single "Skip sideboard" button.

    Used during the /draft multi-photo session to allow the user
    to skip the sideboard photo and generate the report immediately.

    Returns:
        InlineKeyboardMarkup with one button.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="Пропустити sideboard",
            callback_data="skip_sideboard",
        )
    )
    return builder.as_markup()


def build_single_card_keyboard(card_name: str, set_code: str) -> InlineKeyboardMarkup:
    """
    Build a keyboard with a "💰 Актуальна ціна" button for single card recognition.

    Handles Telegram's 64-byte callback_data limit by truncating the card name
    if necessary (in practice, all real MTG card names fit within the limit).

    Args:
        card_name: The recognized card name.
        set_code: The active set code (e.g., "ECL").

    Returns:
        InlineKeyboardMarkup with one price button.
    """
    prefix = f"card_price:{set_code}:".encode("utf-8")
    name_bytes = card_name.encode("utf-8")
    max_name_bytes = 64 - len(prefix)
    if len(name_bytes) > max_name_bytes:
        name_bytes = name_bytes[:max_name_bytes]
        card_name = name_bytes.decode("utf-8", errors="ignore")

    callback_data = f"card_price:{set_code}:{card_name}"
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="💰 Актуальна ціна", callback_data=callback_data)
        ]]
    )


def build_card_price_keyboard(
    tcgplayer_url: str | None,
    cardmarket_url: str | None,
) -> InlineKeyboardMarkup | None:
    """
    Build a keyboard with URL buttons for card purchase links.

    Args:
        tcgplayer_url: TCGPlayer purchase URL or None.
        cardmarket_url: Cardmarket purchase URL or None.

    Returns:
        InlineKeyboardMarkup with URL buttons, or None if no links available.
    """
    buttons = []
    if tcgplayer_url:
        buttons.append(InlineKeyboardButton(text="🛒 TCGPlayer", url=tcgplayer_url))
    if cardmarket_url:
        buttons.append(InlineKeyboardButton(text="🛒 Cardmarket", url=cardmarket_url))
    if not buttons:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def build_analysis_actions_keyboard(
    analysis_id: int,
    has_advice: bool = False,
) -> InlineKeyboardMarkup:
    """
    Build an inline keyboard with actions for a specific analysis.

    Actions: get/view advice, repeat analysis, view details, delete.

    Args:
        analysis_id: ID of the analysis.
        has_advice: Whether advice has already been generated.

    Returns:
        InlineKeyboardMarkup with action buttons.
    """
    builder = InlineKeyboardBuilder()

    # First row: advice button
    if has_advice:
        builder.row(
            InlineKeyboardButton(
                text="💡 Переглянути поради",
                callback_data=f"view_advice:{analysis_id}",
            ),
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text="💡 Отримати поради",
                callback_data=f"get_advice:{analysis_id}",
            ),
        )

    # Second row: other actions
    builder.row(
        InlineKeyboardButton(
            text="🔄 Повторити",
            callback_data=f"repeat:{analysis_id}",
        ),
        InlineKeyboardButton(
            text="📋 Деталі",
            callback_data=f"details:{analysis_id}",
        ),
        InlineKeyboardButton(
            text="🗑 Видалити",
            callback_data=f"delete:{analysis_id}",
        ),
    )

    return builder.as_markup()
