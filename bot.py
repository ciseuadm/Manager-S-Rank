"""
S-RANK MANAGER BOT — Entry point
Solo Leveling themed Telegram group management bot.
"""
import asyncio
import sys
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault
from loguru import logger

from config import load_config
from database import init_db, close_db
from handlers import (
    moderation_router, admin_router, user_router, settings_router,
    owner_router, set_bot_id,
)
from middlewares import ThrottleMiddleware
from utils import set_owner_id


# ── Logging ────────────────────────────────────────────────────────────────────

logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    level="INFO",
)
logger.add(
    "logs/srank_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="14 days",
    level="DEBUG",
    encoding="utf-8",
)


# ── Startup / Shutdown ────────────────────────────────────────────────────────

BANNER = r"""
  ____       ____  ___    _   _ _  __
 / ___|     |  _ \/ _ \  | \ | | |/ /
 \___ \ ___ | |_) | |_| | |  \| | ' /
  ___) |___||  _ <|  _ \ | |\  | . \
 |____/     |_| \_\_| |_||_| \_|_|\_\

     M A N A G E R   B O T   v1.0
     Solo Leveling  •  S-Rank System
"""


BOT_COMMANDS = [
    BotCommand(command="start", description="Главное меню бота"),
    BotCommand(command="help", description="Полный список команд"),
    BotCommand(command="rank", description="Моя карточка охотника"),
    BotCommand(command="top", description="Топ охотников чата"),
    BotCommand(command="info", description="Инфо о пользователе"),
    BotCommand(command="stats", description="Статистика чата"),
    BotCommand(command="warn", description="Предупредить (админ)"),
    BotCommand(command="mute", description="Заглушить (админ)"),
    BotCommand(command="ban", description="Забанить (админ)"),
    BotCommand(command="kick", description="Выгнать (админ)"),
    BotCommand(command="settings", description="Настройки чата (админ)"),
    BotCommand(command="ping", description="Проверить работу бота"),
    BotCommand(command="id", description="Узнать свой ID"),
]


async def on_startup(bot: Bot, config) -> None:
    me = await bot.get_me()
    set_bot_id(me.id)
    set_owner_id(config.owner_id)
    try:
        await bot.set_my_commands(BOT_COMMANDS, scope=BotCommandScopeDefault())
    except Exception as e:
        logger.warning(f"set_my_commands error: {e}")
    logger.info(f"Bot started: @{me.username} (ID: {me.id}) | Owner: {config.owner_id}")

    if config.log_channel_id:
        try:
            await bot.send_message(
                config.log_channel_id,
                "⚡ <b>S-РАНГ МЕНЕДЖЕР — ЗАПУЩЕН</b>\n"
                "<i>Система Solo Leveling активирована. Наблюдение начато.</i>",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"Log channel error: {e}")


async def on_shutdown(bot: Bot) -> None:
    logger.info("Bot shutting down...")
    await close_db()


# ── Main ───────────────────────────────────────────────────────────────────────

async def main() -> None:
    print(BANNER)
    config = load_config()

    os.makedirs("logs", exist_ok=True)
    await init_db(config.db_path)

    bot = Bot(
        token=config.token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Middlewares
    dp.message.middleware(ThrottleMiddleware(rate=0.5))

    # Routers — order matters: moderation last so admin commands take priority
    dp.include_router(owner_router)
    dp.include_router(admin_router)
    dp.include_router(user_router)
    dp.include_router(settings_router)
    dp.include_router(moderation_router)

    async def _startup() -> None:
        await on_startup(bot, config)

    async def _shutdown() -> None:
        await on_shutdown(bot)

    dp.startup.register(_startup)
    dp.shutdown.register(_shutdown)

    logger.info("Starting polling...")
    await dp.start_polling(
        bot,
        allowed_updates=["message", "chat_member", "callback_query", "my_chat_member"],
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
