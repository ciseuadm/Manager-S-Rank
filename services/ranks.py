"""
Ранги по выполненным заданиям (глобально по user_id).

Источник истины ранга — число зачтённых подписок (`count_user_credited_subs`).
`sync_task_rank` вызывается после начисления за задание и после clawback:
ловит повышение, обновляет хранимый ранг (wallets.rank), выдаёт разовый
бонус руды, объявляет повышение и платит агенту-вербовщику за веху рекрута.
"""
from aiogram import Bot
from loguru import logger

from database import (
    count_user_credited_subs, get_wallet_rank, set_wallet_rank,
)
from utils import (
    calculate_rank, rank_index, get_rank_label, get_rank_title,
    score_to_next_rank, rank_progress_bar,
)

from .economy import award_rank_up
from .referral import reward_agent_on_rank


RANKUP_DM = (
    "⚡ <b>СИСТЕМА: НОВЫЙ РАНГ!</b>\n\n"
    "Ты поднялся: {old_label} → <b>{new_label}</b>\n"
    "🎖 Звание: <i>{title}</i>\n"
    "📌 Заданий выполнено: <b>{score}</b>{bonus_line}\n\n"
    "<i>Чем выше ранг — тем круче статус и привилегии. Так держать, охотник!</i>"
)


async def get_rank_score(user_id: int) -> int:
    return await count_user_credited_subs(user_id)


async def rank_card(user_id: int) -> dict:
    """Данные ранга для отображения в карточках (/rank, /me, welcome и т.д.)."""
    score = await count_user_credited_subs(user_id)
    rank = calculate_rank(score)
    return {
        "score": score,
        "rank": rank,
        "label": get_rank_label(rank),
        "title": get_rank_title(rank),
        "progress": rank_progress_bar(score, rank),
        "to_next": score_to_next_rank(score, rank),
    }


async def sync_task_rank(bot: Bot, user_id: int, *, announce: bool = True) -> str:
    """
    Пересчитывает глобальный ранг по числу заданий и фиксирует его.
    При повышении: бонус руды + объявление + агентская награда вербовщику.
    При понижении (clawback): тихо обновляет хранимый ранг. Возвращает ранг.
    """
    score = await count_user_credited_subs(user_id)
    new_rank = calculate_rank(score)
    old_rank = await get_wallet_rank(user_id)
    if new_rank == old_rank:
        return new_rank

    await set_wallet_rank(user_id, new_rank)

    if rank_index(new_rank) <= rank_index(old_rank):
        return new_rank  # понижение/откат — без шума

    # ── Повышение ранга ──────────────────────────────────────────────────────
    bonus = 0
    try:
        bonus = await award_rank_up(user_id, 0, new_rank)
    except Exception:
        pass

    if announce:
        bonus_line = f"\n⛏ Бонус за ранг: <b>+{bonus}</b> руды" if bonus else ""
        try:
            await bot.send_message(
                user_id,
                RANKUP_DM.format(
                    old_label=get_rank_label(old_rank),
                    new_label=get_rank_label(new_rank),
                    title=get_rank_title(new_rank),
                    score=score,
                    bonus_line=bonus_line,
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    # Агент-вербовщик получает награду за новую веху своего рекрута.
    try:
        await reward_agent_on_rank(bot, user_id, new_rank)
    except Exception:
        pass

    logger.info(f"[RANK] user={user_id} {old_rank}→{new_rank} (score={score})")
    return new_rank
