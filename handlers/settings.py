"""
Settings handler: /settings, /addword, /rmword, /words, /setwelcome
+ inline callback handler for settings toggles.
"""
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from database import (
    get_chat_settings, update_chat_setting,
    add_blacklist_word, remove_blacklist_word, get_blacklist_words,
)
from keyboards import settings_keyboard
from utils import SETTINGS_MSG, is_owner

router = Router()


def _is_admin(status: str) -> bool:
    return status in ("administrator", "creator")


async def _check_admin(message: Message, bot: Bot) -> bool:
    if not message.from_user:
        return False
    if is_owner(message.from_user.id):
        return True
    member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    if not _is_admin(member.status):
        await message.reply("❌ Только администраторы могут изменять настройки.")
        return False
    return True


# ── /settings ─────────────────────────────────────────────────────────────────

@router.message(Command("settings"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_settings(message: Message, bot: Bot) -> None:
    if not await _check_admin(message, bot):
        return
    settings = await get_chat_settings(message.chat.id)
    await message.answer(
        SETTINGS_MSG.format(chat_title=message.chat.title or ""),
        parse_mode="HTML",
        reply_markup=settings_keyboard(settings),
    )


# ── Toggle callback ────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("toggle:"))
async def cb_toggle(call: CallbackQuery, bot: Bot) -> None:
    key = call.data.split(":")[1]
    if not call.message or not call.from_user:
        return

    if not is_owner(call.from_user.id):
        member = await bot.get_chat_member(call.message.chat.id, call.from_user.id)
        if not _is_admin(member.status):
            await call.answer("❌ Только администраторы.", show_alert=True)
            return

    settings = await get_chat_settings(call.message.chat.id)
    new_val = 0 if settings.get(key, 0) else 1
    await update_chat_setting(call.message.chat.id, key, new_val)

    settings[key] = new_val
    try:
        await call.message.edit_reply_markup(reply_markup=settings_keyboard(settings))
        await call.answer("✅ Настройка обновлена")
    except Exception:
        await call.answer("✅ Обновлено")


@router.callback_query(F.data == "settings:refresh")
async def cb_settings_refresh(call: CallbackQuery, bot: Bot) -> None:
    if not call.message:
        return
    settings = await get_chat_settings(call.message.chat.id)
    await call.message.edit_reply_markup(reply_markup=settings_keyboard(settings))
    await call.answer("🔄 Обновлено")


@router.callback_query(F.data == "settings:close")
async def cb_settings_close(call: CallbackQuery) -> None:
    if call.message:
        await call.message.delete()
    await call.answer()


# ── /addword /rmword /words ────────────────────────────────────────────────────

@router.message(Command("addword"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_addword(message: Message, bot: Bot) -> None:
    if not await _check_admin(message, bot):
        return
    args = (message.text or "").split()
    if len(args) < 2:
        await message.reply("✏️ Использование: /addword <слово>")
        return
    word = args[1].lower()
    success = await add_blacklist_word(message.chat.id, word, message.from_user.id)
    if success:
        await message.answer(f"✅ Слово <code>{word}</code> добавлено в чёрный список.", parse_mode="HTML")
    else:
        await message.answer(f"⚠️ Слово <code>{word}</code> уже в списке.", parse_mode="HTML")


@router.message(Command("rmword"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_rmword(message: Message, bot: Bot) -> None:
    if not await _check_admin(message, bot):
        return
    args = (message.text or "").split()
    if len(args) < 2:
        await message.reply("✏️ Использование: /rmword <слово>")
        return
    word = args[1].lower()
    await remove_blacklist_word(message.chat.id, word)
    await message.answer(f"✅ Слово <code>{word}</code> удалено из чёрного списка.", parse_mode="HTML")


@router.message(Command("words"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_words(message: Message, bot: Bot) -> None:
    if not await _check_admin(message, bot):
        return
    words = await get_blacklist_words(message.chat.id)
    if not words:
        await message.answer("📋 Чёрный список пуст.")
        return
    text = "📋 <b>Чёрный список слов:</b>\n\n" + "\n".join(f"• <code>{w}</code>" for w in words)
    await message.answer(text, parse_mode="HTML")


# ── /setwelcome ────────────────────────────────────────────────────────────────

@router.message(Command("setwelcome"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_setwelcome(message: Message, bot: Bot) -> None:
    if not await _check_admin(message, bot):
        return
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.reply(
            "✏️ Использование: /setwelcome <текст>\n\n"
            "Доступные переменные:\n"
            "<code>{mention}</code> — упоминание пользователя\n"
            "<code>{name}</code> — имя пользователя\n"
            "<code>{rank_label}</code> — ранг\n"
            "<code>{chat}</code> — название чата",
            parse_mode="HTML",
        )
        return
    text = args[1]
    from database import update_chat_setting
    await update_chat_setting(message.chat.id, "welcome_msg", text)
    await message.answer("✅ Приветственное сообщение обновлено.")
