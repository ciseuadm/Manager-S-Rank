"""
User-facing commands: /rank /top /stats /info /help /ping /id
"""
import asyncio

from loguru import logger
from aiogram import Router, F, Bot
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, ChatMemberUpdated, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter, JOIN_TRANSITION

from database import (
    get_or_create_user, get_chat_settings, set_chat_title,
    get_top_users, get_chat_stats, claim_daily,
    get_top_inviters, get_wallet_rank,
)
from keyboards import invite_keyboard, welcome_keyboard
from services import (
    award_daily, register_bot_referral, register_chat_referral,
    claim_dungeon_reward, balance_of, rank_card,
)
from utils import (
    get_rank_label,
    mention_html, escape_html, safe_format,
    WELCOME_DEFAULT, HELP_MSG, START_MSG, BOTFATHER_COMMANDS,
    INVITE_MSG, DAILY_MSG, DAILY_DONE_MSG, RULES_DEFAULT, INVITE_JOIN_MSG,
    DUNGEON_AD_HINT, DUNGEON_CLAIMED_MSG, DUNGEON_TOPUP_MSG, DUNGEON_DONE_MSG,
    DUNGEON_MILESTONE_MSG, DUNGEON_PRIVATE_MSG,
    EARN_MSG, format_mana, get_config,
)
from utils.media import answer_with_banner

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
    if payload == "earn":
        banner, text = "earn", EARN_MSG
    else:
        banner, text = "start", START_MSG
    try:
        await answer_with_banner(message, banner, text)
    except Exception as e:
        logger.warning(f"[START] send failed: {e}")


# ── /help ──────────────────────────────────────────────────────────────────────

@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    try:
        await answer_with_banner(message, "help", HELP_MSG)
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
    card = await rank_card(user.id)

    next_line = (
        f"\n🔜 До следующего ранга: <b>{card['xp_to_next']}</b> опыта"
        if card["xp_to_next"] is not None else "\n👑 <b>МАКСИМАЛЬНЫЙ РАНГ ДОСТИГНУТ!</b>"
    )

    text = (
        f"⚡ <b>КАРТОЧКА ОХОТНИКА</b>\n\n"
        f"👤 {mention_html(user)}\n"
        f"🏆 Ранг: <b>{card['label']}</b>\n"
        f"🎖 Звание: <i>{card['title']}</i>\n"
        f"⭐ Опыт: <b>{card['xp']}</b>\n"
        f"💬 Сообщений: <b>{msgs}</b>\n"
        f"⚠️ Предупреждений: <b>{db_user.get('warns', 0)}</b>\n\n"
        f"📊 Прогресс ранга: {card['progress']}{next_line}\n"
        f"<i>Опыт даётся за задания (/tasks) — 100 за подписку — и за подземелье "
        f"(/dungeon, +руда = +опыт). Трата руды на подарки опыт не уменьшает.</i>"
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
        # Ранг глобальный (по заданиям), активность чата — по сообщениям.
        label = get_rank_label(await get_wallet_rank(u["user_id"]))
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

    label = get_rank_label(await get_wallet_rank(user.id))

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
    await answer_with_banner(message, "rules", rules)


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

    card = await rank_card(user.id)
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
            rank_label=card["label"],
        ) + mana_line,
        parse_mode="HTML",
    )


# ── /dungeon — ежедневное подземелье (бесплатная руда + реклама в профиле) ──────

