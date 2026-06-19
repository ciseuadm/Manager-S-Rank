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

-- ── Гильдии (вербовочные кланы охотников) ───────────────────────────────────
-- Гильдия = вербовщик (agent/owner). Её состав — приглашённые в бота охотники
-- (referrals с chat_id = 0). Охотник может быть только в одной гильдии (первый,
-- кто его привёл). ss_blocks_paid/sss_blocks_paid — сколько «десяток» игроков
-- ранга SS/SSS уже оплачено агенту (веховые награды).
CREATE TABLE IF NOT EXISTS guilds (
    owner_id        INTEGER PRIMARY KEY,
    name            TEXT,
    ss_blocks_paid  INTEGER DEFAULT 0,
    sss_blocks_paid INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ── Заявки рекламодателей (анонимные для пользователей) ─────────────────────
-- Рекламодатель подаёт заявку: канал, краткое описание, желаемое число
-- подписчиков, тип (временный/постоянный). Владелец одобряет/отклоняет; при
-- одобрении создаётся задание (tasks) со спонсорскими метаданными.
CREATE TABLE IF NOT EXISTS ad_requests (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    advertiser_id    INTEGER,                       -- кто подал (для связи/учёта, скрыт от юзеров)
    advertiser_name  TEXT DEFAULT '',
    channel_url      TEXT,
    channel_username TEXT DEFAULT '',
    description      TEXT DEFAULT '',               -- 2 слова о канале
    target_subs      INTEGER DEFAULT 0,             -- сколько подписчиков хочет привести
    sponsor_type     TEXT DEFAULT 'temporary',      -- 'temporary' | 'permanent'
    status           TEXT DEFAULT 'pending',        -- 'pending' | 'approved' | 'rejected'
    note             TEXT DEFAULT '',
    task_id          INTEGER DEFAULT 0,             -- созданное задание после одобрения
    created_at       TEXT DEFAULT (datetime('now')),
    decided_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_adreq_status ON ad_requests(status);

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
    status       TEXT DEFAULT 'active',   -- 'active' | 'paused' | 'done' | 'deleted'
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

-- ── Tasks (платные задания: подписки, в будущем CPA/видео) ───────────────────────
CREATE TABLE IF NOT EXISTS tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    type          TEXT DEFAULT 'channel_sub',  -- 'channel_sub' | 'cpa_link' | 'video'
    title         TEXT,
    channel_id    INTEGER,                      -- chat_id канала (бот обязан быть админом)
    channel_username TEXT,                       -- @username для отображения
    url           TEXT,                          -- ссылка для подписки/оффера
    reward        INTEGER DEFAULT 0,             -- руда пользователю
    revenue_cents INTEGER DEFAULT 0,             -- сколько платит рекламодатель нам (в центах) — для P&L
    daily         INTEGER DEFAULT 0,             -- задание-«ротация»
    active        INTEGER DEFAULT 1,
    created_by    INTEGER,
    created_at    TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tasks_active ON tasks(active, type);

CREATE TABLE IF NOT EXISTS task_completions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER,
    user_id     INTEGER,
    reward      INTEGER DEFAULT 0,              -- сколько начислено (для clawback)
    status      TEXT DEFAULT 'credited',        -- 'credited' | 'reverted'
    created_at  TEXT DEFAULT (datetime('now')),
    checked_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(task_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_taskcomp_user ON task_completions(user_id);
CREATE INDEX IF NOT EXISTS idx_taskcomp_status ON task_completions(status, task_id);

-- ── Payout requests (обмен redeemable-руды на подарок) ───────────────────────────
CREATE TABLE IF NOT EXISTS payout_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    amount      INTEGER,                        -- списано руды (escrow)
    product     TEXT,                           -- что выбрал пользователь
    usd_cents   INTEGER DEFAULT 0,              -- наша себестоимость, в центах
    status      TEXT DEFAULT 'pending',         -- 'pending' | 'approved' | 'rejected' | 'fulfilled'
    note        TEXT,
    created_at  TEXT DEFAULT (datetime('now')),
    decided_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_payout_status ON payout_requests(status);

-- ── Achievements (бейджи/ачивки: «первые 100 к рангу A» и т.д.) ──────────────────
CREATE TABLE IF NOT EXISTS achievements (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER,
    code       TEXT,
    awarded_at TEXT DEFAULT (datetime('now')),
    UNIQUE(user_id, code)
);
CREATE INDEX IF NOT EXISTS idx_ach_code ON achievements(code);

-- Дедуп выдачи per-chat целей приглашений (/setgoal): одна цель — один раз на
-- охотника. Чинит баг «цель, созданная позже порога, никогда не срабатывает»
-- (теперь сравнение >=, а не точное ==).
CREATE TABLE IF NOT EXISTS referral_goal_awards (
    goal_id    INTEGER,
    user_id    INTEGER,
    awarded_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (goal_id, user_id)
);
"""


# New columns on existing tables: {table: {column: ddl}}
_NEW_COLUMNS = {
    "chat_settings": {
        "ads_enabled": "INTEGER DEFAULT 1",
        "ref_link": "TEXT",
        "delete_service_msgs": "INTEGER DEFAULT 1",
        # Функции доверия (включаются админом чата): анти-рейд (режим «только
        # чтение» при всплеске входов) и CAS-бан (авто-бан известных спам-ботов
        # по базе cas.chat). Капчи нет — «живость» проверяется D-ранговым гейтом.
        "antiraid": "INTEGER DEFAULT 0",
        "cas_ban": "INTEGER DEFAULT 0",
    },
    "wallets": {
        # Баланс единый (wallets.mana). Колонки ниже зарезервированы под будущую
        # фазу CPA (B4): окно реверса (pending) и учёт заработка заданиями (P&L).
        "mana_pending": "INTEGER DEFAULT 0",
        "tasks_earned": "INTEGER DEFAULT 0",
        # Ежедневное подземелье: дата последнего сбора (UTC) и выдан ли
        # сегодня бонус за рекламу бота в описании профиля.
        "dungeon_date": "TEXT",
        "dungeon_ad_bonus": "INTEGER DEFAULT 0",
        # Стрик чек-инов: текущая серия дней подряд, рекорд и флаг выдачи
        # единоразовой награды за 30-дневный стрик.
        "dungeon_streak": "INTEGER DEFAULT 0",
        "dungeon_streak_best": "INTEGER DEFAULT 0",
        "dungeon_streak_30": "INTEGER DEFAULT 0",
        # Глобальный ранг (по числу выполненных заданий). Хранится, чтобы
        # ловить повышения и не слать одно и то же повышение дважды.
        "rank": "TEXT DEFAULT 'E'",
        # Накопленный ОПЫТ (для рангов): задания + подземелье. Не уменьшается
        # при трате руды; уменьшается только при clawback за отписку.
        "xp": "INTEGER DEFAULT 0",
    },
    "referrals": {
        # Наивысший ранг рекрута, за который агенту уже выплачена награда
        # ('' = ещё ничего). Позволяет платить агенту за каждую новую веху.
        "paid_rank": "TEXT DEFAULT ''",
    },
    "tasks": {
        # Спонсорство и гарантии неотписки:
        #  sponsor_type: 'house' (наш внутренний, бессрочно) | 'permanent'
        #    (постоянный спонсор, гарантия неотписки пока активен + 7 дней после
        #    отмены) | 'temporary' (временный, гарантия guarantee_days от подписки).
        "sponsor_type": "TEXT DEFAULT 'house'",
        "advertiser_id": "INTEGER DEFAULT 0",
        "anonymous": "INTEGER DEFAULT 1",
        "description": "TEXT DEFAULT ''",
        "target_subs": "INTEGER DEFAULT 0",     # авто-завершение при достижении (temporary)
        "guarantee_days": "INTEGER DEFAULT 0",  # окно неотписки для temporary (0=бессрочно для house/permanent)
        "ended_at": "TEXT",                     # когда спонсорство отменено (NULL=активно)
    },
}


async def run_migrations(db) -> None:
    await db.executescript(_NEW_TABLES)
    xp_added = False
    for table, columns in _NEW_COLUMNS.items():
        async with db.execute(f"PRAGMA table_info({table})") as cur:
            existing = {row["name"] for row in await cur.fetchall()}
        for name, ddl in columns.items():
            if name not in existing:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
                logger.info(f"DB migrate: {table}.{name} added")
                if table == "wallets" and name == "xp":
                    xp_added = True
    await db.commit()

    # Бэкфилл опыта при первом появлении колонки: переносим уже заработанное
    # заданиями (сумма наград засчитанных подписок), чтобы ранги не сбросились.
    if xp_added:
        await db.execute(
            """UPDATE wallets SET xp = COALESCE((
                   SELECT COUNT(*) * 100 FROM task_completions tc
                   JOIN tasks t ON t.id = tc.task_id
                   WHERE tc.user_id = wallets.user_id
                     AND tc.status = 'credited' AND t.type = 'channel_sub'
               ), 0)"""
        )
        await db.commit()
        logger.info("DB migrate: wallets.xp backfilled from credited subscriptions")
    logger.info("Growth-stage migrations applied")
