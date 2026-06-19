"""
Безопасные обёртки над вызовами Telegram API для модерации.

Правило проекта: каждый вызов Telegram API — в try/except с ретраем при
TelegramRetryAfter (флуд-контроль). Эти хелперы:
  • один раз ждут retry_after и повторяют запрос при флуд-контроле;
  • не роняют хендлер при отсутствии прав/устаревшем сообщении;
  • возвращают bool успеха, чтобы вызывающий код мог сообщить админу об ошибке;
  • откладывают удаление уведомлений без блокировки обработчика апдейта.
"""
import asyncio
from datetime import datetime
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import ChatPermissions, Message
from loguru import logger

# Полные права участника — для снятия мута (восстановление возможностей писать).
UNMUTE_PERMISSIONS = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
)

MUTE_PERMISSIONS = ChatPermissions(can_send_messages=False)


async def _retry_once(coro_factory, what: str) -> bool:
    """Выполнить вызов; при TelegramRetryAfter подождать и повторить один раз."""
    try:
        await coro_factory()
        return True
    except TelegramRetryAfter as e:
        logger.warning(f"[TG] flood wait {e.retry_after}s on {what}")
        await asyncio.sleep(e.retry_after + 1)
        try:
            await coro_factory()
            return True
        except Exception as e2:
            logger.warning(f"[TG] retry failed on {what}: {e2}")
            return False
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        logger.warning(f"[TG] {what} failed (no rights / bad request): {e}")
        return False
    except Exception as e:
        logger.warning(f"[TG] {what} error: {e}")
        return False


async def safe_restrict(
    bot: Bot, chat_id: int, user_id: int,
    permissions: ChatPermissions, until_date: Optional[datetime] = None,
) -> bool:
    return await _retry_once(
        lambda: bot.restrict_chat_member(
            chat_id=chat_id, user_id=user_id,
            permissions=permissions, until_date=until_date,
        ),
        f"restrict {user_id}@{chat_id}",
    )


async def safe_mute(bot: Bot, chat_id: int, user_id: int,
                    until_date: Optional[datetime] = None) -> bool:
    return await safe_restrict(bot, chat_id, user_id, MUTE_PERMISSIONS, until_date)


async def safe_unmute(bot: Bot, chat_id: int, user_id: int) -> bool:
    return await safe_restrict(bot, chat_id, user_id, UNMUTE_PERMISSIONS)


async def safe_ban(bot: Bot, chat_id: int, user_id: int) -> bool:
    return await _retry_once(
        lambda: bot.ban_chat_member(chat_id=chat_id, user_id=user_id),
        f"ban {user_id}@{chat_id}",
    )


async def safe_unban(bot: Bot, chat_id: int, user_id: int,
                     only_if_banned: bool = True) -> bool:
    return await _retry_once(
        lambda: bot.unban_chat_member(
            chat_id=chat_id, user_id=user_id, only_if_banned=only_if_banned,
        ),
        f"unban {user_id}@{chat_id}",
    )


async def safe_kick(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Кик = бан + немедленный разбан (пользователь может вернуться)."""
    ok = await safe_ban(bot, chat_id, user_id)
    if ok:
        await safe_unban(bot, chat_id, user_id, only_if_banned=True)
    return ok


def delete_later(message: Message, delay: int = 15) -> None:
    """Удалить сообщение через `delay` секунд, не блокируя обработчик апдейта."""
    async def _job() -> None:
        try:
            await asyncio.sleep(delay)
            await message.delete()
        except Exception:
            pass
    asyncio.create_task(_job())
