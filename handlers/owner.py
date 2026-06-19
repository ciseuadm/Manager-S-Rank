"""
Owner-only control panel for the bot creator (@nonright).
Commands: /owner /panel /gstats /chats /broadcast /leavechat
Works in private chat with the bot.
"""
from aiogram import Router, F, Bot
from aiogram.filters import Command, BaseFilter
from aiogram.types import Message, CallbackQuery
from loguru import logger

from database import (
    get_all_chats, get_global_stats, get_mana_emission,
    payments_total, ads_global_stats,
)
from keyboards import owner_keyboard
from services import broadcast
from utils import is_owner, format_mana, escape_html
from utils.media import answer_with_banner

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
    "/gstats — глобальная статистика (чаты, экономика, доход, реклама)\n"
    "/chats — список всех чатов бота\n"
    "/broadcast <code>текст</code> — рассылка во все чаты\n"
    "   ↳ или ответь на сообщение командой /broadcast\n"
    "/leavechat <code>id</code> — выйти из чата\n\n"
    "<b>📢 Реклама (монетизация):</b>\n"
    "/newad — создать рекламную кампанию (мастер)\n"
    "/ads — список кампаний и статистика\n"
    "/sendads — разослать активные кампании сейчас\n"
    "/pausead, /resumead <code>id</code> — пауза/возобновление\n"
    "/deletead <code>id</code> — удалить неактуальную кампанию\n\n"
    "<b>🗄 Защита данных:</b>\n"
    "/backup — снимок БД сейчас + копия тебе в личку\n"
    "/dbcheck — проверить целостность базы\n"
    "/restore — ответь на файл бэкапа, чтобы восстановить базу\n\n"
    "Ты также <b>супер-админ</b> во всех чатах: тебе доступны все\n"
    "команды модерации, даже если ты не админ группы."
)


async def _stats_text() -> str:
    s = await get_global_stats()
    eco = await get_mana_emission()
    pay = await payments_total()
    ads = await ads_global_stats()
    return (
        "📊 <b>ГЛОБАЛЬНАЯ СТАТИСТИКА</b>\n\n"
        f"💬 Чатов: <b>{s['chats']}</b>\n"
        f"👥 Уникальных охотников: <b>{s['users']}</b>\n"
        f"✉️ Всего сообщений: <b>{s['messages']}</b>\n"
        f"🗑 Удалено нарушений: <b>{s['deleted']}</b>\n"
        f"⚠️ Выдано предупреждений: <b>{s['warns']}</b>\n"
        f"🚫 Банов: <b>{s['bans']}</b>\n\n"
        "🔹 <b>ЭКОНОМИКА</b>\n"
        f"В обороте: <b>{format_mana(eco.get('supply', 0))}</b>\n"
        f"Всего добыто: <b>{format_mana(eco.get('earned', 0))}</b> | "
        f"кошельков: <b>{eco.get('holders', 0)}</b>\n\n"
        "💳 <b>ДОХОД (Stars)</b>\n"
        f"⭐ Всего: <b>{pay.get('stars', 0)}</b> | заказов: <b>{pay.get('orders', 0)}</b>\n\n"
        "📢 <b>РЕКЛАМА</b>\n"
        f"Кампаний: <b>{ads.get('campaigns', 0)}</b> | активных: <b>{ads.get('active', 0)}</b> | "
        f"показов: <b>{ads.get('impressions', 0)}</b>"
    )


async def _chats_text() -> str:
    chats = await get_all_chats()
    if not chats:
        return "💬 Бот пока не добавлен ни в один чат."
    lines = [f"💬 <b>ЧАТЫ БОТА</b> ({len(chats)})\n"]
    for c in chats[:50]:
        title = escape_html(c.get("title") or "—")
        lines.append(f"• <b>{title}</b>\n  <code>{c['chat_id']}</code>")
    if len(chats) > 50:
        lines.append(f"\n<i>…и ещё {len(chats) - 50}</i>")
    return "\n".join(lines)


