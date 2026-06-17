"""
Economy data layer — Мана-руда wallets and transaction ledger.
Balance is GLOBAL per user_id (not per chat). Pure SQL, no business logic.
"""
from datetime import datetime, timedelta
from typing import Optional

from .db import get_db


async def get_wallet(user_id: int) -> dict:
    db = await get_db()
    async with db.execute("SELECT * FROM wallets WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
    if row is None:
        await db.execute("INSERT OR IGNORE INTO wallets (user_id) VALUES (?)", (user_id,))
        await db.commit()
        async with db.execute("SELECT * FROM wallets WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
    return dict(row)


async def get_wallet_balance(user_id: int) -> int:
    return (await get_wallet(user_id)).get("mana", 0)


async def _log_tx(db, user_id: int, amount: int, reason: str,
                  ref_id: str = "", chat_id: int = 0) -> None:
    await db.execute(
        "INSERT INTO mana_tx (user_id, amount, reason, ref_id, chat_id) VALUES (?, ?, ?, ?, ?)",
        (user_id, amount, reason, ref_id, chat_id),
    )


async def add_mana(user_id: int, amount: int, reason: str,
                   ref_id: str = "", chat_id: int = 0) -> int:
    """Credit mana. Returns new balance."""
    if amount <= 0:
        return await get_wallet_balance(user_id)
    await get_wallet(user_id)
    db = await get_db()
    await db.execute(
        """UPDATE wallets
           SET mana = mana + ?, total_earned = total_earned + ?, updated_at = datetime('now')
           WHERE user_id = ?""",
        (amount, amount, user_id),
    )
    await _log_tx(db, user_id, amount, reason, ref_id, chat_id)
    await db.commit()
    return await get_wallet_balance(user_id)


async def spend_mana(user_id: int, amount: int, reason: str,
                     ref_id: str = "", chat_id: int = 0) -> Optional[int]:
    """
    Debit mana atomically. Returns new balance, or None if insufficient funds.
    """
    if amount <= 0:
        return await get_wallet_balance(user_id)
    await get_wallet(user_id)
    db = await get_db()
    # Conditional update guarantees no negative balance even under races.
    cur = await db.execute(
        """UPDATE wallets
           SET mana = mana - ?, total_spent = total_spent + ?, updated_at = datetime('now')
           WHERE user_id = ? AND mana >= ?""",
        (amount, amount, user_id, amount),
    )
    if cur.rowcount == 0:
        await db.commit()
        return None
    await _log_tx(db, user_id, -amount, reason, ref_id, chat_id)
    await db.commit()
    return await get_wallet_balance(user_id)


async def revert_mana(user_id: int, amount: int, reason: str,
                      ref_id: str = "", chat_id: int = 0) -> int:
    """
    Откат начисления (clawback при отписке от канала задания). Списывает руду,
    но НЕ уводит баланс в минус (если уже потрачена). Возвращает новый баланс.
    """
    if amount <= 0:
        return await get_wallet_balance(user_id)
    await get_wallet(user_id)
    db = await get_db()
    await db.execute(
        """UPDATE wallets
           SET mana = MAX(0, mana - ?), updated_at = datetime('now')
           WHERE user_id = ?""",
        (amount, user_id),
    )
    await _log_tx(db, user_id, -amount, reason, ref_id, chat_id)
    await db.commit()
    return await get_wallet_balance(user_id)


async def can_reward_message(user_id: int, cooldown_seconds: int) -> bool:
    """True if enough time passed since the last per-message mana reward."""
    w = await get_wallet(user_id)
    last = w.get("last_msg_reward")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
    except (ValueError, TypeError):
        return True
    return datetime.utcnow() - last_dt >= timedelta(seconds=cooldown_seconds)


async def mark_message_reward(user_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE wallets SET last_msg_reward = ? WHERE user_id = ?",
        (datetime.utcnow().isoformat(), user_id),
    )
    await db.commit()


async def get_top_mana(limit: int = 10) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT user_id, mana, total_earned FROM wallets ORDER BY mana DESC LIMIT ?",
        (limit,),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_mana_emission() -> dict:
    """Aggregate economy figures for the owner dashboard."""
    db = await get_db()
    async with db.execute(
        "SELECT COALESCE(SUM(mana),0) AS supply, COALESCE(SUM(total_earned),0) AS earned, "
        "COALESCE(SUM(total_spent),0) AS spent, COUNT(*) AS holders FROM wallets"
    ) as cur:
        row = await cur.fetchone()
    return dict(row)
