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
    mana_per_message: int = 1
    mana_message_cooldown: int = 30      # секунд между начислениями за сообщения
    mana_daily_bonus: int = 50
    mana_invite_bonus: int = 200
    mana_transfer_fee_pct: int = 5       # комиссия казны при /transfer

    # ── Referrals / VIP ─────────────────────────────────────────────────────
    vip_invite_threshold: int = 50       # приглашений в бота для VIP-доступа
    vip_chat_link: str = ""              # инвайт-ссылка в VIP-чат с разработчиком

    # ── Ads ─────────────────────────────────────────────────────────────────
    ads_enabled: bool = True
    ads_daily_limit_per_chat: int = 1
    ads_send_hour: int = 12              # час по UTC ежедневной рекламной рассылки

    # ── Payments (Telegram Stars / XTR) ─────────────────────────────────────
    payments_enabled: bool = True

    # Канал-витрина бота (анонсы, реклама)
    bot_channel_id: Optional[int] = None
    bot_username: str = ""               # заполняется на старте из get_me


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
        mana_message_cooldown=_get_int("MANA_MESSAGE_COOLDOWN", 30),
        mana_daily_bonus=_get_int("MANA_DAILY_BONUS", 50),
        mana_invite_bonus=_get_int("MANA_INVITE_BONUS", 200),
        mana_transfer_fee_pct=_get_int("MANA_TRANSFER_FEE_PCT", 5),
        vip_invite_threshold=_get_int("VIP_INVITE_THRESHOLD", 50),
        vip_chat_link=os.getenv("VIP_CHAT_LINK", ""),
        ads_enabled=_get_bool("ADS_ENABLED", True),
        ads_daily_limit_per_chat=_get_int("ADS_DAILY_LIMIT_PER_CHAT", 1),
        ads_send_hour=_get_int("ADS_SEND_HOUR", 12),
        payments_enabled=_get_bool("PAYMENTS_ENABLED", True),
        bot_channel_id=bot_channel_id,
    )
