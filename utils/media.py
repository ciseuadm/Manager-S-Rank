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
    """Переход на другой экран кнопочной навигации (drill-down).

    Принципиально НЕ редактируем сообщение, а шлём новое и удаляем старое:
    редактирование в Telegram всегда вешает на пост пометку «изменено», что
    выглядит как баг. Новый пост приходит чистым.

    Чтобы не перезагружать картинку и не терять баннер, фото переотправляем
    по уже готовому file_id текущего сообщения (мгновенно, без повторной
    загрузки). Если текст не влезает в подпись (лимит 1024) — шлём только текст.
    Старое сообщение удаляем лишь после успешной отправки нового, чтобы
    навигация никогда не «зависала» на пустом месте.
    """
    photo_id = message.photo[-1].file_id if message.photo else None
    new_msg: Message | None = None
    try:
        if photo_id and visible_len(text) <= _CAPTION_LIMIT:
            new_msg = await message.answer_photo(
                photo_id, caption=text, parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
        else:
            new_msg = await message.answer(
                text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview,
            )
    except Exception as e:
        logger.warning(f"[EDIT_SCREEN] send new screen failed: {e}")
        # Последняя попытка — простым текстом без фото.
        try:
            new_msg = await message.answer(
                text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview,
            )
        except Exception as e2:
            logger.warning(f"[EDIT_SCREEN] text fallback failed: {e2}")
            return None

    if new_msg is not None:
        try:
            await message.delete()
        except Exception:
            pass
    return new_msg
