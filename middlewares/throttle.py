"""
Throttle middleware — rate-limits user actions to absorb command spam / flood.

Covers both messages and callback-button taps:
  • Messages exceeding the rate are dropped silently (flood protection).
  • Callback queries exceeding the rate are answered with a short notice so the
    button doesn't look frozen, but the heavy handler (which may hit the Telegram
    API, e.g. get_chat_member on task checks) is skipped.

Separate per-user timestamp maps for messages and callbacks so a normal tap
right after sending a message isn't falsely throttled.
"""
from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from time import time

from utils import is_owner


class ThrottleMiddleware(BaseMiddleware):
    def __init__(
        self,
        rate: float = 0.5,
        callback_rate: float = 0.7,
        cleanup_after: int = 300,
    ):
        self.rate = rate
        self.callback_rate = callback_rate
        self._cleanup_after = cleanup_after
        self._msg_ts: dict[int, float] = {}
        self._cb_ts: dict[int, float] = {}
        self._last_cleanup = time()

    def _cleanup(self, now: float) -> None:
        # Prevent unbounded memory growth from one-off users.
        if now - self._last_cleanup < self._cleanup_after:
            return
        cutoff = now - self._cleanup_after
        self._msg_ts = {uid: ts for uid, ts in self._msg_ts.items() if ts > cutoff}
        self._cb_ts = {uid: ts for uid, ts in self._cb_ts.items() if ts > cutoff}
        self._last_cleanup = now

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        now = time()

        if isinstance(event, Message) and event.from_user:
            uid = event.from_user.id
            if not is_owner(uid):
                self._cleanup(now)
                if now - self._msg_ts.get(uid, 0.0) < self.rate:
                    return  # Drop silently — flood protection
                self._msg_ts[uid] = now

        elif isinstance(event, CallbackQuery) and event.from_user:
            uid = event.from_user.id
            if not is_owner(uid):
                self._cleanup(now)
                if now - self._cb_ts.get(uid, 0.0) < self.callback_rate:
                    try:
                        await event.answer("⏳ Не так быстро.", show_alert=False)
                    except Exception:
                        pass
                    return  # Skip the heavy handler — anti-spam on buttons
                self._cb_ts[uid] = now

        return await handler(event, data)
