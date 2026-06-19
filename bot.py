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
from aiogram.types import (
    BotCommand, BotCommandScopeDefault, BotCommandScopeAllPrivateChats,
    BotCommandScopeAllGroupChats, BotCommandScopeAllChatAdministrators,
    BotCommandScopeChat, ErrorEvent,
)
from aiogram.exceptions import TelegramRetryAfter
from loguru import logger

from config import load_config
from database import init_db, close_db
from handlers import (
    moderation_router, admin_router, user_router, settings_router,
    owner_router, economy_router, referral_router, payments_router,
    ads_router, tasks_router, cursor_router, fun_router, set_bot_id,
)
from services.cursor_bridge import bridge as cursor_bridge
from middlewares import ThrottleMiddleware
from scheduler import setup_scheduler
from utils import set_owner_id, set_config


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


# Commands visible to every member (no moderation/settings here).
PUBLIC_COMMANDS = [
    BotCommand(command="rank", description="🏆 Моя карточка охотника"),
    BotCommand(command="top", description="📊 Топ охотников чата"),
    BotCommand(command="wallet", description="🔹 Хранилище Мана-руды"),
    BotCommand(command="shop", description="🛒 Рынок гильдии"),
    BotCommand(command="dungeon", description="🏰 Подземелье: до 50 руды/день"),
    BotCommand(command="daily", description="🎁 Ежедневный бонус опыта"),
    BotCommand(command="tasks", description="📋 Задания: +100 руды за подписку"),
    BotCommand(command="redeem", description="🎁 Обменять руду на подарок"),
    BotCommand(command="achievements", description="🏅 Мои достижения"),
    BotCommand(command="invite", description="⚔️ Пригласить друзей"),
    BotCommand(command="guild", description="🏛 Моя гильдия"),
    BotCommand(command="guilds", description="🏆 Рейтинг гильдий"),
    BotCommand(command="myref", description="🔗 Моя реф-ссылка"),
    BotCommand(command="vip", description="👑 VIP-зал"),
    BotCommand(command="invites", description="👥 Топ по приглашениям"),
    BotCommand(command="transfer", description="💸 Передать руду (ответом)"),
    BotCommand(command="info", description="ℹ️ Инфо о пользователе"),
    BotCommand(command="stats", description="📈 Статистика чата"),
    BotCommand(command="rules", description="📜 Правила чата"),
    BotCommand(command="oracle", description="🔮 Предсказание Системы"),
    BotCommand(command="duel", description="⚔️ Дуэль охотников"),
    BotCommand(command="dice", description="🎲 Бросок кубика"),
    BotCommand(command="help", description="📋 Список команд"),
    BotCommand(command="id", description="🆔 Узнать свой ID"),
]

# Commands shown only in private chat with the bot.
PRIVATE_COMMANDS = [
    BotCommand(command="start", description="⚡ Главное меню бота"),
    BotCommand(command="dungeon", description="🏰 Подземелье: до 50 руды/день"),
    BotCommand(command="wallet", description="🔹 Хранилище Мана-руды"),
    BotCommand(command="tasks", description="📋 Задания: +100 руды за подписку"),
    BotCommand(command="redeem", description="🎁 Обменять руду на подарок"),
    BotCommand(command="shop", description="🛒 Рынок гильдии"),
    BotCommand(command="buy", description="💎 Купить руду за Stars"),
    BotCommand(command="guild", description="🏛 Моя гильдия"),
    BotCommand(command="guilds", description="🏆 Рейтинг гильдий"),
    BotCommand(command="myref", description="🔗 Моя реф-ссылка"),
    BotCommand(command="vip", description="👑 VIP-зал"),
    BotCommand(command="donate", description="💛 Поддержать проект"),
    BotCommand(command="help", description="📋 Список команд"),
    BotCommand(command="id", description="🆔 Узнать свой ID"),
]

# Admin-only management commands (appended to the public list for admins).
ADMIN_ONLY_COMMANDS = [
    BotCommand(command="warn", description="⚠️ Предупредить"),
    BotCommand(command="unwarn", description="✅ Снять предупреждение"),
    BotCommand(command="warns", description="📋 Предупреждения"),
    BotCommand(command="mute", description="🔇 Заглушить"),
    BotCommand(command="unmute", description="🔊 Размутить"),
    BotCommand(command="ban", description="🚫 Забанить"),
    BotCommand(command="unban", description="♻️ Разбанить"),
    BotCommand(command="kick", description="👟 Выгнать"),
    BotCommand(command="del", description="🗑 Удалить сообщение"),
    BotCommand(command="settings", description="⚙️ Настройки чата"),
    BotCommand(command="addword", description="➕ Слово в чёрный список"),
    BotCommand(command="rmword", description="➖ Убрать слово"),
    BotCommand(command="words", description="📋 Чёрный список"),
    BotCommand(command="setwelcome", description="📝 Изменить приветствие"),
    BotCommand(command="setrules", description="📜 Изменить правила"),
    BotCommand(command="setgoal", description="🎯 Цель приглашений"),
    BotCommand(command="goals", description="🎯 Список целей"),
    BotCommand(command="ads", description="📢 Реклама в чате on/off"),
]

