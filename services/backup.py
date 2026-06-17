"""
Автоматические бэкапы SQLite-базы.

Используем `VACUUM INTO` — это создаёт целостный снимок БД даже при включённом
WAL (в отличие от простого копирования файла, которое может поймать
несогласованное состояние). Снимки кладём в backups/ рядом с проектом, держим
последние N штук (retention), старые удаляем.
"""
import os
from datetime import datetime
from pathlib import Path

from loguru import logger

from database.db import get_db

BACKUP_DIR = Path(__file__).resolve().parents[1] / "backups"


async def backup_database(keep: int = 14) -> Path:
    """Сделать снимок БД в backups/ и почистить старые. Возвращает путь снимка."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    target = BACKUP_DIR / f"srank_{ts}.db"

    db = await get_db()
    # VACUUM INTO требует, чтобы целевой файл не существовал.
    await db.execute("VACUUM INTO ?", (str(target),))
    await db.commit()
    logger.info(f"[BACKUP] snapshot created: {target.name}")

    _prune(keep)
    return target


def _prune(keep: int) -> None:
    snaps = sorted(BACKUP_DIR.glob("srank_*.db"))
    extra = len(snaps) - max(keep, 1)
    for old in snaps[:extra] if extra > 0 else []:
        try:
            old.unlink()
            logger.info(f"[BACKUP] pruned old snapshot: {old.name}")
        except OSError as e:
            logger.warning(f"[BACKUP] prune failed for {old.name}: {e}")
