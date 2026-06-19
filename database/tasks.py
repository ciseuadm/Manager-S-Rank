"""
Tasks data layer — платные задания, выполнения и payout-запросы.

Pure SQL, без бизнес-логики (она в services/tasks.py).

Баланс единый (wallets.mana) — начисление/списание руды живёт в
database/economy.py (add_mana / spend_mana / revert_mana).
"""
from typing import Optional

from .db import get_db


# ── Tasks CRUD ───────────────────────────────────────────────────────────────

async def create_task(
    *, type: str, title: str, channel_id: int, channel_username: str,
    url: str, reward: int, revenue_cents: int, daily: int, created_by: int,
    sponsor_type: str = "house", advertiser_id: int = 0, anonymous: int = 1,
    description: str = "", target_subs: int = 0, guarantee_days: int = 0,
) -> int:
    db = await get_db()
    cur = await db.execute(
        """INSERT INTO tasks
           (type, title, channel_id, channel_username, url, reward,
            revenue_cents, daily, created_by, sponsor_type, advertiser_id,
            anonymous, description, target_subs, guarantee_days)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (type, title, channel_id, channel_username, url, reward,
         revenue_cents, daily, created_by, sponsor_type, advertiser_id,
         anonymous, description, target_subs, guarantee_days),
    )
    await db.commit()
    return cur.lastrowid


async def get_task(task_id: int) -> Optional[dict]:
    db = await get_db()
    async with db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def get_active_tasks(type: Optional[str] = None, limit: int = 50) -> list[dict]:
    db = await get_db()
    if type:
        sql = "SELECT * FROM tasks WHERE active = 1 AND type = ? ORDER BY id DESC LIMIT ?"
        args = (type, limit)
    else:
        sql = "SELECT * FROM tasks WHERE active = 1 ORDER BY id DESC LIMIT ?"
        args = (limit,)
    async with db.execute(sql, args) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def list_tasks(limit: int = 50) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,)
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def set_task_active(task_id: int, active: int) -> None:
    db = await get_db()
    await db.execute("UPDATE tasks SET active = ? WHERE id = ?", (active, task_id))
    await db.commit()


async def task_completions_count(task_id: int) -> int:
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) AS c FROM task_completions WHERE task_id = ? AND status = 'credited'",
        (task_id,),
    ) as cur:
        row = await cur.fetchone()
    return row["c"] if row else 0


# ── Completions ──────────────────────────────────────────────────────────────

async def get_completion(task_id: int, user_id: int) -> Optional[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM task_completions WHERE task_id = ? AND user_id = ?",
        (task_id, user_id),
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def get_completed_task_ids(user_id: int) -> set[int]:
    db = await get_db()
    async with db.execute(
        "SELECT task_id FROM task_completions WHERE user_id = ? AND status = 'credited'",
        (user_id,),
    ) as cur:
        rows = await cur.fetchall()
    return {r["task_id"] for r in rows}


async def record_completion(
    task_id: int, user_id: int, reward: int, status: str = "credited"
) -> bool:
    """Insert a completion. Returns False if it already exists (duplicate)."""
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO task_completions (task_id, user_id, reward, status)
               VALUES (?, ?, ?, ?)""",
            (task_id, user_id, reward, status),
        )
        await db.commit()
        return True
    except Exception:
        return False


async def count_user_completions_today(user_id: int) -> int:
    """Сколько заданий охотник засчитал сегодня (UTC) — для дневного лимита.
    Считаем по дате создания выполнения: повторный зачёт после возврата на
    канал (reverted→credited) не создаёт новую строку и в лимит не попадает."""
    db = await get_db()
    async with db.execute(
        """SELECT COUNT(*) AS c FROM task_completions
           WHERE user_id = ? AND status = 'credited'
             AND date(created_at) = date('now')""",
        (user_id,),
    ) as cur:
        row = await cur.fetchone()
    return row["c"] if row else 0


async def count_user_credited_subs(user_id: int) -> int:
    """Сколько подписок-заданий у пользователя засчитано прямо сейчас (стрик)."""
    db = await get_db()
    async with db.execute(
        """SELECT COUNT(*) AS c
           FROM task_completions tc
           JOIN tasks t ON t.id = tc.task_id
           WHERE tc.user_id = ? AND tc.status = 'credited' AND t.type = 'channel_sub'""",
        (user_id,),
    ) as cur:
        row = await cur.fetchone()
    return row["c"] if row else 0


