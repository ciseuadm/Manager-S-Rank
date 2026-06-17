"""
Tasks business logic — платные задания (подписки на каналы), начисление руды
на ЕДИНЫЙ баланс, ежедневная ре-проверка подписок с clawback и обмен руды
на подарки через payout-запросы.

Баланс один (wallets.mana): и бесплатная добыча, и задания идут в него.
Маржу держим двумя рычагами:
  • бесплатная добыча сведена к минимуму (config: mana_per_message/daily);
  • награда за задание = revenue_usd × mana_per_usd × payout_ratio,
    т.е. при дефолте (20000 руды/$1, ratio 50%) мы оставляем себе ≥50%.
"""
from typing import Optional

from aiogram import Bot
from loguru import logger

from database import (
    get_task, get_active_tasks, get_completion, get_completed_task_ids,
    record_completion, add_mana, spend_mana, revert_mana, get_wallet_balance,
    get_wallet, get_credited_channel_completions, mark_completion_reverted,
    create_payout_request, count_user_credited_subs,
    award_achievement_capped, count_achievement,
)
from utils import get_config


# ── Экономика ────────────────────────────────────────────────────────────────

def reward_for_revenue(revenue_cents: int) -> int:
    """
    Награда в руде за задание с доходом revenue_cents (в центах).
    Гарантирует маржу (100 - payout_ratio)%.
    """
    cfg = get_config()
    revenue_usd = revenue_cents / 100
    return int(round(revenue_usd * cfg.mana_per_usd * cfg.task_payout_ratio / 100))


def mana_to_usd_cents(amount: int) -> int:
    """Себестоимость вывода `amount` руды, в центах (по базовому пегу)."""
    cfg = get_config()
    if cfg.mana_per_usd <= 0:
        return 0
    return int(round(amount / cfg.mana_per_usd * 100))


async def user_streak(user_id: int) -> int:
    """Текущий стрик = число сохранённых подписок-заданий."""
    return await count_user_credited_subs(user_id)


def streak_multiplier(streak: int) -> float:
    """Множитель награды за лесенку: 1 + min(streak, cap) × step%."""
    cfg = get_config()
    eff = min(max(streak, 0), cfg.task_streak_cap)
    return 1 + eff * cfg.task_streak_step_pct / 100


def _is_subscribed(member) -> bool:
    status = getattr(member, "status", None)
    status = getattr(status, "value", status)  # ChatMemberStatus enum → str
    if status in ("creator", "administrator", "member"):
        return True
    if status == "restricted":
        return bool(getattr(member, "is_member", False))
    return False


# ── Список заданий пользователя ──────────────────────────────────────────────

async def list_available_tasks(user_id: int) -> list[dict]:
    """Активные задания с пометкой, выполнено ли пользователем."""
    tasks = await get_active_tasks()
    done = await get_completed_task_ids(user_id)
    for t in tasks:
        t["done"] = t["id"] in done
    return tasks


# ── Проверка и начисление за подписку ────────────────────────────────────────

async def check_and_credit_subscription(
    bot: Bot, user_id: int, task_id: int
) -> tuple[str, int]:
    """
    Проверяет подписку на канал задания и начисляет руду один раз.
    Возвращает (code, reward), где code:
      'credited' | 'already' | 'not_subscribed' | 'misconfig' | 'inactive'
    """
    task = await get_task(task_id)
    if not task or not task.get("active"):
        return "inactive", 0
    if task.get("type") != "channel_sub":
        return "misconfig", 0

    existing = await get_completion(task_id, user_id)
    if existing and existing.get("status") == "credited":
        return "already", task.get("reward", 0)

    channel_id = task.get("channel_id")
    try:
        member = await bot.get_chat_member(channel_id, user_id)
    except Exception as e:
        logger.warning(f"[TASKS] get_chat_member failed task={task_id} ch={channel_id}: {e}")
        return "misconfig", 0

    if not _is_subscribed(member):
        return "not_subscribed", task.get("reward", 0)

    # Награда растёт со стриком (лесенка): чем больше сохранённых подписок — тем выше.
    base = task.get("reward", 0)
    streak = await user_streak(user_id)
    reward = int(round(base * streak_multiplier(streak)))

    # record_completion имеет UNIQUE(task_id,user_id) — защита от гонки/дублей.
    if existing and existing.get("status") == "reverted":
        # Пользователь вернулся: начисляем снова и переводим в credited.
        from database import get_db
        db = await get_db()
        await db.execute(
            "UPDATE task_completions SET status='credited', reward=?, checked_at=datetime('now') "
            "WHERE id=?",
            (reward, existing["id"]),
        )
        await db.commit()
    else:
        created = await record_completion(task_id, user_id, reward, "credited")
        if not created:
            return "already", reward

    await add_mana(user_id, reward, "task_subscribe", ref_id=str(task_id))
    logger.info(f"[TASKS] credited user={user_id} task={task_id} +{reward} (streak={streak})")
    await check_milestones(bot, user_id)
    return "credited", reward


