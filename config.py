import os
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


# Постоянные («домашние») каналы владельца для стартового пула заданий-подписок.
# Бот должен быть админом в каждом из них (иначе подписку не проверить — канал
# тихо пропускается при сидинге). Переопределяется env STARTER_TASK_CHANNELS.
DEFAULT_STARTER_CHANNELS = [
    "https://t.me/best_motivation_music",
    "https://t.me/best_paradise_music",
    "https://t.me/ferrator_phonk",
    "https://t.me/crypto_alt_season",
    "https://t.me/minecraftnewscis",
    "https://t.me/best_love_games",
    "https://t.me/interesting_facts_best",
    "https://t.me/veseliyvzriv",
    "https://t.me/kulinarnietainy",
]


@dataclass
class Config:
    token: str
    owner_id: int
    log_channel_id: Optional[int]
    moderator_ids: list[int]
    db_path: str

    # Punishment thresholds
    warn_limit_mute: int = 3
    warn_limit_ban: int = 5
    mute_duration_minutes: int = 60
    flood_messages: int = 5
    flood_seconds: int = 5

    # ── Economy (Мана-руда) ─────────────────────────────────────────────────
    # Баланс ЕДИНЫЙ. Бесплатная добыча намеренно минимальна, чтобы основной
    # заработок шёл через задания (/tasks). Подписка ≈ 500 руды против ~1/сообщение.
    mana_per_message: int = 1
    mana_message_cooldown: int = 60      # секунд между начислениями за сообщения
    mana_daily_bonus: int = 0            # /daily даёт только опыт; руду даёт /dungeon
    # Реферальная руда теперь платится НЕ за вход, а когда приглашённый докажет
    # активность (первое повышение ранга). Это отсекает «слепую» накрутку.
    mana_invite_bonus: int = 0
    mana_referral_rankup: int = 50       # инвайтеру, когда приглашённый поднял ранг E→D (= AGENT_REWARDS["D"])
    # Веховые награды агенту за массовость гильдии: за каждые N игроков ранга
    # SS — +ss_block_reward, ранга SSS — +sss_block_reward. Цель растёт на N.
    agent_milestone_block: int = 10
    agent_ss_block_reward: int = 2000
    agent_sss_block_reward: int = 4000
    mana_transfer_fee_pct: int = 5       # комиссия казны при /transfer

    # ── Спонсоры / реклама в заданиях ────────────────────────────────────────
    # Временный спонсор: окно гарантии неотписки от подписки (дней).
    sponsor_temp_guarantee_days: int = 7
    # Постоянный спонсор после отмены: ещё столько дней держим гарантию.
    sponsor_post_cancel_grace_days: int = 7
    # Self-serve реклама: рекламодатель платит Stars в эскроу при подаче заявки.
    # Цена = max(ad_min_stars, target_subs × ad_price_per_sub_stars). Деньги
    # держатся ботом; при отклонении заявки — авто-возврат. Авто-публикации нет:
    # задание создаётся ТОЛЬКО после ручного одобрения владельцем.
    ad_self_serve_enabled: bool = True
    ad_price_per_sub_stars: int = 1
    ad_min_stars: int = 50
    # Платный приоритет задания в выдаче /tasks (буст позиции для спонсора).
    # Доплата к заявке; задание получает priority=task_boost_priority на boost-срок.
    ad_boost_stars: int = 150
    task_boost_priority: int = 100

    # ── Pro-чат (платная подписка чата за Stars) ─────────────────────────────
    # Премиум для чата: расширенная аналитика (/modstats за 90 дней), повышенные
    # лимиты триггеров/заметок, бейдж. Покупает админ чата; срок — pro_until.
    pro_chat_enabled: bool = True
    pro_price_30_stars: int = 150        # 30 дней
    pro_price_90_stars: int = 350        # 90 дней (выгоднее)
    pro_triggers_limit: int = 500        # против обычного лимита
    pro_analytics_days: int = 90

    # ── Ежедневное подземелье (бесплатный крючок) ────────────────────────────
    # /dungeon раз в день (ТОЛЬКО в чатах — бесплатная реклама): база + бонус
    # за рекламу бота в описании профиля. 25 + 25 = до 50 руды/день.
    daily_dungeon_base: int = 25
    daily_dungeon_ad_bonus: int = 25
    # Стрик: чек-ин подряд. На 30-й день — единоразовая награда (руда + тег).
    dungeon_streak_milestone: int = 30
    dungeon_streak_reward: int = 1000

    # ── Referrals / VIP ─────────────────────────────────────────────────────
    vip_invite_threshold: int = 50       # приглашений в бота для VIP-доступа
    vip_chat_link: str = ""              # инвайт-ссылка в VIP-чат с разработчиком

    # ── Tasks economy (платные задания) ──────────────────────────────────────
    # Пег для пользователя: 50 руды = 1 ₽. Подписка 2 ₽ → 50 руды охотнику, 50 — маржа.
    mana_per_rub: int = 50
    stars_usd_cents_per_1000: int = 1620   # 1000 ⭐ = $16.20
    usd_rub_rate: int = 76
    # Без наценки на обмен: вся маржа уже заложена в цене спонсора (он платит
    # 3–4 ₽ за подписчика, охотнику уходит ~2 ₽). Курс честный: 50 руды = 1 ₽.
    redeem_margin_pct: int = 0
    # Устаревший пег (для P&L владельца); основной курс — mana_per_rub.
    mana_per_usd: int = 20000
    task_payout_ratio: int = 50
    task_reward_subscribe: int = 100       # 2 ₽ пользователю при подписке спонсора 3–4 ₽
    task_revenue_rub_default: int = 4      # доход с рекламодателя за подписчика
    redeem_min: int = 1000                 # самый дешёвый подарок (15 ⭐ ≈ 1000 руды)
    # Базовый дневной лимит выполняемых заданий на охотника. Защищает экономику:
    # не платим за бесконечные подписки за день. Высокие ранги (S/SS/SSS) получают
    # надбавку к лимиту (см. utils.ranks.RANK_PERKS).
    tasks_daily_limit: int = 5

    # Стартовый («домашний») пул заданий-подписок: каналы, на которые бот сидит
    # задания на старте (постоянные, sponsor_type='house'). Канал бота
    # (sub_gate_channel) добавляется автоматически. Бот ДОЛЖЕН быть админом в
    # каждом канале (иначе подписку не проверить — канал тихо пропускается).
    # Переопределяется env STARTER_TASK_CHANNELS: "@chan1,@chan2,https://t.me/chan3".
    starter_task_channels: list[str] = field(default_factory=list)

    # ── Лесенка стрика: награда растёт за каждую сохранённую подписку ──────────
    # Множитель = 1 + min(streak, cap) × step%. При 10%/cap10 → до ×2.0.
    task_streak_step_pct: int = 10
    task_streak_cap: int = 10

    # ── Ачивка «первые 100 к рангу A» ─────────────────────────────────────────
    achievement_rank_a_mana: int = 10000    # порог total_earned (~200 ₽ при 50 руды/₽)
    achievement_first_slots: int = 100
    achievement_rank_a_bonus: int = 500

    # ── Ads ─────────────────────────────────────────────────────────────────
    ads_enabled: bool = True
    ads_daily_limit_per_chat: int = 1
    ads_send_hour: int = 12              # час по UTC ежедневной рекламной рассылки

    # ── Payments (Telegram Stars / XTR) ─────────────────────────────────────
    payments_enabled: bool = True

    # Канал-витрина бота (анонсы, реклама)
    bot_channel_id: Optional[int] = None
    bot_username: str = ""               # заполняется на старте из get_me

    # ── Обязательная подписка на канал бота (гейт доступа) ───────────────────
    # Без подписки на этот канал в личке бота доступен только /start: Система
    # просит вступить в гильдию. Бот ДОЛЖЕН быть админом канала (для проверки).
    sub_gate_enabled: bool = True
    sub_gate_channel: str = "@Manager_Rank_S"   # @username или -100… ID для проверки
    sub_gate_channel_url: str = "https://t.me/Manager_Rank_S"

    # ── Вывод руды в криптовалюте (через крипто-бота) — настраивается позже ───
    # Заготовка: когда будет выбран крипто-бот и получен токен — включить и
    # вписать токен ниже, остальная обвязка экономики уже готова (payout_requests).
    crypto_withdraw_enabled: bool = False
    crypto_bot_token: str = ""           # СЮДА ВСТАВИТЬ токен крипто-бота Crypto Pay (@CryptoBot → Crypto Pay → Create App)
    crypto_asset: str = "USDT"           # актив для выплат (USDT/TON/…)
    crypto_api_base: str = "https://pay.crypt.bot/api"  # mainnet; для тестнета: https://testnet-pay.crypt.bot/api
    # Лимиты крипто-вывода (анти-фрод): минимум за раз и суточный лимит в рудах.
    crypto_min_mana: int = 5000          # минимум на вывод (≈100 ₽ при 50 руды/₽)
    crypto_daily_limit_mana: int = 50000 # потолок суммы заявок в сутки на охотника

    # ── Постбэк-проверка заданий (S2S callback / CPA-модель) ─────────────────
    # Автоматический зачёт действий, которые Telegram не даёт проверить «снаружи»
    # (запуск чужого бота, очки в чужой игре и т.п.). Схема: мы выдаём охотнику
    # подписанный токен в deep-link на бота рекламодателя; бот рекламодателя при
    # выполнении дёргает наш URL /cb/task?token=… — мы проверяем подпись и
    # начисляем. Секрет подписи; если пусто — берём производную от токена бота.
    task_callback_secret: str = ""

    # ── Mini App (Telegram WebApp) ───────────────────────────────────────────
    # Бэкенд Mini App поднимается в том же процессе (aiohttp) на webapp_port.
    # webapp_url — ПУБЛИЧНЫЙ https-адрес (нужен для кнопки web_app в Telegram).
    # На Railway: задать WEBAPP_URL = https://<your-app>.up.railway.app, порт
    # берётся из PORT автоматически. Локально/без https кнопка web_app скрыта.
    webapp_enabled: bool = False
    webapp_url: str = ""                 # СЮДА ВСТАВИТЬ публичный https-адрес Mini App
    webapp_port: int = 8080

    # ── Масштаб (Фаза 6): webhook вместо polling ─────────────────────────────
    # При росте включи webhook: бот перестаёт «опрашивать» Telegram и принимает
    # апдейты на публичный https-эндпоинт (меньше задержка, держит больше нагрузки).
    # Работает на том же aiohttp-сервере, что и Mini App (порт PORT/webapp_port).
    webhook_enabled: bool = False
    webhook_url: str = ""                # СЮДА ВСТАВИТЬ публичный https-адрес (без пути), напр. https://app.up.railway.app
    webhook_path: str = "/webhook"       # путь приёма апдейтов
    webhook_secret: str = ""             # секрет проверки апдейтов (любая случайная строка)

    # ── PostgreSQL (при росте; по умолчанию SQLite) ──────────────────────────
    # Если задан DATABASE_URL (postg:// …) — драйвер БД переключится на Postgres
    # (см. database/db.py). Пока пусто — используется SQLite (db_path).
    database_url: str = ""               # СЮДА ВСТАВИТЬ postgres://user:pass@host:port/db при переезде

    # ── Локализация (i18n) ───────────────────────────────────────────────────
    # Язык по умолчанию для текстов бота. RU — основной (лор Solo Leveling),
    # EN — резервный для англоязычных охотников (utils/i18n.py).
    default_lang: str = "ru"

    # ── Cursor-мост (Cloud Agents API → GitHub-репозиторий проекта) ───────────
    cursor_api_key: str = ""
    cursor_repo_url: str = "https://github.com/ciseuadm/Manager-S-Rank"
    cursor_repo_ref: str = "main"
    cursor_work_on_branch: bool = True   # пуш в main, не в cursor/feature-ветки
    cursor_auto_pr: bool = False         # False = без PR, Railway деплоит сам
    cursor_model_sonnet: str = "claude-sonnet-4-6"
    cursor_model_opus: str = "claude-opus-4-8"

    # ── Бэкапы БД ─────────────────────────────────────────────────────────────
    backup_hour: int = 4                 # час по UTC ежедневного бэкапа БД
    backup_keep: int = 14                # сколько последних бэкапов хранить
    backup_channel_id: Optional[int] = None  # приватный канал для оффсайт-копий


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name, "")
    return int(raw) if raw.lstrip("-").isdigit() else default


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN not set in .env")

    owner_id_raw = os.getenv("OWNER_ID", "0")
    owner_id = int(owner_id_raw) if owner_id_raw.isdigit() else 0

    log_channel_raw = os.getenv("LOG_CHANNEL_ID", "")
    log_channel_id = int(log_channel_raw) if log_channel_raw.lstrip("-").isdigit() else None

    moderator_ids_raw = os.getenv("MODERATOR_IDS", "")
    moderator_ids = [int(x.strip()) for x in moderator_ids_raw.split(",") if x.strip().isdigit()]

    db_path = os.getenv("DB_PATH", "data/srank.db")

    bot_channel_raw = os.getenv("BOT_CHANNEL_ID", "")
    bot_channel_id = int(bot_channel_raw) if bot_channel_raw.lstrip("-").isdigit() else None

    return Config(
        token=token,
        owner_id=owner_id,
        log_channel_id=log_channel_id,
        moderator_ids=moderator_ids,
        db_path=db_path,
        mana_per_message=_get_int("MANA_PER_MESSAGE", 1),
        mana_message_cooldown=_get_int("MANA_MESSAGE_COOLDOWN", 60),
        mana_daily_bonus=_get_int("MANA_DAILY_BONUS", 0),
        mana_invite_bonus=_get_int("MANA_INVITE_BONUS", 0),
        mana_referral_rankup=_get_int("MANA_REFERRAL_RANKUP", 50),
        agent_milestone_block=_get_int("AGENT_MILESTONE_BLOCK", 10),
        agent_ss_block_reward=_get_int("AGENT_SS_BLOCK_REWARD", 2000),
        agent_sss_block_reward=_get_int("AGENT_SSS_BLOCK_REWARD", 4000),
        mana_transfer_fee_pct=_get_int("MANA_TRANSFER_FEE_PCT", 5),
        sponsor_temp_guarantee_days=_get_int("SPONSOR_TEMP_GUARANTEE_DAYS", 7),
        sponsor_post_cancel_grace_days=_get_int("SPONSOR_POST_CANCEL_GRACE_DAYS", 7),
        ad_self_serve_enabled=_get_bool("AD_SELF_SERVE_ENABLED", True),
        ad_price_per_sub_stars=_get_int("AD_PRICE_PER_SUB_STARS", 1),
        ad_min_stars=_get_int("AD_MIN_STARS", 50),
        ad_boost_stars=_get_int("AD_BOOST_STARS", 150),
        task_boost_priority=_get_int("TASK_BOOST_PRIORITY", 100),
        pro_chat_enabled=_get_bool("PRO_CHAT_ENABLED", True),
        pro_price_30_stars=_get_int("PRO_PRICE_30_STARS", 150),
        pro_price_90_stars=_get_int("PRO_PRICE_90_STARS", 350),
        pro_triggers_limit=_get_int("PRO_TRIGGERS_LIMIT", 500),
        pro_analytics_days=_get_int("PRO_ANALYTICS_DAYS", 90),
        daily_dungeon_base=_get_int("DAILY_DUNGEON_BASE", 25),
        daily_dungeon_ad_bonus=_get_int("DAILY_DUNGEON_AD_BONUS", 25),
        dungeon_streak_milestone=_get_int("DUNGEON_STREAK_MILESTONE", 30),
        dungeon_streak_reward=_get_int("DUNGEON_STREAK_REWARD", 1000),
        vip_invite_threshold=_get_int("VIP_INVITE_THRESHOLD", 50),
        vip_chat_link=os.getenv("VIP_CHAT_LINK", ""),
        mana_per_rub=_get_int("MANA_PER_RUB", 50),
        stars_usd_cents_per_1000=_get_int("STARS_USD_CENTS_PER_1000", 1620),
        usd_rub_rate=_get_int("USD_RUB_RATE", 76),
        redeem_margin_pct=_get_int("REDEEM_MARGIN_PCT", 0),
        mana_per_usd=_get_int("MANA_PER_USD", 20000),
        task_payout_ratio=_get_int("TASK_PAYOUT_RATIO", 50),
        task_reward_subscribe=_get_int("TASK_REWARD_SUBSCRIBE", 100),
        task_revenue_rub_default=_get_int("TASK_REVENUE_RUB", 4),
        redeem_min=_get_int("REDEEM_MIN", 1000),
        tasks_daily_limit=_get_int("TASKS_DAILY_LIMIT", 5),
        starter_task_channels=(
            [x.strip() for x in os.getenv("STARTER_TASK_CHANNELS", "").split(",") if x.strip()]
            or list(DEFAULT_STARTER_CHANNELS)
        ),
        task_streak_step_pct=_get_int("TASK_STREAK_STEP_PCT", 10),
        task_streak_cap=_get_int("TASK_STREAK_CAP", 10),
        achievement_rank_a_mana=_get_int("ACHIEVEMENT_RANK_A_MANA", 10000),
        achievement_first_slots=_get_int("ACHIEVEMENT_FIRST_SLOTS", 100),
        achievement_rank_a_bonus=_get_int("ACHIEVEMENT_RANK_A_BONUS", 500),
        ads_enabled=_get_bool("ADS_ENABLED", True),
        ads_daily_limit_per_chat=_get_int("ADS_DAILY_LIMIT_PER_CHAT", 1),
        ads_send_hour=_get_int("ADS_SEND_HOUR", 12),
        payments_enabled=_get_bool("PAYMENTS_ENABLED", True),
        bot_channel_id=bot_channel_id,
        sub_gate_enabled=_get_bool("SUB_GATE_ENABLED", True),
        sub_gate_channel=os.getenv("SUB_GATE_CHANNEL", "@Manager_Rank_S").strip(),
        sub_gate_channel_url=os.getenv(
            "SUB_GATE_CHANNEL_URL", "https://t.me/Manager_Rank_S"
        ).strip(),
        crypto_withdraw_enabled=_get_bool("CRYPTO_WITHDRAW_ENABLED", False),
        crypto_bot_token=os.getenv("CRYPTO_BOT_TOKEN", "").strip(),
        crypto_asset=os.getenv("CRYPTO_ASSET", "USDT").strip(),
        crypto_api_base=os.getenv("CRYPTO_API_BASE", "https://pay.crypt.bot/api").strip(),
        crypto_min_mana=_get_int("CRYPTO_MIN_MANA", 5000),
        crypto_daily_limit_mana=_get_int("CRYPTO_DAILY_LIMIT_MANA", 50000),
        task_callback_secret=os.getenv("TASK_CALLBACK_SECRET", "").strip(),
        webapp_enabled=_get_bool("WEBAPP_ENABLED", False),
        webapp_url=os.getenv("WEBAPP_URL", "").strip(),
        webapp_port=_get_int("PORT", _get_int("WEBAPP_PORT", 8080)),
        webhook_enabled=_get_bool("WEBHOOK_ENABLED", False),
        webhook_url=os.getenv("WEBHOOK_URL", "").strip(),
        webhook_path=os.getenv("WEBHOOK_PATH", "/webhook").strip() or "/webhook",
        webhook_secret=os.getenv("WEBHOOK_SECRET", "").strip(),
        database_url=os.getenv("DATABASE_URL", "").strip(),
        default_lang=os.getenv("DEFAULT_LANG", "ru").strip().lower() or "ru",
        cursor_api_key=os.getenv("CURSOR_API_KEY", "").strip(),
        cursor_repo_url=os.getenv("CURSOR_REPO_URL", "https://github.com/ciseuadm/Manager-S-Rank").strip(),
        cursor_repo_ref=os.getenv("CURSOR_REPO_REF", "main").strip(),
        cursor_work_on_branch=_get_bool("CURSOR_WORK_ON_BRANCH", True),
        cursor_auto_pr=_get_bool("CURSOR_AUTO_PR", False),
        cursor_model_sonnet=os.getenv("CURSOR_MODEL_SONNET", "claude-sonnet-4-6").strip(),
        cursor_model_opus=os.getenv("CURSOR_MODEL_OPUS", "claude-opus-4-8").strip(),
        backup_hour=_get_int("BACKUP_HOUR", 4),
        backup_keep=_get_int("BACKUP_KEEP", 14),
        backup_channel_id=(
            int(os.getenv("BACKUP_CHANNEL_ID"))
            if os.getenv("BACKUP_CHANNEL_ID", "").lstrip("-").isdigit() else None
        ),
    )
