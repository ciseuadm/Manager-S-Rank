"""
Payments via Telegram Stars (XTR).

Sells Мана-руда packs and accepts donations. Telegram Stars need no external
provider: currency='XTR', provider_token='' , price amount = number of stars.
"""
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, LabeledPrice, PreCheckoutQuery,
)
from loguru import logger

from database import add_mana, add_payment, get_payment_by_charge
from utils import get_config, format_mana

router = Router()


# Пакеты Мана-руды: (id, stars, mana). Чем больше пакет — тем выгоднее курс.
MANA_PACKS = [
    (1, 50, 6000),
    (2, 100, 13000),
    (3, 250, 35000),
    (4, 500, 75000),
    (5, 1000, 160000),
]
_PACKS_BY_ID = {p[0]: p for p in MANA_PACKS}

# Сколько руды дарим за 1 звезду доната (благодарность).
DONATE_MANA_PER_STAR = 120


def _buy_keyboard():
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    for pid, stars, mana in MANA_PACKS:
        b.row(InlineKeyboardButton(
            text=f"⭐ {stars} → {mana:,} руды".replace(",", " "),
            callback_data=f"buy:{pid}",
        ))
    b.row(InlineKeyboardButton(text="✖ Закрыть", callback_data="buy:close"))
    return b.as_markup()


# ── /buy — витрина пакетов руды ──────────────────────────────────────────────

@router.message(Command("buy", "topup"))
async def cmd_buy(message: Message) -> None:
    cfg = get_config()
    if not cfg.payments_enabled:
        await message.answer("💤 Покупки временно отключены.")
        return
    if message.chat.type != "private":
        await message.reply(
            "💳 Пополнение доступно в личке бота.\n"
            "Открой меня в ЛС и отправь /buy."
        )
        return
    await message.answer(
        "🔹 <b>МАГАЗИН МАНА-РУДЫ</b>\n\n"
        "Пополни запас руды за Telegram Stars ⭐.\n"
        "Чем больше пакет — тем выгоднее курс.\n\n"
        "Выбери пакет:",
        parse_mode="HTML",
        reply_markup=_buy_keyboard(),
    )


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(call: CallbackQuery, bot: Bot) -> None:
    action = call.data.split(":")[1]
    if action == "close":
        try:
            await call.message.delete()
        except Exception:
            pass
        await call.answer()
        return

    if not action.isdigit() or int(action) not in _PACKS_BY_ID:
        await call.answer("Пакет не найден.", show_alert=True)
        return

    pid, stars, mana = _PACKS_BY_ID[int(action)]
    try:
        await bot.send_invoice(
            chat_id=call.from_user.id,
            title=f"Мана-руда ×{mana}",
            description=f"{mana} Мана-руды для твоего охотника. Оплата {stars} Telegram Stars.",
            payload=f"mana:{pid}",
            currency="XTR",
            prices=[LabeledPrice(label=f"{mana} руды", amount=stars)],
            provider_token="",
        )
        await call.answer("Счёт отправлен ⭐")
    except Exception as e:
        logger.warning(f"[PAY] invoice error: {e}")
        await call.answer("Не удалось выставить счёт. Открой бота в ЛС.", show_alert=True)


# ── /donate — поддержать проект ──────────────────────────────────────────────

@router.message(Command("donate", "support"))
async def cmd_donate(message: Message, bot: Bot) -> None:
    cfg = get_config()
    if not cfg.payments_enabled:
        await message.answer("💤 Платежи временно отключены.")
        return
    args = (message.text or "").split()
    stars = 50
    for a in args[1:]:
        if a.isdigit():
            stars = max(1, min(int(a), 100000))
            break
    bonus = stars * DONATE_MANA_PER_STAR
    try:
        await bot.send_invoice(
            chat_id=message.from_user.id,
            title="Поддержка Системы",
            description=f"Спасибо за поддержку! Бонусом получишь {bonus} Мана-руды.",
            payload="donate",
            currency="XTR",
            prices=[LabeledPrice(label=f"Донат {stars}⭐", amount=stars)],
            provider_token="",
        )
        if message.chat.type != "private":
            await message.reply("💛 Счёт на поддержку отправлен тебе в ЛС.")
    except Exception as e:
        logger.warning(f"[PAY] donate invoice error: {e}")
        await message.reply("Не удалось выставить счёт. Открой бота в ЛС и повтори.")


# ── Pre-checkout: подтверждаем готовность принять платёж ─────────────────────

@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery) -> None:
    await query.answer(ok=True)


# ── Успешная оплата: начисляем товар ─────────────────────────────────────────

@router.message(F.successful_payment)
async def on_successful_payment(message: Message) -> None:
    sp = message.successful_payment
    user_id = message.from_user.id
    charge_id = sp.telegram_payment_charge_id
    stars = sp.total_amount  # для XTR это количество звёзд
    payload = sp.invoice_payload or ""

    # Идемпотентность: один charge_id обрабатываем один раз.
    if await get_payment_by_charge(charge_id):
        return

    if payload.startswith("mana:"):
        pid = payload.split(":")[1]
        pack = _PACKS_BY_ID.get(int(pid)) if pid.isdigit() else None
        mana = pack[2] if pack else stars * DONATE_MANA_PER_STAR
        await add_mana(user_id, mana, "purchase", ref_id=charge_id)
        await add_payment(user_id, stars, "mana_pack", str(pid), charge_id)
        await message.answer(
            f"✅ <b>Оплата получена!</b>\n\n"
            f"Начислено: <b>{format_mana(mana)}</b>\n"
            f"Спасибо, охотник. Сила прибывает ⚡",
            parse_mode="HTML",
        )
    elif payload == "donate":
        bonus = stars * DONATE_MANA_PER_STAR
        await add_mana(user_id, bonus, "donate", ref_id=charge_id)
        await add_payment(user_id, stars, "donate", "", charge_id)
        await message.answer(
            f"💛 <b>Спасибо за поддержку Системы!</b>\n\n"
            f"Твой вклад держит дозорного в строю 24/7.\n"
            f"Бонусом: <b>{format_mana(bonus)}</b>",
            parse_mode="HTML",
        )
    else:
        await add_payment(user_id, stars, "unknown", payload, charge_id)
