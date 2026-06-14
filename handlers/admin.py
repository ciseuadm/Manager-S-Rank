"""
Admin commands: /warn /unwarn /warns /mute /unmute /ban /unban /kick /del
"""
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, ChatPermissions
from datetime import datetime, timedelta
from loguru import logger

from database import (
    get_or_create_user, add_warn, remove_warn, reset_warns,
    get_warn_history, mute_user, unmute_user, ban_user, unban_user,
    get_chat_settings,
)
from utils import parse_time_arg, require_admin, WARN_MSG

router = Router()


def _is_admin_status(status: str) -> bool:
    return status in ("administrator", "creator")


async def _check_admin(message: Message, bot: Bot) -> bool:
    return await require_admin(message, bot)


async def _check_staff(message: Message, bot: Bot) -> bool:
    """Soft moderation: Telegram admins + in-bot moderators (referral-earned)."""
    return await require_admin(message, bot, allow_staff=True)


async def _resolve_target(message: Message) -> tuple[int, str] | None:
    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        return u.id, u.full_name
    args = (message.text or "").split()
    if len(args) >= 2:
        arg = args[1]
        if arg.lstrip("-").isdigit():
            return int(arg), arg
    return None


# ── /warn ──────────────────────────────────────────────────────────────────────

@router.message(Command("warn"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_warn(message: Message, bot: Bot) -> None:
    if not await _check_staff(message, bot):
        return

    target = await _resolve_target(message)
    if not target:
        await message.reply("↩️ Ответь на сообщение нарушителя или укажи ID.")
        return

    user_id, name = target
    args = (message.text or "").split(maxsplit=2)
    reason = args[2] if len(args) >= 3 else "Нарушение правил"

    try:
        victim = await bot.get_chat_member(message.chat.id, user_id)
        if _is_admin_status(victim.status):
            await message.reply("❌ Нельзя предупреждать администраторов.")
            return
        name = victim.user.full_name
    except Exception:
        pass

    settings = await get_chat_settings(message.chat.id)
    admin_id = message.from_user.id

    await get_or_create_user(user_id, message.chat.id, full_name=name)
    warns = await add_warn(user_id, message.chat.id, admin_id, reason)
    warn_limit = settings.get("warn_limit", 3)
    ban_limit = warn_limit + 2

    mention = f'<a href="tg://user?id={user_id}">{name}</a>'

    if warns >= ban_limit:
        await bot.ban_chat_member(message.chat.id, user_id)
        await ban_user(user_id, message.chat.id, admin_id, reason)
        await message.answer(
            f"🚫 <b>{mention}</b> забанен после {warns} предупреждений.",
            parse_mode="HTML",
        )
    elif warns >= warn_limit:
        mute_min = settings.get("mute_time", 60)
        until = datetime.utcnow() + timedelta(minutes=mute_min)
        await bot.restrict_chat_member(
            message.chat.id, user_id,
            ChatPermissions(can_send_messages=False),
            until_date=until,
        )
        await mute_user(user_id, message.chat.id, mute_min)
        await message.answer(
            f"🔇 <b>{mention}</b> заглушён на {mute_min} мин. ({warns} предупреждений).",
            parse_mode="HTML",
        )
    else:
        remaining = warn_limit - warns
        await message.answer(
            WARN_MSG.format(
                mention=mention,
                reason=reason,
                warns=warns,
                limit=warn_limit,
                extra=f"Ещё <b>{remaining}</b> предупреждений — мут!",
            ),
            parse_mode="HTML",
        )


# ── /unwarn ────────────────────────────────────────────────────────────────────

@router.message(Command("unwarn"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_unwarn(message: Message, bot: Bot) -> None:
    if not await _check_admin(message, bot):
        return
    target = await _resolve_target(message)
    if not target:
        await message.reply("↩️ Ответь на сообщение пользователя.")
        return
    user_id, name = target
    warns = await remove_warn(user_id, message.chat.id)
    mention = f'<a href="tg://user?id={user_id}">{name}</a>'
    await message.answer(
        f"✅ Одно предупреждение снято с {mention}. Осталось: <b>{warns}</b>",
        parse_mode="HTML",
    )


# ── /warns ─────────────────────────────────────────────────────────────────────

@router.message(Command("warns"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_warns(message: Message, bot: Bot) -> None:
    target = await _resolve_target(message)
    if not target:
        if message.from_user:
            target = (message.from_user.id, message.from_user.full_name)
        else:
            return

    user_id, name = target
    db_user = await get_or_create_user(user_id, message.chat.id, full_name=name)
    history = await get_warn_history(user_id, message.chat.id)
    mention = f'<a href="tg://user?id={user_id}">{name}</a>'

    text = f"📋 <b>Предупреждения</b> {mention}\n\nВсего: <b>{db_user['warns']}</b>\n\n"
    if history:
        for i, w in enumerate(history[:5], 1):
            text += f"{i}. {w['reason']} — <i>{w['created_at'][:10]}</i>\n"
    else:
        text += "<i>Предупреждений не найдено</i>"

    await message.answer(text, parse_mode="HTML")


# ── /mute ──────────────────────────────────────────────────────────────────────

@router.message(Command("mute"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_mute(message: Message, bot: Bot) -> None:
    if not await _check_staff(message, bot):
        return
    target = await _resolve_target(message)
    if not target:
        await message.reply("↩️ Ответь на сообщение пользователя.")
        return

    user_id, name = target
    args = (message.text or "").split()
    time_arg = args[2] if len(args) >= 3 else "60"
    reason = args[3] if len(args) >= 4 else "Нарушение правил"
    minutes = parse_time_arg(time_arg)

    try:
        victim = await bot.get_chat_member(message.chat.id, user_id)
        if _is_admin_status(victim.status):
            await message.reply("❌ Нельзя мутить администраторов.")
            return
        name = victim.user.full_name
    except Exception:
        pass

    until = datetime.utcnow() + timedelta(minutes=minutes)
    await bot.restrict_chat_member(
        message.chat.id, user_id,
        ChatPermissions(can_send_messages=False),
        until_date=until,
    )
    await mute_user(user_id, message.chat.id, minutes)

    mention = f'<a href="tg://user?id={user_id}">{name}</a>'
    await message.answer(
        f"🔇 <b>{mention}</b> заглушён на <b>{minutes} мин.</b>\n📋 Причина: {reason}",
        parse_mode="HTML",
    )


# ── /unmute ────────────────────────────────────────────────────────────────────

@router.message(Command("unmute"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_unmute(message: Message, bot: Bot) -> None:
    if not await _check_staff(message, bot):
        return
    target = await _resolve_target(message)
    if not target:
        await message.reply("↩️ Ответь на сообщение пользователя.")
        return

    user_id, name = target
    await bot.restrict_chat_member(
        message.chat.id, user_id,
        ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
        ),
    )
    await unmute_user(user_id, message.chat.id)

    mention = f'<a href="tg://user?id={user_id}">{name}</a>'
    await message.answer(f"🔊 <b>{mention}</b> размучен.", parse_mode="HTML")


# ── /ban ───────────────────────────────────────────────────────────────────────

@router.message(Command("ban"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_ban(message: Message, bot: Bot) -> None:
    if not await _check_admin(message, bot):
        return
    target = await _resolve_target(message)
    if not target:
        await message.reply("↩️ Ответь на сообщение пользователя.")
        return

    user_id, name = target
    args = (message.text or "").split(maxsplit=2)
    reason = args[2] if len(args) >= 3 else "Нарушение правил"

    try:
        victim = await bot.get_chat_member(message.chat.id, user_id)
        if _is_admin_status(victim.status):
            await message.reply("❌ Нельзя банить администраторов.")
            return
        name = victim.user.full_name
    except Exception:
        pass

    await bot.ban_chat_member(message.chat.id, user_id)
    await ban_user(user_id, message.chat.id, message.from_user.id, reason)

    mention = f'<a href="tg://user?id={user_id}">{name}</a>'
    await message.answer(
        f"🚫 <b>{mention}</b> забанен.\n📋 Причина: <b>{reason}</b>\n"
        f"<i>Лицензия охотника отозвана системой Solo Leveling.</i>",
        parse_mode="HTML",
    )
    logger.info(f"[BAN] {user_id} in {message.chat.id} by {message.from_user.id}")


# ── /unban ─────────────────────────────────────────────────────────────────────

@router.message(Command("unban"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_unban(message: Message, bot: Bot) -> None:
    if not await _check_admin(message, bot):
        return
    target = await _resolve_target(message)
    if not target:
        await message.reply("↩️ Укажи ID пользователя или ответь на его сообщение.")
        return

    user_id, name = target
    await bot.unban_chat_member(message.chat.id, user_id, only_if_banned=True)
    await unban_user(user_id, message.chat.id)

    mention = f'<a href="tg://user?id={user_id}">{name}</a>'
    await message.answer(
        f"✅ <b>{mention}</b> разбанен. Лицензия охотника восстановлена.",
        parse_mode="HTML",
    )


# ── /kick ──────────────────────────────────────────────────────────────────────

@router.message(Command("kick"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_kick(message: Message, bot: Bot) -> None:
    if not await _check_admin(message, bot):
        return
    target = await _resolve_target(message)
    if not target:
        await message.reply("↩️ Ответь на сообщение пользователя.")
        return

    user_id, name = target
    try:
        victim = await bot.get_chat_member(message.chat.id, user_id)
        if _is_admin_status(victim.status):
            await message.reply("❌ Нельзя кикать администраторов.")
            return
        name = victim.user.full_name
    except Exception:
        pass

    await bot.ban_chat_member(message.chat.id, user_id)
    await bot.unban_chat_member(message.chat.id, user_id)

    mention = f'<a href="tg://user?id={user_id}">{name}</a>'
    await message.answer(
        f"👟 <b>{mention}</b> выгнан из чата.",
        parse_mode="HTML",
    )


# ── /del ───────────────────────────────────────────────────────────────────────

@router.message(Command("del"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_del(message: Message, bot: Bot) -> None:
    if not await _check_staff(message, bot):
        return
    if not message.reply_to_message:
        await message.reply("↩️ Ответь на сообщение для удаления.")
        return
    try:
        await message.reply_to_message.delete()
        await message.delete()
    except Exception as e:
        await message.reply(f"❌ Не удалось удалить: {e}")
