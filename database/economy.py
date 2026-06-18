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


async def claim_dungeon(
    user_id: int, has_ad: bool, base: int, ad_bonus: int, chat_id: int = 0
) -> tuple[str, int, int]:
    """
    Ежедневный сбор «подземелья» (раз в UTC-сутки, глобально по user_id).

    Логика:
      • первый сбор за день → base (+ ad_bonus, если в профиле есть реклама);
      • если уже собрал базу, но рекламы тогда не было, а теперь появилась —
        до-выдаём ad_bonus (top-up) в тот же день;
      • иначе → already.

    Возвращает (status, base_granted, ad_granted), status ∈
      'claimed' | 'topup' | 'already'.
    """
    today = datetime.utcnow().date().isoformat()
    await get_wallet(user_id)
    db = await get_db()
    async with db.execute(
        "SELECT dungeon_date, dungeon_ad_bonus FROM wallets WHERE user_id = ?",
        (user_id,),
    ) as cur:
        row = await cur.fetchone()
    last_date = row["dungeon_date"] if row else None
    ad_given = (row["dungeon_ad_bonus"] if row else 0) or 0

    if last_date != today:
        ad_part = ad_bonus if has_ad else 0
        await db.execute(
            "UPDATE wallets SET dungeon_date = ?, dungeon_ad_bonus = ? WHERE user_id = ?",
            (today, 1 if has_ad else 0, user_id),
        )
        await db.commit()
        await add_mana(user_id, base + ad_part, "dungeon", chat_id=chat_id)
        return "claimed", base, ad_part

    if not ad_given and has_ad:
        await db.execute(
            "UPDATE wallets SET dungeon_ad_bonus = 1 WHERE user_id = ?", (user_id,)
        )
        await db.commit()
        await add_mana(user_id, ad_bonus, "dungeon_ad", chat_id=chat_id)
        return "topup", 0, ad_bonus

    return "already", 0, 0


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
