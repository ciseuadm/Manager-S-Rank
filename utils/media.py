"""
Баннеры для атмосферных команд бота (Solo Leveling стиль).

Caption у фото в Telegram — до 1024 символов ВИДИМОГО текста (HTML/<tg-emoji>
теги в лимит не входят, эмодзи = 2 ед. UTF-16). Если текст влезает — шлём фото
с подписью и кнопками ОДНИМ сообщением. Если нет (например, /help) — шлём только
текст одним сообщением, без «оторванной» аватарки отдельным постом.
"""
from __future__ import annotations

from pathlib import Path

from aiogram.types import FSInputFile, Message
from loguru import logger

from utils.premium_emoji import visible_len

ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"

# Ключ → файл в assets/
BANNERS: dict[str, str] = {
    "start": "bot_banner_960x540.png",
    "earn": "banner_earn.png",
    "help": "banner_help.png",
    "shop": "banner_shop.png",
    "rules": "banner_rules.png",
    "settings": "banner_settings.png",
    "owner": "banner_owner.png",
    "tasks": "banner_tasks.png",
    "buy": "banner_shop.png",
}

_CAPTION_LIMIT = 1024


def banner_path(key: str) -> Path | None:
    name = BANNERS.get(key)
    if not name:
        return None
    path = ASSETS_DIR / name
    return path if path.is_file() else None


def banner_file(key: str) -> FSInputFile | None:
    path = banner_path(key)
    return FSInputFile(path) if path else None


async def answer_with_banner(
    message: Message,
    banner_key: str,
    text: str,
    *,
    parse_mode: str = "HTML",
    reply_markup=None,
    disable_web_page_preview: bool | None = None,
) -> Message | None:
    """Фото-баннер + текст (caption или отдельным сообщением). Возвращает последнее сообщение."""
    photo = banner_file(banner_key)
    if photo is None:
        return await message.answer(
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )

    kwargs: dict = {"parse_mode": parse_mode}
    if disable_web_page_preview is not None:
        kwargs["disable_web_page_preview"] = disable_web_page_preview

    # Лимит подписи считаем по ВИДИМОМУ тексту (без HTML/<tg-emoji> тегов),
    # иначе длинные премиум-теги ложно «выталкивают» фото в отдельное сообщение.
    if visible_len(text) <= _CAPTION_LIMIT:
        try:
            return await message.answer_photo(
                photo,
                caption=text,
                reply_markup=reply_markup,
                **kwargs,
            )
        except Exception as e:
            logger.warning(f"[BANNER:{banner_key}] photo+caption failed: {e}")

    # Текст не влезает в подпись (например, /help): НЕ шлём фото отдельным
    # сообщением (это и есть «оторванная аватарка»), а отправляем только текст
    # одним сообщением. Принцип: либо фото+текст слитно, либо просто текст.
    logger.info(f"[BANNER:{banner_key}] text too long for caption "
                f"(visible={visible_len(text)}), sending text-only")
    return await message.answer(
        text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
        disable_web_page_preview=disable_web_page_preview,
    )


async def edit_screen(
    message: Message,
    text: str,
    *,
    reply_markup=None,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = True,
) -> Message | None:
    """Редактирует сообщение «на месте» для кнопочной навигации (drill-down).

    Если сообщение с фото-баннером — правим caption (лимит 1024), иначе text
    (лимит 4096). При сбое (например, текст не влез в caption) — отправляем
    новое сообщение, чтобы навигация никогда не «зависала».
    """
    try:
        if message.photo and visible_len(text) <= _CAPTION_LIMIT:
            return await message.edit_caption(
                caption=text, parse_mode=parse_mode, reply_markup=reply_markup
            )
        if not message.photo:
            return await message.edit_text(
                text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview,
            )
    except Exception as e:
        logger.warning(f"[EDIT_SCREEN] edit failed: {e}")
    # Фото с длинным текстом или ошибка → новое сообщение.
    try:
        return await message.answer(
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )
    except Exception as e:
        logger.warning(f"[EDIT_SCREEN] answer fallback failed: {e}")
        return None
