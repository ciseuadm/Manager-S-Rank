"""
Auto-moderation handler: watches every message, deletes violations,
issues warnings and automatically escalates to mute/ban.
"""
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message
from datetime import datetime, timedelta
from loguru import logger
import time as _time

from database import (
    get_chat_settings, get_or_create_user, increment_messages,
    add_warn, mute_user, ban_user,
    get_blacklist_words, increment_stat, get_whitelist_words,
)
from filters import analyze_message, flood_tracker
from services import award_message
from services.triggers import match_trigger
from utils import (
    WARN_MSG, MUTE_AUTO_MSG, BAN_AUTO_MSG,
    DELETE_SOFT_MSG, REVEAL_LINE, REVEAL_MEDIA_LINE,
    FLOOD_WARN, VIOLATION_REASONS,
    mention_html, is_owner, escape_html,
)
from utils.tg_safe import safe_mute, safe_ban, delete_later


def _media_kind(message: Message) -> str:
    """Человекочитаемый тип медиа (для спойлера, когда текста нет)."""
    if message.sticker:
        return "стикер"
    if message.photo:
        return "фото"
    if message.video or message.video_note:
        return "видео"
    if message.animation:
        return "GIF-анимация"
    if message.voice:
        return "голосовое"
    if message.document:
        return "документ"
    return "вложение"


def _build_reveal(content: str, media_kind: str = "") -> str:
    """Строка-спойлер с самим нарушением (метка видна, текст скрыт под тап)."""
    text = (content or "").strip()
    if text:
        return REVEAL_LINE.format(content=escape_html(text[:300]))
    if media_kind:
        return REVEAL_MEDIA_LINE.format(kind=escape_html(media_kind))
    return ""


async def _handle_violation(
    bot: Bot, message: Message, user, settings: dict,
    vtype: str, matched: str, content: str, media_kind: str = "",
    *, source: str = "auto",
) -> None:
    """
    Единая мягкая реакция на нарушение: удалить сообщение, показать его под
    спойлером и эскалировать по-доброму.

    Эскалация (бот — «солдат, а не палач», наказания в крайнем случае):
      • первые `soft_grace` нарушений — только удаление + вежливая просьба;
      • далее — предупреждения со счётчиком;
      • мут — при warns >= soft_grace + warn_limit;
      • бан — очень редко: warns >= mute_threshold + 4.
    """
    reason = VIOLATION_REASONS.get(vtype, vtype)
    try:
        await message.delete()
        await increment_stat(message.chat.id, "deleted")
    except Exception:
        pass

    warns = await add_warn(user.id, message.chat.id, BOT_USER_ID, reason)
    grace = int(settings.get("soft_grace", 2) or 0)
    warn_limit = int(settings.get("warn_limit", 3) or 3)
    mute_threshold = grace + warn_limit
    ban_threshold = mute_threshold + 4
    reveal = _build_reveal(content, media_kind)

    if warns >= ban_threshold:
        await _apply_ban(bot, message.chat.id, user.id)
        await ban_user(user.id, message.chat.id, BOT_USER_ID, reason)
        text_msg = BAN_AUTO_MSG.format(mention=mention_html(user), warns=warns) + "\n" + reveal
    elif warns >= mute_threshold:
        mute_min = settings.get("mute_time", 60)
        await _apply_mute(bot, message.chat.id, user.id, mute_min)
        text_msg = MUTE_AUTO_MSG.format(
            mention=mention_html(user), warns=warns, minutes=mute_min,
        ) + "\n" + reveal
    elif warns <= grace:
        text_msg = DELETE_SOFT_MSG.format(
            mention=mention_html(user), reason=reason, reveal=reveal,
        )
    else:
        remaining = mute_threshold - warns
        text_msg = WARN_MSG.format(
            mention=mention_html(user), reason=reason, warns=warns,
            limit=mute_threshold,
            extra=f"Ещё {remaining} — и Система заглушит тебя.",
        ) + "\n" + reveal

    try:
        notify = await message.answer(text_msg, parse_mode="HTML")
        delete_later(notify, 20)
    except Exception:
        pass
    logger.info(
        f"[MOD:{source}] {user.id} @{user.username} in {message.chat.id} | {vtype}: {matched}"
    )


def _night_active(settings: dict) -> bool:
    """Активен ли ночной режим сейчас (по UTC-часу окна [start, end))."""
    if not settings.get("night_mode", 0):
        return False
    start = int(settings.get("night_start", 23) or 0)
    end = int(settings.get("night_end", 7) or 0)
    hour = datetime.utcnow().hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # окно через полночь


_night_notified: dict[int, float] = {}

router = Router()
BOT_USER_ID: int = 0  # filled on startup


def set_bot_id(bot_id: int) -> None:
    global BOT_USER_ID
    BOT_USER_ID = bot_id


