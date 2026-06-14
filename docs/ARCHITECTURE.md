# 🏛 ARCHITECTURE — целевая структура

> Текущая структура хорошая, но «плоская». Цель — нарастить её модулями
> под монетизацию и масштаб, **не ломая** существующее. Принцип: handlers тонкие,
> вся логика — в `services/`, все запросы к БД — в `database/`.

---

## 1. Текущая структура (как есть)

```
Manager S Rank/
├── bot.py              # точка входа, polling, команды, роутеры
├── config.py           # конфиг из .env
├── database/
│   ├── db.py           # один глобальный коннект aiosqlite
│   └── models.py       # все CRUD одним файлом
├── handlers/           # moderation, admin, user, settings, owner
├── filters/            # content (regex), flood
├── middlewares/        # throttle
├── utils/              # ranks, texts, helpers
└── keyboards/          # inline
```

## 2. Целевая структура (куда растём)

Новое выделено `🆕`. Существующее остаётся на месте и дорабатывается.

```
Manager S Rank/
├── bot.py
├── config.py                  # + новые секции: ads, economy, payments
├── docs/                      # 🆕 этот раздел планирования
│
├── database/
│   ├── db.py                  # + индексы, pool-ready слой
│   ├── migrations.py          # 🆕 версионируемые миграции (вместо _migrate в db.py)
│   └── models/                # 🆕 разбить models.py по доменам
│       ├── chats.py           #    настройки чатов
│       ├── users.py           #    охотники, ранги, варны
│       ├── economy.py         # 🆕 кошельки Мана-руды, транзакции
│       ├── referrals.py       # 🆕 реф-ссылки, пороги, повышения
│       ├── ads.py             # 🆕 рекламные кампании, показы
│       └── stats.py           #    статистика
│
├── handlers/
│   ├── moderation.py          # автомодерация (есть)
│   ├── admin.py               # команды админа (есть)
│   ├── user.py                # пользовательские команды (есть)
│   ├── settings.py            # настройки чата (есть)
│   ├── owner.py               # панель владельца (есть, расширяем)
│   ├── economy.py             # 🆕 /wallet /mine /shop /transfer
│   ├── referral.py            # 🆕 /invite (deep-link), /myref, пороги
│   ├── ads.py                 # 🆕 рекламный кабинет: создать кампанию, статистика
│   └── payments.py            # 🆕 Telegram Stars: пополнение, покупка рекламы
│
├── services/                  # 🆕 бизнес-логика (handlers её только вызывают)
│   ├── economy.py             # 🆕 начисление/списание руды, антифрод
│   ├── referral.py            # 🆕 учёт рефералов, авто-повышение ролей
│   ├── ads_scheduler.py       # 🆕 ежедневная рассылка рекламы (APScheduler)
│   ├── broadcaster.py         # 🆕 безопасная рассылка с rate-limit и ретраями
│   ├── moderation.py          # 🆕 вынести логику наказаний из handlers
│   └── rewards.py             # 🆕 выдача подарков/Premium за руду
│
├── filters/
│   ├── content.py             # regex-фильтры (есть, расширяем словари)
│   └── flood.py               # антифлуд (есть)
│
├── middlewares/
│   ├── throttle.py            # rate limiter (есть)
│   └── db_user.py             # 🆕 авто get_or_create_user + прокидывание в handler
│
├── scheduler/                 # 🆕 фоновые задачи
│   └── jobs.py                # 🆕 ежедневная реклама, снятие мутов, дейли-сброс
│
├── utils/
│   ├── ranks.py               # ранги (есть)
│   ├── texts.py               # тексты (есть, выносим рекламные/экономические)
│   ├── helpers.py             # хелперы (есть)
│   └── mana.py                # 🆕 формулы заработка руды, форматирование
│
└── keyboards/
    └── inline.py              # + клавиатуры магазина, реф-кабинета, рекламы
```

## 3. Слои и зависимости (направление импортов)

```
handlers  →  services  →  database/models  →  database/db
   │            │
   └────────────┴──→  utils, keyboards, filters
```

- **handlers** — только парсинг апдейта, проверка прав, вызов сервиса, ответ.
- **services** — вся бизнес-логика (экономика, рефералы, рассылки, наказания).
- **database/models** — только SQL, никакой логики.
- Никаких обратных импортов (models не знает про services и т.д.).

## 4. Роли пользователей (иерархия прав)

```
МОНАРХ (owner_id)         ← ты, супер-админ во всех чатах, рекламный кабинет
  └ Создатель чата        ← creator в Telegram
     └ Админ чата         ← administrator в Telegram
        └ Модератор бота   🆕 назначается через рефералку/руду, права в рамках бота
           └ Охотник       ← обычный участник
```

`Модератор бота` — новая роль **внутри бота** (таблица `chat_roles`), не путать с
админом Telegram. Даёт доступ к части модерации (варны/мут), но не к настройкам.

## 5. Принципы устойчивости (24/7)

- Глобальный `errors` handler уже есть — расширить логированием в канал.
- Все внешние вызовы Telegram оборачивать в try/except + ретрай при `RetryAfter`.
- Рассылки — только через `services/broadcaster.py` с задержками и батчингом.
- Состояние FSM сейчас в памяти — при росте перенести в Redis (не срочно).
- БД — WAL уже включён; добавить индексы (см. DATABASE.md), бэкап volume.

## 6. Конфигурация (расширение config.py)

Новые переменные `.env`:

```env
# Экономика
MANA_PER_MESSAGE=1
MANA_DAILY_BONUS=50
MANA_INVITE_BONUS=200

# Реклама
ADS_ENABLED=1
ADS_DAILY_LIMIT_PER_CHAT=1
ADS_SEND_HOUR=12            # час по UTC для ежедневной рассылки

# Платежи (Telegram Stars — провайдер не нужен)
PAYMENTS_ENABLED=1

# Канал бота для рекламы и анонсов
BOT_CHANNEL_ID=-100...
```