async def get_credited_channel_completions() -> list[dict]:
    """Все засчитанные подписки (для ежедневной ре-проверки/clawback).
    Тащим и спонсорские поля задания — для расчёта окна гарантии неотписки."""
    db = await get_db()
    async with db.execute(
        """SELECT tc.id AS comp_id, tc.user_id, tc.reward, tc.status,
                  tc.created_at AS comp_created_at,
                  t.id AS task_id, t.channel_id, t.title, t.url, t.channel_username,
                  t.sponsor_type, t.guarantee_days, t.ended_at
           FROM task_completions tc
           JOIN tasks t ON t.id = tc.task_id
           WHERE tc.status = 'credited' AND t.type = 'channel_sub'""",
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_user_channel_task_completions(user_id: int) -> list[dict]:
    """Все подписки-задания пользователя с ссылками и спонсорскими полями
    (для расчёта окна гарантии неотписки при гейтинге следующего задания)."""
    db = await get_db()
    async with db.execute(
        """SELECT tc.id AS comp_id, tc.status, tc.reward, tc.task_id,
                  tc.created_at AS comp_created_at,
                  t.title, t.url, t.channel_username, t.channel_id, t.active,
                  t.sponsor_type, t.guarantee_days, t.ended_at
           FROM task_completions tc
           JOIN tasks t ON t.id = tc.task_id
           WHERE tc.user_id = ? AND t.type = 'channel_sub'
           ORDER BY tc.id DESC""",
        (user_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def mark_completion_reverted(comp_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE task_completions SET status = 'reverted', checked_at = datetime('now') WHERE id = ?",
        (comp_id,),
    )
    await db.commit()


async def mark_completion_released(comp_id: int) -> None:
    """Гарантия неотписки истекла: пользователь отписался, но штрафа нет —
    помечаем выполнение released (награда и опыт сохраняются, из речека уходит)."""
    db = await get_db()
    await db.execute(
        "UPDATE task_completions SET status = 'released', checked_at = datetime('now') WHERE id = ?",
        (comp_id,),
    )
    await db.commit()


async def end_task_sponsorship(task_id: int) -> None:
    """Спонсор отменил оплату: снимаем задание из активных и фиксируем момент
    окончания (от него отсчитываются 7 дней пост-гарантии неотписки)."""
    db = await get_db()
    await db.execute(
        "UPDATE tasks SET active = 0, ended_at = datetime('now') WHERE id = ?",
        (task_id,),
    )
    await db.commit()


# ── Payout requests ──────────────────────────────────────────────────────────

async def create_payout_request(
    user_id: int, amount: int, product: str, usd_cents: int
) -> int:
    db = await get_db()
    cur = await db.execute(
        """INSERT INTO payout_requests (user_id, amount, product, usd_cents)
           VALUES (?, ?, ?, ?)""",
        (user_id, amount, product, usd_cents),
    )
    await db.commit()
    return cur.lastrowid


async def get_payout_request(req_id: int) -> Optional[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM payout_requests WHERE id = ?", (req_id,)
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def list_payout_requests(status: Optional[str] = None, limit: int = 30) -> list[dict]:
    db = await get_db()
    if status:
        sql = "SELECT * FROM payout_requests WHERE status = ? ORDER BY id DESC LIMIT ?"
        args = (status, limit)
    else:
        sql = "SELECT * FROM payout_requests ORDER BY id DESC LIMIT ?"
        args = (limit,)
    async with db.execute(sql, args) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def set_payout_status(req_id: int, status: str, note: str = "") -> None:
    db = await get_db()
    await db.execute(
        "UPDATE payout_requests SET status = ?, note = ?, decided_at = datetime('now') WHERE id = ?",
        (status, note, req_id),
    )
    await db.commit()


# ── Achievements ─────────────────────────────────────────────────────────────

async def has_achievement(user_id: int, code: str) -> bool:
    db = await get_db()
    async with db.execute(
        "SELECT 1 FROM achievements WHERE user_id = ? AND code = ?", (user_id, code)
    ) as cur:
        return await cur.fetchone() is not None


async def count_achievement(code: str) -> int:
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) AS c FROM achievements WHERE code = ?", (code,)
    ) as cur:
        row = await cur.fetchone()
    return row["c"] if row else 0


async def award_achievement(user_id: int, code: str) -> bool:
    """Grant an achievement once. Returns True if newly granted."""
    db = await get_db()
    cur = await db.execute(
        "INSERT OR IGNORE INTO achievements (user_id, code) VALUES (?, ?)",
        (user_id, code),
    )
    await db.commit()
    return cur.rowcount > 0


async def award_achievement_capped(user_id: int, code: str, max_slots: int) -> str:
    """
    Grant a limited-slot achievement (e.g. «первые 100»). Returns:
      'granted' | 'already' | 'full'
    """
    if await has_achievement(user_id, code):
        return "already"
    if await count_achievement(code) >= max_slots:
        return "full"
    granted = await award_achievement(user_id, code)
    return "granted" if granted else "already"


async def get_user_achievements(user_id: int) -> list[str]:
    db = await get_db()
    async with db.execute(
        "SELECT code FROM achievements WHERE user_id = ? ORDER BY awarded_at", (user_id,)
    ) as cur:
        rows = await cur.fetchall()
    return [r["code"] for r in rows]
