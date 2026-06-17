"""
User-facing commands: /rank /top /stats /info /help /ping /id
"""
import asyncio

from loguru import logger
from aiogram import Router, F, Bot
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, ChatMemberUpdated, CallbackQuery
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter, JOIN_TRANSITION

from database import (
    get_or_create_user, get_chat_settings, set_chat_title,
    get_top_users, get_chat_stats, claim_daily,
    get_top_inviters, update_user_rank,
)
from keyboards import invite_keyboard, welcome_keyboard
from services import award_daily, register_bot_referral, register_chat_referral
from utils import (
    calculate_rank, get_rank_label, get_rank_title,
    messages_to_next_rank, rank_progress_bar,
    mention_html, escape_html, safe_format,
    WELCOME_DEFAULT, HELP_MSG, START_MSG, BOTFATHER_COMMANDS,
    INVITE_MSG, DAILY_MSG, DAILY_DONE_MSG, RULES_DEFAULT, INVITE_JOIN_MSG,
    RANK_UP_MSG, EARN_MSG, format_mana, get_config,
)

router = Router()

DAILY_BONUS = 15
INVITE_BONUS = 30


# ── /start ────────────────────────────────────────────────────────────────────

@router.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject, bot: Bot) -> None:
    # Deep-link referral: t.me/bot?start=ref_<inviter_id>
    payload = (command.args or "").strip()
    if payload.startswith("ref_") and message.from_user:
        rest = payload[4:]
        if rest.isdigit():
            inviter_id = int(rest)
            try:
                await register_bot_referral(bot, inviter_id, message.from_user.id)
            except Exception:
                pass

    # Маркетинговый «крючок» из приветствия: t.me/bot?start=earn
    text = EARN_MSG if payload == "earn" else START_MSG
    try:
        await message.answer(text, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"[START] send failed: {e}")


# ── /help ──────────────────────────────────────────────────────────────────────

@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    try:
        await message.answer(HELP_MSG, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"[HELP] send failed: {e}")


# ── /commands — список команд для BotFather ────────────────────────────────────

@router.message(Command("commands"))
async def cmd_commands(message: Message) -> None:
    try:
        await message.answer(BOTFATHER_COMMANDS, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"[COMMANDS] send failed: {e}")


# ── /ping ──────────────────────────────────────────────────────────────────────

@router.message(Command("ping"))
async def cmd_ping(message: Message) -> None:
    import time
    t = time.monotonic()
    msg = await message.answer("⚡ Система онлайн...")
    elapsed = int((time.monotonic() - t) * 1000)
    await msg.edit_text(
        f"⚡ <b>S-РАНГ МЕНЕДЖЕР — АКТИВЕН</b>\n\n"
        f"Пинг: <b>{elapsed}ms</b>\n"
        f"Статус: <code>ONLINE 24/7</code>\n"
        f"<i>Система Solo Leveling работает в штатном режиме.</i>",
        parse_mode="HTML",
    )


# ── /id ────────────────────────────────────────────────────────────────────────

@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    lines = [f"👤 Твой ID: <code>{message.from_user.id}</code>"]
    lines.append(f"💬 ID чата: <code>{message.chat.id}</code>")
    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        lines.append(f"↩️ ID пользователя: <code>{u.id}</code>")
    await message.answer("\n".join(lines), parse_mode="HTML")


# ── /rank ──────────────────────────────────────────────────────────────────────

@router.message(Command("rank", "me"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_rank(message: Message) -> None:
    user = message.from_user
    if not user:
        return

    if message.reply_to_message and message.reply_to_message.from_user:
        user = message.reply_to_message.from_user

    db_user = await get_or_create_user(user.id, message.chat.id, full_name=user.full_name)
    msgs = db_user.get("messages", 0)
    rank = calculate_rank(msgs)
    label = get_rank_label(rank)
    title = get_rank_title(rank)
    progress = rank_progress_bar(msgs, rank)
    to_next = messages_to_next_rank(msgs, rank)

    next_line = f"\n🔜 До следующего ранга: <b>{to_next}</b> сообщений" if to_next else "\n👑 <b>МАКСИМАЛЬНЫЙ РАНГ ДОСТИГНУТ!</b>"

    text = (
        f"⚡ <b>КАРТОЧКА ОХОТНИКА</b>\n\n"
        f"👤 {mention_html(user)}\n"
        f"🏆 Ранг: <b>{label}</b>\n"
        f"🎖 Звание: <i>{title}</i>\n"
        f"💬 Сообщений: <b>{msgs}</b>\n"
        f"⚠️ Предупреждений: <b>{db_user.get('warns', 0)}</b>\n\n"
        f"📊 Прогресс: {progress}{next_line}"
    )
    await message.answer(text, parse_mode="HTML")


# ── /top ───────────────────────────────────────────────────────────────────────

@router.message(Command("top"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_top(message: Message) -> None:
    users = await get_top_users(message.chat.id, limit=10)
    if not users:
        await message.answer("📊 Статистики пока нет.")
        return

    MEDALS = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    lines = ["⚡ <b>ТОП ОХОТНИКОВ ЧАТА</b>\n"]
    for i, u in enumerate(users):
        name = escape_html(u.get("full_name") or u.get("username") or str(u["user_id"]))
        label = get_rank_label(u.get("rank", "E"))
        lines.append(
            f"{MEDALS[i]} {i+1}. <b>{name}</b> {label} — {u['messages']} сообщений"
        )

    await message.answer("\n".join(lines), parse_mode="HTML")


# ── /info ──────────────────────────────────────────────────────────────────────

@router.message(Command("info"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_info(message: Message, bot) -> None:
    user = message.from_user
    if message.reply_to_message and message.reply_to_message.from_user:
        user = message.reply_to_message.from_user

    db_user = await get_or_create_user(user.id, message.chat.id, full_name=user.full_name)

    try:
        member = await bot.get_chat_member(message.chat.id, user.id)
        status = member.status
    except Exception:
        status = "unknown"

    rank = calculate_rank(db_user.get("messages", 0))
    label = get_rank_label(rank)

    status_icons = {
        "creator": "👑 Создатель",
        "administrator": "🛡 Администратор",
        "member": "👤 Участник",
        "restricted": "🔇 Ограничен",
        "left": "🚪 Покинул",
        "kicked": "🚫 Заблокирован",
    }
    status_str = status_icons.get(status, status)

    text = (
        f"📋 <b>ИНФОРМАЦИЯ ОБ ОХОТНИКЕ</b>\n\n"
        f"👤 Имя: {mention_html(user)}\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"📛 Username: @{user.username or 'нет'}\n"
        f"⚙️ Статус: {status_str}\n"
        f"🏆 Ранг: <b>{label}</b>\n"
        f"💬 Сообщений: <b>{db_user.get('messages', 0)}</b>\n"
        f"⚠️ Предупреждений: <b>{db_user.get('warns', 0)}</b>\n"
        f"📅 В чате с: <i>{db_user.get('joined_at', '—')[:10]}</i>"
    )
    await message.answer(text, parse_mode="HTML")


# ── /stats ─────────────────────────────────────────────────────────────────────

@router.message(Command("stats"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_stats(message: Message) -> None:
    rows = await get_chat_stats(message.chat.id, days=7)
    chat = message.chat

    total_msgs = sum(r.get("messages", 0) for r in rows)
    total_deleted = sum(r.get("deleted", 0) for r in rows)
    total_warns = sum(r.get("warns_given", 0) for r in rows)
    total_bans = sum(r.get("bans", 0) for r in rows)

    text = (
        f"📊 <b>СТАТИСТИКА ЧАТА</b>\n"
        f"<i>{escape_html(chat.title)}</i> — последние 7 дней\n\n"
        f"💬 Сообщений: <b>{total_msgs}</b>\n"
        f"🗑 Удалено: <b>{total_deleted}</b>\n"
        f"⚠️ Предупреждений: <b>{total_warns}</b>\n"
        f"🚫 Банов: <b>{total_bans}</b>\n\n"
        f"<i>Система S-Ранг Менеджер следит за порядком 24/7</i>"
    )
    await message.answer(text, parse_mode="HTML")


# ── /rules ─────────────────────────────────────────────────────────────────────

@router.message(Command("rules"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_rules(message: Message) -> None:
    settings = await get_chat_settings(message.chat.id)
    rules = settings.get("rules") or RULES_DEFAULT
    await message.answer(rules, parse_mode="HTML")


# ── /daily — ежедневный бонус (маркетинг: удержание) ────────────────────────────

@router.message(Command("daily"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_daily(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    await get_or_create_user(
        user.id, message.chat.id,
        username=user.username or "", full_name=user.full_name,
    )
    total = await claim_daily(user.id, message.chat.id, DAILY_BONUS)
    if total is None:
        await message.answer(
            DAILY_DONE_MSG.format(mention=mention_html(user)), parse_mode="HTML"
        )
        return

    await _sync_rank(message, user.id, message.chat.id, total)
    rank = calculate_rank(total)
    mana_line = ""
    try:
        mana_bonus = await award_daily(user.id, message.chat.id)
        if mana_bonus:
            mana_line = f"\n⛏ Добыто: <b>{format_mana(mana_bonus)}</b>"
    except Exception:
        pass
    await message.answer(
        DAILY_MSG.format(
            mention=mention_html(user),
            bonus=DAILY_BONUS,
            total=total,
            rank_label=get_rank_label(rank),
        ) + mana_line,
        parse_mode="HTML",
    )


# ── /invite — пригласить друзей (маркетинг: вирусный рост) ──────────────────────

@router.message(Command("invite"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_invite(message: Message, bot: Bot) -> None:
    user = message.from_user
    chat = message.chat

    # Личная именная инвайт-ссылка → позволяет засчитать, кто кого привёл.
    link = None
    try:
        personal = await bot.create_chat_invite_link(
            chat.id, name=f"ref{user.id}"[:32]
        )
        link = personal.invite_link
    except Exception:
        pass

    if not link:
        try:
            full_chat = await bot.get_chat(chat.id)
            if full_chat.username:
                link = f"https://t.me/{full_chat.username}"
            elif full_chat.invite_link:
                link = full_chat.invite_link
        except Exception:
            pass
    if not link:
        try:
            link = await bot.export_chat_invite_link(chat.id)
        except Exception:
            await message.reply(
                "⚠️ Не удалось получить ссылку-приглашение.\n"
                "Дай боту право «Пригласительные ссылки» или сделай чат публичным."
            )
            return

    db_user = await get_or_create_user(
        user.id, chat.id, username=user.username or "", full_name=user.full_name,
    )
    rank = calculate_rank(db_user.get("messages", 0))
    text = INVITE_MSG.format(chat=escape_html(chat.title or "наш чат"), rank=get_rank_label(rank))
    share_text = (
        f"⚔️ Заходи в «{chat.title or 'наш чат'}» — система рангов Solo Leveling, "
        f"топы охотников и ежедневные бонусы!"
    )
    await message.answer(
        text, parse_mode="HTML", reply_markup=invite_keyboard(link, share_text)
    )


# ── /invites — топ пригласивших ─────────────────────────────────────────────────

@router.message(Command("invites"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_invites(message: Message) -> None:
    inviters = await get_top_inviters(message.chat.id, limit=10)
    if not inviters:
        await message.answer(
            "👥 Пока никто не приглашал друзей.\n"
            "Будь первым — отправь /invite и зови охотников в чат!"
        )
        return
    MEDALS = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    lines = ["👥 <b>ТОП ВЕРБОВЩИКОВ ГИЛЬДИИ</b>\n"]
    for i, u in enumerate(inviters):
        name = escape_html(u.get("full_name") or u.get("username") or str(u["user_id"]))
        lines.append(f"{MEDALS[i]} {i+1}. <b>{name}</b> — {u['invited_count']} приглашённых")
    await message.answer("\n".join(lines), parse_mode="HTML")


# ── Helpers ──────────────────────────────────────────────────────────────────────

async def _sync_rank(message: Message, user_id: int, chat_id: int, messages: int) -> None:
    """Update stored rank after a bonus and announce a rank-up if it happened."""
    db_user = await get_or_create_user(user_id, chat_id)
    old_rank = db_user.get("rank", "E")
    new_rank = calculate_rank(messages)
    if new_rank != old_rank:
        await update_user_rank(user_id, chat_id, new_rank)
        try:
            await message.answer(
                RANK_UP_MSG.format(
                    name=mention_html(message.from_user),
                    old_label=get_rank_label(old_rank),
                    new_label=get_rank_label(new_rank),
                    title=get_rank_title(new_rank),
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass


# ── Авто-чистка сервисных сообщений «X присоединился / вышел» ────────────────────

@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.new_chat_members | F.left_chat_member,
)
async def clean_service_messages(message: Message) -> None:
    """
    Удаляет сервисные сообщения о входе/выходе, чтобы чат был чистым.
    Бот сам наводит порядок вместо админов. Управляется настройкой
    `delete_service_msgs` (по умолчанию включено). Идёт в user_router,
    который проверяется раньше moderation_router, поэтому модерация это
    сообщение уже не увидит (и не начислит за него руду).
    """
    settings = await get_chat_settings(message.chat.id)
    if not settings.get("delete_service_msgs", 1):
        return
    try:
        await message.delete()
    except Exception:
        pass


# ── Кнопка «Правила» в приветствии ───────────────────────────────────────────────

@router.callback_query(F.data == "welcome:rules")
async def cb_welcome_rules(call: CallbackQuery) -> None:
    settings = await get_chat_settings(call.message.chat.id)
    rules = settings.get("rules") or RULES_DEFAULT
    try:
        await call.answer()
        notify = await call.message.answer(rules, parse_mode="HTML")
        await asyncio.sleep(30)
        await notify.delete()
    except Exception:
        pass


# ── Welcome new members ────────────────────────────────────────────────────────

@router.chat_member(ChatMemberUpdatedFilter(JOIN_TRANSITION))
async def on_new_member(event: ChatMemberUpdated) -> None:
    user = event.new_chat_member.user
    if user.is_bot:
        return

    await set_chat_title(event.chat.id, event.chat.title or "")
    db_user = await get_or_create_user(
        user.id, event.chat.id,
        username=user.username or "",
        full_name=user.full_name,
    )
    settings = await get_chat_settings(event.chat.id)
    rank = calculate_rank(db_user.get("messages", 0))
    rank_label = get_rank_label(rank)

    welcome = settings.get("welcome_msg") or WELCOME_DEFAULT
    text = safe_format(
        welcome,
        mention=mention_html(user),
        name=escape_html(user.full_name),
        username=escape_html(f"@{user.username}" if user.username else user.full_name),
        rank_label=rank_label,
        chat=escape_html(event.chat.title or ""),
    )
    try:
        bot_username = get_config().bot_username
        await event.answer(
            text,
            parse_mode="HTML",
            reply_markup=welcome_keyboard(bot_username) if bot_username else None,
        )
    except Exception:
        pass

    # ── Реферальная атрибуция: кто привёл нового участника ──────────────────────
    inviter_id = None
    inviter_name = ""
    source = "chat_join"

    # 1) Если зашёл по личной именной ссылке (ref<id>) — берём оттуда.
    inv_link = getattr(event, "invite_link", None)
    if inv_link and inv_link.name and inv_link.name.startswith("ref"):
        rest = inv_link.name[3:]
        if rest.isdigit():
            inviter_id = int(rest)
            source = "invite_link"

    # 2) Иначе — тот, кто добавил участника напрямую.
    if inviter_id is None and event.from_user and not event.from_user.is_bot:
        if event.from_user.id != user.id:
            inviter_id = event.from_user.id
            inviter_name = event.from_user.full_name

    if inviter_id and inviter_id != user.id:
        await get_or_create_user(inviter_id, event.chat.id, full_name=inviter_name)
        try:
            count = await register_chat_referral(
                event.bot, inviter_id, user.id, event.chat.id,
                inviter_name=inviter_name, source=source,
            )
        except Exception:
            count = None
        if count is not None:
            try:
                from utils import mention_html_raw
                await event.answer(
                    INVITE_JOIN_MSG.format(
                        mention=mention_html_raw(inviter_id, inviter_name or "Охотник"),
                        bonus=INVITE_BONUS,
                        count=count,
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass
