"""
Chat lifecycle: реагируем на добавление/повышение/удаление бота в чатах
(my_chat_member) — регистрация чата, приветствие и очистка БД.
"""
from aiogram import Router, Bot
from aiogram.types import ChatMemberUpdated

from services import handle_bot_membership

router = Router()


@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated, bot: Bot) -> None:
    await handle_bot_membership(bot, event)
