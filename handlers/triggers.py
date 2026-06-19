"""
Инструменты вовлечения для чатов (уровень Iris): триггеры/кастом-команды,
заметки и белый список к антимату. Управление — только админам; просмотр заметок
и срабатывание триггеров — всем участникам.
"""
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message

from database import (
    add_trigger, remove_trigger, list_triggers, count_triggers,
    save_note, get_note, delete_note, list_notes,
    add_whitelist_word, remove_whitelist_word, get_whitelist_words,
    update_chat_setting, get_chat_settings,
)
from services.triggers import invalidate as invalidate_triggers
from utils import require_admin, escape_html, get_config, is_chat_pro

router = Router()
_GROUP = F.chat.type.in_({"group", "supergroup"})
_MAX_TRIGGERS = 100


async def _admin(message: Message, bot: Bot) -> bool:
    return await require_admin(message, bot)


# ── Триггеры ──────────────────────────────────────────────────────────────────

@router.message(Command("addtrigger", "settrigger"), _GROUP)
async def cmd_addtrigger(message: Message, bot: Bot) -> None:
    if not await _admin(message, bot):
        return
    raw = (message.text or "").split(maxsplit=1)
    body = raw[1] if len(raw) > 1 else ""
    if "|" not in body:
        await message.reply(
            "✏️ Формат: <code>/addtrigger ключ | ответ</code>\n\n"
            "Пример: <code>/addtrigger правила | Читай /rules, охотник.</code>\n"
            "Бот будет отвечать, когда в сообщении встретится «ключ».",
            parse_mode="HTML",
        )
        return
    pattern, response = (p.strip() for p in body.split("|", 1))
    if not pattern or not response:
        await message.reply("⚠️ И ключ, и ответ должны быть непустыми.")
        return
    settings = await get_chat_settings(message.chat.id)
    limit = get_config().pro_triggers_limit if is_chat_pro(settings) else _MAX_TRIGGERS
    if await count_triggers(message.chat.id) >= limit:
        hint = "" if is_chat_pro(settings) else " Подними лимит до Pro: /pro"
        await message.reply(
            f"⚠️ Достигнут лимит триггеров ({limit}). Удали лишние: /deltrigger.{hint}"
        )
        return
    ok = await add_trigger(message.chat.id, pattern, response, "contains", message.from_user.id)
    invalidate_triggers(message.chat.id)
    if ok:
        await message.reply(
            f"✅ Триггер на «<b>{escape_html(pattern)}</b>» сохранён.", parse_mode="HTML"
        )
    else:
        await message.reply("⚠️ Не удалось сохранить триггер.")


@router.message(Command("deltrigger", "rmtrigger"), _GROUP)
async def cmd_deltrigger(message: Message, bot: Bot) -> None:
    if not await _admin(message, bot):
        return
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.reply("✏️ Использование: <code>/deltrigger ключ</code>", parse_mode="HTML")
        return
    ok = await remove_trigger(message.chat.id, args[1])
    invalidate_triggers(message.chat.id)
    await message.reply("✅ Триггер удалён." if ok else "⚠️ Такого триггера нет.")


@router.message(Command("triggers"), _GROUP)
async def cmd_triggers(message: Message) -> None:
    rows = await list_triggers(message.chat.id)
    if not rows:
        await message.reply("📋 Триггеров пока нет. Добавь: <code>/addtrigger ключ | ответ</code>", parse_mode="HTML")
        return
    lines = "\n".join(f"• <code>{escape_html(r['pattern'])}</code>" for r in rows[:50])
    await message.reply(f"📋 <b>Триггеры чата ({len(rows)}):</b>\n\n{lines}", parse_mode="HTML")


# ── Заметки ───────────────────────────────────────────────────────────────────

@router.message(Command("save"), _GROUP)
async def cmd_save_note(message: Message, bot: Bot) -> None:
    if not await _admin(message, bot):
        return
    args = (message.text or "").split(maxsplit=2)
    if len(args) < 2:
        await message.reply(
            "✏️ Формат: <code>/save имя текст</code> или ответом на сообщение: <code>/save имя</code>",
            parse_mode="HTML",
        )
        return
    name = args[1]
    if len(args) >= 3:
        content = args[2]
    elif message.reply_to_message and (message.reply_to_message.text or message.reply_to_message.caption):
        content = message.reply_to_message.text or message.reply_to_message.caption
    else:
        await message.reply("⚠️ Дай текст заметки или ответь на сообщение.")
        return
    ok = await save_note(message.chat.id, name, content, message.from_user.id)
    if ok:
        await message.reply(
            f"✅ Заметка «<b>{escape_html(name)}</b>» сохранена. Вызвать: <code>/note {escape_html(name)}</code>",
            parse_mode="HTML",
        )
    else:
        await message.reply("⚠️ Не удалось сохранить заметку.")


