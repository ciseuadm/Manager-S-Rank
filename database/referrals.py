"""
Referral data layer — invitations, per-chat goals and in-bot roles.
chat_id = 0 means a referral into the bot itself (used for VIP threshold).
"""
from typing import Optional

from .db import get_db


async def add_referral(inviter_id: int, invited_id: int, chat_id: int,
                       source: str) -> bool:
    """
    Record a referral. Returns True if it counted as new, False if duplicate
    or self-referral.
    """
    if inviter_id == invited_id:
        return False
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO referrals (inviter_id, invited_id, chat_id, source)
               VALUES (?, ?, ?, ?)""",
            (inviter_id, invited_id, chat_id, source),
        )
        await db.commit()
        return True
    except Exception:
        return False  # UNIQUE(invited_id, chat_id) → уже учтён


async def count_referrals(inviter_id: int, chat_id: int) -> int:
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) AS c FROM referrals WHERE inviter_id = ? AND chat_id = ?",
        (inviter_id, chat_id),
    ) as cur:
        return (await cur.fetchone())["c"]


async def count_bot_referrals(inviter_id: int) -> int:
    """Total invitations into the bot itself (chat_id = 0) — used for VIP."""
    return await count_referrals(inviter_id, 0)


async def mark_referral_rewarded(invited_id: int, chat_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE referrals SET rewarded = 1 WHERE invited_id = ? AND chat_id = ?",
        (invited_id, chat_id),
    )
    await db.commit()


async def get_unrewarded_referral(invited_id: int) -> Optional[dict]:
    """
    Самое раннее невыплаченное приглашение этого пользователя (любой источник).
    Используется, чтобы заплатить пригласившему, когда новичок докажет активность.
    """
    db = await get_db()
    async with db.execute(
        "SELECT * FROM referrals WHERE invited_id = ? AND rewarded = 0 "
        "ORDER BY id ASC LIMIT 1",
        (invited_id,),
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def mark_all_referrals_rewarded(invited_id: int) -> None:
    """Помечаем все приглашения этого новичка как выплаченные (платим один раз)."""
    db = await get_db()
    await db.execute(
        "UPDATE referrals SET rewarded = 1 WHERE invited_id = ?", (invited_id,)
    )
    await db.commit()


# ── Goals ────────────────────────────────────────────────────────────────────

async def add_referral_goal(chat_id: int, invites_required: int,
                            reward_type: str, reward_value: str,
                            created_by: int) -> None:
    db = await get_db()
    await db.execute(
        """INSERT INTO referral_goals
           (chat_id, invites_required, reward_type, reward_value, created_by)
           VALUES (?, ?, ?, ?, ?)""",
        (chat_id, invites_required, reward_type, reward_value, created_by),
    )
    await db.commit()


async def get_referral_goals(chat_id: int, active_only: bool = True) -> list[dict]:
    db = await get_db()
    q = "SELECT * FROM referral_goals WHERE chat_id = ?"
    if active_only:
        q += " AND active = 1"
    q += " ORDER BY invites_required ASC"
    async with db.execute(q, (chat_id,)) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def deactivate_goal(goal_id: int, chat_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE referral_goals SET active = 0 WHERE id = ? AND chat_id = ?",
        (goal_id, chat_id),
    )
    await db.commit()


# ── In-bot roles ───────────────────────────────────────────────────────────────

async def set_chat_role(user_id: int, chat_id: int, role: str,
                        granted_by: int) -> None:
    db = await get_db()
    await db.execute(
        """INSERT INTO chat_roles (user_id, chat_id, role, granted_by)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(user_id, chat_id) DO UPDATE SET role = excluded.role,
               granted_by = excluded.granted_by, granted_at = datetime('now')""",
        (user_id, chat_id, role, granted_by),
    )
    await db.commit()


async def get_chat_role(user_id: int, chat_id: int) -> Optional[str]:
    db = await get_db()
    async with db.execute(
        "SELECT role FROM chat_roles WHERE user_id = ? AND chat_id = ?",
        (user_id, chat_id),
    ) as cur:
        row = await cur.fetchone()
    return row["role"] if row else None
