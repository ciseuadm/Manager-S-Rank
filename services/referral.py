"""
Referral business logic.

Two referral channels:
  • chat_id = 0  → invitation into the BOT itself (deep-link). Counts toward VIP.
  • chat_id > 0  → invitation into a specific group. Drives per-chat goals
                   (e.g. "invite 5 → moderator").
"""
from typing import Optional

from aiogram import Bot
from loguru import logger

from database import (
    add_referral, count_referrals, count_bot_referrals,
    get_referral_goals, set_chat_role, add_mana, credit_invite,
    get_unrewarded_referral, mark_all_referrals_rewarded,
    get_primary_referral, set_referral_paid_rank,
)
from utils import (
    get_config, mention_html_raw, format_mana,
    get_rank_label, rank_index,
)


VIP_REACHED_MSG = (
    "👑 <b>ДОСТУП МОНАРХА ОТКРЫТ!</b>\n\n"
    "Ты пригласил <b>{count}</b> охотников в Систему и доказал свою силу.\n"
    "Тебе открыт <b>VIP-зал</b> с прямой связью с создателем (Богом Системы).\n\n"
    "🔗 Вход: {link}\n\n"
    "<i>Это награда для сильнейших вербовщиков. Добро пожаловать в элиту.</i>"
)

GOAL_ROLE_MSG = (
    "⚡ <b>ПОВЫШЕНИЕ ПО ЗАСЛУГАМ!</b>\n\n"
    "{mention} пригласил <b>{count}</b> охотников и получает роль "
    "<b>{role}</b> в этой гильдии!"
)

GOAL_MANA_MSG = (
    "🎯 <b>ЦЕЛЬ ДОСТИГНУТА!</b>\n\n"
    "{mention} пригласил <b>{count}</b> охотников и получает награду: "
    "<b>{reward}</b>"
)

_ROLE_LABELS = {"moderator": "🛡 Модератор", "admin": "👑 Админ"}


