"""
Auto-moderation handler: watches every message, deletes violations,
issues warnings and automatically escalates to mute/ban.
"""
from aiogram import Router, F, Bot
from aiogram.types import Message
from datetime import datetime, timedelta
from loguru import logger

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
    DELETE_NOTIFY, FLOOD_WARN, VIOLATION_REASONS,
    mention_html, is_owner,
)
from utils.tg_safe import safe_mute, safe_ban, delete_later


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
        reason = VIOLATION_REASONS.get(vtype, vtype)

        try:
            await message.delete()
            await increment_stat(message.chat.id, "deleted")
        except Exception:
            pass

        warns = await add_warn(user.id, message.chat.id, BOT_USER_ID, reason)
        warn_limit = settings.get("warn_limit", 3)
        ban_limit = warn_limit + 2

        # Decide escalation
        extra = ""
        if warns >= ban_limit:
            await _apply_ban(bot, message.chat.id, user.id)
            await ban_user(user.id, message.chat.id, BOT_USER_ID, reason)
            text_msg = BAN_AUTO_MSG.format(mention=mention_html(user), warns=warns)
        elif warns >= warn_limit:
            mute_min = settings.get("mute_time", 60)
            await _apply_mute(bot, message.chat.id, user.id, mute_min)
            text_msg = MUTE_AUTO_MSG.format(
                mention=mention_html(user),
                warns=warns,
                minutes=mute_min,
            )
        else:
            remaining = warn_limit - warns
            extra = f"Ещё {remaining} предупреждений — мут!"
            text_msg = WARN_MSG.format(
                mention=mention_html(user),
                reason=reason,
                warns=warns,
                limit=warn_limit,
                extra=extra,
            )

        try:
            notify = await message.answer(text_msg, parse_mode="HTML")
            delete_later(notify, 15)
        except Exception:
            pass

        logger.info(
            f"[MOD] {user.id} @{user.username} in {message.chat.id} | {vtype}: {matched}"
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
    reason = VIOLATION_REASONS.get(vtype, vtype)
    try:
        await message.delete()
        await increment_stat(message.chat.id, "deleted")
    except Exception:
        pass

    warns = await add_warn(user.id, message.chat.id, BOT_USER_ID, reason)
    warn_limit = settings.get("warn_limit", 3)
    ban_limit = warn_limit + 2
    if warns >= ban_limit:
        await _apply_ban(bot, message.chat.id, user.id)
        await ban_user(user.id, message.chat.id, BOT_USER_ID, reason)
        text_msg = BAN_AUTO_MSG.format(mention=mention_html(user), warns=warns)
    elif warns >= warn_limit:
        mute_min = settings.get("mute_time", 60)
        await _apply_mute(bot, message.chat.id, user.id, mute_min)
        text_msg = MUTE_AUTO_MSG.format(
            mention=mention_html(user), warns=warns, minutes=mute_min,
        )
    else:
        remaining = warn_limit - warns
        text_msg = WARN_MSG.format(
            mention=mention_html(user), reason=reason, warns=warns,
            limit=warn_limit, extra=f"Ещё {remaining} предупреждений — мут!",
        )
    try:
        notify = await message.answer(text_msg, parse_mode="HTML")
        delete_later(notify, 15)
    except Exception:
        pass
    logger.info(f"[MOD-EDIT] {user.id} in {message.chat.id} | {vtype}: {matched}")


async def _update_rank(message: Message, user_id: int, chat_id: int, bot: Bot) -> None:
    # Сообщения копят активность и дают руду за чат (с кулдауном). Ранг теперь
    # зависит НЕ от сообщений, а от числа выполненных заданий (см. services/ranks.py).
    await increment_messages(user_id, chat_id)
    try:
        await award_message(user_id, chat_id)
    except Exception:
        pass
