"""
Баннеры для атмосферных команд бота (Solo Leveling стиль).

Telegram caption — до 1024 символов; длинный текст уходит отдельным сообщением.
"""
from __future__ import annotations

from pathlib import Path

from aiogram.types import FSInputFile, Message
from loguru import logger

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

    if len(text) <= _CAPTION_LIMIT:
        try:
            return await message.answer_photo(
                photo,
                caption=text,
                reply_markup=reply_markup,
                **kwargs,
            )
        except Exception as e:
            logger.warning(f"[BANNER:{banner_key}] photo+caption failed: {e}")

    try:
        await message.answer_photo(photo)
    except Exception as e:
        logger.warning(f"[BANNER:{banner_key}] photo failed: {e}")

    return await message.answer(
        text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
        disable_web_page_preview=disable_web_page_preview,
    )
