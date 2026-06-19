"""
Data layer for chat acquisition (owner-рефералка).

Каждая запись — чат, в который кто-то добавил бота-модератора. inviter_id —
охотник, который привёл чат (event.from_user из my_chat_member). Это главный
рычаг роста: за приведённые чаты охотник получает руду и вехи.

Pure SQL, без бизнес-логики (она в services/chat_growth.py).
"""
from typing import Optional

from .db import get_db


async def record_chat_referral(chat_id: int, inviter_id: int, title: str = "") -> bool:
    """
    Зафиксировать, что бота добавили в чат. Возвращает True, если это новая
    запись (чат раньше не привязывался). Если чат уже был, но помечен как 'left'
    — реактивируем (бота вернули), но новой записью НЕ считаем (награду не дублим).
    """
    db = await get_db()
    async with db.execute(
        "SELECT chat_id, status FROM chat_referrals WHERE chat_id = ?", (chat_id,)
    ) as cur:
        row = await cur.fetchone()
    if row is not None:
        await db.execute(
            "UPDATE chat_referrals SET status = 'active', left_at = NULL, "
            "title = CASE WHEN ? != '' THEN ? ELSE title END WHERE chat_id = ?",
            (title, title, chat_id),
        )
        await db.commit()
        return False
    await db.execute(
        """INSERT INTO chat_referrals (chat_id, inviter_id, title)
           VALUES (?, ?, ?)""",
        (chat_id, inviter_id, title),
    )
    await db.commit()
    return True


async def get_chat_referral(chat_id: int) -> Optional[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM chat_referrals WHERE chat_id = ?", (chat_id,)
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def set_chat_referral_admin(chat_id: int, is_admin: bool) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE chat_referrals SET is_admin = ? WHERE chat_id = ?",
        (1 if is_admin else 0, chat_id),
    )
    await db.commit()


async def mark_chat_referral_rewarded(chat_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE chat_referrals SET rewarded = 1 WHERE chat_id = ?", (chat_id,)
    )
    await db.commit()


async def mark_chat_referral_left(chat_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE chat_referrals SET status = 'left', left_at = datetime('now') "
        "WHERE chat_id = ?",
        (chat_id,),
    )
    await db.commit()


async def count_active_chats_brought(inviter_id: int) -> int:
    """Сколько АКТИВНЫХ чатов с админкой бота привёл этот охотник."""
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) AS c FROM chat_referrals "
        "WHERE inviter_id = ? AND status = 'active' AND is_admin = 1",
        (inviter_id,),
    ) as cur:
        return (await cur.fetchone())["c"]


async def list_chats_brought(inviter_id: int, limit: int = 20) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM chat_referrals WHERE inviter_id = ? "
        "ORDER BY status = 'active' DESC, created_at DESC LIMIT ?",
        (inviter_id, limit),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def top_chat_recruiters(limit: int = 10) -> list[dict]:
    db = await get_db()
    async with db.execute(
        """SELECT inviter_id, COUNT(*) AS chats
           FROM chat_referrals
           WHERE status = 'active' AND is_admin = 1 AND inviter_id != 0
           GROUP BY inviter_id
           ORDER BY chats DESC
           LIMIT ?""",
        (limit,),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ── Веховые блоки за привлечение чатов ───────────────────────────────────────

async def get_recruit_blocks_paid(owner_id: int) -> int:
    db = await get_db()
    async with db.execute(
        "SELECT blocks_paid FROM chat_recruit_blocks WHERE owner_id = ?", (owner_id,)
    ) as cur:
        row = await cur.fetchone()
    return (row["blocks_paid"] if row else 0) or 0


async def set_recruit_blocks_paid(owner_id: int, blocks: int) -> None:
    db = await get_db()
    await db.execute(
        """INSERT INTO chat_recruit_blocks (owner_id, blocks_paid) VALUES (?, ?)
           ON CONFLICT(owner_id) DO UPDATE SET blocks_paid = excluded.blocks_paid""",
        (owner_id, blocks),
    )
    await db.commit()
