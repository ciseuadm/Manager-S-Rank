"""
Versioned, idempotent schema migrations for the new subsystems
(economy, referrals, ads, payments). Safe to run on every startup.

Base tables created in db.py::_create_tables() stay there; this module only
adds the growth-stage schema so the original release keeps working untouched.
"""
from loguru import logger


# New tables. Each statement is idempotent via IF NOT EXISTS.
_NEW_TABLES = """
-- ── Economy: Мана-руда (global per user_id) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS wallets (
    user_id      INTEGER PRIMARY KEY,
    mana         INTEGER DEFAULT 0,
    total_earned INTEGER DEFAULT 0,
    total_spent  INTEGER DEFAULT 0,
    last_msg_reward TEXT,                 -- ISO ts последнего начисления за сообщение
    updated_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS mana_tx (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER,
    amount    INTEGER,
    reason    TEXT,
    ref_id    TEXT,
    chat_id   INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mana_tx_user ON mana_tx(user_id);

-- ── Referrals ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS referrals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    inviter_id  INTEGER,
    invited_id  INTEGER,
    chat_id     INTEGER,                  -- 0 = приглашение в самого бота
    source      TEXT,
    rewarded    INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(invited_id, chat_id)
);
CREATE INDEX IF NOT EXISTS idx_ref_inviter ON referrals(inviter_id, chat_id);

CREATE TABLE IF NOT EXISTS referral_goals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER,
    invites_required INTEGER,
    reward_type TEXT,                     -- 'role' | 'mana'
    reward_value TEXT,                    -- 'moderator'/'admin' | сумма руды
    created_by  INTEGER,
    active      INTEGER DEFAULT 1,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chat_roles (
    user_id    INTEGER,
    chat_id    INTEGER,
    role       TEXT,                      -- 'moderator' | 'admin'
    granted_by INTEGER,
    granted_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, chat_id)
);

-- ── Ads ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ad_campaigns (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id     INTEGER,
    title        TEXT,
    content_type TEXT,                    -- 'text' | 'copy'
    payload      TEXT,                    -- текст рекламы (для 'text')
    from_chat_id INTEGER,                 -- для 'copy': откуда копировать
    from_msg_id  INTEGER,                 -- для 'copy': id сообщения
    button_text  TEXT,
    button_url   TEXT,
    target       TEXT DEFAULT 'all',      -- 'all' | 'channel'
    days_total   INTEGER DEFAULT 1,
    days_done    INTEGER DEFAULT 0,
    last_sent_date TEXT,                  -- date() последней рассылки
    status       TEXT DEFAULT 'active',   -- 'active' | 'paused' | 'done'
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ad_impressions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER,
    chat_id     INTEGER,
    sent_at     TEXT DEFAULT (datetime('now')),
    status      TEXT
);
CREATE INDEX IF NOT EXISTS idx_ad_imp_chat ON ad_impressions(chat_id, sent_at);

-- ── Payments (Telegram Stars / XTR) ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS payments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER,
    stars           INTEGER,
    product         TEXT,
    product_ref     TEXT,
    telegram_charge_id TEXT,
    status          TEXT DEFAULT 'paid',
    created_at      TEXT DEFAULT (datetime('now'))
);
"""


# New columns on existing tables: {table: {column: ddl}}
_NEW_COLUMNS = {
    "chat_settings": {
        "ads_enabled": "INTEGER DEFAULT 1",
        "ref_link": "TEXT",
    },
}


async def run_migrations(db) -> None:
    await db.executescript(_NEW_TABLES)
    for table, columns in _NEW_COLUMNS.items():
        async with db.execute(f"PRAGMA table_info({table})") as cur:
            existing = {row["name"] for row in await cur.fetchall()}
        for name, ddl in columns.items():
            if name not in existing:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
                logger.info(f"DB migrate: {table}.{name} added")
    await db.commit()
    logger.info("Growth-stage migrations applied")
