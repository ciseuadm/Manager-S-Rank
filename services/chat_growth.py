"""
Реакция на изменение статуса САМОГО бота в чате (`my_chat_member`).

Регистрирует чат в БД, приветствует Систему в стиле SL и чистит запись при
удалении бота. Отдельных наград «за добавление чата» нет — рост идёт через
стандартную реферальную систему (награда за приглашённых пользователей).
"""
from aiogram import Bot
from aiogram.types import ChatMemberUpdated
from loguru import logger

from database import set_chat_title, remove_chat
from utils import BOT_ADDED_WELCOME, BOT_NEEDS_ADMIN_MSG

# Статусы, означающие, что участник присутствует в чате.
_PRESENT = {"member", "administrator", "creator", "restricted"}


def _present(status: str) -> bool:
    return status in _PRESENT


async def _send_chat(bot: Bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id, text, parse_mode="HTML",
                               disable_web_page_preview=True)
    except Exception as e:
        logger.warning(f"[GROWTH] chat msg {chat_id} failed: {e}")


async def handle_bot_membership(bot: Bot, event: ChatMemberUpdated) -> None:
    """Единая точка обработки изменения статуса бота в чате."""
    chat = event.chat
    if chat.type not in ("group", "supergroup"):
        return

    old = event.old_chat_member.status
    new = event.new_chat_member.status
    title = chat.title or ""

    became_present = (not _present(old)) and _present(new)
    became_absent = _present(old) and (not _present(new))
    is_admin_now = new == "administrator"

    if became_absent:
        await remove_chat(chat.id)
        logger.info(f"[GROWTH] bot removed from {chat.id}")
        return

    if became_present:
        await set_chat_title(chat.id, title)
        await _send_chat(bot, chat.id, BOT_ADDED_WELCOME if is_admin_now else BOT_NEEDS_ADMIN_MSG)
        return

    # Повышение до админа уже присутствующего бота — поприветствуем один раз.
    if is_admin_now and old != "administrator":
        await set_chat_title(chat.id, title)
        await _send_chat(bot, chat.id, BOT_ADDED_WELCOME)
