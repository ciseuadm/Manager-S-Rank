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
from utils import SETTINGS_MSG, is_chat_admin, require_admin

router = Router()


async def _check_admin(message: Message, bot: Bot) -> bool:
    return await require_admin(message, bot)


async def _cb_admin_guard(call: CallbackQuery, bot: Bot) -> bool:
    """Block non-admins from touching settings buttons."""
    if not call.message or not call.from_user:
        return False
    if await is_chat_admin(bot, call.message.chat.id, call.from_user.id):
        return True
    await call.answer("❌ Только администраторы.", show_alert=True)
    return False


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
    if not await _cb_admin_guard(call, bot):
        return
    key = call.data.split(":")[1]

    settings = await get_chat_settings(call.message.chat.id)
    new_val = 0 if settings.get(key, 0) else 1
    await update_chat_setting(call.message.chat.id, key, new_val)

    settings[key] = new_val
    try:
        await call.message.edit_reply_markup(reply_markup=settings_keyboard(settings))
        await call.answer("✅ Настройка обновлена")
    except Exception:
        await call.answer("✅ Обновлено")


# ── Numeric/value settings (warn limit, mute time, welcome) ─────────────────────

_WARN_LIMIT_CYCLE = [3, 4, 5, 7, 10]
_MUTE_TIME_CYCLE = [30, 60, 120, 360, 1440]


def _next_in_cycle(cycle: list[int], current: int) -> int:
    if current in cycle:
        return cycle[(cycle.index(current) + 1) % len(cycle)]
    return cycle[0]


@router.callback_query(F.data.startswith("set:"))
async def cb_set_value(call: CallbackQuery, bot: Bot) -> None:
    if not await _cb_admin_guard(call, bot):
        return
    key = call.data.split(":")[1]
    settings = await get_chat_settings(call.message.chat.id)

    if key == "warn_limit":
        new_val = _next_in_cycle(_WARN_LIMIT_CYCLE, settings.get("warn_limit", 3))
        await update_chat_setting(call.message.chat.id, "warn_limit", new_val)
        await call.answer(f"⚠️ Лимит варнов: {new_val} (бан при {new_val + 2})")
    elif key == "mute_time":
        new_val = _next_in_cycle(_MUTE_TIME_CYCLE, settings.get("mute_time", 60))
        await update_chat_setting(call.message.chat.id, "mute_time", new_val)
        label = f"{new_val // 60} ч" if new_val >= 60 else f"{new_val} мин"
        await call.answer(f"🔇 Время мута: {label}")
    elif key == "welcome_msg":
        await call.answer(
            "📝 Измени приветствие командой:\n/setwelcome <текст>",
            show_alert=True,
        )
        return
    else:
        await call.answer()
        return

    settings = await get_chat_settings(call.message.chat.id)
    try:
        await call.message.edit_reply_markup(reply_markup=settings_keyboard(settings))
    except Exception:
        pass


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
    await update_chat_setting(message.chat.id, "welcome_msg", text)
    await message.answer("✅ Приветственное сообщение обновлено.")


# ── /setrules ──────────────────────────────────────────────────────────────────

@router.message(Command("setrules"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_setrules(message: Message, bot: Bot) -> None:
    if not await _check_admin(message, bot):
        return
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.reply("✏️ Использование: /setrules <текст правил>")
        return
    await update_chat_setting(message.chat.id, "rules", args[1])
    await message.answer("✅ Правила чата обновлены. Участники увидят их через /rules.")
