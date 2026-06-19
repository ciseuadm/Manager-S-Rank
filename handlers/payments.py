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

from database import (
    add_mana, add_payment, get_payment_by_charge,
    set_payment_status, revert_mana,
)
from utils import get_config, format_mana, is_owner
from utils.media import answer_with_banner

router = Router()


# Пакеты Мана-руды: (id, stars, mana). Заработок через /tasks выгоднее покупки.
MANA_PACKS = [
    (1, 50, 2500),
    (2, 100, 5500),
    (3, 250, 15000),
    (4, 500, 32000),
    (5, 1000, 70000),
]
_PACKS_BY_ID = {p[0]: p for p in MANA_PACKS}

# Бонус за донат: ~50 руды за 1 ⭐ (курс близок к пегу, но без маржи магазина).
DONATE_MANA_PER_STAR = 50


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
    await answer_with_banner(
        message,
        "buy",
        "🔹 <b>МАГАЗИН МАНА-РУДЫ</b>\n\n"
        "Пополни запас руды за Telegram Stars ⭐.\n"
        "Чем больше пакет — тем выгоднее курс.\n\n"
        "Выбери пакет:",
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


def _valid_pro_payload(payload: str) -> bool:
    # pro:<chat_id>:<days> — chat_id может быть отрицательным.
    if not payload.startswith("pro:"):
        return False
    parts = payload.split(":")
    return (
        len(parts) == 3
        and parts[1].lstrip("-").isdigit()
        and parts[2].isdigit()
    )


# ── Pre-checkout: подтверждаем готовность принять платёж ─────────────────────

@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery) -> None:
    payload = query.invoice_payload or ""
    ok = payload == "donate" or (
        payload.startswith("mana:")
        and payload.split(":", 1)[1].isdigit()
        and int(payload.split(":", 1)[1]) in _PACKS_BY_ID
    ) or (
        payload.startswith("adreq:") and payload.split(":", 1)[1].isdigit()
    ) or _valid_pro_payload(payload)
    if ok:
        await query.answer(ok=True)
    else:
        logger.warning(f"[PAY] rejected pre_checkout, bad payload: {payload!r}")
        await query.answer(ok=False, error_message="Счёт устарел. Открой /buy и повтори.")


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
    elif payload.startswith("adreq:"):
        # Self-serve реклама: оплата в эскроу. Задание НЕ создаётся автоматически —
        # заявка лишь встаёт в очередь ручной модерации владельца.
        from services import confirm_ad_payment
        req_id = int(payload.split(":", 1)[1])
        await add_payment(user_id, stars, "ad", str(req_id), charge_id)
        req = await confirm_ad_payment(req_id, stars, charge_id)
        await message.answer(
            "✅ <b>Оплата получена!</b>\n\n"
            f"Заявка №{req_id} ушла на модерацию. Деньги в эскроу: если канал "
            "не подойдёт — вернём полностью. Уведомим о запуске. Спасибо!",
            parse_mode="HTML",
        )
        if req:
            try:
                from handlers.sponsors import _notify_owner_new_request
                await _notify_owner_new_request(message.bot, req_id)
            except Exception as e:
                logger.warning(f"[PAY] owner notify (adreq) failed: {e}")
    elif _valid_pro_payload(payload):
        # Pro-подписка чата: включаем/продлеваем и уведомляем покупателя и чат.
        from database import set_chat_pro
        _, chat_raw, days_raw = payload.split(":")
        target_chat = int(chat_raw)
        days = int(days_raw)
        until = await set_chat_pro(target_chat, days)
        await add_payment(user_id, stars, "pro_chat", f"{target_chat}:{days}", charge_id)
        until_d = until[:10]
        await message.answer(
            "✅ <b>Pro-чат активирован!</b>\n\n"
            f"Срок: <b>+{days} дн.</b> (до {until_d}).\n"
            "Расширенная аналитика (/modstats за 90 дней), повышенные лимиты "
            "триггеров и Pro-бейдж уже работают. Спасибо!",
            parse_mode="HTML",
        )
        try:
            await message.bot.send_message(
                target_chat,
                "⭐ <b>Этот чат получил Pro!</b>\n"
                f"Премиум-режим Системы активен до {until_d}.",
                parse_mode="HTML",
            )
        except Exception:
            pass
    else:
        await add_payment(user_id, stars, "unknown", payload, charge_id)


# ── /refund — возврат Stars владельцем ───────────────────────────────────────

def _granted_mana(payment: dict) -> int:
    """Сколько руды было начислено за платёж — чтобы списать при возврате."""
    product = payment.get("product")
    stars = payment.get("stars", 0)
    if product == "mana_pack":
        ref = str(payment.get("product_ref") or "")
        pack = _PACKS_BY_ID.get(int(ref)) if ref.isdigit() else None
        return pack[2] if pack else stars * DONATE_MANA_PER_STAR
    if product == "donate":
        return stars * DONATE_MANA_PER_STAR
    return 0


@router.message(Command("refund"))
async def cmd_refund(message: Message, bot: Bot) -> None:
    if not is_owner(message.from_user.id if message.from_user else None):
        return
    args = (message.text or "").split()
    if len(args) < 2:
        await message.answer(
            "↩️ <b>Возврат Stars</b>\n\n"
            "Использование: <code>/refund &lt;charge_id&gt;</code>\n"
            "charge_id берётся из таблицы платежей (telegram_payment_charge_id).\n"
            "Я верну звёзды пользователю и спишу начисленную за них руду.",
            parse_mode="HTML",
        )
        return

    charge_id = args[1].strip()
    pay = await get_payment_by_charge(charge_id)
    if not pay:
        await message.answer("❌ Платёж с таким charge_id не найден.")
        return
    if pay.get("status") == "refunded":
        await message.answer("ℹ️ Этот платёж уже возвращён ранее.")
        return

    user_id = pay["user_id"]
    try:
        await bot.refund_star_payment(
            user_id=user_id, telegram_payment_charge_id=charge_id,
        )
    except Exception as e:
        logger.warning(f"[PAY] refund failed {charge_id}: {e}")
        await message.answer(f"❌ Не удалось вернуть Stars: <code>{e}</code>", parse_mode="HTML")
        return

    await set_payment_status(charge_id, "refunded")
    clawback = _granted_mana(pay)
    if clawback > 0:
        await revert_mana(user_id, clawback, "refund", ref_id=charge_id)

    await message.answer(
        f"✅ Возврат <b>{pay.get('stars', 0)}⭐</b> пользователю "
        f"<code>{user_id}</code> выполнен.\n"
        f"Списано руды: <b>{format_mana(clawback)}</b>.",
        parse_mode="HTML",
    )
    try:
        await bot.send_message(
            user_id,
            "↩️ <b>Возврат средств</b>\n\n"
            f"Система вернула тебе <b>{pay.get('stars', 0)}⭐</b>. "
            "Соответствующая руда списана с баланса.",
            parse_mode="HTML",
        )
    except Exception:
        pass
