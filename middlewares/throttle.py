"""
Throttle middleware — rate-limits user actions to avoid spam of commands.
"""
from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message
from time import time
from collections import defaultdict


class ThrottleMiddleware(BaseMiddleware):
    def __init__(self, rate: float = 1.0):
        self.rate = rate
        self._timestamps: dict[int, float] = defaultdict(float)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.from_user:
            uid = event.from_user.id
            now = time()
            if now - self._timestamps[uid] < self.rate:
                return  # Drop silently
            self._timestamps[uid] = now
        return await handler(event, data)
