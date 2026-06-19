"""
Payments data layer — Telegram Stars (XTR) purchases.
"""
from typing import Optional

from .db import get_db


async def add_payment(user_id: int, stars: int, product: str,
                      product_ref: str, telegram_charge_id: str) -> int:
    db = await get_db()
    cur = await db.execute(
        """INSERT INTO payments
           (user_id, stars, product, product_ref, telegram_charge_id)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, stars, product, product_ref, telegram_charge_id),
    )
    await db.commit()
    return cur.lastrowid


async def get_payment_by_charge(charge_id: str) -> Optional[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM payments WHERE telegram_charge_id = ?", (charge_id,)
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def set_payment_status(charge_id: str, status: str) -> None:
    """Обновить статус платежа (например, 'refunded' после возврата Stars)."""
    db = await get_db()
    await db.execute(
        "UPDATE payments SET status = ? WHERE telegram_charge_id = ?",
        (status, charge_id),
    )
    await db.commit()


async def get_user_last_payment(user_id: int) -> Optional[dict]:
    """Последний платёж пользователя (для возврата по ID/реплаю)."""
    db = await get_db()
    async with db.execute(
        "SELECT * FROM payments WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (user_id,),
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def payments_total() -> dict:
    """Total Stars revenue and number of paid orders for the owner dashboard."""
    db = await get_db()
    async with db.execute(
        "SELECT COALESCE(SUM(stars),0) AS stars, COUNT(*) AS orders "
        "FROM payments WHERE status = 'paid'"
    ) as cur:
        return dict(await cur.fetchone())
