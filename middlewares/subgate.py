"""
Subscription-gate middleware — требует подписки на канал бота для работы в ЛИЧКЕ.

Правила:
  • Действует только в личных чатах с ботом. Группы (модерация) не трогаем.
  • Всегда пропускаем /start (его хендлер сам покажет гейт) и callback проверки
    подписки (GATE_CALLBACK) — это «точки входа».
  • Если охотник не подписан — на сообщение показываем гейт-сообщение, на нажатие
    чужой кнопки отвечаем алертом. Хендлер при этом не вызывается.
  • Владелец и режим с выключенным гейтом не блокируются (логика в is_gate_passed).
"""
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

from services import is_gate_passed, send_gate, GATE_CALLBACK


class SubGateMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        bot = data.get("bot")

        if isinstance(event, Message):
            if (
                event.chat.type != "private"
                or not event.from_user
                or bot is None
                or (event.text or "").startswith("/start")
            ):
                return await handler(event, data)
            if await is_gate_passed(bot, event.from_user.id):
                return await handler(event, data)
            await send_gate(event)
            return  # блокируем: команда не выполнится без подписки

        if isinstance(event, CallbackQuery):
            msg = event.message
            if (
                msg is None
                or getattr(msg.chat, "type", None) != "private"
                or not event.from_user
                or bot is None
                or (event.data or "") == GATE_CALLBACK
            ):
                return await handler(event, data)
            if await is_gate_passed(bot, event.from_user.id):
                return await handler(event, data)
            try:
                await event.answer(
                    "🔒 Сначала подпишись на канал бота — нажми /start.",
                    show_alert=True,
                )
            except Exception:
                pass
            return

        return await handler(event, data)
