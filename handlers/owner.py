"""
Owner-only control panel for the bot creator (@nonright).
Commands: /owner /panel /gstats /chats /broadcast /leavechat
Works in private chat with the bot.
"""
from aiogram import Router, F, Bot
from aiogram.filters import Command, BaseFilter
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from database import (
    get_all_chats, get_global_stats, get_mana_emission,
    payments_total, ads_global_stats,
    mana_emission_by_reason, payout_cost_summary, sponsor_revenue_cents,
)
from keyboards import owner_keyboard
from services import broadcast
from utils import (
    is_owner, format_mana, escape_html, get_config,
    ANNOUNCE_LAUNCH, ANNOUNCE_REFERRAL, strip_custom_emoji,
)
from utils.economy_rates import star_rub
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
    "/bank — 🏦 центральный банк: приход, долг рудой, эмиссия, профит\n"
    "/announce — 📣 опубликовать пост в канал бота\n"
    "/emojiid — 🧩 узнать ID премиум-эмодзи (для красивых постов)\n"
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


# Человекочитаемые названия источников эмиссии руды для «банка».
_REASON_LABELS = {
    "task_subscribe": "📋 Задания (подписки)",
    "dungeon": "🏰 Подземелье",
    "dungeon_ad": "🏰 Подземелье (реклама в профиле)",
    "dungeon_streak": "🔥 Стрик подземелья",
    "rank_up": "🏆 Бонусы за ранг",
    "agent_reward": "🕴 Агентские награды",
    "agent_milestone": "🏛 Веховые бонусы агентам",
    "ref_goal": "🎯 Реф-цели чатов",
    "invite": "⚔️ Приглашения в чат",
    "invite_bot": "⚔️ Приглашения в бота",
    "buy_mana": "💎 Покупка руды за Stars",
    "redeem": "🎁 Обмен на подарки",
    "redeem_refund": "↩️ Возвраты обменов",
    "transfer_in": "💸 Переводы (получено)",
    "transfer_out": "💸 Переводы (отдано)",
    "ach_rank_a_top100": "🥇 Ачивка «ранг A»",
    "message": "💬 Активность в чатах",
}


async def _bank_text() -> str:
    """Центральный банк Системы: приход (Stars + спонсоры), обязательства (руда),
    расход на подарки, эмиссия по источникам и оценка чистого профита."""
    cfg = get_config()
    mpr = max(cfg.mana_per_rub, 1)

    eco = await get_mana_emission()
    pay = await payments_total()
    payouts = await payout_cost_summary()
    sponsor_cents = await sponsor_revenue_cents()
    breakdown = await mana_emission_by_reason()

    def rub(mana: int) -> float:
        return mana / mpr

    stars = pay.get("stars", 0)
    stars_rub = star_rub(
        stars, usd_cents_per_1000=cfg.stars_usd_cents_per_1000, usd_rub=cfg.usd_rub_rate
    )
    sponsor_rub = sponsor_cents / 100
    supply = eco.get("supply", 0)
    paid_mana = payouts.get("paid_mana", 0)
    pending_mana = payouts.get("pending_mana", 0)
    pending_cnt = payouts.get("pending_count", 0)

    income_rub = stars_rub + sponsor_rub
    spent_rub = rub(paid_mana)
    net_rub = income_rub - spent_rub

    lines = [
        "🏦 <b>ЦЕНТРАЛЬНЫЙ БАНК СИСТЕМЫ</b>",
        f"<i>Курс: {cfg.mana_per_rub} руды = 1 ₽</i>\n",
        "💎 <b>ПРИХОД (реальные деньги)</b>",
        f"⭐ Stars получено: <b>{stars}</b> (~{stars_rub:.0f} ₽), заказов: {pay.get('orders', 0)}",
        f"🤝 Доход от спонсоров: <b>~{sponsor_rub:.0f} ₽</b>",
        f"<b>Итого приход: ~{income_rub:.0f} ₽</b>\n",
        "📉 <b>ОБЯЗАТЕЛЬСТВА (руда = долг банка)</b>",
        f"🔹 Руды в обороте: <b>{format_mana(supply)}</b> (~{rub(supply):.0f} ₽ к выплате)",
        f"🎁 Выплачено подарками: <b>{format_mana(paid_mana)}</b> (~{spent_rub:.0f} ₽)",
        f"⏳ Заявок в ожидании: <b>{pending_cnt}</b> на {format_mana(pending_mana)}\n",
        "🧮 <b>ЭМИССИЯ РУДЫ ПО ИСТОЧНИКАМ</b>",
    ]
    shown = [b for b in breakdown if b["minted"] > 0][:8]
    if shown:
        for b in shown:
            label = _REASON_LABELS.get(b["reason"], f"• {b['reason']}")
            lines.append(f"{label}: <b>{format_mana(b['minted'])}</b> (~{rub(b['minted']):.0f} ₽)")
    else:
        lines.append("<i>Пока ничего не напечатано.</i>")

    lines.append("")
    lines.append("📊 <b>ОЦЕНКА ПРОФИТА</b>")
    lines.append(f"Приход − выплачено = <b>~{net_rub:.0f} ₽</b>")
    lines.append(
        "<i>Руда в обороте — отложенный долг: реальные затраты возникают только "
        "при обмене руды на подарки/крипту, и обмен крупных сумм ты подтверждаешь сам "
        "(/payouts). Так банк не уходит в минус.</i>"
    )
    return "\n".join(lines)


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


