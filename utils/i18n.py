"""
Локализация (i18n) для масштабирования на англоязычную аудиторию.

RU — основной язык (лор Solo Leveling), EN — резервный. Использование:

    from utils.i18n import t, lang_of
    await message.answer(t("welcome_back", lang_of(message.from_user)))

`t(key, lang, **kwargs)` берёт строку из нужного словаря (фолбэк: RU → ключ) и
подставляет именованные параметры. `lang_of(user)` определяет язык по
Telegram `language_code` (en* → en, иначе дефолт из конфига).

Здесь собран базовый общий набор строк; расширяется по мере перевода экранов.
Тематические RU-тексты живут в utils/texts.py — переносить их в i18n нужно
только когда появится реальный EN-трафик.
"""
from __future__ import annotations

from typing import Optional

_DEFAULT = "ru"

TRANSLATIONS: dict[str, dict[str, str]] = {
    "ru": {
        "welcome_back": "С возвращением, охотник!",
        "balance": "Баланс: {amount} Мана-руды",
        "tasks_title": "Задания на сегодня",
        "no_tasks": "Доступных заданий пока нет — загляни позже.",
        "daily_limit": "Лимит заданий на сегодня исчерпан. Возвращайся завтра!",
        "credited": "Начислено +{reward} Мана-руды!",
        "already_done": "Это задание уже выполнено.",
        "not_subscribed": "Сначала подпишись на канал, затем проверь.",
        "wrong_answer": "Неверный ответ, попробуй ещё раз.",
        "shop_title": "Магазин наград",
        "leaderboard_title": "Топ охотников",
        "admin_only": "Команда доступна только администраторам.",
        "rank": "Ранг",
        "streak": "Стрик",
    },
    "en": {
        "welcome_back": "Welcome back, hunter!",
        "balance": "Balance: {amount} Mana Ore",
        "tasks_title": "Today's tasks",
        "no_tasks": "No tasks available right now — check back later.",
        "daily_limit": "Daily task limit reached. Come back tomorrow!",
        "credited": "Credited +{reward} Mana Ore!",
        "already_done": "You've already completed this task.",
        "not_subscribed": "Subscribe to the channel first, then verify.",
        "wrong_answer": "Wrong answer, try again.",
        "shop_title": "Rewards shop",
        "leaderboard_title": "Top hunters",
        "admin_only": "This command is for administrators only.",
        "rank": "Rank",
        "streak": "Streak",
    },
}


def set_default_lang(lang: str) -> None:
    global _DEFAULT
    _DEFAULT = normalize_lang(lang)


def normalize_lang(code: Optional[str]) -> str:
    """Приводит Telegram language_code к поддерживаемому коду ('ru'/'en')."""
    if not code:
        return _DEFAULT
    code = code.lower()
    if code.startswith("en"):
        return "en"
    if code.startswith("ru") or code.startswith("uk") or code.startswith("be"):
        return "ru"
    return _DEFAULT


def lang_of(user) -> str:
    """Язык пользователя по Telegram language_code (с фолбэком на дефолт)."""
    return normalize_lang(getattr(user, "language_code", None))


def t(key: str, lang: Optional[str] = None, **kwargs) -> str:
    """Локализованная строка. Фолбэк: запрошенный язык → RU → сам ключ."""
    lang = normalize_lang(lang)
    table = TRANSLATIONS.get(lang) or TRANSLATIONS[_DEFAULT]
    text = table.get(key) or TRANSLATIONS["ru"].get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text