async def _apply_mute(bot: Bot, chat_id: int, user_id: int, minutes: int) -> None:
    until = datetime.utcnow() + timedelta(minutes=minutes)
    await safe_mute(bot, chat_id, user_id, until_date=until)
    await mute_user(user_id, chat_id, minutes)


async def _apply_ban(bot: Bot, chat_id: int, user_id: int) -> None:
    await safe_ban(bot, chat_id, user_id)


# ── Жалоба от обычного участника ─────────────────────────────────────────────
# Даже постоянная модерация не ловит 100% маскировки. Любой участник может
# отметить сообщение командой /report (ответом) — Система тут же перепроверит.
_report_cooldown: dict[tuple[int, int], float] = {}
_REPORT_COOLDOWN_SEC = 20


@router.message(Command("report", "жалоба", "репорт"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_report(message: Message, bot: Bot) -> None:
    reporter = message.from_user
    if not reporter or reporter.is_bot:
        return

    reply = message.reply_to_message
    # Команду-обращение убираем из чата, чтобы не мусорить.
    async def _cleanup() -> None:
        try:
            await message.delete()
        except Exception:
            pass

    if not reply or not reply.from_user:
        warn = await message.reply(
            "🛡 <b>Жалоба Системе</b>\n\n"
            "Ответь этой командой (<code>/report</code>) на сообщение-нарушение — "
            "и я тут же его перепроверю.",
            parse_mode="HTML",
        )
        delete_later(warn, 12)
        await _cleanup()
        return

    # Анти-абуз: кулдаун на жалобы от одного охотника в чате.
    key = (message.chat.id, reporter.id)
    now = _time.monotonic()
    if now - _report_cooldown.get(key, 0.0) < _REPORT_COOLDOWN_SEC:
        await _cleanup()
        return
    _report_cooldown[key] = now

    target = reply.from_user
    # На бота и на самого себя жаловаться смысла нет.
    if target.is_bot or target.id == reporter.id:
        await _cleanup()
        return

    # Владельца и админов модерация не трогает (правило проекта).
    if is_owner(target.id):
        note = await message.reply("👑 На Монарха жаловаться бесполезно, охотник.")
        delete_later(note, 8)
        await _cleanup()
        return
    try:
        member = await bot.get_chat_member(message.chat.id, target.id)
        if member.status in ("administrator", "creator"):
            note = await message.reply(
                "🛡 Это администратор гильдии — он вне моей юрисдикции. "
                "Если нужно, реши вопрос с другими админами."
            )
            delete_later(note, 10)
            await _cleanup()
            return
    except Exception:
        pass

    settings = await get_chat_settings(message.chat.id)
    content = reply.text or reply.caption or ""
    blacklist = await get_blacklist_words(message.chat.id)
    whitelist = await get_whitelist_words(message.chat.id)
    violations = analyze_message(content, blacklist, settings, whitelist)

    if violations:
        vtype, matched = violations[0]
        # Караем автора отмеченного сообщения тем же мягким механизмом.
        await _handle_violation(
            bot, reply, target, settings, vtype, matched, content, source="report",
        )
        thanks = await message.answer(
            f"✅ <b>Спасибо, {mention_html(reporter)}!</b> Система проверила сигнал "
            "и приняла меры. Гильдия под защитой.",
            parse_mode="HTML",
        )
        delete_later(thanks, 12)
        await _cleanup()
        return

    # Текст чист (или нарушение в медиа, которое бот не распознаёт) — зовём админов.
    kind = _media_kind(reply) if not content else ""
    admin_mentions = await _admin_mentions(bot, message.chat.id, exclude=target.id)
    extra = f"\n{admin_mentions}" if admin_mentions else ""
    body = (
        "🔍 <b>Сигнал принят.</b>\n\n"
        "В тексте я не нашёл явных нарушений"
        + (f" — возможно, оно скрыто в медиа ({escape_html(kind)})." if kind else ".")
        + " Призываю администраторов на ручную проверку."
        + extra
    )
    note = await message.answer(body, parse_mode="HTML")
    delete_later(note, 30)
    await _cleanup()


async def _admin_mentions(bot: Bot, chat_id: int, exclude: int = 0, limit: int = 3) -> str:
    """HTML-упоминания нескольких админов чата (для призыва на ручную проверку)."""
    try:
        admins = await bot.get_chat_administrators(chat_id)
    except Exception:
        return ""
    out: list[str] = []
    for a in admins:
        u = getattr(a, "user", None)
        if not u or u.is_bot or u.id == exclude:
            continue
        out.append(mention_html(u))
        if len(out) >= limit:
            break
    return "👮 " + ", ".join(out) if out else ""


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def on_group_message(message: Message, bot: Bot) -> None:
    user = message.from_user
    if not user or user.is_bot:
        return

    # Owner is never moderated, but still earns rank
    if is_owner(user.id):
        await _update_rank(message, user.id, message.chat.id, bot)
        return

    # Skip admins/creators
    try:
        member = await bot.get_chat_member(message.chat.id, user.id)
        if member.status in ("administrator", "creator"):
            # Still count messages and update rank
            await _update_rank(message, user.id, message.chat.id, bot)
            return
    except Exception:
        pass

    settings = await get_chat_settings(message.chat.id)
    db_user = await get_or_create_user(
        user.id, message.chat.id,
        username=user.username or "",
        full_name=user.full_name,
    )

    # ── Ночной режим: чат «спит», сообщения не-админов удаляются ────────────────
    if _night_active(settings):
        try:
            await message.delete()
            await increment_stat(message.chat.id, "deleted")
        except Exception:
            pass
        import time as _t
        now = _t.monotonic()
        if now - _night_notified.get(message.chat.id, 0.0) > 600:
            _night_notified[message.chat.id] = now
            try:
                notify = await message.answer(
                    "🌙 <b>Ночной режим Системы.</b> Подземелье спит — "
                    "сообщения принимаются только от админов. Утром продолжим, охотник.",
                    parse_mode="HTML",
                )
                delete_later(notify, 15)
            except Exception:
                pass
        return

    # ── Блокировка пересланных сообщений (анти-реклама) ─────────────────────────
    if settings.get("block_forwards", 0) and (
        getattr(message, "forward_origin", None) or message.forward_date
    ):
        try:
            await message.delete()
            await increment_stat(message.chat.id, "deleted")
        except Exception:
            pass
        return

    # ── Anti-flood ────────────────────────────────────────────────────────────
    if settings.get("antiflood", 1):
        if flood_tracker.is_flood(user.id, message.chat.id):
            try:
                await message.delete()
            except Exception:
                pass
            mute_min = settings.get("mute_time", 60)
            await _apply_mute(bot, message.chat.id, user.id, mute_min)
            await increment_stat(message.chat.id, "deleted")
            try:
                notify = await message.answer(
                    FLOOD_WARN.format(mention=mention_html(user), minutes=mute_min),
                    parse_mode="HTML",
                )
                delete_later(notify, 10)
            except Exception:
                pass
            return

    # ── Sticker filter ────────────────────────────────────────────────────────
    if settings.get("filter_stickers", 0) and message.sticker:
        try:
            await message.delete()
            await increment_stat(message.chat.id, "deleted")
        except Exception:
            pass
        return

    # ── Content analysis ──────────────────────────────────────────────────────
    text = message.text or message.caption or ""
    blacklist = await get_blacklist_words(message.chat.id)
    whitelist = await get_whitelist_words(message.chat.id)
    violations = analyze_message(text, blacklist, settings, whitelist)

    if violations:
        vtype, matched = violations[0]
        await _handle_violation(
            bot, message, user, settings, vtype, matched, text, source="auto",
        )
        return

    # ── Update message count & rank ───────────────────────────────────────────
    await _update_rank(message, user.id, message.chat.id, bot)

    # ── Триггеры/кастом-команды: бот сам отвечает на слово/фразу ────────────────
    if text:
        try:
            response = await match_trigger(message.chat.id, text)
            if response:
                await message.reply(response, parse_mode="HTML",
                                    disable_web_page_preview=True)
        except Exception:
            pass


# ── Модерация отредактированных сообщений ────────────────────────────────────
# Нарушитель может отправить чистый текст и затем вписать в него мат/ссылку/инвайт.
# Проверяем правки тем же контент-анализом (без флуда/начисления руды).

@router.edited_message(F.chat.type.in_({"group", "supergroup"}))
async def on_group_edited(message: Message, bot: Bot) -> None:
    user = message.from_user
    if not user or user.is_bot or is_owner(user.id):
        return
    try:
        member = await bot.get_chat_member(message.chat.id, user.id)
        if member.status in ("administrator", "creator"):
            return
    except Exception:
        pass

    settings = await get_chat_settings(message.chat.id)
    text = message.text or message.caption or ""
    blacklist = await get_blacklist_words(message.chat.id)
    whitelist = await get_whitelist_words(message.chat.id)
    violations = analyze_message(text, blacklist, settings, whitelist)
    if not violations:
        return

    vtype, matched = violations[0]
    await _handle_violation(
        bot, message, user, settings, vtype, matched, text, source="edit",
    )


async def _update_rank(message: Message, user_id: int, chat_id: int, bot: Bot) -> None:
    # Сообщения копят активность и дают руду за чат (с кулдауном). Ранг теперь
    # зависит НЕ от сообщений, а от числа выполненных заданий (см. services/ranks.py).
    await increment_messages(user_id, chat_id)
    try:
        await award_message(user_id, chat_id)
    except Exception:
        pass
