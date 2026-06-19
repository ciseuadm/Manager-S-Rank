import os
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


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
    mana_referral_rankup: int = 50       # инвайтеру, когда приглашённый поднял ранг E→D
    mana_transfer_fee_pct: int = 5       # комиссия казны при /transfer

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
    # Час по UTC ежедневной ре-проверки подписок (clawback при отписке).
    tasks_recheck_hour: int = 3

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
        mana_transfer_fee_pct=_get_int("MANA_TRANSFER_FEE_PCT", 5),
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
        tasks_recheck_hour=_get_int("TASKS_RECHECK_HOUR", 3),
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
        cursor_api_key=os.getenv("CURSOR_API_KEY", "").strip(),
        cursor_repo_url=os.getenv("CURSOR_REPO_URL", "https://github.com/ciseuadm/Manager-S-Rank").strip(),
        cursor_repo_ref=os.getenv("CURSOR_REPO_REF", "main").strip(),
        cursor_work_on_branch=_get_bool("CURSOR_WORK_ON_BRANCH", True),
        cursor_auto_pr=_get_bool("CURSOR_AUTO_PR", False),
        cursor_model_sonnet=os.getenv("CURSOR_MODEL_SONNET", "claude-sonnet-4-6").strip(),
        cursor_model_opus=os.getenv("CURSOR_MODEL_OPUS", "claude-opus-4-8").strip(),
        backup_hour=_get_int("BACKUP_HOUR", 4),
        backup_keep=_get_int("BACKUP_KEEP", 14),
    )