# ── /bank — центральный банк / P&L ─────────────────────────────────────────────

@router.message(Command("bank", "pl", "treasury"))
async def cmd_bank(message: Message) -> None:
    await message.answer(await _bank_text(), parse_mode="HTML")


# ── /emojiid — извлечь custom_emoji_id из присланных премиум-эмодзи ─────────────

@router.message(Command("emojiid", "emoji", "ce"))
async def cmd_emojiid(message: Message) -> None:
    """Владелец шлёт премиум-эмодзи (в этом же сообщении после команды или
    ответом на сообщение с ними) — бот вернёт копируемые custom_emoji_id."""
    src = message.reply_to_message or message
    text = src.text or src.caption or ""
    entities = list(src.entities or []) + list(src.caption_entities or [])
    found = [
        (e.custom_emoji_id, e.extract_from(text))
        for e in entities
        if e.type == "custom_emoji" and e.custom_emoji_id
    ]
    if not found:
        await message.answer(
            "🧩 <b>Как получить ID премиум-эмодзи</b>\n\n"
            "1) Включи Telegram Premium на своём аккаунте.\n"
            "2) Пришли мне <b>/emojiid</b> и сразу — нужные премиум-эмодзи "
            "(в одном сообщении), либо <b>ответь</b> командой на сообщение с ними.\n"
            "3) Я верну список <code>emoji-id</code> — впишешь их в "
            "<code>utils/premium_emoji.py</code>.\n\n"
            "<i>Обычные (не премиум) эмодзи ID не имеют — нужны именно премиум.</i>",
            parse_mode="HTML",
        )
        return

    lines = ["🧩 <b>НАЙДЕННЫЕ ПРЕМИУМ-ЭМОДЗИ</b>\n",
             "Скопируй id в <code>utils/premium_emoji.py</code> → поле \"id\":\n"]
    block = "\n".join(f'{alt}  →  {eid}' for eid, alt in found)
    lines.append(f"<pre>{escape_html(block)}</pre>")
    lines.append(
        "\nГотовый HTML-тег (можно проверить отправкой):\n"
        + "\n".join(f'{alt}: <code>&lt;tg-emoji emoji-id="{eid}"&gt;{escape_html(alt)}&lt;/tg-emoji&gt;</code>'
                    for eid, alt in found)
    )
    await message.answer("\n".join(lines), parse_mode="HTML")


# ── /announce — публикация маркетинговых постов в канал ─────────────────────────

def _announce_target(cfg) -> str | int | None:
    """Куда публикуем: спец-канал витрины, иначе канал гейта (@Manager_Rank_S)."""
    return cfg.bot_channel_id or cfg.sub_gate_channel or None


def _announce_kit(kind: str, cfg) -> tuple[str, object]:
    """Текст поста + публичная клавиатура (URL-кнопки) под него.

    Цель — канал. В канале бот не может показать премиум-эмодзи (ограничение
    Telegram), поэтому снимаем теги заранее: и превью, и реальный пост будут
    выглядеть одинаково (превью = то, что увидят подписчики).
    """
    uname = (cfg.bot_username or "").lstrip("@")
    kb = InlineKeyboardBuilder()
    if kind == "launch":
        if uname:
            kb.row(InlineKeyboardButton(
                text="➕ Добавить бота в свой чат",
                url=f"https://t.me/{uname}?startgroup=true",
            ))
            kb.row(InlineKeyboardButton(text="⚡ Открыть бота", url=f"https://t.me/{uname}"))
        return strip_custom_emoji(ANNOUNCE_LAUNCH), kb.as_markup()
    # ref
    if uname:
        kb.row(InlineKeyboardButton(
            text="🕴 Стать Агентом — забрать ссылку",
            url=f"https://t.me/{uname}?start=earn",
        ))
    return strip_custom_emoji(ANNOUNCE_REFERRAL), kb.as_markup()


