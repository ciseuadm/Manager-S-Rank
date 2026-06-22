from datetime import datetime, timedelta, timezone
from typing import Optional
from .db import get_db


# ── Chat settings ──────────────────────────────────────────────────────────────

async def get_chat_settings(chat_id: int) -> dict:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM chat_settings WHERE chat_id = ?", (chat_id,)
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        await db.execute(
            "INSERT OR IGNORE INTO chat_settings (chat_id) VALUES (?)", (chat_id,)
        )
        await db.commit()
        async with db.execute(
            "SELECT * FROM chat_settings WHERE chat_id = ?", (chat_id,)
        ) as cur:
            row = await cur.fetchone()
    return dict(row)


async def update_chat_setting(chat_id: int, key: str, value) -> None:
    db = await get_db()
    await db.execute(
        f"UPDATE chat_settings SET {key} = ? WHERE chat_id = ?", (value, chat_id)
    )
    await db.commit()


async def set_chat_pro(chat_id: int, days: int) -> str:
    """Включить/продлить Pro-подписку чата на `days` дней.

    Если подписка ещё активна — продлеваем от её срока, иначе от текущего
    момента. Возвращает новый pro_until (ISO, UTC).
    """
    from utils import is_chat_pro
    settings = await get_chat_settings(chat_id)
    now = datetime.now(timezone.utc)
    base = now
    if is_chat_pro(settings):
        try:
            cur = datetime.fromisoformat(str(settings.get("pro_until")))
            if cur.tzinfo is None:
                cur = cur.replace(tzinfo=timezone.utc)
            base = max(base, cur)
        except (ValueError, TypeError):
            pass
    until = (base + timedelta(days=days)).isoformat()
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO chat_settings (chat_id) VALUES (?)", (chat_id,)
    )
    await db.execute(
        "UPDATE chat_settings SET pro = 1, pro_until = ? WHERE chat_id = ?",
        (until, chat_id),
    )
    await db.commit()
    return until


async def set_chat_title(chat_id: int, title: str) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO chat_settings (chat_id, title) VALUES (?, ?)",
        (chat_id, title),
    )
    await db.execute(
        "UPDATE chat_settings SET title = ? WHERE chat_id = ?", (title, chat_id)
    )
    await db.commit()


# ── User CRUD ─────────────────────────────────────────────────────────────────

async def get_or_create_user(user_id: int, chat_id: int, username: str = "", full_name: str = "") -> dict:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM users WHERE user_id = ? AND chat_id = ?", (user_id, chat_id)
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        await db.execute(
            """INSERT OR IGNORE INTO users (user_id, chat_id, username, full_name)
               VALUES (?, ?, ?, ?)""",
            (user_id, chat_id, username, full_name),
        )
        await db.commit()
        async with db.execute(
            "SELECT * FROM users WHERE user_id = ? AND chat_id = ?", (user_id, chat_id)
        ) as cur:
            row = await cur.fetchone()
    return dict(row)


async def increment_messages(user_id: int, chat_id: int) -> int:
    db = await get_db()
    await db.execute(
        """UPDATE users
           SET messages = messages + 1, last_seen = datetime('now')
           WHERE user_id = ? AND chat_id = ?""",
        (user_id, chat_id),
    )
    await db.commit()
    async with db.execute(
        "SELECT messages FROM users WHERE user_id = ? AND chat_id = ?", (user_id, chat_id)
    ) as cur:
        row = await cur.fetchone()
    return row["messages"] if row else 0


async def add_messages(user_id: int, chat_id: int, amount: int) -> int:
    """Add a bonus amount to the message counter (used by /daily, invites)."""
    db = await get_db()
    await db.execute(
        """UPDATE users
           SET messages = messages + ?, last_seen = datetime('now')
           WHERE user_id = ? AND chat_id = ?""",
        (amount, user_id, chat_id),
    )
    await db.commit()
    async with db.execute(
        "SELECT messages FROM users WHERE user_id = ? AND chat_id = ?", (user_id, chat_id)
    ) as cur:
        row = await cur.fetchone()
    return row["messages"] if row else 0


