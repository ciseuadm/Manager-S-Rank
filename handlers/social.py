"""
Социальные механики поверх руды (вовлечение/удержание/виральность):
  • кланы — объединения в чате со складчиной руды в общую казну (руда-сейф);
  • браки охотников — RP-пары через предложение/согласие;
  • групповые рейды — кооперативный ивент чата с маленькой наградой раз в день.

Экономически безопасно: создание клана и складчина — это СТОК/перераспределение
руды (не эмиссия), а рейд-награда выдаётся не чаще раза в сутки на охотника.
"""
import asyncio

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import (
    create_clan, get_clan, get_clan_by_name, get_user_clan, join_clan,
    leave_clan, clan_member_count, add_clan_treasury, top_clans,
    get_marriage, create_marriage, divorce,
    spend_mana, add_mana, got_reason_today, get_wallet_balance,
)
from utils import escape_html, mention_html, mention_html_raw, format_mana

router = Router()
_GROUP = F.chat.type.in_({"group", "supergroup"})

# Экономические параметры социальных фич.
CLAN_CREATE_COST = 500       # сток руды за создание клана
RAID_REWARD = 15             # руда каждому участнику рейда (раз в день)
RAID_WINDOW = 60             # секунд на сбор отряда

# Активные рейды в памяти процесса: chat_id -> {"users": set, "open": bool}.
_raids: dict[int, dict] = {}


# ── Кланы ─────────────────────────────────────────────────────────────────────

@router.message(Command("createclan", "newclan"), _GROUP)
async def cmd_createclan(message: Message) -> None:
    user = message.from_user
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.reply(
            "✏️ Формат: <code>/createclan Название</code>\n"
            f"Стоимость основания: <b>{format_mana(CLAN_CREATE_COST)}</b>.",
            parse_mode="HTML",
        )
        return
    name = args[1].strip()[:32]
    if await get_user_clan(message.chat.id, user.id):
        await message.reply("⚠️ Ты уже в клане. Сначала покинь его: /leaveclan")
        return
    if await get_clan_by_name(message.chat.id, name):
        await message.reply("⚠️ Клан с таким именем уже есть. Выбери другое.")
        return
    spent = await spend_mana(user.id, CLAN_CREATE_COST, "clan_create", chat_id=message.chat.id)
    if spent is None:
        await message.reply(
            f"💎 Недостаточно руды. Нужно <b>{format_mana(CLAN_CREATE_COST)}</b> на основание клана.",
            parse_mode="HTML",
        )
        return
    clan_id = await create_clan(message.chat.id, name, user.id)
    if not clan_id:
        await add_mana(user.id, CLAN_CREATE_COST, "clan_create_refund", chat_id=message.chat.id)
        await message.reply("⚠️ Не удалось создать клан. Руда возвращена.")
        return
    await message.answer(
        f"🏛 <b>КЛАН ОСНОВАН!</b>\n\n"
        f"Гильдия <b>«{escape_html(name)}»</b> зарождается под рукой {mention_html(user)}.\n"
        f"Зови охотников: <code>/joinclan {escape_html(name)}</code>\n"
        f"Складчина в казну: <code>/clandonate сумма</code>",
        parse_mode="HTML",
    )


@router.message(Command("joinclan"), _GROUP)
async def cmd_joinclan(message: Message) -> None:
    user = message.from_user
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.reply("✏️ Использование: <code>/joinclan Название</code>", parse_mode="HTML")
        return
    if await get_user_clan(message.chat.id, user.id):
        await message.reply("⚠️ Ты уже в клане. Покинь текущий: /leaveclan")
        return
    clan = await get_clan_by_name(message.chat.id, args[1].strip())
    if not clan:
        await message.reply("⚠️ Клан не найден. Список: /clans")
        return
    await join_clan(clan["id"], user.id, message.chat.id)
    count = await clan_member_count(clan["id"])
    await message.reply(
        f"⚔️ {mention_html(user)} вступает в клан <b>«{escape_html(clan['name'])}»</b>! "
        f"Бойцов в строю: <b>{count}</b>.",
        parse_mode="HTML",
    )


@router.message(Command("leaveclan"), _GROUP)
async def cmd_leaveclan(message: Message) -> None:
    ok = await leave_clan(message.chat.id, message.from_user.id)
    await message.reply("👋 Ты покинул клан." if ok else "⚠️ Ты не состоишь в клане.")


@router.message(Command("clandonate"), _GROUP)
async def cmd_clandonate(message: Message) -> None:
    user = message.from_user
    args = (message.text or "").split()
    if len(args) < 2 or not args[1].isdigit() or int(args[1]) <= 0:
        await message.reply("✏️ Использование: <code>/clandonate сумма</code>", parse_mode="HTML")
        return
    amount = int(args[1])
    clan = await get_user_clan(message.chat.id, user.id)
    if not clan:
        await message.reply("⚠️ Сначала вступи в клан: /joinclan или создай /createclan")
        return
    spent = await spend_mana(user.id, amount, "clan_donate", ref_id=str(clan["id"]), chat_id=message.chat.id)
    if spent is None:
        await message.reply("💎 Недостаточно руды для складчины.")
        return
    await add_clan_treasury(clan["id"], amount)
    fresh = await get_clan(clan["id"])
    await message.reply(
        f"💰 {mention_html(user)} вносит <b>{format_mana(amount)}</b> в казну клана "
        f"<b>«{escape_html(clan['name'])}»</b>.\nКазна клана: <b>{format_mana(fresh['treasury'])}</b>.",
        parse_mode="HTML",
    )


@router.message(Command("clan"), _GROUP)
async def cmd_clan(message: Message) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) >= 2:
        clan = await get_clan_by_name(message.chat.id, args[1].strip())
    else:
        clan = await get_user_clan(message.chat.id, message.from_user.id)
    if not clan:
        await message.reply("🏛 Ты не в клане. Создай: /createclan · вступи: /joinclan · топ: /clans")
        return
    count = await clan_member_count(clan["id"])
    await message.reply(
        f"🏛 <b>КЛАН «{escape_html(clan['name'])}»</b>\n\n"
        f"👑 Лидер: {mention_html_raw(clan['leader_id'], 'охотник')}\n"
        f"⚔️ Бойцов: <b>{count}</b>\n"
        f"💰 Казна: <b>{format_mana(clan['treasury'])}</b>\n\n"
        f"Складчина: <code>/clandonate сумма</code>",
        parse_mode="HTML",
    )


@router.message(Command("clans"), _GROUP)
async def cmd_clans(message: Message) -> None:
    rows = await top_clans(message.chat.id, 10)
    if not rows:
        await message.reply("🏛 В этом чате ещё нет кланов. Основай первый: /createclan")
        return
    medals = ["🥇", "🥈", "🥉"] + ["▫️"] * 7
    lines = "\n".join(
        f"{medals[i]} <b>{escape_html(c['name'])}</b> — {c['members']} бойцов · "
        f"{format_mana(c['treasury'])}"
        for i, c in enumerate(rows)
    )
    await message.reply(f"🏆 <b>ТОП КЛАНОВ ЧАТА</b>\n\n{lines}", parse_mode="HTML")


# ── Браки ─────────────────────────────────────────────────────────────────────

@router.message(Command("marry"), _GROUP, F.reply_to_message)
async def cmd_marry(message: Message) -> None:
    a = message.from_user
    b = message.reply_to_message.from_user
    if not b or b.is_bot or b.id == a.id:
        await message.reply("⚠️ Сделай предложение живому охотнику (ответом на его сообщение).")
        return
    if await get_marriage(message.chat.id, a.id):
        await message.reply("💔 Ты уже в браке. Сначала /divorce.")
        return
    if await get_marriage(message.chat.id, b.id):
        await message.reply("💔 Этот охотник уже в браке.")
        return
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="💍 Согласиться", callback_data=f"marry:yes:{a.id}:{b.id}"),
        InlineKeyboardButton(text="🙅 Отказать", callback_data=f"marry:no:{a.id}:{b.id}"),
    )
    await message.answer(
        f"💍 <b>ПРЕДЛОЖЕНИЕ СОЮЗА</b>\n\n"
        f"{mention_html(a)} зовёт {mention_html(b)} в союз охотников!\n"
        f"{mention_html(b)}, твой ответ?",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )


@router.message(Command("marry"), _GROUP)
async def cmd_marry_help(message: Message) -> None:
    await message.reply("💍 Ответь на сообщение охотника командой /marry, чтобы сделать предложение.")


@router.callback_query(F.data.startswith("marry:"))
async def cb_marry(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    if len(parts) != 4:
        await call.answer()
        return
    _, decision, a_id, b_id = parts
    a_id, b_id = int(a_id), int(b_id)
    if not call.from_user or call.from_user.id != b_id:
        await call.answer("Это предложение адресовано не тебе.", show_alert=True)
        return
    if decision == "no":
        await call.message.edit_text("💔 Предложение отклонено. Союз не состоялся.")
        await call.answer()
        return
    if await get_marriage(call.message.chat.id, a_id) or await get_marriage(call.message.chat.id, b_id):
        await call.message.edit_text("💔 Поздно — кто-то уже связал себя узами.")
        await call.answer()
        return
    await create_marriage(call.message.chat.id, a_id, b_id)
    await call.message.edit_text(
        f"💞 <b>СОЮЗ ЗАКЛЮЧЁН!</b>\n\n"
        f"{mention_html_raw(a_id, 'охотник')} и {mention_html_raw(b_id, 'охотник')} "
        f"теперь пара по версии Системы. Совет да руда!",
        parse_mode="HTML",
    )
    await call.answer("💍")


@router.message(Command("divorce"), _GROUP)
async def cmd_divorce(message: Message) -> None:
    ok = await divorce(message.chat.id, message.from_user.id)
    await message.reply("💔 Союз расторгнут." if ok else "🙂 Ты не в браке.")


# ── Групповой рейд ────────────────────────────────────────────────────────────

@router.message(Command("raid"), _GROUP)
async def cmd_raid(message: Message, bot: Bot) -> None:
    chat_id = message.chat.id
    if _raids.get(chat_id, {}).get("open"):
        await message.reply("⚔️ Рейд уже идёт! Жми кнопку под сообщением, чтобы вступить.")
        return
    _raids[chat_id] = {"users": set(), "open": True}
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="⚔️ Вступить в рейд", callback_data="raid:join"))
    sent = await message.answer(
        f"🐉 <b>РЕЙД НА ПОДЗЕМЕЛЬЕ!</b>\n\n"
        f"Система открыла врата на <b>{RAID_WINDOW} сек</b>. Собирайте отряд!\n"
        f"Каждый участник получит <b>{format_mana(RAID_REWARD)}</b> "
        f"(раз в день).\n\n<i>Жми кнопку ниже, охотник.</i>",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )
    asyncio.create_task(_close_raid(bot, chat_id, sent))


async def _close_raid(bot: Bot, chat_id: int, sent: Message) -> None:
    await asyncio.sleep(RAID_WINDOW)
    raid = _raids.get(chat_id)
    if not raid:
        return
    raid["open"] = False
    users = list(raid["users"])
    _raids.pop(chat_id, None)
    if not users:
        try:
            await sent.edit_text("🚪 Врата закрылись. Отряд не собрался — рейд провален.")
        except Exception:
            pass
        return
    rewarded = 0
    for uid in users:
        if await got_reason_today(uid, "raid"):
            continue
        await add_mana(uid, RAID_REWARD, "raid", chat_id=chat_id)
        rewarded += 1
    try:
        await sent.edit_text(
            f"🏆 <b>РЕЙД ЗАВЕРШЁН!</b>\n\n"
            f"Отряд из <b>{len(users)}</b> охотников зачистил подземелье.\n"
            f"Награду получили: <b>{rewarded}</b> (остальные уже ходили в рейд сегодня).",
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.callback_query(F.data == "raid:join")
async def cb_raid_join(call: CallbackQuery) -> None:
    raid = _raids.get(call.message.chat.id) if call.message else None
    if not raid or not raid.get("open"):
        await call.answer("Рейд уже закрыт.", show_alert=True)
        return
    if call.from_user.id in raid["users"]:
        await call.answer("Ты уже в отряде, охотник.")
        return
    raid["users"].add(call.from_user.id)
    await call.answer("⚔️ Ты в отряде!")
