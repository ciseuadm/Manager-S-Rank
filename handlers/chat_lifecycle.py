"""
Chat lifecycle: реагируем на добавление/повышение/удаление бота в чатах
(my_chat_member) и даём охотникам кабинет привлечения чатов (/mychats).

Это ядро роста: каждый, кто добавил бота-модератора в свой чат, получает руду
и становится нашим распространителем.
"""
from aiogram import Router, Bot
from aiogram.filters import Command
from aiogram.types import (
    Message, ChatMemberUpdated, InlineKeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import list_chats_brought, count_active_chats_brought
from services import handle_bot_membership, progress_line
from utils import get_config, escape_html, format_mana, MYCHATS_MSG, MYCHATS_EMPTY_HINT

router = Router()


# ── Изменение статуса бота в чате ────────────────────────────────────────────

@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated, bot: Bot) -> None:
    await handle_bot_membership(bot, event)


# ── /mychats — кабинет привлечения чатов ─────────────────────────────────────

def _mychats_keyboard(bot_username: str) -> object:
    b = InlineKeyboardBuilder()
    if bot_username:
        b.row(InlineKeyboardButton(
            text="➕ Добавить бота в свой чат",
            url=f"https://t.me/{bot_username}?startgroup=true",
        ))
    return b.as_markup()


@router.message(Command("mychats", "mynetwork"))
async def cmd_mychats(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    cfg = get_config()
    active = await count_active_chats_brought(user.id)
    chats = await list_chats_brought(user.id, limit=15)

    if chats:
        lines = []
        for c in chats:
            mark = "🛡" if (c.get("status") == "active" and c.get("is_admin")) else "💤"
            title = escape_html(c.get("title") or str(c.get("chat_id")))
            lines.append(f"{mark} {title}")
        chats_block = "<b>Твои чаты:</b>\n" + "\n".join(lines)
    else:
        chats_block = MYCHATS_EMPTY_HINT

    text = MYCHATS_MSG.format(
        active=active,
        progress=progress_line(active, cfg.chat_recruit_block),
        bonus=format_mana(cfg.mana_chat_owner_bonus),
        block=cfg.chat_recruit_block,
        block_reward=format_mana(cfg.chat_recruit_block_reward),
        chats=chats_block,
    )
    await message.answer(
        text, parse_mode="HTML", disable_web_page_preview=True,
        reply_markup=_mychats_keyboard(cfg.bot_username),
    )