async def claim_daily(user_id: int, chat_id: int, bonus: int) -> Optional[int]:
    """
    Grant the daily bonus once per UTC day.
    Returns the new message total, or None if already claimed today.
    """
    today = datetime.utcnow().date().isoformat()
    db = await get_db()
    async with db.execute(
        "SELECT last_daily FROM users WHERE user_id = ? AND chat_id = ?", (user_id, chat_id)
    ) as cur:
        row = await cur.fetchone()
    if row and row["last_daily"] == today:
        return None
    await db.execute(
        """UPDATE users
           SET messages = messages + ?, last_daily = ?, last_seen = datetime('now')
           WHERE user_id = ? AND chat_id = ?""",
        (bonus, today, user_id, chat_id),
    )
    await db.commit()
    async with db.execute(
        "SELECT messages FROM users WHERE user_id = ? AND chat_id = ?", (user_id, chat_id)
    ) as cur:
        row = await cur.fetchone()
    return row["messages"] if row else 0


async def credit_invite(inviter_id: int, chat_id: int, bonus: int) -> int:
    """Reward a member for bringing a new user. Returns their invite total."""
    db = await get_db()
    await db.execute(
        """UPDATE users
           SET invited_count = invited_count + 1, messages = messages + ?
           WHERE user_id = ? AND chat_id = ?""",
        (bonus, inviter_id, chat_id),
    )
    await db.commit()
    async with db.execute(
        "SELECT invited_count FROM users WHERE user_id = ? AND chat_id = ?",
        (inviter_id, chat_id),
    ) as cur:
        row = await cur.fetchone()
    return row["invited_count"] if row else 0


async def get_top_inviters(chat_id: int, limit: int = 10) -> list[dict]:
    db = await get_db()
    async with db.execute(
        """SELECT user_id, username, full_name, invited_count
           FROM users
           WHERE chat_id = ? AND invited_count > 0 AND is_banned = 0
           ORDER BY invited_count DESC LIMIT ?""",
        (chat_id, limit),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def update_user_rank(user_id: int, chat_id: int, rank: str) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE users SET rank = ? WHERE user_id = ? AND chat_id = ?",
        (rank, user_id, chat_id),
    )
    await db.commit()


# ── Warnings ──────────────────────────────────────────────────────────────────

async def add_warn(user_id: int, chat_id: int, admin_id: int, reason: str = "") -> int:
    db = await get_db()
    await db.execute(
        """INSERT INTO warn_history (user_id, chat_id, admin_id, reason)
           VALUES (?, ?, ?, ?)""",
        (user_id, chat_id, admin_id, reason),
    )
    await db.execute(
        "UPDATE users SET warns = warns + 1 WHERE user_id = ? AND chat_id = ?",
        (user_id, chat_id),
    )
    await db.execute(
        """INSERT OR IGNORE INTO chat_stats (chat_id, date) VALUES (?, date('now'));
        """,
        (chat_id,),
    )
    await db.execute(
        """UPDATE chat_stats SET warns_given = warns_given + 1
           WHERE chat_id = ? AND date = date('now')""",
        (chat_id,),
    )
    await db.commit()
    async with db.execute(
        "SELECT warns FROM users WHERE user_id = ? AND chat_id = ?", (user_id, chat_id)
    ) as cur:
        row = await cur.fetchone()
    return row["warns"] if row else 0


async def remove_warn(user_id: int, chat_id: int) -> int:
    db = await get_db()
    await db.execute(
        "UPDATE users SET warns = MAX(warns - 1, 0) WHERE user_id = ? AND chat_id = ?",
        (user_id, chat_id),
    )
    await db.commit()
    async with db.execute(
        "SELECT warns FROM users WHERE user_id = ? AND chat_id = ?", (user_id, chat_id)
    ) as cur:
        row = await cur.fetchone()
    return row["warns"] if row else 0


async def reset_warns(user_id: int, chat_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE users SET warns = 0 WHERE user_id = ? AND chat_id = ?",
        (user_id, chat_id),
    )
    await db.commit()


