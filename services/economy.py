"""
Economy business logic — earning and spending Мана-руда.

Handlers and other services call these functions; raw SQL stays in
database/economy.py. Balance is GLOBAL per user (one wallet across all chats).
"""
from typing import Optional

from aiogram import Bot

from database import (
    add_mana, spend_mana, get_wallet, get_wallet_balance,
    can_reward_message, mark_message_reward, claim_dungeon,
    award_achievement, add_xp, get_xp,
)
from utils import get_config, calculate_rank, rank_perks

# Код ачивки за 30-дневный стрик подземелья (уникальный тег для профиля).
STREAK_30_ACHIEVEMENT = "dungeon_streak_30"


# Разовый бонус руды при достижении нового ранга.
RANK_UP_BONUS = {
    "D": 100,
    "C": 250,
    "B": 600,
    "A": 1500,
    "S": 5000,
    "SS": 10000,
    "SSS": 25000,
}


async def award_message(user_id: int, chat_id: int) -> int:
    """
    Reward a user for chat activity, respecting the per-message cooldown.
    Returns the amount granted (0 if on cooldown / disabled).
    """
    cfg = get_config()
    amount = cfg.mana_per_message
    if amount <= 0:
        return 0
    if not await can_reward_message(user_id, cfg.mana_message_cooldown):
        return 0
    await add_mana(user_id, amount, "message", chat_id=chat_id)
    await mark_message_reward(user_id)
    return amount


async def award_daily(user_id: int, chat_id: int) -> int:
    cfg = get_config()
    if cfg.mana_daily_bonus <= 0:
        return 0
    await add_mana(user_id, cfg.mana_daily_bonus, "daily", chat_id=chat_id)
    return cfg.mana_daily_bonus


async def user_has_bot_ad(bot: Bot, user_id: int) -> bool:
    """
    True, если в описании профиля (bio) пользователя упомянут @username бота.
    Используется как «реклама бота» → бонус в ежедневном подземелье.
    """
    cfg = get_config()
    uname = (cfg.bot_username or "").lstrip("@").lower()
    if not uname:
        return False
    try:
        chat = await bot.get_chat(user_id)
    except Exception:
        return False
    bio = (getattr(chat, "bio", "") or "").lower()
    return uname in bio


async def claim_dungeon_reward(
    bot: Bot, user_id: int, chat_id: int = 0
) -> tuple[str, int, int, bool, int, int]:
    """
    Сбор ежедневного подземелья с проверкой рекламы в профиле и стриком.

    Возвращает (status, base_granted, ad_granted, has_ad, streak, milestone_bonus),
    где milestone_bonus > 0 ровно в тот сбор, когда стрик впервые достиг вехи
    (тогда же выдаётся единоразовая руда + уникальная ачивка-тег).
    """
    cfg = get_config()
    has_ad = await user_has_bot_ad(bot, user_id)
    status, base, ad, streak, milestone_hit = await claim_dungeon(
        user_id, has_ad, cfg.daily_dungeon_base, cfg.daily_dungeon_ad_bonus,
        chat_id, cfg.dungeon_streak_milestone,
    )
    milestone_bonus = 0
    if milestone_hit and cfg.dungeon_streak_reward > 0:
        milestone_bonus = cfg.dungeon_streak_reward
        await add_mana(user_id, milestone_bonus, "dungeon_streak", chat_id=chat_id)
        await add_xp(user_id, milestone_bonus)  # награда за стрик = опыт
        await award_achievement(user_id, STREAK_30_ACHIEVEMENT)

    # Подземелье даёт опыт → ранг мог вырасти. Тихо/громко синхронизируем.
    if status in ("claimed", "topup") or milestone_bonus:
        try:
            from .ranks import sync_rank
            await sync_rank(bot, user_id)
        except Exception:
            pass
    return status, base, ad, has_ad, streak, milestone_bonus


async def award_invite(user_id: int, chat_id: int) -> int:
    cfg = get_config()
    if cfg.mana_invite_bonus <= 0:
        return 0
    await add_mana(user_id, cfg.mana_invite_bonus, "invite", chat_id=chat_id)
    return cfg.mana_invite_bonus


async def award_rank_up(user_id: int, chat_id: int, new_rank: str) -> int:
    """Grant the one-off bonus for reaching `new_rank`. Returns granted amount."""
    bonus = RANK_UP_BONUS.get(new_rank, 0)
    if bonus > 0:
        await add_mana(user_id, bonus, "rank_up", ref_id=new_rank, chat_id=chat_id)
    return bonus


async def transfer_mana(
    from_id: int, to_id: int, amount: int, chat_id: int = 0
) -> tuple[bool, int, Optional[str]]:
    """
    Transfer mana between players. A small fee is burned to the treasury
    (deflation). Returns (ok, fee_burned, error_message).
    """
    if from_id == to_id:
        return False, 0, "Нельзя перевести руду самому себе."
    if amount <= 0:
        return False, 0, "Сумма должна быть больше нуля."

    cfg = get_config()
    # Привилегия ранга: высокоранговые охотники платят меньше комиссии казны.
    rank = calculate_rank(await get_xp(from_id))
    fee_pct = max(0, cfg.mana_transfer_fee_pct - rank_perks(rank)["transfer_fee_off"])
    fee = amount * fee_pct // 100
    total = amount + fee

    new_bal = await spend_mana(from_id, total, "transfer_out", ref_id=str(to_id), chat_id=chat_id)
    if new_bal is None:
        return False, 0, "Недостаточно руды (учти комиссию казны)."

    await add_mana(to_id, amount, "transfer_in", ref_id=str(from_id), chat_id=chat_id)
    return True, fee, None


async def balance_of(user_id: int) -> int:
    return await get_wallet_balance(user_id)


async def wallet_of(user_id: int) -> dict:
    return await get_wallet(user_id)