async def register_bot_referral(bot: Bot, inviter_id: int, invited_id: int) -> None:
    """A new user started the bot via someone's deep-link. Reward + VIP check."""
    before = await count_bot_referrals(inviter_id)
    is_new = await add_referral(inviter_id, invited_id, 0, "deeplink")
    if not is_new:
        return

    cfg = get_config()
    if cfg.mana_invite_bonus > 0:
        await add_mana(inviter_id, cfg.mana_invite_bonus, "invite_bot", ref_id=str(invited_id))

    after = before + 1
    # Notify the inviter privately about progress. Награда за приглашение
    # начисляется НЕ за вход, а когда новичок впервые поднимет ранг (E→D) —
    # это отсекает накрутку «мёртвыми» аккаунтами.
    reward_line = (
        f"Начислено <b>{format_mana(cfg.mana_invite_bonus)}</b>.\n"
        if cfg.mana_invite_bonus > 0
        else (
            f"Награда <b>{format_mana(cfg.mana_referral_rankup)}</b> придёт, когда "
            f"новичок поднимет свой первый ранг (докажет, что он живой).\n"
        )
    )
    try:
        await bot.send_message(
            inviter_id,
            f"⚔️ По твоей ссылке пришёл новый охотник!\n"
            + reward_line
            + f"Всего приглашено в бота: <b>{after}</b>"
            + (
                f"  (до VIP: {max(0, cfg.vip_invite_threshold - after)})"
                if after < cfg.vip_invite_threshold else ""
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass

    # VIP threshold crossed exactly now → unlock VIP room.
    if before < cfg.vip_invite_threshold <= after and cfg.vip_chat_link:
        try:
            await bot.send_message(
                inviter_id,
                VIP_REACHED_MSG.format(count=after, link=cfg.vip_chat_link),
                parse_mode="HTML",
            )
        except Exception:
            pass
        logger.info(f"[VIP] user {inviter_id} reached {after} bot referrals")


async def register_chat_referral(
    bot: Bot, inviter_id: int, invited_id: int, chat_id: int,
    inviter_name: str = "", source: str = "chat_join",
) -> Optional[int]:
    """
    A new member joined a group thanks to `inviter_id`.
    Records it, rewards mana + legacy invite counter, checks per-chat goals.
    Returns the inviter's new referral count for this chat, or None if duplicate.
    """
    is_new = await add_referral(inviter_id, invited_id, chat_id, source)
    if not is_new:
        return None

    cfg = get_config()
    # Legacy counter + experience bonus (existing behaviour) and mana.
    await credit_invite(inviter_id, chat_id, cfg.mana_invite_bonus)
    if cfg.mana_invite_bonus > 0:
        await add_mana(inviter_id, cfg.mana_invite_bonus, "invite", ref_id=str(invited_id), chat_id=chat_id)

    new_count = await count_referrals(inviter_id, chat_id)
    await _check_goals(bot, inviter_id, chat_id, new_count, inviter_name)
    return new_count


async def _check_goals(bot: Bot, inviter_id: int, chat_id: int,
                       new_count: int, inviter_name: str) -> None:
    """Fire any goal whose threshold equals the inviter's new count (exact-cross)."""
    goals = await get_referral_goals(chat_id, active_only=True)
    mention = mention_html_raw(inviter_id, inviter_name or "Охотник")
    for g in goals:
        if g["invites_required"] != new_count:
            continue
        if g["reward_type"] == "role":
            role = g["reward_value"]
            await set_chat_role(inviter_id, chat_id, role, 0)
            try:
                await bot.send_message(
                    chat_id,
                    GOAL_ROLE_MSG.format(
                        mention=mention, count=new_count,
                        role=_ROLE_LABELS.get(role, role),
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass
        elif g["reward_type"] == "mana":
            try:
                amount = int(g["reward_value"])
            except (ValueError, TypeError):
                amount = 0
            if amount > 0:
                await add_mana(inviter_id, amount, "ref_goal", ref_id=str(chat_id), chat_id=chat_id)
                try:
                    await bot.send_message(
                        chat_id,
                        GOAL_MANA_MSG.format(
                            mention=mention, count=new_count,
                            reward=format_mana(amount),
                        ),
                        parse_mode="HTML",
                    )
                except Exception:
                    pass


# Агентские награды: руда вербовщику («агенту») за каждую новую ранговую веху
# его рекрута. Финансируются нашей маржой — пока рекрут жмёт подписки, мы зарабатываем
# больше, чем платим агенту. D даёт «доказательство жизни», дальше — за рост.
AGENT_REWARDS = {
    "D": 50,
    "C": 100,
    "B": 300,
    "A": 800,
    "S": 2000,
    "SS": 4000,
    "SSS": 8000,
}

AGENT_REWARD_MSG = (
    "🕴 <b>ОТЧЁТ АГЕНТА</b>\n\n"
    "Твой рекрут дорос до ранга <b>{rank}</b>.\n"
    "Гильдия начисляет агентское вознаграждение: <b>{reward}</b>.\n\n"
    "<i>Ты — Агент Системы: зови сильных охотников и расти вместе с ними.</i>"
)


async def reward_agent_on_rank(bot: Bot, invited_id: int, new_rank: str) -> None:
    """
    Платит агенту-вербовщику за каждую НОВУЮ ранговую веху его рекрута.
    Суммирует награды за все вехи между уже оплаченным рангом и текущим
    (на случай «прыжка» через ранг). Платит ровно одному агенту на рекрута.
    """
    new_idx = rank_index(new_rank)
    if new_idx <= 0:  # E или неизвестный ранг — не платим
        return
    ref = await get_primary_referral(invited_id)
    if not ref:
        return
    inviter_id = ref["inviter_id"]
    if inviter_id == invited_id:
        return
    paid_idx = rank_index(ref.get("paid_rank") or "E")
    if paid_idx < 0:
        paid_idx = 0
    if new_idx <= paid_idx:
        return  # за эту веху уже заплачено

    amount = sum(
        reward for r, reward in AGENT_REWARDS.items()
        if paid_idx < rank_index(r) <= new_idx
    )
    await set_referral_paid_rank(ref["id"], new_rank)
    if amount <= 0:
        return
    await add_mana(inviter_id, amount, "agent_reward", ref_id=str(invited_id))
    try:
        await bot.send_message(
            inviter_id,
            AGENT_REWARD_MSG.format(rank=get_rank_label(new_rank), reward=format_mana(amount)),
            parse_mode="HTML",
        )
    except Exception:
        pass


async def vip_status(inviter_id: int) -> tuple[int, int, bool]:
    """Returns (bot_referrals, threshold, is_vip)."""
    cfg = get_config()
    count = await count_bot_referrals(inviter_id)
    return count, cfg.vip_invite_threshold, count >= cfg.vip_invite_threshold