async def get_warn_history(user_id: int, chat_id: int) -> list[dict]:
    db = await get_db()
    async with db.execute(
        """SELECT * FROM warn_history WHERE user_id = ? AND chat_id = ?
           ORDER BY created_at DESC LIMIT 10""",
        (user_id, chat_id),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ── Mute / Ban ────────────────────────────────────────────────────────────────

async def mute_user(user_id: int, chat_id: int, minutes: int) -> None:
    until = (datetime.utcnow() + timedelta(minutes=minutes)).isoformat()
    db = await get_db()
    await db.execute(
        "UPDATE users SET is_muted = 1, mute_until = ? WHERE user_id = ? AND chat_id = ?",
        (until, user_id, chat_id),
    )
    await db.commit()


async def unmute_user(user_id: int, chat_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE users SET is_muted = 0, mute_until = NULL WHERE user_id = ? AND chat_id = ?",
        (user_id, chat_id),
    )
    await db.commit()


async def clear_expired_mutes() -> int:
    """
    Снять «протухшие» муты: у кого срок (mute_until) уже истёк, но флаг is_muted
    в БД остался. Telegram снимает ограничение сам по until_date — мы лишь
    синхронизируем БД, чтобы флаг не врал. Возвращает число обновлённых записей.
    """
    db = await get_db()
    now = datetime.utcnow().isoformat()
    cur = await db.execute(
        "UPDATE users SET is_muted = 0, mute_until = NULL "
        "WHERE is_muted = 1 AND mute_until IS NOT NULL AND mute_until <= ?",
        (now,),
    )
    await db.commit()
    return cur.rowcount or 0


async def ban_user(user_id: int, chat_id: int, admin_id: int, reason: str = "") -> None:
    db = await get_db()
    await db.execute(
        "UPDATE users SET is_banned = 1 WHERE user_id = ? AND chat_id = ?",
        (user_id, chat_id),
    )
    await db.execute(
        """INSERT INTO ban_history (user_id, chat_id, admin_id, reason, ban_type)
           VALUES (?, ?, ?, ?, 'ban')""",
        (user_id, chat_id, admin_id, reason),
    )
    await db.execute(
        "INSERT OR IGNORE INTO chat_stats (chat_id, date) VALUES (?, date('now'))",
        (chat_id,),
    )
    await db.execute(
        "UPDATE chat_stats SET bans = bans + 1 WHERE chat_id = ? AND date = date('now')",
        (chat_id,),
    )
    await db.commit()


async def unban_user(user_id: int, chat_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE users SET is_banned = 0 WHERE user_id = ? AND chat_id = ?",
        (user_id, chat_id),
    )
    await db.commit()


# ── Blacklist words ───────────────────────────────────────────────────────────

async def add_blacklist_word(chat_id: int, word: str, added_by: int) -> bool:
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO blacklist_words (chat_id, word, added_by) VALUES (?, ?, ?)",
            (chat_id, word.lower(), added_by),
        )
        await db.commit()
        return True
    except Exception:
        return False


async def remove_blacklist_word(chat_id: int, word: str) -> bool:
    db = await get_db()
    await db.execute(
        "DELETE FROM blacklist_words WHERE chat_id = ? AND word = ?",
        (chat_id, word.lower()),
    )
    await db.commit()
    return True


async def get_blacklist_words(chat_id: int) -> list[str]:
    db = await get_db()
    async with db.execute(
        "SELECT word FROM blacklist_words WHERE chat_id = ?", (chat_id,)
    ) as cur:
        rows = await cur.fetchall()
    return [r["word"] for r in rows]


# ── Stats ─────────────────────────────────────────────────────────────────────

async def increment_stat(chat_id: int, field: str) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO chat_stats (chat_id, date) VALUES (?, date('now'))",
        (chat_id,),
    )
    await db.execute(
        f"UPDATE chat_stats SET {field} = {field} + 1 WHERE chat_id = ? AND date = date('now')",
        (chat_id,),
    )
    await db.commit()


