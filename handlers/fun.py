"""
Развлекательные команды — бесплатно, без затрат для владельца.
Добавляют атмосферу Solo Leveling и повод вернуться в чат.
"""
import random

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message

router = Router()

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


@router.message(Command("duel"), F.reply_to_message)
async def cmd_duel(message: Message) -> None:
    if not message.from_user or not message.reply_to_message.from_user:
        return
    a = message.from_user
    b = message.reply_to_message.from_user
    if b.is_bot:
        await message.reply("🤖 С ботами дuel не проводят — только с охотниками.")
        return
    pa, pb = random.randint(50, 999), random.randint(50, 999)
    if pa == pb:
        pa += random.randint(1, 50)
    if pa > pb:
        winner, loser, wp = a, b, pa
    else:
        winner, loser, wp = b, a, pb
    tpl = random.choice(_DUEL_WIN)
    await message.answer(
        tpl.format(
            winner=f"<b>{winner.full_name}</b>",
            loser=f"<b>{loser.full_name}</b>",
            power=wp,
        ),
        parse_mode="HTML",
    )


@router.message(Command("duel"))
async def cmd_duel_help(message: Message) -> None:
    await message.answer(
        "⚔️ <b>ДУЭЛЬ ОХОТНИКОВ</b>\n\n"
        "Ответь на сообщение соперника командой /duel — "
        "Система определит победителя по «силе тени».",
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
