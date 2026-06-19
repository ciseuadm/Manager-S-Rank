"""
Background scheduler (APScheduler).

Currently runs the daily ad broadcast at the configured UTC hour. Extend here
with future periodic jobs (weekly top digest, stats aggregation, etc.).
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from loguru import logger

from services.ads_scheduler import send_due_ads
from services.backup import backup_and_ship


def setup_scheduler(bot: Bot, cfg) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")

    async def _daily_ads() -> None:
        try:
            await send_due_ads(bot)
        except Exception as e:
            logger.warning(f"[SCHED] daily ads error: {e}")

    async def _daily_backup() -> None:
        try:
            await backup_and_ship(bot, keep=cfg.backup_keep)
        except Exception as e:
            logger.warning(f"[SCHED] backup error: {e}")
            # Простой алертинг: бэкап — критичная вещь, владелец должен знать.
            if cfg.owner_id:
                try:
                    await bot.send_message(
                        cfg.owner_id,
                        "⚠️ <b>Бэкап БД не удался</b>\n"
                        f"Причина: <code>{e}</code>\n"
                        "Проверь свободное место и права на папку бэкапов.",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass

    scheduler.add_job(
        _daily_ads, "cron",
        hour=cfg.ads_send_hour, minute=0,
        id="daily_ads", replace_existing=True,
    )
    scheduler.add_job(
        _daily_backup, "cron",
        hour=cfg.backup_hour, minute=30,
        id="daily_backup", replace_existing=True,
    )
    logger.info(
        f"Scheduler ready: ads at {cfg.ads_send_hour:02d}:00 UTC, "
        f"backup at {cfg.backup_hour:02d}:30 UTC (keep {cfg.backup_keep})"
    )
    return scheduler
