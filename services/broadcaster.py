"""
Safe fan-out delivery to many chats.

Handles Telegram rate limits (RetryAfter), retries, and auto-removes dead chats
(bot kicked/blocked) from the DB. Used by /broadcast and the ads scheduler so we
never trip flood control even with thousands of chats.
"""
import asyncio
from typing import Awaitable, Callable, Iterable, Optional

from aiogram import Bot
from aiogram.exceptions import (
    TelegramRetryAfter, TelegramForbiddenError, TelegramBadRequest,
)
from loguru import logger

from database import remove_chat

# Telegram allows ~30 msg/sec to different chats. 0.05s ≈ 20/sec — safe headroom.
_DELAY = 0.05

# Errors that mean the chat is gone for good → clean it from the DB.
_DEAD_MARKERS = (
    "chat not found", "bot was kicked", "bot was blocked",
    "user is deactivated", "the group chat was deleted",
    "not enough rights", "bot is not a member", "chat_write_forbidden",
)


def _is_dead(text: str) -> bool:
    t = text.lower()
    return any(m in t for m in _DEAD_MARKERS)


async def broadcast(
    bot: Bot,
    chat_ids: Iterable[int],
    send_fn: Callable[[Bot, int], Awaitable[None]],
    *,
    cleanup_dead: bool = True,
    on_progress: Optional[Callable[[int, int, int], Awaitable[None]]] = None,
    progress_every: int = 25,
) -> dict:
    """
    Deliver to every chat via `send_fn(bot, chat_id)`.

    Returns {'sent': int, 'failed': int, 'removed': int}.
    `on_progress(sent, failed, removed)` is awaited every `progress_every` chats.
    """
    sent = failed = removed = 0
    chat_list = list(chat_ids)

    for i, chat_id in enumerate(chat_list, 1):
        try:
            await send_fn(bot, chat_id)
            sent += 1
        except TelegramRetryAfter as e:
            logger.warning(f"[BROADCAST] flood wait {e.retry_after}s on {chat_id}")
            await asyncio.sleep(e.retry_after + 1)
            try:
                await send_fn(bot, chat_id)
                sent += 1
            except Exception as e2:
                failed += 1
                logger.warning(f"[BROADCAST] retry failed {chat_id}: {e2}")
        except (TelegramForbiddenError, TelegramBadRequest) as e:
            failed += 1
            if cleanup_dead and _is_dead(str(e)):
                try:
                    await remove_chat(chat_id)
                    removed += 1
                except Exception:
                    pass
            logger.warning(f"[BROADCAST] {chat_id} failed: {e}")
        except Exception as e:
            failed += 1
            logger.warning(f"[BROADCAST] {chat_id} error: {e}")

        if on_progress and i % progress_every == 0:
            try:
                await on_progress(sent, failed, removed)
            except Exception:
                pass
        await asyncio.sleep(_DELAY)

    return {"sent": sent, "failed": failed, "removed": removed}
