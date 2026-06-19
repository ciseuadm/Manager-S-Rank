"""
Развлекательные команды — бесплатно, без затрат для владельца.
Добавляют атмосферу Solo Leveling и повод вернуться в чат.
"""
import random

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import spend_mana, add_mana, get_wallet_balance
from utils import mention_html_raw, format_mana

router = Router()

# Дуэль на ставку: банк делится победителю минус комиссия казны (сток руды).
_DUEL_FEE_PCT = 5

_ORACLES = [
    "Система шепчет: сегодня твой ранг вырастет быстрее обычного.",
    "Тени подсказывают — удачный день для /daily и /tasks.",
    "Враta подземелья приоткрыты. Один смелый шаг изменит баланс руды.",
    "Монарх одобряет: твоя активность замечена. Не останавливайся.",
    "Предупреждение S-ранга: завтра удвоится удача в спорах — выбирай /duel.",
    "Система выдала скрытый квест: пригласи одного друга — и получишь бонус.",
    "Руны говорят: сегодня лучший момент для /invite и роста гильдии.",
    "Тёмный монарх молчит… значит, ты на верном пути.",
]

_WISHES = [
    "Пусть Мана-руда льётся в твоё хранилище без остановки.",
    "Пусть каждый твой пост повышает ранг на шаг ближе к S.",
    "Пусть модерация S-ранга всегда прикрывает тебе спину.",
    "Пусть подземелье чата приносит только победы и награды.",
]

_DUEL_WIN = [
    "⚔️ <b>ПОБЕДА В ДУЭЛИ!</b>\n\n{winner} одолел {loser}!\n"
    "Система фиксирует: сила охотника — <b>{power}</b> ед.",
    "⚡ <b>ТЕНЬ ПОБЕДИЛА!</b>\n\n{winner} → {loser}\n"
    "Мощность: <b>{power}</b>. Ранг чувствует это.",
]

_BUFFS = [
    "🔮 Баф «Острота тени»: +{pct}% к удаче в спорах на 1 час (RP).",
    "💎 Баф «Рудная жила»: Система благоволит твоему кошельку сегодня.",
    "🛡 Баф «Щит гильдии»: модераторы на твоей стороне.",
    "⚡ Баф «Разгон охотника»: сообщения в чате идут на пользу рангу.",
]


@router.message(Command("oracle", "prophecy", "oracul"))
async def cmd_oracle(message: Message) -> None:
    text = random.choice(_ORACLES)
    await message.answer(
        f"🔮 <b>ОРАКУЛ СИСТЕМЫ</b>\n\n<i>{text}</i>",
        parse_mode="HTML",
    )


@router.message(Command("wish", "bless"))
async def cmd_wish(message: Message) -> None:
    name = message.from_user.full_name if message.from_user else "охотник"
    await message.answer(
        f"✨ <b>ПОЖЕЛАНИЕ МОНАРХА</b>\n\n"
        f"Для {name}:\n<i>{random.choice(_WISHES)}</i>",
        parse_mode="HTML",
    )


@router.message(Command("luck", "buff"))
async def cmd_luck(message: Message) -> None:
    pct = random.randint(5, 25)
    text = random.choice(_BUFFS).format(pct=pct)
    await message.answer(
        f"🎲 <b>СЛУЧАЙНЫЙ БАФ</b>\n\n{text}\n\n"
        "<i>Чисто RP — но настроение точно поднимется.</i>",
        parse_mode="HTML",
    )


def _duel_power() -> tuple[int, int]:
    pa, pb = random.randint(50, 999), random.randint(50, 999)
    if pa == pb:
        pa += random.randint(1, 50)
    return pa, pb


