"""
User-facing commands: /rank /top /stats /info /help /ping /id
"""
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, ChatMemberUpdated
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter, JOIN_TRANSITION

from database import (
    get_or_create_user, get_chat_settings, set_chat_title,
    get_top_users, get_chat_stats, claim_daily, credit_invite,
    get_top_inviters, update_user_rank,
)
from keyboards import invite_keyboard
from utils import (
    calculate_rank, get_rank_label, get_rank_title,
    messages_to_next_rank, rank_progress_bar,
    mention_html, WELCOME_DEFAULT, HELP_MSG, START_MSG, BOTFATHER_COMMANDS,
    INVITE_MSG, DAILY_MSG, DAILY_DONE_MSG, RULES_DEFAULT, INVITE_JOIN_MSG,
    RANK_UP_MSG,
)

router = Router()

DAILY_BONUS = 15
INVITE_BONUS = 30


# ── /start ────────────────────────────────────────────────────────────────────

@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    try:
        await message.answer(START_MSG, parse_mode="HTML")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


# ── /help ──────────────────────────────────────────────────────────────────────

@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    try:
        await message.answer(HELP_MSG, parse_mode="HTML")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


# ── /commands — список команд для BotFather ────────────────────────────────────

@router.message(Command("commands"))
async def cmd_commands(message: Message) -> None:
    try:
        await message.answer(BOTFATHER_COMMANDS, parse_mode="HTML")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


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
        name = u.get("full_name") or u.get("username") or str(u["user_id"])
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
        f"<i>{chat.title}</i> — последние 7 дней\n\n"
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
    await message.answer(
        DAILY_MSG.format(
            mention=mention_html(user),
            bonus=DAILY_BONUS,
            total=total,
            rank_label=get_rank_label(rank),
        ),
        parse_mode="HTML",
    )


# ── /invite — пригласить друзей (маркетинг: вирусный рост) ──────────────────────

@router.message(Command("invite"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_invite(message: Message, bot: Bot) -> None:
    user = message.from_user
    chat = message.chat

    link = None
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
    text = INVITE_MSG.format(chat=chat.title or "наш чат", rank=get_rank_label(rank))
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
        name = u.get("full_name") or u.get("username") or str(u["user_id"])
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
    text = welcome.format(
        mention=mention_html(user),
        name=user.full_name,
        username=f"@{user.username}" if user.username else user.full_name,
        rank_label=rank_label,
        chat=event.chat.title or "",
    )
    try:
        await event.answer(text, parse_mode="HTML")
    except Exception:
        pass

    # ── Реферальная награда: кто-то привёл нового участника ──────────────────────
    inviter = event.from_user
    if inviter and not inviter.is_bot and inviter.id != user.id:
        await get_or_create_user(
            inviter.id, event.chat.id,
            username=inviter.username or "", full_name=inviter.full_name,
        )
        count = await credit_invite(inviter.id, event.chat.id, INVITE_BONUS)
        try:
            await event.answer(
                INVITE_JOIN_MSG.format(
                    mention=mention_html(inviter),
                    bonus=INVITE_BONUS,
                    count=count,
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass
