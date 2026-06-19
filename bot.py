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
    MenuButtonWebApp, MenuButtonCommands, WebAppInfo,
)
from aiogram.exceptions import TelegramRetryAfter
from loguru import logger

from config import load_config
from database import init_db, close_db
from handlers import (
    moderation_router, admin_router, user_router, settings_router,
    owner_router, economy_router, referral_router, payments_router,
    ads_router, sponsors_router, tasks_router, cursor_router, fun_router,
    menu_router, chat_lifecycle_router, triggers_router, social_router,
    pro_router,
    set_bot_id,
)
from services.cursor_bridge import bridge as cursor_bridge
from middlewares import ThrottleMiddleware, SubGateMiddleware, EmojiFallbackMiddleware
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
    BotCommand(command="privileges", description="👑 Привилегии рангов S/SS/SSS"),
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
    BotCommand(command="duel", description="⚔️ Дуэль (на ставку: /duel 100)"),
    BotCommand(command="raid", description="🐉 Групповой рейд за рудой"),
    BotCommand(command="clan", description="🏛 Мой клан"),
    BotCommand(command="clans", description="🏆 Топ кланов чата"),
    BotCommand(command="marry", description="💍 Брак охотников (ответом)"),
    BotCommand(command="note", description="📝 Показать заметку чата"),
    BotCommand(command="notes", description="📒 Заметки чата"),
    BotCommand(command="dice", description="🎲 Бросок кубика"),
    BotCommand(command="help", description="📋 Список команд"),
    BotCommand(command="id", description="🆔 Узнать свой ID"),
]

# Commands shown only in private chat with the bot.
PRIVATE_COMMANDS = [
    BotCommand(command="start", description="⚡ Главное меню бота"),
    BotCommand(command="menu", description="📲 Меню в кнопках (всё сразу)"),
    BotCommand(command="dungeon", description="🏰 Подземелье: до 50 руды/день"),
    BotCommand(command="wallet", description="🔹 Хранилище Мана-руды"),
    BotCommand(command="tasks", description="📋 Задания: +100 руды за подписку"),
    BotCommand(command="redeem", description="🎁 Обменять руду на подарок"),
    BotCommand(command="privileges", description="👑 Привилегии рангов S/SS/SSS"),
    BotCommand(command="shop", description="🛒 Рынок гильдии"),
    BotCommand(command="buy", description="💎 Купить руду за Stars"),
    BotCommand(command="guild", description="🏛 Моя гильдия"),
    BotCommand(command="guilds", description="🏆 Рейтинг гильдий"),
    BotCommand(command="myref", description="🔗 Моя реф-ссылка"),
    BotCommand(command="vip", description="👑 VIP-зал"),
    BotCommand(command="donate", description="💛 Поддержать проект"),
    BotCommand(command="advertise", description="📣 Реклама канала у нас"),
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
    BotCommand(command="setup", description="🚀 Запуск за 60 секунд"),
    BotCommand(command="settings", description="⚙️ Настройки чата"),
    BotCommand(command="addword", description="➕ Слово в чёрный список"),
    BotCommand(command="rmword", description="➖ Убрать слово"),
    BotCommand(command="words", description="📋 Чёрный список"),
    BotCommand(command="setwelcome", description="📝 Изменить приветствие"),
    BotCommand(command="setwelcomebtn", description="🔘 Кнопка в приветствии"),
    BotCommand(command="setrules", description="📜 Изменить правила"),
    BotCommand(command="setgoal", description="🎯 Цель приглашений"),
    BotCommand(command="goals", description="🎯 Список целей"),
    BotCommand(command="addtrigger", description="⚡ Добавить триггер"),
    BotCommand(command="deltrigger", description="➖ Удалить триггер"),
    BotCommand(command="triggers", description="📋 Триггеры чата"),
    BotCommand(command="save", description="💾 Сохранить заметку"),
    BotCommand(command="delnote", description="🗑 Удалить заметку"),
    BotCommand(command="allowword", description="✅ Слово в белый список"),
    BotCommand(command="allowlist", description="📋 Белый список антимата"),
    BotCommand(command="modstats", description="📊 Аналитика модерации"),
    BotCommand(command="pro", description="⭐ Pro-чат за Stars"),
    BotCommand(command="ads", description="📢 Реклама в чате on/off"),
]

# Admins see public + management commands.
ADMIN_COMMANDS = PUBLIC_COMMANDS + ADMIN_ONLY_COMMANDS

# Owner gets the control panel commands in their private chat.
OWNER_COMMANDS = PRIVATE_COMMANDS + [
    BotCommand(command="owner", description="👑 Панель владельца"),
    BotCommand(command="gstats", description="📊 Глобальная статистика"),
    BotCommand(command="bank", description="🏦 Центральный банк / P&L"),
    BotCommand(command="metrics", description="📈 Дашборд роста (DAU/k-factor/ARPU)"),
    BotCommand(command="announce", description="📣 Пост в канал бота"),
    BotCommand(command="chats", description="💬 Список чатов"),
    BotCommand(command="broadcast", description="📢 Рассылка"),
    BotCommand(command="newad", description="📢 Новая рекламная кампания"),
    BotCommand(command="ads", description="📢 Кампании и статистика"),
    BotCommand(command="sendads", description="📤 Разослать рекламу сейчас"),
    BotCommand(command="deletead", description="🗑 Удалить рекламную кампанию"),
    BotCommand(command="addtask", description="🆕 Задание-подписка/вступление"),
    BotCommand(command="addwatch", description="▶️ Задание-просмотр"),
    BotCommand(command="addquiz", description="❓ Задание-квиз"),
    BotCommand(command="addproof", description="📤 Задание с ручным пруфом"),
    BotCommand(command="taskproofs", description="📥 Очередь пруфов"),
    BotCommand(command="tasklist", description="📋 Список заданий"),
    BotCommand(command="boosttask", description="🚀 Поднять задание в выдаче"),
    BotCommand(command="adreqs", description="📥 Заявки рекламодателей"),
    BotCommand(command="endsponsor", description="🛑 Остановить спонсорство"),
    BotCommand(command="payouts", description="🎁 Заявки на вывод"),
    BotCommand(command="refund", description="↩️ Вернуть Stars по charge_id"),
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
    try:
        from utils.i18n import set_default_lang
        set_default_lang(config.default_lang)
    except Exception:
        pass
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

    # Кнопка-меню рядом с полем ввода в ЛС: открывает Mini App, если задан
    # публичный https-адрес (требование Telegram для web_app).
    try:
        if config.webapp_enabled and config.webapp_url.startswith("https://"):
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="🎮 Платформа",
                    web_app=WebAppInfo(url=config.webapp_url),
                )
            )
            logger.info("Mini App: кнопка-меню web_app установлена")
        else:
            await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    except Exception as e:
        logger.warning(f"set_chat_menu_button error: {e}")
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


async def on_shutdown(bot: Bot, scheduler=None, webapp_runner=None) -> None:
    logger.info("Bot shutting down...")
    if scheduler is not None:
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            pass
    if webapp_runner is not None:
        try:
            await webapp_runner.cleanup()
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
    # Премиум-эмодзи: если Telegram отвергнет <tg-emoji> (нет Premium у владельца
    # или это пост канала) — автоматически повторяем запрос с обычными эмодзи.
    bot.session.middleware(EmojiFallbackMiddleware())
    dp = Dispatcher(storage=MemoryStorage())

    # Middlewares — throttle messages and inline-button taps (anti-flood / anti-spam).
    throttle = ThrottleMiddleware(rate=0.5, callback_rate=0.7)
    dp.message.middleware(throttle)
    dp.callback_query.middleware(throttle)
    # Subscription gate — после throttle: требует подписки на канал бота в личке.
    subgate = SubGateMiddleware()
    dp.message.middleware(subgate)
    dp.callback_query.middleware(subgate)

    # Routers — order matters: moderation last so admin commands take priority
    dp.include_router(owner_router)
    dp.include_router(chat_lifecycle_router)
    dp.include_router(menu_router)
    dp.include_router(tasks_router)
    dp.include_router(sponsors_router)
    dp.include_router(ads_router)
    dp.include_router(admin_router)
    dp.include_router(triggers_router)
    dp.include_router(social_router)
    dp.include_router(pro_router)
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
    webapp_state: dict = {}

    allowed = [
        "message", "edited_message", "chat_member",
        "callback_query", "my_chat_member", "pre_checkout_query",
    ]
    use_webhook = bool(config.webhook_enabled and config.webhook_url.startswith("https://"))

    async def _startup() -> None:
        await on_startup(bot, config)
        scheduler.start()
        if use_webhook:
            # Webhook: апдейты приходят на наш https-эндпоинт (меньше задержка,
            # выше пропускная способность). Mini App живёт в том же app.
            url = config.webhook_url.rstrip("/") + config.webhook_path
            await bot.set_webhook(
                url=url,
                secret_token=config.webhook_secret or None,
                allowed_updates=allowed,
                drop_pending_updates=True,
            )
            logger.info(f"Webhook установлен: {url}")
        else:
            # Polling: на всякий случай снимаем возможный старый webhook.
            try:
                await bot.delete_webhook(drop_pending_updates=False)
            except Exception:
                pass
            try:
                from services.webapp import start_webapp
                webapp_state["runner"] = await start_webapp(bot)
            except Exception as e:
                logger.warning(f"Mini App backend не запущен: {e}")

    async def _shutdown() -> None:
        await on_shutdown(bot, scheduler, webapp_state.get("runner"))

    dp.startup.register(_startup)
    dp.shutdown.register(_shutdown)

    if use_webhook:
        from aiohttp import web
        from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
        from services.webapp import build_app

        # Один aiohttp-сервер на всё: приём апдейтов + Mini App + healthz.
        app = build_app(bot)
        SimpleRequestHandler(
            dispatcher=dp, bot=bot,
            secret_token=config.webhook_secret or None,
        ).register(app, path=config.webhook_path)
        setup_application(app, dp, bot=bot)

        runner = web.AppRunner(app)
        await runner.setup()  # триггерит dp startup (set_webhook и пр.)
        site = web.TCPSite(runner, host="0.0.0.0", port=config.webapp_port)
        await site.start()
        logger.info(f"Webhook-сервер слушает :{config.webapp_port}")
        try:
            await asyncio.Event().wait()  # держим процесс
        finally:
            await runner.cleanup()
    else:
        logger.info("Starting polling...")
        await dp.start_polling(bot, allowed_updates=allowed)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
