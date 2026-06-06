"""
Throttle middleware — rate-limits user actions to absorb command spam / flood.
Drops excess events silently so the bot can't be overwhelmed by a single user.
"""
from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message
from time import time

from utils import is_owner


class ThrottleMiddleware(BaseMiddleware):
    def __init__(self, rate: float = 0.5, cleanup_after: int = 300):
        self.rate = rate
        self._cleanup_after = cleanup_after
        self._timestamps: dict[int, float] = {}
        self._last_cleanup = time()

    def _cleanup(self, now: float) -> None:
        # Prevent unbounded memory growth from one-off users.
        if now - self._last_cleanup < self._cleanup_after:
            return
        cutoff = now - self._cleanup_after
        self._timestamps = {
            uid: ts for uid, ts in self._timestamps.items() if ts > cutoff
        }
        self._last_cleanup = now

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.from_user:
            uid = event.from_user.id
            if not is_owner(uid):
                now = time()
                self._cleanup(now)
                last = self._timestamps.get(uid, 0.0)
                if now - last < self.rate:
                    return  # Drop silently — flood protection
                self._timestamps[uid] = now
        return await handler(event, data)
