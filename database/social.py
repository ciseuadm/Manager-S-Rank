"""
Социальные механики поверх руды: кланы (объединения внутри чата со складчиной
в казну) и браки охотников (RP-статус). Чистый SQL, бизнес-логика — в services.
"""
from typing import Optional

from .db import get_db


# ── Кланы ─────────────────────────────────────────────────────────────────────

async def create_clan(chat_id: int, name: str, leader_id: int) -> Optional[int]:
    name = (name or "").strip()
    if not name:
        return None
    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO clans (chat_id, name, leader_id) VALUES (?, ?, ?)",
            (chat_id, name, leader_id),
        )
        await db.execute(
            "INSERT OR IGNORE INTO clan_members (clan_id, user_id, chat_id) VALUES (?, ?, ?)",
            (cur.lastrowid, leader_id, chat_id),
        )
        await db.commit()
        return cur.lastrowid
    except Exception:
        return None


async def get_clan(clan_id: int) -> Optional[dict]:
    db = await get_db()
    async with db.execute("SELECT * FROM clans WHERE id = ?", (clan_id,)) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def get_clan_by_name(chat_id: int, name: str) -> Optional[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM clans WHERE chat_id = ? AND name = ?", (chat_id, name.strip())
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def get_user_clan(chat_id: int, user_id: int) -> Optional[dict]:
    db = await get_db()
    async with db.execute(
        """SELECT c.* FROM clans c
           JOIN clan_members m ON m.clan_id = c.id
           WHERE m.chat_id = ? AND m.user_id = ?""",
        (chat_id, user_id),
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def join_clan(clan_id: int, user_id: int, chat_id: int) -> bool:
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO clan_members (clan_id, user_id, chat_id) VALUES (?, ?, ?)",
            (clan_id, user_id, chat_id),
        )
        await db.commit()
        return True
    except Exception:
        return False


async def leave_clan(chat_id: int, user_id: int) -> bool:
    db = await get_db()
    cur = await db.execute(
        "DELETE FROM clan_members WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)
    )
    await db.commit()
    return (cur.rowcount or 0) > 0


async def clan_member_count(clan_id: int) -> int:
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) AS c FROM clan_members WHERE clan_id = ?", (clan_id,)
    ) as cur:
        row = await cur.fetchone()
    return row["c"] if row else 0


async def add_clan_treasury(clan_id: int, amount: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE clans SET treasury = treasury + ? WHERE id = ?", (amount, clan_id)
    )
    await db.commit()


async def top_clans(chat_id: int, limit: int = 10) -> list[dict]:
    db = await get_db()
    async with db.execute(
        """SELECT c.*, COUNT(m.user_id) AS members
           FROM clans c LEFT JOIN clan_members m ON m.clan_id = c.id
           WHERE c.chat_id = ?
           GROUP BY c.id
           ORDER BY c.treasury DESC, members DESC LIMIT ?""",
        (chat_id, limit),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ── Браки ─────────────────────────────────────────────────────────────────────

def _pair(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a <= b else (b, a)


async def get_marriage(chat_id: int, user_id: int) -> Optional[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM marriages WHERE chat_id = ? AND (user_a = ? OR user_b = ?)",
        (chat_id, user_id, user_id),
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def create_marriage(chat_id: int, a: int, b: int) -> bool:
    ua, ub = _pair(a, b)
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO marriages (chat_id, user_a, user_b) VALUES (?, ?, ?)",
            (chat_id, ua, ub),
        )
        await db.commit()
        return True
    except Exception:
        return False


async def divorce(chat_id: int, user_id: int) -> bool:
    db = await get_db()
    cur = await db.execute(
        "DELETE FROM marriages WHERE chat_id = ? AND (user_a = ? OR user_b = ?)",
        (chat_id, user_id, user_id),
    )
    await db.commit()
    return (cur.rowcount or 0) > 0
