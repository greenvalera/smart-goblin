"""
Message formatting helpers for Smart Goblin Telegram bot.

Provides functions for formatting history lists, card statistics,
error messages, and help text. All user-facing text is in Ukrainian.

The main analysis report is rendered via src.reports.telegram.TelegramRenderer.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from src.db.models import Analysis, Card, CardRating

# Maximum number of cards shown in a list before truncating
MAX_CARDS_DISPLAYED = 20


def format_history_list(analyses: list[Analysis]) -> str:
    """
    Format a list of analyses for the /history command.

    Args:
        analyses: List of Analysis objects sorted by date descending.

    Returns:
        Formatted string with analysis summaries, or a message if empty.
    """
    if not analyses:
        return "У вас ще немає аналізів. Надішліть фото колоди з командою /analyze."

    lines = ["📜 *Ваші останні аналізи:*", ""]

    for analysis in analyses:
        date_str = analysis.created_at.strftime("%d.%m.%Y %H:%M")
        set_label = ""
        if analysis.set and analysis.set.code:
            set_label = f" [{analysis.set.code}]"

        card_count = len(analysis.main_deck) if analysis.main_deck else 0

        score_str = ""
        if analysis.total_score is not None:
            score_str = f" — ⭐ {analysis.total_score:.1f}/5.0"

        lines.append(
            f"• *Аналіз #{analysis.id}*{set_label} ({date_str})\n"
            f"  {card_count} карт{score_str}"
        )

    lines.append("")
    lines.append("Натисніть кнопку нижче, щоб переглянути деталі.")

    return "\n".join(lines)


def format_card_stats(card: Card, ratings: list[CardRating]) -> str:
    """
    Format statistics for a single card (/stats command).

    Args:
        card: The Card object with metadata.
        ratings: List of CardRating objects for this card.

    Returns:
        Formatted string with card information and ratings.
    """
    lines = [f"🃏 *{card.name}*"]

    if card.set:
        lines.append(f"Сет: {card.set.name} ({card.set.code})")

    if card.type_line:
        lines.append(f"Тип: {card.type_line}")

    if card.mana_cost:
        lines.append(f"Мана: {card.mana_cost}")

    if card.rarity:
        rarity_map = {
            "common": "Звичайна",
            "uncommon": "Незвичайна",
            "rare": "Рідкісна",
            "mythic": "Міфічна",
        }
        lines.append(f"Рідкість: {rarity_map.get(card.rarity, card.rarity)}")

    if card.colors:
        color_names = {
            "W": "Білий",
            "U": "Синій",
            "B": "Чорний",
            "R": "Червоний",
            "G": "Зелений",
        }
        color_str = ", ".join(color_names.get(c, c) for c in card.colors)
        lines.append(f"Кольори: {color_str}")

    if ratings:
        lines.append("")
        lines.append("📊 *Рейтинги:*")
        for r in ratings:
            source_label = r.source
            format_label = f" ({r.format})" if r.format else ""
            parts = [f"• {source_label}{format_label}:"]

            if r.rating is not None:
                parts.append(f"⭐ {r.rating:.1f}")
            if r.win_rate is not None:
                parts.append(f"| {r.win_rate:.1f}% WR")
            if r.games_played is not None:
                parts.append(f"| {r.games_played} ігор")

            lines.append(" ".join(parts))
    else:
        lines.append("")
        lines.append("Рейтинги для цієї карти відсутні.")

    return "\n".join(lines)


def format_card_list(card_names: list[str], max_items: int = MAX_CARDS_DISPLAYED) -> str:
    """
    Format a list of card names, truncating if it exceeds max_items.

    Args:
        card_names: List of card names.
        max_items: Maximum number of cards to display before truncating.

    Returns:
        Formatted string with card list.
    """
    if not card_names:
        return "Немає карт."

    if len(card_names) <= max_items:
        return "\n".join(f"• {name}" for name in card_names)

    displayed = card_names[:max_items]
    remaining = len(card_names) - max_items
    lines = [f"• {name}" for name in displayed]
    lines.append(f"...та ще {remaining} карт")

    return "\n".join(lines)


def format_error(error_type: str = "general") -> str:
    """
    Return a user-friendly error message in Ukrainian.

    Args:
        error_type: Type of error. Supported types:
            - "general" — generic error
            - "llm" — LLM service error
            - "vision" — image recognition error
            - "no_cards" — no cards recognized
            - "no_photo" — no photo attached
            - "db" — database error
            - "not_found" — analysis/card not found
            - "rate_limit" — too many requests

    Returns:
        Error message in Ukrainian.
    """
    messages = {
        "general": (
            "На жаль, сталася помилка. Спробуйте ще раз пізніше. "
            "Якщо проблема повторюється, зверніться до підтримки."
        ),
        "llm": (
            "Сервіс аналізу тимчасово недоступний. "
            "Спробуйте надіслати фото ще раз через кілька хвилин."
        ),
        "vision": (
            "Не вдалося розпізнати карти на зображенні. "
            "Переконайтеся, що фото чітке та карти добре видно."
        ),
        "no_cards": (
            "Не знайдено жодної карти на зображенні. "
            "Спробуйте зробити більш чітке фото або скріншот з MTG Arena."
        ),
        "no_photo": (
            "Будь ласка, надішліть фото колоди разом з командою /analyze. "
            "Підтримуються скріншоти MTG Arena та фото фізичних карт."
        ),
        "db": (
            "Помилка доступу до бази даних. "
            "Спробуйте ще раз через кілька хвилин."
        ),
        "not_found": (
            "Запитану інформацію не знайдено. "
            "Перевірте правильність введених даних."
        ),
        "rate_limit": (
            "Забагато запитів. Будь ласка, зачекайте хвилину "
            "перед наступним аналізом."
        ),
    }

    return messages.get(error_type, messages["general"])


def format_help() -> str:
    """
    Return the help message for the /help command.

    Returns:
        Help text in Ukrainian with command descriptions.
    """
    return (
        "🧙 *Smart Goblin — ваш помічник з аналізу драфт-колод MTG*\n"
        "\n"
        "*Як користуватися:*\n"
        "1. Зробіть скріншот колоди в MTG Arena або фото фізичних карт.\n"
        "2. Надішліть фото — бот автоматично визначить що на ньому (одна карта або колода).\n"
        "3. Або використайте /analyze чи /draft для явного вибору режиму.\n"
        "4. Отримайте аналіз з оцінками та рекомендаціями.\n"
        "\n"
        "*Команди:*\n"
        "/start — Розпочати роботу з ботом\n"
        "/help — Показати цю довідку\n"
        "/analyze — Аналіз колоди (фото можна надсилати без цієї команди)\n"
        "/draft — Режим драфту: аналіз деки з двох фото (main deck + sideboard)\n"
        "/history — Переглянути минулі аналізи\n"
        "/stats _назва карти_ — Статистика конкретної карти\n"
        "/set _код сету_ — Вказати сет вручну (наприклад, /set MKM)\n"
        "\n"
        "*Підтримувані формати фото:*\n"
        "• Скріншоти MTG Arena (колода та сайдборд)\n"
        "• Фото фізичних карт, розкладених рядками\n"
        "\n"
        "💡 Для найкращих результатів переконайтеся, що назви карт чітко видно."
    )


def format_start() -> str:
    """
    Return the welcome message for the /start command.

    Returns:
        Welcome text in Ukrainian.
    """
    return (
        "👋 Вітаю! Я *Smart Goblin* — ваш AI-помічник для аналізу "
        "драфт-колод Magic: The Gathering.\n"
        "\n"
        "Просто надішліть мені фото — я автоматично розпізнаю що на ньому:\n"
        "• Одна карта → грейд і вінрейт з 17lands\n"
        "• Колода (3+ карти) → повний аналіз з рекомендаціями\n"
        "\n"
        "Або скористайтеся командами:\n"
        "• /analyze — аналіз колоди\n"
        "• /draft — режим драфту з main deck та sideboard\n"
        "\n"
        "Введіть /help для повного списку команд."
    )