@router.message(Command("note", "get"), _GROUP)
async def cmd_get_note(message: Message) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.reply("✏️ Использование: <code>/note имя</code>", parse_mode="HTML")
        return
    note = await get_note(message.chat.id, args[1])
    if not note:
        await message.reply("⚠️ Заметка не найдена. Список: /notes")
        return
    await message.reply(note["content"], parse_mode="HTML", disable_web_page_preview=True)


@router.message(Command("notes"), _GROUP)
async def cmd_notes(message: Message) -> None:
    rows = await list_notes(message.chat.id)
    if not rows:
        await message.reply("📋 Заметок пока нет. Добавь: <code>/save имя текст</code>", parse_mode="HTML")
        return
    lines = "  ".join(f"<code>{escape_html(r['name'])}</code>" for r in rows[:80])
    await message.reply(f"📋 <b>Заметки чата:</b>\n\n{lines}\n\nВызов: <code>/note имя</code>", parse_mode="HTML")


@router.message(Command("delnote", "clearnote"), _GROUP)
async def cmd_delnote(message: Message, bot: Bot) -> None:
    if not await _admin(message, bot):
        return
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.reply("✏️ Использование: <code>/delnote имя</code>", parse_mode="HTML")
        return
    ok = await delete_note(message.chat.id, args[1])
    await message.reply("✅ Заметка удалена." if ok else "⚠️ Такой заметки нет.")


# ── Белый список к антимату ─────────────────────────────────────────────────

@router.message(Command("allowword"), _GROUP)
async def cmd_allowword(message: Message, bot: Bot) -> None:
    if not await _admin(message, bot):
        return
    args = (message.text or "").split()
    if len(args) < 2:
        await message.reply("✏️ Использование: <code>/allowword слово</code>", parse_mode="HTML")
        return
    word = args[1].lower()
    await add_whitelist_word(message.chat.id, word, message.from_user.id)
    await message.reply(
        f"✅ «<code>{escape_html(word)}</code>» в белом списке — фильтры его пропустят.",
        parse_mode="HTML",
    )


@router.message(Command("rmallow"), _GROUP)
async def cmd_rmallow(message: Message, bot: Bot) -> None:
    if not await _admin(message, bot):
        return
    args = (message.text or "").split()
    if len(args) < 2:
        await message.reply("✏️ Использование: <code>/rmallow слово</code>", parse_mode="HTML")
        return
    ok = await remove_whitelist_word(message.chat.id, args[1].lower())
    await message.reply("✅ Убрано из белого списка." if ok else "⚠️ Слова нет в списке.")


@router.message(Command("allowlist"), _GROUP)
async def cmd_allowlist(message: Message) -> None:
    words = await get_whitelist_words(message.chat.id)
    if not words:
        await message.reply("📋 Белый список пуст.")
        return
    lines = "\n".join(f"• <code>{escape_html(w)}</code>" for w in words)
    await message.reply(f"📋 <b>Белый список (антимат):</b>\n\n{lines}", parse_mode="HTML")


# ── Кнопка в приветствии новичка ────────────────────────────────────────────

@router.message(Command("setwelcomebtn"), _GROUP)
async def cmd_setwelcomebtn(message: Message, bot: Bot) -> None:
    if not await _admin(message, bot):
        return
    raw = (message.text or "").split(maxsplit=1)
    body = raw[1] if len(raw) > 1 else ""
    if body.strip().lower() in ("off", "выкл", "-"):
        await update_chat_setting(message.chat.id, "welcome_btn_text", "")
        await update_chat_setting(message.chat.id, "welcome_btn_url", "")
        await message.reply("✅ Кнопка приветствия убрана.")
        return
    if "|" not in body:
        await message.reply(
            "✏️ Формат: <code>/setwelcomebtn Текст кнопки | https://ссылка</code>\n"
            "Убрать: <code>/setwelcomebtn off</code>",
            parse_mode="HTML",
        )
        return
    text, url = (p.strip() for p in body.split("|", 1))
    if not text or not url.startswith(("http://", "https://", "t.me/")):
        await message.reply("⚠️ Нужны текст и корректная ссылка (http/https/t.me).")
        return
    await update_chat_setting(message.chat.id, "welcome_btn_text", text)
    await update_chat_setting(message.chat.id, "welcome_btn_url", url)
    await message.reply("✅ Кнопка приветствия настроена.")
