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

    return Config(
        token=token,
        owner_id=owner_id,
        log_channel_id=log_channel_id,
        moderator_ids=moderator_ids,
        db_path=db_path,
    )
