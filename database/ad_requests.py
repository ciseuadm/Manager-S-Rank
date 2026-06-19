"""
Заявки рекламодателей. Pure SQL. Анонимность для пользователей обеспечивается
на уровне отображения (advertiser_id хранится, но не показывается).
"""
from typing import Optional

from .db import get_db


async def create_ad_request(
    *, advertiser_id: int, advertiser_name: str, channel_url: str,
    channel_username: str, description: str, target_subs: int,
    sponsor_type: str, status: str = "pending",
) -> int:
    db = await get_db()
    cur = await db.execute(
        """INSERT INTO ad_requests
           (advertiser_id, advertiser_name, channel_url, channel_username,
            description, target_subs, sponsor_type, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (advertiser_id, advertiser_name, channel_url, channel_username,
         description, target_subs, sponsor_type, status),
    )
    await db.commit()
    return cur.lastrowid


async def mark_ad_request_paid(req_id: int, stars: int, charge_id: str) -> None:
    """Оплата Stars получена → заявка встаёт в очередь модерации (pending)."""
    db = await get_db()
    await db.execute(
        """UPDATE ad_requests
           SET paid = 1, stars_paid = ?, charge_id = ?, status = 'pending'
           WHERE id = ?""",
        (stars, charge_id, req_id),
    )
    await db.commit()


async def get_ad_request(req_id: int) -> Optional[dict]:
    db = await get_db()
    async with db.execute("SELECT * FROM ad_requests WHERE id = ?", (req_id,)) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def list_ad_requests(status: str = "pending", limit: int = 30) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM ad_requests WHERE status = ? ORDER BY id DESC LIMIT ?",
        (status, limit),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def set_ad_request_status(
    req_id: int, status: str, *, note: str = "", task_id: int = 0
) -> None:
    db = await get_db()
    await db.execute(
        """UPDATE ad_requests
           SET status = ?, note = ?, task_id = ?, decided_at = datetime('now')
           WHERE id = ?""",
        (status, note, task_id, req_id),
    )
    await db.commit()
