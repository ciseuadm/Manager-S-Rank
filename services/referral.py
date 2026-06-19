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
    get_or_create_guild, guild_rank_counts, set_guild_blocks,
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

    # Гарантируем строку гильдии вербовщика — чтобы он попадал в рейтинг и
    # корректно копились веховые бонусы за состав.
    await get_or_create_guild(inviter_id)

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


# Агентские награды (фиксированные, одноразово за каждую веху рекрута).
# До S включительно — за ранг рекрута. SS и SSS персональных наград не дают:
# вместо этого ведётся СЧЁТ игроков SS/SSS в гильдии и платятся веховые бонусы
# за каждые N таких игроков (см. agent_*_block_reward в конфиге).
AGENT_REWARDS = {
    "D": 50,
    "C": 100,
    "B": 200,
    "A": 400,
    "S": 800,
}

# Индексы рангов SS/SSS в общей лестнице (для подсчёта состава гильдии).
_SS_IDX = rank_index("SS")
_SSS_IDX = rank_index("SSS")

AGENT_REWARD_MSG = (
    "🕴 <b>ОТЧЁТ АГЕНТА</b>\n\n"
    "Твой рекрут дорос до ранга <b>{rank}</b>.\n"
    "Гильдия начисляет агентское вознаграждение: <b>{reward}</b>.\n\n"
    "<i>Ты — Агент Системы: зови сильных охотников и расти вместе с ними.</i>"
)

AGENT_MILESTONE_MSG = (
    "🏛 <b>ВЕХА ГИЛЬДИИ!</b>\n\n"
    "В твоей гильдии уже <b>{count}</b> охотников ранга <b>{rank}</b>.\n"
    "Награда за веху: <b>{reward}</b>.\n"
    "🎯 Следующая цель: <b>{next_goal}</b> игроков ранга {rank}.\n\n"
    "<i>Чем больше сильных охотников ты привёл — тем щедрее Система.</i>"
)


def _count_at_or_above(counts: dict[str, int], min_idx: int) -> int:
    """Сколько участников гильдии имеют ранг с индексом >= min_idx."""
    return sum(c for r, c in counts.items() if rank_index(r) >= min_idx)


async def _pay_milestone(bot: Bot, owner_id: int, rank_label_id: str, count: int,
                         block: int, paid_blocks: int, block_reward: int) -> int:
    """Доплачивает веховые бонусы за новые «десятки» игроков. Возвращает новое
    число оплаченных блоков."""
    blocks = count // block
    if blocks <= paid_blocks:
        return paid_blocks
    amount = (blocks - paid_blocks) * block_reward
    await add_mana(owner_id, amount, "agent_milestone", ref_id=rank_label_id)
    try:
        await bot.send_message(
            owner_id,
            AGENT_MILESTONE_MSG.format(
                count=count,
                rank=get_rank_label(rank_label_id),
                reward=format_mana(amount),
                next_goal=(blocks + 1) * block,
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass
    return blocks


async def reward_agent_on_rank(bot: Bot, invited_id: int, new_rank: str) -> None:
    """
    Платит агенту-вербовщику за рост его рекрута.
    • Ранги D..S — фиксированная награда за каждую новую веху (одноразово).
    • Ранги SS/SSS — персональных наград нет; пересчитываем число таких игроков
      в гильдии агента и платим веховый бонус за каждые N игроков.
    Платит ровно одному агенту на рекрута (первичный реферал).
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

    cfg = get_config()
    paid_idx = rank_index(ref.get("paid_rank") or "E")
    if paid_idx < 0:
        paid_idx = 0

    # 1) Фиксированные награды за вехи D..S (суммируем неоплаченные).
    if new_idx > paid_idx:
        amount = sum(
            reward for r, reward in AGENT_REWARDS.items()
            if paid_idx < rank_index(r) <= new_idx
        )
        await set_referral_paid_rank(ref["id"], new_rank)
        if amount > 0:
            await add_mana(inviter_id, amount, "agent_reward", ref_id=str(invited_id))
            try:
                await bot.send_message(
                    inviter_id,
                    AGENT_REWARD_MSG.format(
                        rank=get_rank_label(new_rank), reward=format_mana(amount),
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass

    # 2) Веховые бонусы за массовость SS/SSS (только когда рекрут добрался до SS+).
    if new_idx >= _SS_IDX:
        guild = await get_or_create_guild(inviter_id)
        counts = await guild_rank_counts(inviter_id)
        ss_count = _count_at_or_above(counts, _SS_IDX)
        sss_count = _count_at_or_above(counts, _SSS_IDX)
        block = cfg.agent_milestone_block

        new_ss = await _pay_milestone(
            bot, inviter_id, "SS", ss_count, block,
            guild.get("ss_blocks_paid", 0), cfg.agent_ss_block_reward,
        )
        new_sss = await _pay_milestone(
            bot, inviter_id, "SSS", sss_count, block,
            guild.get("sss_blocks_paid", 0), cfg.agent_sss_block_reward,
        )
        if new_ss != guild.get("ss_blocks_paid", 0) or new_sss != guild.get("sss_blocks_paid", 0):
            await set_guild_blocks(inviter_id, ss=new_ss, sss=new_sss)


async def vip_status(inviter_id: int) -> tuple[int, int, bool]:
    """Returns (bot_referrals, threshold, is_vip)."""
    cfg = get_config()
    count = await count_bot_referrals(inviter_id)
    return count, cfg.vip_invite_threshold, count >= cfg.vip_invite_threshold