def _dungeon_text(user, status: str, base: int, ad: int, has_ad: bool,
                  balance: int, streak: int = 0, milestone_bonus: int = 0) -> str:
    cfg = get_config()
    full = cfg.daily_dungeon_base + cfg.daily_dungeon_ad_bonus
    bot_tag = f"@{cfg.bot_username}" if cfg.bot_username else "@этого_бота"

    if status == "topup":
        return DUNGEON_TOPUP_MSG.format(ad=ad, balance=format_mana(balance), full=full)

    if status == "claimed":
        total = base + ad
        ad_line = f" (база {base} + реклама {ad})" if ad else ""
        text = DUNGEON_CLAIMED_MSG.format(
            mention=mention_html(user), total=total, ad_line=ad_line,
            balance=format_mana(balance), streak=streak,
        )
    else:  # already
        text = DUNGEON_DONE_MSG.format(balance=format_mana(balance), streak=streak)

    if milestone_bonus:
        text += DUNGEON_MILESTONE_MSG.format(bonus=format_mana(milestone_bonus))
    if not has_ad:
        text += "\n" + DUNGEON_AD_HINT.format(
            full=full, ad=cfg.daily_dungeon_ad_bonus, bot=bot_tag
        )
    return text


def _dungeon_keyboard(owner_id: int, has_ad: bool):
    b = InlineKeyboardBuilder()
    if not has_ad:
        b.row(InlineKeyboardButton(
            text="🔍 Я добавил рекламу — проверить",
            callback_data=f"dungeon:check:{owner_id}",
        ))
    b.row(InlineKeyboardButton(
        text="⚔️ Задания (+100 руды за подписку)",
        callback_data="task:list",
    ))
    return b.as_markup()


@router.message(Command("dungeon", "raid", "подземелье"))
async def cmd_dungeon(message: Message, bot: Bot) -> None:
    user = message.from_user
    if not user:
        return
    # Только в чатах: команды и награды видят другие → бесплатная реклама бота.
    if message.chat.type not in ("group", "supergroup"):
        await message.answer(
            DUNGEON_PRIVATE_MSG, parse_mode="HTML", disable_web_page_preview=True
        )
        return
    status, base, ad, has_ad, streak, milestone = await claim_dungeon_reward(
        bot, user.id, message.chat.id
    )
    balance = await balance_of(user.id)
    await message.answer(
        _dungeon_text(user, status, base, ad, has_ad, balance, streak, milestone),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=_dungeon_keyboard(user.id, has_ad),
    )


@router.callback_query(F.data.startswith("dungeon:check:"))
async def cb_dungeon_check(call: CallbackQuery, bot: Bot) -> None:
    parts = call.data.split(":")
    owner_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    if owner_id and call.from_user.id != owner_id:
        await call.answer(
            "Это чужое подземелье. Отправь свою команду /dungeon 🏰", show_alert=True
        )
        return

    chat_id = call.message.chat.id if call.message else 0
    status, base, ad, has_ad, streak, milestone = await claim_dungeon_reward(
        bot, call.from_user.id, chat_id
    )
    balance = await balance_of(call.from_user.id)

    if status == "topup":
        await call.answer(f"✨ Реклама засчитана! +{ad} руды добавлено.", show_alert=True)
    elif status == "claimed":
        await call.answer(f"🏰 Подземелье пройдено! +{base + ad} руды.", show_alert=True)
    elif has_ad:
        await call.answer("Сегодня всё собрано ✅ Возвращайся завтра.", show_alert=True)
    else:
        await call.answer(
            "Реклама в профиле не найдена. Добавь упоминание бота в «О себе» "
            "и нажми кнопку снова.",
            show_alert=True,
        )

    if call.message:
        try:
            await call.message.edit_text(
                _dungeon_text(call.from_user, status, base, ad, has_ad,
                              balance, streak, milestone),
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=_dungeon_keyboard(call.from_user.id, has_ad),
            )
        except Exception:
            pass


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
    rank_label = get_rank_label(await get_wallet_rank(user.id))
    text = INVITE_MSG.format(chat=escape_html(chat.title or "наш чат"), rank=rank_label)
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
        notify = await answer_with_banner(call.message, "rules", rules)
        if notify:
            await asyncio.sleep(30)
            try:
                await notify.delete()
            except Exception:
                pass
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
    rank_label = get_rank_label(await get_wallet_rank(user.id))

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