async def check_milestones(bot: Bot, user_id: int) -> None:
    """
    Ачивка «первые 100 к рангу A»: первые N охотников, накопивших порог
    заработка, получают статус и разовый бонус. Остальные просто достигают
    порога без особой награды.
    """
    cfg = get_config()
    w = await get_wallet(user_id)
    if w.get("total_earned", 0) < cfg.achievement_rank_a_mana:
        return
    res = await award_achievement_capped(
        user_id, "rank_a_top100", cfg.achievement_first_slots
    )
    if res != "granted":
        return
    await add_mana(user_id, cfg.achievement_rank_a_bonus, "ach_rank_a_top100")
    place = await count_achievement("rank_a_top100")
    try:
        await bot.send_message(
            user_id,
            "👑 <b>СИСТЕМА: ДОСТИГНУТ РАНГ A!</b>\n\n"
            f"Ты вошёл в <b>первую сотню</b> охотников ранга A — место <b>#{place}</b> из "
            f"{cfg.achievement_first_slots}.\n"
            f"Награда первопроходца: <b>+{cfg.achievement_rank_a_bonus}</b> руды.\n\n"
            "<i>Имя занесено в анналы гильдии. Так держать, охотник!</i>",
            parse_mode="HTML",
        )
    except Exception:
        pass


# ── Ежедневная ре-проверка подписок (clawback) ───────────────────────────────

async def recheck_subscriptions(bot: Bot) -> dict:
    """
    Проверяет, остались ли пользователи подписанными. При отписке снимает
    начисленную руду (clawback) и помечает выполнение reverted.
    """
    comps = await get_credited_channel_completions()
    checked = 0
    reverted = 0
    for c in comps:
        checked += 1
        try:
            member = await bot.get_chat_member(c["channel_id"], c["user_id"])
        except Exception:
            # Канал/бот недоступен — не наказываем пользователя, пропускаем.
            continue
        if _is_subscribed(member):
            continue
        await revert_mana(
            c["user_id"], c["reward"], "task_clawback", ref_id=str(c["task_id"])
        )
        await mark_completion_reverted(c["comp_id"])
        reverted += 1
        try:
            await bot.send_message(
                c["user_id"],
                "⚠️ <b>Система зафиксировала отписку</b>\n\n"
                f"Награда за задание «{c.get('title') or 'подписка'}» отозвана "
                f"(−{c['reward']} руды). Подпишись снова и пройди задание заново, "
                "чтобы вернуть награду.",
                parse_mode="HTML",
            )
        except Exception:
            pass
    logger.info(f"[TASKS] recheck done: checked={checked} reverted={reverted}")
    return {"checked": checked, "reverted": reverted}


# ── Обмен руды на подарок ────────────────────────────────────────────────────

async def request_payout(user_id: int, amount: int, product: str) -> tuple[bool, Optional[int], str]:
    """
    Создаёт заявку на вывод: списывает redeemable-руду в escrow и регистрирует
    payout_request (владелец подтверждает вручную). Возвращает (ok, req_id, err).
    """
    cfg = get_config()
    if amount < cfg.redeem_min:
        return False, None, f"Минимум для обмена — {cfg.redeem_min} руды."
    bal = await get_wallet_balance(user_id)
    if bal < amount:
        return False, None, "Недостаточно Мана-руды на балансе."

    new_bal = await spend_mana(user_id, amount, "redeem", ref_id=product)
    if new_bal is None:
        return False, None, "Недостаточно руды (списание не прошло)."

    usd_cents = mana_to_usd_cents(amount)
    req_id = await create_payout_request(user_id, amount, product, usd_cents)
    logger.info(f"[TASKS] payout request #{req_id} user={user_id} {amount} → {product}")
    return True, req_id, ""


async def refund_payout(user_id: int, amount: int, ref: str = "") -> None:
    """Вернуть руду при отклонении заявки владельцем."""
    await add_mana(user_id, amount, "redeem_refund", ref_id=ref)
