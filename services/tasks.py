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

import time

from database import (
    get_task, get_active_tasks, get_completion, get_completed_task_ids,
    record_completion, add_mana, spend_mana, get_wallet_balance,
    get_wallet, set_task_active, task_completions_count,
    create_payout_request, count_user_credited_subs, add_xp, get_xp,
    award_achievement_capped, count_achievement,
    get_user_channel_task_completions, count_user_completions_today,
    get_completion_by_id, set_completion_status, has_pending_completion,
    payout_sum_today,
)
from utils import (
    get_config, calculate_rank, rank_reward_multiplier,
)


# ── Типы заданий и режимы проверки ───────────────────────────────────────────
# Любое задание создаёт ТОЛЬКО владелец (ручное одобрение) — фрод-задания
# исключены на входе. Режим проверки выбирается автоматически по типу:
#   membership — подписка/вступление (Bot API: get_chat_member) — авто;
#   timer      — просмотр N секунд (таймер внутри бота) — авто;
#   quiz       — верный ответ (сверка с эталоном) — авто;
#   proof      — ручной пруф (react/boost/bot_start/external/UGC): выполнение
#                уходит в очередь, владелец подтверждает/отклоняет.
_VERIFY_BY_TYPE = {
    "channel_sub": "membership",
    "chat_join": "membership",
    "watch": "timer",
    "quiz": "quiz",
}


def default_verify_mode(task_type: str) -> str:
    return _VERIFY_BY_TYPE.get(task_type, "proof")


# Старт таймера просмотра в памяти процесса: (user_id, task_id) -> monotonic ts.
_watch_starts: dict[tuple[int, int], float] = {}


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
    """Оценка себестоимости `amount` руды в центах USD (для P&L владельца)."""
    cfg = get_config()
    rub = amount / max(cfg.mana_per_rub, 1)
    usd = rub / max(cfg.usd_rub_rate, 1)
    return int(round(usd * 100))


def mana_to_rub(amount: int) -> float:
    cfg = get_config()
    return amount / max(cfg.mana_per_rub, 1)


async def find_unsubscribed_channels(
    bot: Bot, user_id: int, exclude_task_id: int = 0
) -> list[dict]:
    """
    Каналы прошлых спонсоров, на которых пользователь ДОЛЖЕН оставаться подписан
    (гарантия неотписки ещё активна), но отписался. Именно они блокируют
    зачёт следующего задания. Каналы с истёкшей гарантией не блокируют.
    Никаких штрафов: руда и опыт за прошлые задания не трогаются.
    """
    from .sponsors import completion_guaranteed

    comps = await get_user_channel_task_completions(user_id)
    seen: set[int] = set()
    missing: list[dict] = []
    for c in comps:
        if c.get("status") != "credited":
            continue
        tid = c["task_id"]
        if tid == exclude_task_id or tid in seen:
            continue
        seen.add(tid)
        if not completion_guaranteed(c):
            continue  # гарантия истекла — отписка разрешена, не блокируем
        try:
            member = await bot.get_chat_member(c["channel_id"], user_id)
        except Exception:
            continue
        if not _is_subscribed(member):
            missing.append(c)
    return missing


def resubscribe_keyboard(channels: list[dict]):
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    b = InlineKeyboardBuilder()
    for c in channels[:12]:
        url = c.get("url") or (
            f"https://t.me/{c['channel_username']}" if c.get("channel_username") else None
        )
        if not url:
            continue
        title = (c.get("title") or "Канал")[:30]
        b.row(InlineKeyboardButton(text=f"↩️ {title}", url=url))
    b.row(InlineKeyboardButton(text="📋 Открыть задания", callback_data="task:list"))
    return b.as_markup()


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


# ── Дневной лимит и индивидуальный подбор заданий ────────────────────────────

def effective_daily_limit(rank: str = "") -> int:
    """Дневной лимит заданий — ЕДИНЫЙ для всех рангов (макс. 3/день по умолчанию).
    Параметр rank оставлен для совместимости вызовов и не влияет на результат."""
    return get_config().tasks_daily_limit


async def list_available_tasks(user_id: int) -> list[dict]:
    """Активные задания с пометкой, выполнено ли пользователем (без лимита).
    Оставлено для обратной совместимости; UI использует daily_tasks_view."""
    tasks = await get_active_tasks()
    done = await get_completed_task_ids(user_id)
    for t in tasks:
        t["done"] = t["id"] in done
    return tasks


async def daily_tasks_view(user_id: int) -> dict:
    """
    Индивидуальный подбор заданий на сегодня — без повторов и с дневным лимитом.

    • «Без повторов» — из пула исключены уже выполненные охотником задания
      (не предлагаем канал, на который он уже подписан и получил награду).
    • «Дневной лимит» — base (config.tasks_daily_limit) + бонус ранга. Показываем
      ровно столько новых заданий, сколько охотник ещё может выполнить сегодня.

    Возвращает dict: rank, limit, done_today, remaining, tasks, pool_size.
    """
    xp = await get_xp(user_id)
    rank = calculate_rank(xp)
    limit = effective_daily_limit(rank)
    done_today = await count_user_completions_today(user_id)
    remaining = max(0, limit - done_today)

    active = await get_active_tasks()
    done_ids = await get_completed_task_ids(user_id)
    pool = [t for t in active if t["id"] not in done_ids]  # без повторов
    # Платный приоритет выше всего, затем — новые спонсоры (по id).
    pool.sort(key=lambda t: (t.get("priority", 0), t["id"]), reverse=True)
    todays = pool[:remaining]
    for t in todays:
        t["done"] = False
    return {
        "rank": rank,
        "limit": limit,
        "done_today": done_today,
        "remaining": remaining,
        "tasks": todays,
        "pool_size": len(pool),
    }


# ── Проверка и начисление за подписку ────────────────────────────────────────

async def check_and_credit_subscription(
    bot: Bot, user_id: int, task_id: int
) -> tuple[str, int]:
    """
    Проверяет подписку на канал задания и начисляет руду один раз.
    Возвращает (code, reward), где code:
      'credited' | 'already' | 'not_subscribed' | 'misconfig' | 'inactive'
      | 'locked' | 'daily_limit'

    'daily_limit' — на сегодня охотник уже выполнил максимум заданий (база +
    бонус ранга). Новые задания засчитаются завтра; награда/опыт не трогаются.

    'locked' — мягкая блокировка: пользователь отписался от канала прошлого
    спонсора, на котором ещё обязан быть подписан. Штрафов нет — нужно просто
    вернуться на тот канал, и следующее задание снова станет доступно.
    """
    task = await get_task(task_id)
    if not task or not task.get("active"):
        return "inactive", 0
    if task.get("type") != "channel_sub":
        return "misconfig", 0

    existing = await get_completion(task_id, user_id)
    if existing and existing.get("status") == "credited":
        return "already", task.get("reward", 0)

    # Гейт: пока не вернёшься на каналы прошлых спонсоров (с активной гарантией),
    # новое задание не засчитывается. Это единственное «наказание» — без отъёма руды.
    blockers = await find_unsubscribed_channels(bot, user_id, exclude_task_id=task_id)
    if blockers:
        return "locked", 0

    # Ранг считаем один раз: нужен и для дневного лимита, и для бонуса награды.
    xp = await get_xp(user_id)
    rank = calculate_rank(xp)

    # Дневной лимит: новое задание (не восстановление после отписки) сверх лимита
    # не засчитываем — защита экономики от «фарма» подписок за день.
    is_new = not (existing and existing.get("status") == "reverted")
    if is_new:
        done_today = await count_user_completions_today(user_id)
        if done_today >= effective_daily_limit(rank):
            return "daily_limit", 0

    channel_id = task.get("channel_id")
    try:
        member = await bot.get_chat_member(channel_id, user_id)
    except Exception as e:
        logger.warning(f"[TASKS] get_chat_member failed task={task_id} ch={channel_id}: {e}")
        return "misconfig", 0

    if not _is_subscribed(member):
        return "not_subscribed", task.get("reward", 0)

    # Награда растёт со стриком (лесенка) и с привилегией ранга (S/SS/SSS):
    # reward = base × множитель_стрика × множитель_ранга.
    base = task.get("reward", 0)
    streak = await user_streak(user_id)
    reward = int(round(base * streak_multiplier(streak) * rank_reward_multiplier(rank)))

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
    # Опыт за задание — фиксированный (XP_PER_TASK), не зависит от стрик-бонуса
    # руды: так шкала ранга остаётся стабильной (3 задания = ранг D).
    from utils import XP_PER_TASK
    await add_xp(user_id, XP_PER_TASK)
    logger.info(f"[TASKS] credited user={user_id} task={task_id} +{reward} (streak={streak})")
    await check_milestones(bot, user_id)
    # Ранг считается по накопленному опыту → пересчёт + бонус/агент.
    try:
        from .ranks import sync_rank
        await sync_rank(bot, user_id)
    except Exception:
        pass

    # Авто-стоп: заказ спонсора выполнен (набрано нужное число подписчиков) —
    # снимаем канал из активных, дальше игрокам показываются другие задания.
    target = task.get("target_subs", 0) or 0
    if target > 0:
        try:
            done = await task_completions_count(task_id)
            if done >= target:
                await set_task_active(task_id, 0)
                logger.info(f"[TASKS] task={task_id} target {target} reached → auto-stopped")
        except Exception:
            pass

    return "credited", reward