@router.message(Command("duel"), F.reply_to_message)
async def cmd_duel(message: Message) -> None:
    if not message.from_user or not message.reply_to_message.from_user:
        return
    a = message.from_user
    b = message.reply_to_message.from_user
    if b.is_bot:
        await message.reply("🤖 С ботами дуэль не проводят — только с охотниками.")
        return

    # Ставка на руду (опционально): /duel <сумма> ответом на соперника.
    args = (message.text or "").split()
    stake = int(args[1]) if len(args) >= 2 and args[1].isdigit() and int(args[1]) > 0 else 0

    if stake:
        if await get_wallet_balance(a.id) < stake:
            await message.reply("💎 У тебя недостаточно руды для такой ставки.")
            return
        kb = InlineKeyboardBuilder()
        kb.row(
            InlineKeyboardButton(text=f"⚔️ Принять ({format_mana(stake)})",
                                 callback_data=f"duel:yes:{a.id}:{b.id}:{stake}"),
            InlineKeyboardButton(text="🏳️ Отказаться", callback_data=f"duel:no:{a.id}:{b.id}:{stake}"),
        )
        await message.answer(
            f"⚔️ <b>ВЫЗОВ НА ДУЭЛЬ!</b>\n\n"
            f"{mention_html_raw(a.id, a.full_name)} ставит <b>{format_mana(stake)}</b> "
            f"против {mention_html_raw(b.id, b.full_name)}.\n"
            f"Победитель забирает банк (комиссия казны {_DUEL_FEE_PCT}%).\n\n"
            f"{mention_html_raw(b.id, b.full_name)}, принимаешь вызов?",
            parse_mode="HTML",
            reply_markup=kb.as_markup(),
        )
        return

    pa, pb = _duel_power()
    winner, loser, wp = (a, b, pa) if pa > pb else (b, a, pb)
    tpl = random.choice(_DUEL_WIN)
    await message.answer(
        tpl.format(
            winner=f"<b>{winner.full_name}</b>",
            loser=f"<b>{loser.full_name}</b>",
            power=wp,
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("duel:"))
async def cb_duel(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    if len(parts) != 5:
        await call.answer()
        return
    _, decision, a_id, b_id, stake = parts
    a_id, b_id, stake = int(a_id), int(b_id), int(stake)
    if not call.from_user or call.from_user.id != b_id:
        await call.answer("Этот вызов адресован не тебе.", show_alert=True)
        return
    if decision == "no":
        await call.message.edit_text("🏳️ Соперник уклонился от дуэли. Поединок не состоялся.")
        await call.answer()
        return

    # Эскроу обеих ставок; при нехватке — откат.
    if await spend_mana(a_id, stake, "duel_stake", ref_id=str(b_id)) is None:
        await call.message.edit_text("💔 У зачинщика уже не хватает руды — дуэль отменена.")
        await call.answer()
        return
    if await spend_mana(b_id, stake, "duel_stake", ref_id=str(a_id)) is None:
        await add_mana(a_id, stake, "duel_refund", ref_id=str(b_id))
        await call.answer("💎 У тебя недостаточно руды для этой ставки.", show_alert=True)
        return

    pa, pb = _duel_power()
    winner_id, loser_id, wp = (a_id, b_id, pa) if pa > pb else (b_id, a_id, pb)
    pot = stake * 2
    fee = pot * _DUEL_FEE_PCT // 100
    prize = pot - fee
    await add_mana(winner_id, prize, "duel_win", ref_id=str(loser_id))
    await call.message.edit_text(
        f"⚔️ <b>ДУЭЛЬ ЗАВЕРШЕНА!</b>\n\n"
        f"Победитель: {mention_html_raw(winner_id, 'охотник')} (сила <b>{wp}</b>).\n"
        f"Банк: <b>{format_mana(pot)}</b> · комиссия казны: {format_mana(fee)}.\n"
        f"Приз победителю: <b>{format_mana(prize)}</b>.",
        parse_mode="HTML",
    )
    await call.answer("🏆")


@router.message(Command("duel"))
async def cmd_duel_help(message: Message) -> None:
    await message.answer(
        "⚔️ <b>ДУЭЛЬ ОХОТНИКОВ</b>\n\n"
        "Ответь на сообщение соперника командой <code>/duel</code> — "
        "Система определит победителя по «силе тени».\n\n"
        "💰 На ставку: <code>/duel 100</code> ответом на соперника. "
        "Победитель забирает банк (комиссия казны 5%).",
        parse_mode="HTML",
    )


@router.message(Command("dice", "roll"))
async def cmd_dice(message: Message, bot: Bot) -> None:
    sides = ["монарх", "S-ранг", "подземелье", "гильдию", "Мана-руду"]
    await message.answer(
        f"🎲 <b>БРОСОК СИСТЕМЫ</b>\n\n"
        f"Кубик решает судьбу <b>{random.choice(sides)}</b>…",
        parse_mode="HTML",
    )
    await bot.send_dice(message.chat.id, reply_to_message_id=message.message_id)
