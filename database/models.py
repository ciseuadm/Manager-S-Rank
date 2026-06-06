from datetime import datetime, timedelta
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


# ── Owner: global data ──────────────────────────────────────────────────────────

async def get_all_chats() -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT chat_id, title FROM chat_settings ORDER BY created_at DESC"
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


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