async def _grant_generic(
    bot: Bot, task: dict, user_id: int, rank: str, reason: str
) -> tuple[str, int]:
    """Начисление за не-channel_sub задание (без стрика подписок).
    reward = base × множитель ранга. Один раз на охотника."""
    base = task.get("reward", 0)
    reward = int(round(base * rank_reward_multiplier(rank)))
    created = await record_completion(task["id"], user_id, reward, "credited")
    if not created:
        return "already", reward
    await add_mana(user_id, reward, reason, ref_id=str(task["id"]))
    from utils import XP_PER_TASK
    await add_xp(user_id, XP_PER_TASK)
    logger.info(f"[TASKS] credited({task.get('type')}) user={user_id} task={task['id']} +{reward}")
    await check_milestones(bot, user_id)
    try:
        from .ranks import sync_rank
        await sync_rank(bot, user_id)
    except Exception:
        pass
    target = task.get("target_subs", 0) or 0
    if target > 0:
        try:
            if await task_completions_count(task["id"]) >= target:
                await set_task_active(task["id"], 0)
        except Exception:
            pass
    return "credited", reward


async def check_and_credit_task(
    bot: Bot, user_id: int, task_id: int, payload: str = ""
) -> tuple[str, int]:
    """
    Универсальная проверка/начисление по любому типу задания. Диспетчеризует по
    verify_mode. Коды результата (надстройка над channel_sub):
      'credited' | 'already' | 'inactive' | 'locked' | 'daily_limit'
      | 'not_subscribed'                       (membership)
      | 'watch_started' | 'watch_wait'         (timer; reward=сек)
      | 'wrong_answer'                         (quiz)
      | 'proof_submitted' | 'proof_pending'    (proof)
      | 'misconfig'
    """
    task = await get_task(task_id)
    if not task or not task.get("active"):
        return "inactive", 0
    ttype = task.get("type", "channel_sub")
    if ttype == "channel_sub":
        return await check_and_credit_subscription(bot, user_id, task_id)

    mode = task.get("verify_mode") or default_verify_mode(ttype)
    if mode == "timer":
        return await watch_claim(bot, user_id, task_id)

    existing = await get_completion(task_id, user_id)
    if existing and existing.get("status") == "credited":
        return "already", task.get("reward", 0)

    # Гейт обязательств перед прошлыми спонсорами действует для всех типов.
    blockers = await find_unsubscribed_channels(bot, user_id, exclude_task_id=task_id)
    if blockers:
        return "locked", 0

    rank = calculate_rank(await get_xp(user_id))

    if mode == "proof":
        if await has_pending_completion(task_id, user_id):
            return "proof_pending", 0
        await record_completion(task_id, user_id, task.get("reward", 0), "pending", proof=payload)
        logger.info(f"[TASKS] proof submitted user={user_id} task={task_id}")
        return "proof_submitted", 0

    # membership / quiz потребляют дневной лимит при зачёте.
    if await count_user_completions_today(user_id) >= effective_daily_limit(rank):
        return "daily_limit", 0

    if mode == "membership":
        channel_id = task.get("channel_id")
        if not channel_id:
            return "misconfig", 0
        try:
            member = await bot.get_chat_member(channel_id, user_id)
        except Exception as e:
            logger.warning(f"[TASKS] get_chat_member failed task={task_id}: {e}")
            return "misconfig", 0
        if not _is_subscribed(member):
            return "not_subscribed", task.get("reward", 0)
        return await _grant_generic(bot, task, user_id, rank, f"task_{ttype}")

    if mode == "quiz":
        answer = (task.get("answer") or "").strip().lower()
        if not answer:
            return "misconfig", 0
        if (payload or "").strip().lower() != answer:
            return "wrong_answer", 0
        return await _grant_generic(bot, task, user_id, rank, "task_quiz")

    return "misconfig", 0


