import aiosqlite
import os
from loguru import logger


_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _db


async def init_db(db_path: str) -> None:
    global _db
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    _db = await aiosqlite.connect(db_path)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA foreign_keys=ON")
    await _create_tables()
    logger.info(f"Database initialized at {db_path}")


async def close_db() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None


async def _create_tables() -> None:
    db = await get_db()
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS chat_settings (
            chat_id     INTEGER PRIMARY KEY,
            title       TEXT,
            welcome_msg TEXT DEFAULT '',
            filter_nsfw INTEGER DEFAULT 1,
            filter_insults INTEGER DEFAULT 1,
            filter_politics INTEGER DEFAULT 1,
            filter_links INTEGER DEFAULT 0,
            filter_stickers INTEGER DEFAULT 0,
            filter_spam INTEGER DEFAULT 1,
            filter_caps INTEGER DEFAULT 0,
            antiflood INTEGER DEFAULT 1,
            warn_limit  INTEGER DEFAULT 3,
            mute_time   INTEGER DEFAULT 60,
            lang        TEXT DEFAULT 'ru',
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER,
            chat_id     INTEGER,
            username    TEXT,
            full_name   TEXT,
            messages    INTEGER DEFAULT 0,
            rank        TEXT DEFAULT 'E',
            warns       INTEGER DEFAULT 0,
            is_muted    INTEGER DEFAULT 0,
            mute_until  TEXT,
            is_banned   INTEGER DEFAULT 0,
            joined_at   TEXT DEFAULT (datetime('now')),
            last_seen   TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, chat_id)
        );

        CREATE TABLE IF NOT EXISTS warn_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            chat_id     INTEGER,
            admin_id    INTEGER,
            reason      TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS blacklist_words (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id     INTEGER,
            word        TEXT,
            added_by    INTEGER,
            created_at  TEXT DEFAULT (datetime('now')),
            UNIQUE(chat_id, word)
        );

        CREATE TABLE IF NOT EXISTS ban_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            chat_id     INTEGER,
            admin_id    INTEGER,
            reason      TEXT,
            ban_type    TEXT DEFAULT 'ban',
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS chat_stats (
            chat_id     INTEGER,
            date        TEXT,
            messages    INTEGER DEFAULT 0,
            deleted     INTEGER DEFAULT 0,
            warns_given INTEGER DEFAULT 0,
            bans        INTEGER DEFAULT 0,
            PRIMARY KEY (chat_id, date)
        );
    """)
    await db.commit()