def _announce_menu() -> object:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="👁 Превью: Запуск бота", callback_data="announce:prev:launch"))
    b.row(InlineKeyboardButton(text="👁 Превью: Рефералка (доход)", callback_data="announce:prev:ref"))
    return b.as_markup()


@router.message(Command("announce", "post"))
async def cmd_announce(message: Message) -> None:
    cfg = get_config()
    target = _announce_target(cfg)
    where = f"<code>{target}</code>" if target else "—"
    note = "" if target else (
        "\n\n⚠️ Канал для публикации не задан. Укажи <code>BOT_CHANNEL_ID</code> "
        "или <code>SUB_GATE_CHANNEL</code> в .env. Бот должен быть админом канала."
    )
    await message.answer(
        "📣 <b>ПУБЛИКАЦИЯ В КАНАЛ</b>\n\n"
        f"Канал: {where}\n"
        "Выбери пост — сначала покажу превью, потом подтвердишь публикацию." + note,
        parse_mode="HTML",
        reply_markup=_announce_menu(),
    )


@router.callback_query(F.data.startswith("announce:prev:"))
async def cb_announce_preview(call: CallbackQuery) -> None:
    kind = call.data.split(":")[2]
    cfg = get_config()
    text, kb = _announce_kit(kind, cfg)
    await call.answer()
    # Само превью — ровно как будет выглядеть пост в канале.
    try:
        await call.message.answer(text, parse_mode="HTML", reply_markup=kb,
                                  disable_web_page_preview=True)
    except Exception as e:
        await call.message.answer(f"Ошибка превью: {e}")
        return
    # Управление публикацией.
    ctrl = InlineKeyboardBuilder()
    ctrl.row(InlineKeyboardButton(text="✅ Опубликовать в канал", callback_data=f"announce:pub:{kind}"))
    ctrl.row(InlineKeyboardButton(text="✖️ Отмена", callback_data="announce:cancel"))
    await call.message.answer(
        "☝️ Так пост будет выглядеть в канале. Публикуем?",
        reply_markup=ctrl.as_markup(),
    )


@router.callback_query(F.data == "announce:cancel")
async def cb_announce_cancel(call: CallbackQuery) -> None:
    await call.answer("Отменено")
    try:
        await call.message.edit_text("✖️ Публикация отменена.")
    except Exception:
        pass


@router.callback_query(F.data.startswith("announce:pub:"))
async def cb_announce_publish(call: CallbackQuery, bot: Bot) -> None:
    kind = call.data.split(":")[2]
    cfg = get_config()
    target = _announce_target(cfg)
    if not target:
        await call.answer("Канал не задан (BOT_CHANNEL_ID / SUB_GATE_CHANNEL).", show_alert=True)
        return
    text, kb = _announce_kit(kind, cfg)
    try:
        await bot.send_message(target, text, parse_mode="HTML", reply_markup=kb,
                               disable_web_page_preview=True)
    except Exception as e:
        await call.answer("Ошибка публикации", show_alert=True)
        try:
            await call.message.edit_text(
                f"❌ Не удалось опубликовать: {e}\n\n"
                "Проверь, что бот — администратор канала с правом постинга."
            )
        except Exception:
            pass
        return
    await call.answer("✅ Опубликовано!", show_alert=True)
    try:
        await call.message.edit_text(f"✅ Пост опубликован в канал <code>{target}</code>.",
                                     parse_mode="HTML")
    except Exception:
        pass
    logger.info(f"[ANNOUNCE] published '{kind}' to {target}")


# ── /chats ───────────────────────────────────────────────────────────────────────

@router.message(Command("chats"))
async def cmd_chats(message: Message) -> None:
    await message.answer(await _chats_text(), parse_mode="HTML")


# ── /topweek — опубликовать топ охотников недели в канал-витрину ─────────────────

@router.message(Command("topweek", "weeklytop"))
async def cmd_topweek(message: Message, bot: Bot) -> None:
    from services.showcase import post_weekly_top
    ok = await post_weekly_top(bot)
    if ok:
        await message.answer("✅ Топ недели опубликован в канал-витрину.")
    else:
        await message.answer(
            "⚠️ Не удалось опубликовать топ.\n"
            "Проверь: задан ли <code>BOT_CHANNEL_ID</code>/<code>SUB_GATE_CHANNEL</code>, "
            "бот — админ канала, и есть ли охотники с рудой.",
            parse_mode="HTML",
        )


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