# Admins see public + management commands.
ADMIN_COMMANDS = PUBLIC_COMMANDS + ADMIN_ONLY_COMMANDS

# Owner gets the control panel commands in their private chat.
OWNER_COMMANDS = PRIVATE_COMMANDS + [
    BotCommand(command="owner", description="👑 Панель владельца"),
    BotCommand(command="gstats", description="📊 Глобальная статистика"),
    BotCommand(command="chats", description="💬 Список чатов"),
    BotCommand(command="broadcast", description="📢 Рассылка"),
    BotCommand(command="newad", description="📢 Новая рекламная кампания"),
    BotCommand(command="ads", description="📢 Кампании и статистика"),
    BotCommand(command="sendads", description="📤 Разослать рекламу сейчас"),
    BotCommand(command="deletead", description="🗑 Удалить рекламную кампанию"),
    BotCommand(command="addtask", description="🆕 Новое задание-подписка"),
    BotCommand(command="tasklist", description="📋 Список заданий"),
    BotCommand(command="payouts", description="🎁 Заявки на вывод"),
    BotCommand(command="backup", description="🗄 Бэкап БД сейчас"),
    BotCommand(command="dbcheck", description="🩺 Проверить целостность БД"),
    BotCommand(command="cursor", description="🛰 Связь с Курсором"),
]


async def setup_commands(bot: Bot, owner_id: int) -> None:
    """
    Register commands per scope so the "/" menu only shows admin/management
    commands to administrators — regular members never see them.
    """
    await bot.set_my_commands(PUBLIC_COMMANDS, scope=BotCommandScopeDefault())
    await bot.set_my_commands(PRIVATE_COMMANDS, scope=BotCommandScopeAllPrivateChats())
    await bot.set_my_commands(PUBLIC_COMMANDS, scope=BotCommandScopeAllGroupChats())
    await bot.set_my_commands(
        ADMIN_COMMANDS, scope=BotCommandScopeAllChatAdministrators()
    )
    if owner_id:
        try:
            await bot.set_my_commands(
                OWNER_COMMANDS, scope=BotCommandScopeChat(chat_id=owner_id)
            )
        except Exception as e:
            logger.warning(f"owner commands scope error: {e}")


async def on_startup(bot: Bot, config) -> None:
    me = await bot.get_me()
    set_bot_id(me.id)
    set_owner_id(config.owner_id)
    config.bot_username = me.username or ""
    set_config(config)
    cursor_bridge.configure(
        config.cursor_api_key,
        config.cursor_repo_url,
        config.cursor_repo_ref,
        config.cursor_work_on_branch,
        config.cursor_auto_pr,
        config.cursor_model_sonnet,
        config.cursor_model_opus,
    )
    if cursor_bridge.available():
        logger.info("Cursor cloud bridge: configured (/cursor available to owner)")
    else:
        logger.info("Cursor bridge: disabled (no CURSOR_API_KEY)")
    try:
        await setup_commands(bot, config.owner_id)
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


async def on_shutdown(bot: Bot, scheduler=None) -> None:
    logger.info("Bot shutting down...")
    if scheduler is not None:
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            pass
    try:
        await cursor_bridge.close()
    except Exception:
        pass
    await close_db()


async def on_error(event: ErrorEvent) -> bool:
    """Global safety net: log any unhandled error so polling never dies."""
    exc = event.exception
    if isinstance(exc, TelegramRetryAfter):
        logger.warning(f"Flood control: retry after {exc.retry_after}s")
        return True
    logger.exception(f"Unhandled error: {exc}")
    return True  # mark handled — keep the bot alive


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

    # Middlewares — throttle messages and inline-button taps (anti-flood / anti-spam).
    throttle = ThrottleMiddleware(rate=0.5, callback_rate=0.7)
    dp.message.middleware(throttle)
    dp.callback_query.middleware(throttle)

    # Routers — order matters: moderation last so admin commands take priority
    dp.include_router(owner_router)
    dp.include_router(tasks_router)
    dp.include_router(ads_router)
    dp.include_router(admin_router)
    dp.include_router(user_router)
    dp.include_router(settings_router)
    dp.include_router(economy_router)
    dp.include_router(referral_router)
    dp.include_router(payments_router)
    dp.include_router(fun_router)
    dp.include_router(cursor_router)
    dp.include_router(moderation_router)

    dp.errors.register(on_error)

    scheduler = setup_scheduler(bot, config)

    async def _startup() -> None:
        await on_startup(bot, config)
        scheduler.start()

    async def _shutdown() -> None:
        await on_shutdown(bot, scheduler)

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
