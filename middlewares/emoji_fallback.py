"""
Глобальный фолбэк премиум-эмодзи на уровне сессии бота.

Зачем: премиум-эмодзи (<tg-emoji>) бот может отправлять только при активном
Premium у владельца и НЕ в постах каналов. Если Telegram отвергает запрос
из-за custom emoji — этот middleware повторяет запрос, заменив <tg-emoji>
на обычные эмодзи (strip_custom_emoji). Так сообщение уходит в любом случае.

Перехват идёт на уровне session middleware, поэтому покрывает ВСЕ методы
(send_message, send_photo, edit_message_text и т.п.) без правок в хендлерах.
"""
from __future__ import annotations

from typing import Any

from aiogram import Bot
from aiogram.client.session.middlewares.base import (
    BaseRequestMiddleware,
    NextRequestMiddlewareType,
)
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import TelegramMethod
from aiogram.methods.base import TelegramType

from utils.premium_emoji import strip_custom_emoji

# Поля методов Telegram, где может встретиться <tg-emoji>.
_TEXT_FIELDS = ("text", "caption")


def _has_custom_emoji(method: TelegramMethod[Any]) -> bool:
    for field in _TEXT_FIELDS:
        val = getattr(method, field, None)
        if isinstance(val, str) and "<tg-emoji" in val:
            return True
    return False


def _stripped_method(method: TelegramMethod[Any]) -> TelegramMethod[Any]:
    update: dict[str, str] = {}
    for field in _TEXT_FIELDS:
        val = getattr(method, field, None)
        if isinstance(val, str) and "<tg-emoji" in val:
            update[field] = strip_custom_emoji(val)
    return method.model_copy(update=update)


class EmojiFallbackMiddleware(BaseRequestMiddleware):
    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Any:
        try:
            return await make_request(bot, method)
        except TelegramBadRequest:
            if _has_custom_emoji(method):
                return await make_request(bot, _stripped_method(method))
            raise