async def watch_claim(bot: Bot, user_id: int, task_id: int) -> tuple[str, int]:
    """Задание-просмотр: первый клик стартует таймер, повторный (после
    duration_sec) — засчитывает. reward в кодах watch_* = секунды."""
    task = await get_task(task_id)
    if not task or not task.get("active"):
        return "inactive", 0
    existing = await get_completion(task_id, user_id)
    if existing and existing.get("status") == "credited":
        return "already", task.get("reward", 0)

    blockers = await find_unsubscribed_channels(bot, user_id, exclude_task_id=task_id)
    if blockers:
        return "locked", 0

    rank = calculate_rank(await get_xp(user_id))
    if await count_user_completions_today(user_id) >= effective_daily_limit(rank):
        return "daily_limit", 0

    duration = int(task.get("duration_sec", 0) or 30)
    key = (user_id, task_id)
    start = _watch_starts.get(key)
    now = time.monotonic()
    if start is None:
        _watch_starts[key] = now
        return "watch_started", duration
    elapsed = now - start
    if elapsed < duration:
        return "watch_wait", int(duration - elapsed) + 1
    _watch_starts.pop(key, None)
    return await _grant_generic(bot, task, user_id, rank, "task_watch")


async def credit_pending_completion(bot: Bot, comp_id: int) -> tuple[str, int, int]:
    """Владелец подтверждает pending-пруф: начисляет руду+опыт.
    Возвращает (code, user_id, reward)."""
    comp = await get_completion_by_id(comp_id)
    if not comp or comp.get("status") != "pending":
        return "not_found", 0, 0
    task = await get_task(comp["task_id"])
    if not task:
        return "not_found", comp["user_id"], 0
    rank = calculate_rank(await get_xp(comp["user_id"]))
    reward = int(round(task.get("reward", 0) * rank_reward_multiplier(rank)))
    await set_completion_status(comp_id, "credited")
    await add_mana(comp["user_id"], reward, "task_proof", ref_id=str(task["id"]))
    from utils import XP_PER_TASK
    await add_xp(comp["user_id"], XP_PER_TASK)
    try:
        from .ranks import sync_rank
        await sync_rank(bot, comp["user_id"])
    except Exception:
        pass
    return "credited", comp["user_id"], reward


async def reject_pending_completion(comp_id: int) -> tuple[str, int]:
    comp = await get_completion_by_id(comp_id)
    if not comp or comp.get("status") != "pending":
        return "not_found", 0
    await set_completion_status(comp_id, "rejected")
    return "rejected", comp["user_id"]


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


async def request_crypto_payout(user_id: int, amount: int) -> tuple[bool, Optional[int], str]:
    """
    Заявка на КРИПТО-вывод руды: проверяет лимиты (минимум, суточный потолок),
    списывает руду в escrow и регистрирует payout_request с product
    "crypto:<ASSET>". Подтверждает/исполняет владелец в /payouts (авто-перевод
    через Crypto Pay при наличии токена, иначе вручную). (ok, req_id, err).
    """
    cfg = get_config()
    if not cfg.crypto_withdraw_enabled:
        return False, None, "Крипто-вывод пока отключён."
    if amount < cfg.crypto_min_mana:
        return False, None, f"Минимум для крипто-вывода — {cfg.crypto_min_mana} руды."

    bal = await get_wallet_balance(user_id)
    if bal < amount:
        return False, None, "Недостаточно Мана-руды на балансе."

    used_today = await payout_sum_today(user_id, "crypto:")
    if used_today + amount > cfg.crypto_daily_limit_mana:
        left = max(0, cfg.crypto_daily_limit_mana - used_today)
        return False, None, (
            f"Суточный лимит крипто-вывода — {cfg.crypto_daily_limit_mana} руды. "
            f"Сегодня доступно ещё {left}."
        )

    product = f"crypto:{cfg.crypto_asset}"
    new_bal = await spend_mana(user_id, amount, "redeem_crypto", ref_id=product)
    if new_bal is None:
        return False, None, "Недостаточно руды (списание не прошло)."

    usd_cents = mana_to_usd_cents(amount)
    req_id = await create_payout_request(user_id, amount, product, usd_cents)
    logger.info(f"[TASKS] crypto payout request #{req_id} user={user_id} {amount} → {product}")
    return True, req_id, ""
