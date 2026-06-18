"""
Ads data layer — campaigns and impression log.
Daily delivery cap is enforced via ad_impressions (1/day/chat by default).
"""
from typing import Optional

from .db import get_db


async def create_campaign(owner_id: int, title: str, content_type: str,
                          payload: str = "", from_chat_id: int = 0,
                          from_msg_id: int = 0, button_text: str = "",
                          button_url: str = "", target: str = "all",
                          days_total: int = 1) -> int:
    db = await get_db()
    cur = await db.execute(
        """INSERT INTO ad_campaigns
           (owner_id, title, content_type, payload, from_chat_id, from_msg_id,
            button_text, button_url, target, days_total)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (owner_id, title, content_type, payload, from_chat_id, from_msg_id,
         button_text, button_url, target, days_total),
    )
    await db.commit()
    return cur.lastrowid


async def get_campaign(campaign_id: int, include_deleted: bool = False) -> Optional[dict]:
    db = await get_db()
    deleted_filter = "" if include_deleted else " AND status != 'deleted'"
    async with db.execute(
        f"SELECT * FROM ad_campaigns WHERE id = ?{deleted_filter}", (campaign_id,)
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def get_active_campaigns() -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM ad_campaigns WHERE status = 'active' ORDER BY created_at ASC"
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_all_campaigns(limit: int = 30) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM ad_campaigns WHERE status != 'deleted' ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def set_campaign_status(campaign_id: int, status: str) -> bool:
    db = await get_db()
    cur = await db.execute(
        "UPDATE ad_campaigns SET status = ? WHERE id = ? AND status != 'deleted'",
        (status, campaign_id),
    )
    await db.commit()
    return cur.rowcount > 0


async def delete_campaign(campaign_id: int) -> bool:
    db = await get_db()
    cur = await db.execute(
        "UPDATE ad_campaigns SET status = 'deleted' WHERE id = ? AND status != 'deleted'",
        (campaign_id,),
    )
    await db.commit()
    return cur.rowcount > 0


async def mark_campaign_sent(campaign_id: int, today: str) -> None:
    """Advance daily counters after a campaign was delivered for the day."""
    db = await get_db()
    await db.execute(
        """UPDATE ad_campaigns
           SET days_done = days_done + 1, last_sent_date = ?,
               status = CASE WHEN days_done + 1 >= days_total THEN 'done' ELSE status END
           WHERE id = ?""",
        (today, campaign_id),
    )
    await db.commit()


async def log_impression(campaign_id: int, chat_id: int, status: str) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO ad_impressions (campaign_id, chat_id, status) VALUES (?, ?, ?)",
        (campaign_id, chat_id, status),
    )
    await db.commit()


async def impressions_today(chat_id: int) -> int:
    """How many ads this chat already received today (for the 1/day cap)."""
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) AS c FROM ad_impressions "
        "WHERE chat_id = ? AND date(sent_at) = date('now') AND status = 'sent'",
        (chat_id,),
    ) as cur:
        return (await cur.fetchone())["c"]


async def campaign_stats(campaign_id: int) -> dict:
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) AS sent, "
        "SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed "
        "FROM ad_impressions WHERE campaign_id = ?",
        (campaign_id,),
    ) as cur:
        row = await cur.fetchone()
    return dict(row)


async def ads_global_stats() -> dict:
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) AS campaigns, "
        "COALESCE(SUM(CASE WHEN status='active' THEN 1 ELSE 0 END), 0) AS active "
        "FROM ad_campaigns WHERE status != 'deleted'"
    ) as cur:
        camp = dict(await cur.fetchone())
    async with db.execute(
        "SELECT COUNT(*) AS impressions FROM ad_impressions WHERE status = 'sent'"
    ) as cur:
        imp = dict(await cur.fetchone())
    return {**camp, **imp}
