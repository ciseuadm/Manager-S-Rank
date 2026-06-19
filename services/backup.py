"""
Автоматические бэкапы SQLite-базы + оффсайт-копия в Telegram.

Защита данных в несколько слоёв (чтобы «никогда не упасть в грязь лицом»):
  1. VACUUM INTO — целостный снимок БД даже при включённом WAL.
  2. PRAGMA integrity_check — снимок проверяется перед тем, как ему доверять.
  3. Снимки лежат на ПОСТОЯННОМ диске (рядом с самой БД), а не в эфемерной
     папке проекта — переживают передеплой Railway.
  4. Оффсайт-копия: снимок отправляется документом в Telegram (владельцу и/или
     в приватный канал бэкапов). Даже полная потеря диска не уничтожит данные.
  5. Восстановление: validate → бэкап текущего → подмена файла → реконнект.
"""
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from aiogram import Bot
from aiogram.types import FSInputFile
from loguru import logger

from utils import get_config


def _backup_dir() -> Path:
    """Папка бэкапов на постоянном диске (рядом с файлом БД). Переопределяется BACKUP_DIR."""
    env_dir = os.getenv("BACKUP_DIR", "").strip()
    if env_dir:
        d = Path(env_dir)
    else:
        cfg = get_config()
        d = Path(cfg.db_path).resolve().parent / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def integrity_ok(db_file: Path) -> tuple[bool, str]:
    """Проверяет целостность SQLite-файла (integrity_check + foreign_key_check)."""
    try:
        con = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
        try:
            row = con.execute("PRAGMA integrity_check").fetchone()
            result = (row[0] if row else "").lower()
            if result != "ok":
                return False, f"integrity_check: {result}"
            fk = con.execute("PRAGMA foreign_key_check").fetchall()
            if fk:
                return False, f"foreign_key_check: {len(fk)} нарушений"
            return True, "ok"
        finally:
            con.close()
    except Exception as e:
        return False, f"open failed: {e}"


async def backup_database(keep: int = 14) -> Path:
    """Снимок БД на постоянный диск + проверка целостности. Возвращает путь снимка."""
    from database.db import get_db

    backup_dir = _backup_dir()
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    target = backup_dir / f"srank_{ts}.db"

    db = await get_db()
    # VACUUM INTO требует, чтобы целевой файл не существовал.
    await db.execute("VACUUM INTO ?", (str(target),))
    await db.commit()

    ok, detail = integrity_ok(target)
    if not ok:
        logger.error(f"[BACKUP] snapshot {target.name} corrupt: {detail}")
        raise RuntimeError(f"Снимок повреждён: {detail}")

    logger.info(f"[BACKUP] snapshot ok: {target.name} ({target.stat().st_size} bytes)")
    _prune(backup_dir, keep)
    return target


async def backup_and_ship(bot: Bot, keep: int = 14) -> Path:
    """Снимок + оффсайт-копия: отправляем документ владельцу и/или в канал бэкапов."""
    cfg = get_config()
    target = await backup_database(keep=keep)

    caption = (
        "🗄 <b>Бэкап БД S-Ранг</b>\n"
        f"📅 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"📦 {target.stat().st_size // 1024} КБ · целостность ✅\n"
        "<i>Сохрани это сообщение — из файла можно восстановить бота через /restore.</i>"
    )
    doc = FSInputFile(str(target), filename=target.name)

    targets: list[int] = []
    if getattr(cfg, "backup_channel_id", None):
        targets.append(cfg.backup_channel_id)
    if cfg.owner_id:
        targets.append(cfg.owner_id)

    shipped = False
    for chat_id in targets:
        try:
            await bot.send_document(chat_id, doc, caption=caption, parse_mode="HTML")
            shipped = True
        except Exception as e:
            logger.warning(f"[BACKUP] ship to {chat_id} failed: {e}")
    if not shipped:
        logger.warning("[BACKUP] offsite copy not shipped (no reachable target)")
    return target


async def restore_from_file(src: Path) -> tuple[bool, str]:
    """
    Восстановление БД из файла-снимка:
      validate → бэкап текущего → подмена → реконнект.
    Только для владельца (проверяется в хендлере). Возвращает (ok, detail).
    """
    from database.db import init_db, close_db, get_db

    ok, detail = integrity_ok(src)
    if not ok:
        return False, f"Файл не прошёл проверку целостности: {detail}"

    cfg = get_config()
    db_path = Path(cfg.db_path).resolve()

    # Контрольный снимок текущей БД перед перезаписью (на случай отката).
    try:
        await backup_database(keep=cfg.backup_keep)
    except Exception as e:
        logger.warning(f"[RESTORE] pre-restore backup failed: {e}")

    await close_db()
    # Чистим WAL/SHM, чтобы не смешать со старым состоянием.
    for suffix in ("-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass
    shutil.copyfile(src, db_path)
    await init_db(str(db_path))

    # Sanity: БД открылась и базовые таблицы на месте.
    try:
        db = await get_db()
        await db.execute("SELECT 1 FROM wallets LIMIT 1")
    except Exception as e:
        return False, f"БД восстановлена, но запрос не прошёл: {e}"
    return True, "ok"


def _prune(backup_dir: Path, keep: int) -> None:
    snaps = sorted(backup_dir.glob("srank_*.db"))
    extra = len(snaps) - max(keep, 1)
    for old in snaps[:extra] if extra > 0 else []:
        try:
            old.unlink()
            logger.info(f"[BACKUP] pruned old snapshot: {old.name}")
        except OSError as e:
            logger.warning(f"[BACKUP] prune failed for {old.name}: {e}")
