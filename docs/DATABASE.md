# 🗄 DATABASE — схема под рост

> Существующие таблицы (`chat_settings`, `users`, `warn_history`, `ban_history`,
> `blacklist_words`, `chat_stats`) сохраняем. Ниже — что добавить и как
> подготовиться к масштабу.

---

## 1. Существующие таблицы (как есть)

- `chat_settings` — настройки модерации на чат.
- `users` — охотник в конкретном чате (PK: `user_id + chat_id`): messages, rank,
  warns, mute/ban, `invited_count`, `last_daily`.
- `warn_history`, `ban_history` — история наказаний.
- `blacklist_words` — пользовательский ЧС слов.
- `chat_stats` — дневная статистика.

> ⚠️ Важно: `users` хранит баланс **по чату**. Мана-руда должна быть **глобальной**
> (одна на пользователя во всём боте), иначе обмен на подарки/рекламу не сойдётся.
> Поэтому экономика — отдельные таблицы с ключом по `user_id` (без `chat_id`).

## 2. Новые таблицы

### 2.1 Экономика — Мана-руда

```sql
-- Глобальный кошелёк охотника (одна запись на user_id)
CREATE TABLE IF NOT EXISTS wallets (
    user_id      INTEGER PRIMARY KEY,
    mana         INTEGER DEFAULT 0,        -- текущий баланс Мана-руды
    total_earned INTEGER DEFAULT 0,        -- всего намайнено за всё время
    total_spent  INTEGER DEFAULT 0,
    updated_at   TEXT DEFAULT (datetime('now'))
);

-- Журнал всех движений руды (антифрод + история)
CREATE TABLE IF NOT EXISTS mana_tx (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER,
    amount    INTEGER,                      -- + начисление / - списание
    reason    TEXT,                         -- 'message','daily','invite','shop','ad_buy','transfer'
    ref_id    TEXT,                         -- id связанной сущности (заказа/перевода)
    chat_id   INTEGER,                      -- где заработано (если применимо)
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mana_tx_user ON mana_tx(user_id);
```

### 2.2 Рефералы

```sql
-- Персональная реф-привязка: кто кого привёл (в боте/чате через deep-link)
CREATE TABLE IF NOT EXISTS referrals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    inviter_id  INTEGER,                    -- кто пригласил
    invited_id  INTEGER,                    -- кого пригласили
    chat_id     INTEGER,                    -- в какой чат (0 = в бота/канал)
    source      TEXT,                       -- 'deeplink','chat_join','channel_join'
    rewarded    INTEGER DEFAULT 0,          -- начислена ли награда
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(invited_id, chat_id)             -- одного приглашённого засчитываем 1 раз
);
CREATE INDEX IF NOT EXISTS idx_ref_inviter ON referrals(inviter_id, chat_id);

-- Пороги повышения, которые задаёт админ чата
CREATE TABLE IF NOT EXISTS referral_goals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER,
    invites_required INTEGER,               -- сколько пригласить
    reward_type TEXT,                       -- 'role' | 'mana' | 'custom'
    reward_value TEXT,                      -- 'moderator'/'admin' | сумма руды | текст
    created_by  INTEGER,
    active      INTEGER DEFAULT 1
);

-- Роли внутри бота (модератор бота и т.п.), не Telegram-админство
CREATE TABLE IF NOT EXISTS chat_roles (
    user_id   INTEGER,
    chat_id   INTEGER,
    role      TEXT,                          -- 'moderator' | 'admin'
    granted_by INTEGER,
    granted_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, chat_id)
);
```

### 2.3 Реклама

```sql
-- Рекламная кампания (создаёт владелец или рекламодатель)
CREATE TABLE IF NOT EXISTS ad_campaigns (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id     INTEGER,                   -- кто заказал (0 = сам владелец бота)
    title        TEXT,
    content_type TEXT,                      -- 'text','photo','video','forward'
    payload      TEXT,                      -- текст или file_id / message ref
    button_text  TEXT,                      -- опц. кнопка-ссылка
    button_url   TEXT,
    target       TEXT DEFAULT 'all',        -- 'all' | 'chats' | 'channel'
    days_total   INTEGER DEFAULT 1,         -- на сколько дней оплачено
    days_done    INTEGER DEFAULT 0,
    status       TEXT DEFAULT 'pending',    -- 'pending','active','paused','done'
    created_at   TEXT DEFAULT (datetime('now'))
);

-- Лог показов (для статистики и лимита 1/день на чат)
CREATE TABLE IF NOT EXISTS ad_impressions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER,
    chat_id     INTEGER,
    sent_at     TEXT DEFAULT (datetime('now')),
    status      TEXT                        -- 'sent','failed'
);
CREATE INDEX IF NOT EXISTS idx_ad_imp_chat ON ad_impressions(chat_id, sent_at);

-- Согласие чата на рекламу (по умолчанию включено = условие бесплатности)
-- Можно хранить флагом прямо в chat_settings: ads_enabled INTEGER DEFAULT 1
```

### 2.4 Платежи (Telegram Stars)

```sql
CREATE TABLE IF NOT EXISTS payments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER,
    stars           INTEGER,                -- сколько XTR заплачено
    product         TEXT,                   -- 'mana_pack','ad_campaign','premium_gift'
    product_ref     TEXT,                   -- id кампании/пакета
    telegram_charge_id TEXT,                -- для рефандов
    status          TEXT DEFAULT 'paid',    -- 'paid','refunded'
    created_at      TEXT DEFAULT (datetime('now'))
);
```

## 3. Изменения существующих таблиц

```sql
-- chat_settings: согласие на рекламу + язык интерфейса уже есть
ALTER TABLE chat_settings ADD COLUMN ads_enabled INTEGER DEFAULT 1;
ALTER TABLE chat_settings ADD COLUMN ref_link TEXT;        -- инвайт-ссылка чата (кэш)

-- users: связь с глобальным кошельком уже через user_id; добавим роль-кэш не нужен,
-- роль берём из chat_roles.
```

## 4. Миграции

Сейчас миграции живут в `db.py::_migrate()` (ALTER при старте). При росте числа
изменений вынести в `database/migrations.py` со списком версий:

```python
MIGRATIONS = [
    ("0001_init", "..."),          # уже существующие CREATE TABLE
    ("0002_economy", "...sql..."), # wallets, mana_tx
    ("0003_referrals", "..."),
    ("0004_ads", "..."),
    ("0005_payments", "..."),
]
# таблица schema_version хранит применённые
```

Каждая миграция применяется один раз, идемпотентна (`IF NOT EXISTS`).

## 5. Производительность и масштаб

- Добавить индексы (см. выше) — критично при тысячах чатов.
- `chat_stats` чистить/агрегировать старше 90 дней.
- При нагрузке: перейти с одного `aiosqlite`-коннекта на пул или на PostgreSQL
  (`asyncpg`). Модели уже изолированы → меняется только слой `db.py`.
- Бэкап: persistent volume на хостинге + периодический дамп `.db` в канал владельца.
