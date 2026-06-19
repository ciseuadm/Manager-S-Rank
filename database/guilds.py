"""
Гильдии — вербовочные кланы. Гильдия принадлежит вербовщику (owner_id), её
состав — приглашённые им в бота охотники (referrals с chat_id = 0).

Pure SQL, без бизнес-логики (она в services).
"""
from typing import Optional

from .db import get_db


async def get_guild(owner_id: int) -> Optional[dict]:
    db = await get_db()
    async with db.execute("SELECT * FROM guilds WHERE owner_id = ?", (owner_id,)) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def get_or_create_guild(owner_id: int) -> dict:
    g = await get_guild(owner_id)
    if g is not None:
        return g
    db = await get_db()
    await db.execute("INSERT OR IGNORE INTO guilds (owner_id) VALUES (?)", (owner_id,))
    await db.commit()
    return await get_guild(owner_id)


async def set_guild_name(owner_id: int, name: str) -> None:
    await get_or_create_guild(owner_id)
    db = await get_db()
    await db.execute("UPDATE guilds SET name = ? WHERE owner_id = ?", (name, owner_id))
    await db.commit()


async def set_guild_blocks(owner_id: int, *, ss: Optional[int] = None,
                           sss: Optional[int] = None) -> None:
    await get_or_create_guild(owner_id)
    db = await get_db()
    if ss is not None:
        await db.execute("UPDATE guilds SET ss_blocks_paid = ? WHERE owner_id = ?", (ss, owner_id))
    if sss is not None:
        await db.execute("UPDATE guilds SET sss_blocks_paid = ? WHERE owner_id = ?", (sss, owner_id))
    await db.commit()


async def guild_member_count(owner_id: int) -> int:
    """Сколько охотников в гильдии (приглашены в бота этим вербовщиком)."""
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) AS c FROM referrals WHERE inviter_id = ? AND chat_id = 0",
        (owner_id,),
    ) as cur:
        return (await cur.fetchone())["c"]


async def guild_rank_counts(owner_id: int) -> dict[str, int]:
    """Разбивка состава гильдии по текущим рангам участников: {rank: count}."""
    db = await get_db()
    async with db.execute(
        """SELECT COALESCE(w.rank, 'E') AS rank, COUNT(*) AS c
           FROM referrals r
           LEFT JOIN wallets w ON w.user_id = r.invited_id
           WHERE r.inviter_id = ? AND r.chat_id = 0
           GROUP BY COALESCE(w.rank, 'E')""",
        (owner_id,),
    ) as cur:
        rows = await cur.fetchall()
    return {r["rank"]: r["c"] for r in rows}


async def top_guilds(limit: int = 10) -> list[dict]:
    """Рейтинг крупнейших гильдий по числу охотников."""
    db = await get_db()
    async with db.execute(
        """SELECT g.owner_id, g.name,
                  (SELECT COUNT(*) FROM referrals r
                   WHERE r.inviter_id = g.owner_id AND r.chat_id = 0) AS members
           FROM guilds g
           ORDER BY members DESC, g.created_at ASC
           LIMIT ?""",
        (limit,),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]