async def get_chat_stats(chat_id: int, days: int = 7) -> list[dict]:
    db = await get_db()
    async with db.execute(
        """SELECT * FROM chat_stats
           WHERE chat_id = ? AND date >= date('now', ? || ' days')
           ORDER BY date DESC""",
        (chat_id, f"-{days}"),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_top_moderators(chat_id: int, days: int = 30, limit: int = 10) -> list[dict]:
    """
    Топ модераторов чата по активности: число выданных варнов и банов за период.
    Источник — журналы warn_history / ban_history (admin_id = кто наказал).
    """
    db = await get_db()
    async with db.execute(
        """SELECT admin_id,
                  SUM(warns) AS warns, SUM(bans) AS bans, SUM(warns + bans) AS total
           FROM (
               SELECT admin_id, COUNT(*) AS warns, 0 AS bans FROM warn_history
                 WHERE chat_id = ? AND created_at >= datetime('now', ? || ' days')
                       AND admin_id != 0
                 GROUP BY admin_id
               UNION ALL
               SELECT admin_id, 0 AS warns, COUNT(*) AS bans FROM ban_history
                 WHERE chat_id = ? AND created_at >= datetime('now', ? || ' days')
                       AND admin_id != 0
                 GROUP BY admin_id
           )
           GROUP BY admin_id
           ORDER BY total DESC LIMIT ?""",
        (chat_id, f"-{days}", chat_id, f"-{days}", limit),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_chat_activity_summary(chat_id: int, days: int = 7) -> dict:
    """Сводка активности чата за период: сообщения/удаления/варны/баны + актив."""
    db = await get_db()
    async with db.execute(
        """SELECT COALESCE(SUM(messages),0) AS messages,
                  COALESCE(SUM(deleted),0) AS deleted,
                  COALESCE(SUM(warns_given),0) AS warns,
                  COALESCE(SUM(bans),0) AS bans
           FROM chat_stats
           WHERE chat_id = ? AND date >= date('now', ? || ' days')""",
        (chat_id, f"-{days}"),
    ) as cur:
        row = await cur.fetchone()
    summary = dict(row) if row else {"messages": 0, "deleted": 0, "warns": 0, "bans": 0}
    async with db.execute(
        "SELECT COUNT(*) AS c FROM users WHERE chat_id = ? AND is_banned = 0", (chat_id,)
    ) as cur:
        summary["members"] = (await cur.fetchone())["c"]
    return summary


# ── Owner: global data ──────────────────────────────────────────────────────────

async def get_all_chats() -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT chat_id, title, ads_enabled, chat_type FROM chat_settings ORDER BY created_at DESC"
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def remove_chat(chat_id: int) -> None:
    """Drop a chat the bot was kicked/removed from (keeps the DB clean)."""
    db = await get_db()
    await db.execute("DELETE FROM chat_settings WHERE chat_id = ?", (chat_id,))
    await db.commit()


async def get_global_stats() -> dict:
    db = await get_db()
    async with db.execute("SELECT COUNT(*) AS c FROM chat_settings") as cur:
        chats = (await cur.fetchone())["c"]
    async with db.execute("SELECT COUNT(DISTINCT user_id) AS c FROM users") as cur:
        users = (await cur.fetchone())["c"]
    async with db.execute("SELECT COALESCE(SUM(messages), 0) AS c FROM users") as cur:
        messages = (await cur.fetchone())["c"]
    async with db.execute("SELECT COALESCE(SUM(deleted), 0) AS c FROM chat_stats") as cur:
        deleted = (await cur.fetchone())["c"]
    async with db.execute("SELECT COALESCE(SUM(warns_given), 0) AS c FROM chat_stats") as cur:
        warns = (await cur.fetchone())["c"]
    async with db.execute("SELECT COALESCE(SUM(bans), 0) AS c FROM chat_stats") as cur:
        bans = (await cur.fetchone())["c"]
    return {
        "chats": chats, "users": users, "messages": messages,
        "deleted": deleted, "warns": warns, "bans": bans,
    }


async def get_top_users(chat_id: int, limit: int = 10) -> list[dict]:
    db = await get_db()
    async with db.execute(
        """SELECT user_id, username, full_name, messages, rank
           FROM users WHERE chat_id = ? AND is_banned = 0
           ORDER BY messages DESC LIMIT ?""",
        (chat_id, limit),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]
