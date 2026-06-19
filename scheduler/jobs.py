"""
Background scheduler (APScheduler).

Currently runs the daily ad broadcast at the configured UTC hour. Extend here
with future periodic jobs (weekly top digest, stats aggregation, etc.).
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from loguru import logger

from database import clear_expired_mutes
from services.ads_scheduler import send_due_ads
from services.backup import backup_and_ship
from services.showcase import post_weekly_top


def setup_scheduler(bot: Bot, cfg) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")

    async def _daily_ads() -> None:
        try:
            await send_due_ads(bot)
        except Exception as e:
            logger.warning(f"[SCHED] daily ads error: {e}")

    async def _weekly_top() -> None:
        try:
            await post_weekly_top(bot)
        except Exception as e:
            logger.warning(f"[SCHED] weekly top error: {e}")

    async def _sync_mutes() -> None:
        # Синхронизируем «протухшие» муты: Telegram снимает их сам по until_date,
        # а мы чистим флаг is_muted в БД, чтобы он не врал.
        try:
            n = await clear_expired_mutes()
            if n:
                logger.info(f"[SCHED] cleared {n} expired mutes")
        except Exception as e:
            logger.warning(f"[SCHED] mute sync error: {e}")

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
    scheduler.add_job(
        _sync_mutes, "interval",
        minutes=5, id="sync_mutes", replace_existing=True,
    )
    # Канал-витрина: топ охотников недели по понедельникам.
    scheduler.add_job(
        _weekly_top, "cron",
        day_of_week="mon", hour=cfg.ads_send_hour, minute=15,
        id="weekly_top", replace_existing=True,
    )
    logger.info(
        f"Scheduler ready: ads at {cfg.ads_send_hour:02d}:00 UTC, "
        f"backup at {cfg.backup_hour:02d}:30 UTC (keep {cfg.backup_keep}), "
        f"mute-sync every 5 min, weekly top Mon {cfg.ads_send_hour:02d}:15 UTC"
    )
    return scheduler
