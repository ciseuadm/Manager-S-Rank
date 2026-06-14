"""
Background scheduler (APScheduler).

Currently runs the daily ad broadcast at the configured UTC hour. Extend here
with future periodic jobs (weekly top digest, stats aggregation, etc.).
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from loguru import logger

from services.ads_scheduler import send_due_ads


def setup_scheduler(bot: Bot, cfg) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")

    async def _daily_ads() -> None:
        try:
            await send_due_ads(bot)
        except Exception as e:
            logger.warning(f"[SCHED] daily ads error: {e}")

    scheduler.add_job(
        _daily_ads, "cron",
        hour=cfg.ads_send_hour, minute=0,
        id="daily_ads", replace_existing=True,
    )
    logger.info(f"Scheduler ready: daily ads at {cfg.ads_send_hour:02d}:00 UTC")
    return scheduler
