"""
Auto-moderation handler: watches every message, deletes violations,
issues warnings and automatically escalates to mute/ban.
"""
from aiogram import Router, F, Bot
from aiogram.types import Message, ChatPermissions
from datetime import datetime, timedelta
from loguru import logger

from database import (
    get_chat_settings, get_or_create_user, increment_messages,
    add_warn, mute_user, ban_user,
    get_blacklist_words, increment_stat,
)
from filters import analyze_message, flood_tracker
from services import award_message
from utils import (
    WARN_MSG, MUTE_AUTO_MSG, BAN_AUTO_MSG,
    DELETE_NOTIFY, FLOOD_WARN, VIOLATION_REASONS,
    mention_html, is_owner,
)

router = Router()
BOT_USER_ID: int = 0  # filled on startup


def set_bot_id(bot_id: int) -> None:
    global BOT_USER_ID
    BOT_USER_ID = bot_id


async def _apply_mute(bot: Bot, chat_id: int, user_id: int, minutes: int) -> None:
    until = datetime.utcnow() + timedelta(minutes=minutes)
    await bot.restrict_chat_member(
        chat_id=chat_id,
        user_id=user_id,
        permissions=ChatPermissions(can_send_messages=False),
        until_date=until,
    )
    await mute_user(user_id, chat_id, minutes)


async def _apply_ban(bot: Bot, chat_id: int, user_id: int) -> None:
    await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)


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
                import asyncio
                await asyncio.sleep(10)
                await notify.delete()
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
    violations = analyze_message(text, blacklist, settings)

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
            import asyncio
            await asyncio.sleep(15)
            await notify.delete()
        except Exception:
            pass

        logger.info(
            f"[MOD] {user.id} @{user.username} in {message.chat.id} | {vtype}: {matched}"
        )
        return

    # ── Update message count & rank ───────────────────────────────────────────
    await _update_rank(message, user.id, message.chat.id, bot)


async def _update_rank(message: Message, user_id: int, chat_id: int, bot: Bot) -> None:
    # Сообщения копят активность и дают руду за чат (с кулдауном). Ранг теперь
    # зависит НЕ от сообщений, а от числа выполненных заданий (см. services/ranks.py).
    await increment_messages(user_id, chat_id)
    try:
        await award_message(user_id, chat_id)
    except Exception:
        pass
