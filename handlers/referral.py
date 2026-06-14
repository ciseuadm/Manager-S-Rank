"""
Referral commands: /myref, /setgoal, /goals, /delgoal.
Deep-link handling (/start ref_<id>) lives in handlers/user.py and calls
services.referral.register_bot_referral.
"""
from aiogram import Router, F, Bot
from aiogram.filters import Command

from aiogram.types import Message

from database import (
    add_referral_goal, get_referral_goals, deactivate_goal,
)
from services import vip_status
from utils import (
    require_admin, get_config, format_mana,
    MYREF_MSG, MYREF_VIP_MSG, SETGOAL_HELP, GOALS_LIST_MSG,
)

router = Router()

_ROLE_LABELS = {"moderator": "🛡 Модератор", "admin": "👑 Админ"}


def _bot_ref_link(username: str, user_id: int) -> str:
    return f"https://t.me/{username}?start=ref_{user_id}"


# ── /myref ───────────────────────────────────────────────────────────────────

@router.message(Command("myref", "ref"))
async def cmd_myref(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    cfg = get_config()
    link = _bot_ref_link(cfg.bot_username, user.id)
    count, threshold, is_vip = await vip_status(user.id)

    if is_vip and cfg.vip_chat_link:
        text = MYREF_VIP_MSG.format(
            bot_link=link, bot_count=count, vip_link=cfg.vip_chat_link
        )
    else:
        text = MYREF_MSG.format(
            bot_link=link,
            bot_count=count,
            to_vip=max(0, threshold - count),
            bonus=format_mana(cfg.mana_invite_bonus),
        )
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)


# ── /setgoal (admin) ─────────────────────────────────────────────────────────

@router.message(Command("setgoal"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_setgoal(message: Message, bot: Bot) -> None:
    if not await require_admin(message, bot):
        return
    args = (message.text or "").split()
    # /setgoal <N> <role|mana> [value]
    if len(args) < 3 or not args[1].isdigit():
        await message.reply(SETGOAL_HELP, parse_mode="HTML")
        return

    invites = int(args[1])
    kind = args[2].lower()

    if kind in ("moderator", "admin", "role"):
        role = "moderator" if kind == "role" else kind
        if kind == "role":
            role = args[3].lower() if len(args) >= 4 else "moderator"
        if role not in ("moderator", "admin"):
            await message.reply("Роль должна быть <code>moderator</code> или <code>admin</code>.", parse_mode="HTML")
            return
        await add_referral_goal(message.chat.id, invites, "role", role, message.from_user.id)
        await message.answer(
            f"✅ Цель создана: пригласи <b>{invites}</b> → роль <b>{_ROLE_LABELS[role]}</b>.",
            parse_mode="HTML",
        )
    elif kind == "mana":
        if len(args) < 4 or not args[3].isdigit():
            await message.reply("Укажи сумму руды: <code>/setgoal 20 mana 1000</code>", parse_mode="HTML")
            return
        amount = int(args[3])
        await add_referral_goal(message.chat.id, invites, "mana", str(amount), message.from_user.id)
        await message.answer(
            f"✅ Цель создана: пригласи <b>{invites}</b> → <b>{format_mana(amount)}</b>.",
            parse_mode="HTML",
        )
    else:
        await message.reply(SETGOAL_HELP, parse_mode="HTML")


# ── /goals ───────────────────────────────────────────────────────────────────

@router.message(Command("goals"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_goals(message: Message) -> None:
    goals = await get_referral_goals(message.chat.id, active_only=True)
    if not goals:
        await message.answer(
            "🎯 Целей приглашений пока нет.\n"
            "Админ может создать их: /setgoal"
        )
        return
    lines = [GOALS_LIST_MSG]
    for g in goals:
        if g["reward_type"] == "role":
            reward = _ROLE_LABELS.get(g["reward_value"], g["reward_value"])
        else:
            reward = format_mana(int(g["reward_value"]))
        lines.append(
            f"🔸 <code>#{g['id']}</code> пригласи <b>{g['invites_required']}</b> → {reward}"
        )
    await message.answer("\n".join(lines), parse_mode="HTML")


# ── /delgoal (admin) ─────────────────────────────────────────────────────────

@router.message(Command("delgoal"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_delgoal(message: Message, bot: Bot) -> None:
    if not await require_admin(message, bot):
        return
    args = (message.text or "").split()
    if len(args) < 2 or not args[1].isdigit():
        await message.reply("Использование: <code>/delgoal 3</code> (id из /goals)", parse_mode="HTML")
        return
    await deactivate_goal(int(args[1]), message.chat.id)
    await message.answer(f"🗑 Цель <code>#{args[1]}</code> удалена.", parse_mode="HTML")
