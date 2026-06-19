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
    get_or_create_guild, set_guild_name, guild_member_count,
    guild_rank_counts, top_guilds,
)
from services import vip_status
from utils import (
    require_admin, get_config, format_mana, escape_html, mention_html,
    rank_index, get_rank_label, RANKS,
    MYREF_MSG, MYREF_VIP_MSG, SETGOAL_HELP, GOALS_LIST_MSG,
    VIP_PROGRESS_MSG, VIP_OPEN_MSG,
    GUILD_CARD_MSG, GUILD_NO_NAME_HINT, GUILD_RENAMED_MSG, GUILD_NAME_BAD_MSG,
    GUILD_TOP_HEADER, GUILD_TOP_EMPTY,
)

_SS_IDX = rank_index("SS")
_SSS_IDX = rank_index("SSS")

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
        from services import AGENT_REWARDS
        text = MYREF_MSG.format(
            bot_link=link,
            bot_count=count,
            to_vip=max(0, threshold - count),
            bonus=format_mana(AGENT_REWARDS.get("D", cfg.mana_referral_rankup)),
        )
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)


# ── /guild — своя гильдия (создать имя / посмотреть статистику) ───────────────

def _count_at_or_above(counts: dict, min_idx: int) -> int:
    return sum(c for r, c in counts.items() if rank_index(r) >= min_idx)


@router.message(Command("guild", "myguild"))
async def cmd_guild(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    cfg = get_config()

    # Аргумент → задать/переименовать гильдию.
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 2 and parts[1].strip():
        name = " ".join(parts[1].split())
        if not (2 <= len(name) <= 32):
            await message.answer(GUILD_NAME_BAD_MSG, parse_mode="HTML")
            return
        await set_guild_name(user.id, name)
        await message.answer(
            GUILD_RENAMED_MSG.format(name=escape_html(name)), parse_mode="HTML"
        )
        return

    guild = await get_or_create_guild(user.id)
    members = await guild_member_count(user.id)
    counts = await guild_rank_counts(user.id)

    breakdown_lines = []
    for rid, _thr, label, _title in RANKS:
        if rid == "E":
            continue
        c = counts.get(rid, 0)
        if c:
            breakdown_lines.append(f"{label}: <b>{c}</b>")
    breakdown = "\n".join(breakdown_lines) or "<i>пока только новички (E-ранг)</i>"

    block = cfg.agent_milestone_block
    ss = _count_at_or_above(counts, _SS_IDX)
    sss = _count_at_or_above(counts, _SSS_IDX)
    name = guild.get("name")

    text = GUILD_CARD_MSG.format(
        name=escape_html(name) if name else "Безымянная",
        owner=mention_html(user),
        members=members,
        breakdown=breakdown,
        ss=ss,
        sss=sss,
        ss_goal=(ss // block + 1) * block,
        sss_goal=(sss // block + 1) * block,
        ss_reward=format_mana(cfg.agent_ss_block_reward),
        sss_reward=format_mana(cfg.agent_sss_block_reward),
        block=block,
        link=_bot_ref_link(cfg.bot_username, user.id),
    )
    if not name:
        text += GUILD_NO_NAME_HINT
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)


# ── /guilds — рейтинг крупнейших гильдий ──────────────────────────────────────

@router.message(Command("guilds", "topguilds"))
async def cmd_guilds(message: Message) -> None:
    rows = await top_guilds(10)
    rows = [r for r in rows if r["members"] > 0]
    if not rows:
        await message.answer(GUILD_TOP_EMPTY, parse_mode="HTML", disable_web_page_preview=True)
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = [GUILD_TOP_HEADER]
    for i, r in enumerate(rows):
        prefix = medals[i] if i < 3 else f"{i + 1}."
        name = escape_html(r["name"]) if r.get("name") else "Безымянная гильдия"
        lines.append(f"{prefix} <b>«{name}»</b> — {r['members']} охотников")
    await message.answer("\n".join(lines), parse_mode="HTML")


# ── /vip ─────────────────────────────────────────────────────────────────────

@router.message(Command("vip"))
async def cmd_vip(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    cfg = get_config()
    count, threshold, is_vip = await vip_status(user.id)
    if is_vip and cfg.vip_chat_link:
        text = VIP_OPEN_MSG.format(count=count, link=cfg.vip_chat_link)
    else:
        text = VIP_PROGRESS_MSG.format(
            threshold=threshold, count=count, left=max(0, threshold - count)
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
