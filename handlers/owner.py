"""
Owner-only control panel for the bot creator (@nonright).
Commands: /owner /panel /gstats /chats /broadcast /leavechat
Works in private chat with the bot.
"""
import asyncio

from aiogram import Router, F, Bot
from aiogram.filters import Command, BaseFilter
from aiogram.types import Message, CallbackQuery
from loguru import logger

from database import get_all_chats, get_global_stats
from keyboards import owner_keyboard
from utils import is_owner

router = Router()


class IsOwner(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return is_owner(message.from_user.id if message.from_user else None)


class IsOwnerCb(BaseFilter):
    async def __call__(self, call: CallbackQuery) -> bool:
        return is_owner(call.from_user.id if call.from_user else None)


# Owner filter applies to the whole router → никто, кроме владельца, не видит панель.
router.message.filter(IsOwner())
router.callback_query.filter(IsOwnerCb())


PANEL_MSG = (
    "👑 <b>ПАНЕЛЬ ВЛАДЕЛЬЦА</b>\n"
    "<i>S-Ранг Менеджер • режим создателя</i>\n\n"
    "Привет, Монарх. Отсюда ты управляешь ботом во всех чатах.\n\n"
    "<b>Команды владельца:</b>\n"
    "/gstats — глобальная статистика\n"
    "/chats — список всех чатов бота\n"
    "/broadcast <code>текст</code> — рассылка во все чаты\n"
    "   ↳ или ответь на сообщение командой /broadcast\n"
    "/leavechat <code>id</code> — выйти из чата\n\n"
    "Ты также <b>супер-админ</b> во всех чатах: тебе доступны все\n"
    "команды модерации, даже если ты не админ группы."
)


async def _stats_text() -> str:
    s = await get_global_stats()
    return (
        "📊 <b>ГЛОБАЛЬНАЯ СТАТИСТИКА</b>\n\n"
        f"💬 Чатов: <b>{s['chats']}</b>\n"
        f"👥 Уникальных охотников: <b>{s['users']}</b>\n"
        f"✉️ Всего сообщений: <b>{s['messages']}</b>\n"
        f"🗑 Удалено нарушений: <b>{s['deleted']}</b>\n"
        f"⚠️ Выдано предупреждений: <b>{s['warns']}</b>\n"
        f"🚫 Банов: <b>{s['bans']}</b>"
    )


async def _chats_text() -> str:
    chats = await get_all_chats()
    if not chats:
        return "💬 Бот пока не добавлен ни в один чат."
    lines = [f"💬 <b>ЧАТЫ БОТА</b> ({len(chats)})\n"]
    for c in chats[:50]:
        title = c.get("title") or "—"
        lines.append(f"• <b>{title}</b>\n  <code>{c['chat_id']}</code>")
    if len(chats) > 50:
        lines.append(f"\n<i>…и ещё {len(chats) - 50}</i>")
    return "\n".join(lines)


# ── /owner /panel ───────────────────────────────────────────────────────────────

@router.message(Command("owner", "panel"))
async def cmd_owner(message: Message) -> None:
    await message.answer(PANEL_MSG, parse_mode="HTML", reply_markup=owner_keyboard())


# ── /gstats ──────────────────────────────────────────────────────────────────────

@router.message(Command("gstats"))
async def cmd_gstats(message: Message) -> None:
    await message.answer(await _stats_text(), parse_mode="HTML")


# ── /chats ───────────────────────────────────────────────────────────────────────

@router.message(Command("chats"))
async def cmd_chats(message: Message) -> None:
    await message.answer(await _chats_text(), parse_mode="HTML")


# ── /broadcast ────────────────────────────────────────────────────────────────────

@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, bot: Bot) -> None:
    reply = message.reply_to_message
    args = (message.text or "").split(maxsplit=1)
    text = args[1] if len(args) >= 2 else None

    if not reply and not text:
        await message.answer(
            "📢 <b>Рассылка</b>\n\n"
            "Использование:\n"
            "<code>/broadcast текст сообщения</code>\n"
            "или ответь на любое сообщение командой <code>/broadcast</code> "
            "(перешлёт его во все чаты).",
            parse_mode="HTML",
        )
        return

    chats = await get_all_chats()
    if not chats:
        await message.answer("💬 Нет чатов для рассылки.")
        return

    sent = 0
    failed = 0
    status = await message.answer(f"📢 Рассылка в {len(chats)} чат(ов)…")
    for c in chats:
        cid = c["chat_id"]
        try:
            if reply:
                await reply.copy_to(cid)
            else:
                await bot.send_message(cid, text, parse_mode="HTML")
            sent += 1
        except Exception as e:
            failed += 1
            logger.warning(f"[BROADCAST] {cid} failed: {e}")
        await asyncio.sleep(0.05)  # анти-флуд лимит Telegram

    await status.edit_text(
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"Доставлено: <b>{sent}</b>\n"
        f"Ошибок: <b>{failed}</b>",
        parse_mode="HTML",
    )


# ── /leavechat ────────────────────────────────────────────────────────────────────

@router.message(Command("leavechat"))
async def cmd_leavechat(message: Message, bot: Bot) -> None:
    args = (message.text or "").split()
    if len(args) < 2 or not args[1].lstrip("-").isdigit():
        await message.answer("Использование: <code>/leavechat -100123456789</code>", parse_mode="HTML")
        return
    chat_id = int(args[1])
    try:
        await bot.leave_chat(chat_id)
        await message.answer(f"🚪 Бот покинул чат <code>{chat_id}</code>.", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Не удалось: {e}")


# ── Callbacks ──────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "owner:stats")
async def cb_owner_stats(call: CallbackQuery) -> None:
    await call.message.answer(await _stats_text(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "owner:chats")
async def cb_owner_chats(call: CallbackQuery) -> None:
    await call.message.answer(await _chats_text(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "owner:broadcast")
async def cb_owner_broadcast(call: CallbackQuery) -> None:
    await call.message.answer(
        "📢 Чтобы сделать рассылку, отправь:\n"
        "<code>/broadcast текст</code>\n"
        "или ответь на сообщение командой <code>/broadcast</code>.",
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "owner:refresh")
async def cb_owner_refresh(call: CallbackQuery) -> None:
    try:
        await call.message.edit_text(PANEL_MSG, parse_mode="HTML", reply_markup=owner_keyboard())
    except Exception:
        pass
    await call.answer("🔄 Обновлено")


@router.callback_query(F.data == "owner:close")
async def cb_owner_close(call: CallbackQuery) -> None:
    try:
        await call.message.delete()
    except Exception:
        pass
    await call.answer()