# ── /owner /panel ───────────────────────────────────────────────────────────────

@router.message(Command("owner", "panel"))
async def cmd_owner(message: Message) -> None:
    await answer_with_banner(
        message, "owner", PANEL_MSG, reply_markup=owner_keyboard()
    )


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

    status = await message.answer(f"📢 Рассылка в {len(chats)} чат(ов)…")

    async def _send(b: Bot, cid: int) -> None:
        if reply:
            await reply.copy_to(cid)
        else:
            await b.send_message(cid, text, parse_mode="HTML")

    async def _progress(sent: int, failed: int, removed: int) -> None:
        try:
            await status.edit_text(
                f"📢 Рассылка… доставлено {sent}, ошибок {failed}."
            )
        except Exception:
            pass

    result = await broadcast(
        bot, [c["chat_id"] for c in chats], _send, on_progress=_progress
    )

    await status.edit_text(
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"Доставлено: <b>{result['sent']}</b>\n"
        f"Ошибок: <b>{result['failed']}</b>\n"
        f"Удалено мёртвых чатов: <b>{result['removed']}</b>",
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


# ── /backup /dbcheck /restore — защита данных ────────────────────────────────────

@router.message(Command("backup"))
async def cmd_backup(message: Message, bot: Bot) -> None:
    from services.backup import backup_and_ship
    from utils import get_config
    note = await message.answer("🗄 Делаю снимок БД и проверяю целостность…")
    try:
        target = await backup_and_ship(bot, keep=get_config().backup_keep)
        await note.edit_text(
            f"✅ Бэкап готов: <code>{target.name}</code>\n"
            f"Размер: <b>{target.stat().st_size // 1024} КБ</b>, целостность подтверждена.\n"
            "Копия отправлена тебе (и в канал бэкапов, если задан).",
            parse_mode="HTML",
        )
    except Exception as e:
        await note.edit_text(f"❌ Бэкап не удался: <code>{e}</code>", parse_mode="HTML")


@router.message(Command("dbcheck"))
async def cmd_dbcheck(message: Message) -> None:
    from pathlib import Path
    from services.backup import integrity_ok
    from utils import get_config
    db_path = Path(get_config().db_path).resolve()
    ok, detail = integrity_ok(db_path)
    icon = "✅" if ok else "🚨"
    await message.answer(
        f"{icon} <b>Проверка БД</b>\nФайл: <code>{db_path.name}</code>\n"
        f"Результат: <b>{detail}</b>",
        parse_mode="HTML",
    )


@router.message(Command("restore"))
async def cmd_restore(message: Message, bot: Bot) -> None:
    reply = message.reply_to_message
    doc = reply.document if reply else None
    if not doc or not (doc.file_name or "").endswith(".db"):
        await message.answer(
            "♻️ <b>Восстановление БД</b>\n\n"
            "Ответь командой <code>/restore</code> на сообщение с файлом бэкапа "
            "(<code>srank_*.db</code>), который я тебе присылал.\n\n"
            "⚠️ Текущая база будет заменена. Перед заменой я автоматически сделаю "
            "контрольный снимок текущей БД.",
            parse_mode="HTML",
        )
        return

    import tempfile
    from pathlib import Path
    from services.backup import restore_from_file

    note = await message.answer("♻️ Скачиваю файл и проверяю целостность…")
    tmp = Path(tempfile.gettempdir()) / f"restore_{doc.file_unique_id}.db"
    try:
        await bot.download(doc, destination=str(tmp))
        ok, detail = await restore_from_file(tmp)
    except Exception as e:
        await note.edit_text(f"❌ Восстановление не удалось: <code>{e}</code>", parse_mode="HTML")
        return
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass

    if ok:
        await note.edit_text("✅ База восстановлена из бэкапа и снова в работе.")
    else:
        await note.edit_text(f"❌ Не восстановлено: <code>{detail}</code>", parse_mode="HTML")


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
