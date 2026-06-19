"""
Канал-витрина бота: авто-постинг топа охотников недели.

Работает на росте: подписчики канала видят живой рейтинг, FOMO тянет их играть
и звать друзей. Цель публикации — bot_channel_id, иначе канал гейта подписки.
"""
from aiogram import Bot
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from database import get_top_mana, get_wallet_rank
from utils import get_config, format_mana, get_rank_label, escape_html

_MEDALS = ["🥇", "🥈", "🥉"] + ["🔹"] * 7


def _target(cfg) -> object:
    return cfg.bot_channel_id or cfg.sub_gate_channel or None


async def post_weekly_top(bot: Bot) -> bool:
    """Публикует топ-10 добытчиков руды в канал-витрину. True, если опубликовано."""
    cfg = get_config()
    target = _target(cfg)
    if not target:
        return False

    top = [t for t in await get_top_mana(limit=10) if t.get("mana", 0) > 0]
    if not top:
        return False

    lines = [
        "🏆 <b>ТОП ОХОТНИКОВ НЕДЕЛИ</b>",
        "<i>Сильнейшие добытчики Мана-руды Системы.</i>\n",
    ]
    for i, t in enumerate(top):
        try:
            chat = await bot.get_chat(t["user_id"])
            name = escape_html(chat.full_name or chat.username or str(t["user_id"]))
        except Exception:
            name = str(t["user_id"])
        label = get_rank_label(await get_wallet_rank(t["user_id"]))
        lines.append(f"{_MEDALS[i]} {i + 1}. <b>{name}</b> {label} — {format_mana(t['mana'])}")
    lines.append("\n<i>Хочешь в топ? Качай ранг, фарми руду в подземельях и зови охотников.</i>")
    text = "\n".join(lines)

    kb = None
    uname = (cfg.bot_username or "").lstrip("@")
    if uname:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="⚡ Открыть бота", url=f"https://t.me/{uname}"))
        b.row(InlineKeyboardButton(
            text="➕ Добавить в свой чат", url=f"https://t.me/{uname}?startgroup=true",
        ))
        kb = b.as_markup()

    try:
        await bot.send_message(
            target, text, parse_mode="HTML",
            reply_markup=kb, disable_web_page_preview=True,
        )
        logger.info("[SHOWCASE] weekly top posted")
        return True
    except Exception as e:
        logger.warning(f"[SHOWCASE] post failed: {e}")
        return False
