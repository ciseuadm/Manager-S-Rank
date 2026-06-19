"""
Pro-подписка чата за Telegram Stars.

Pro-чат получает премиум Системы: расширенную аналитику (/modstats за 90 дней),
повышенные лимиты триггеров и Pro-бейдж. Покупает админ чата командой /pro;
счёт выставляется в ⭐, активация — после оплаты (handlers/payments.py).
"""
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, LabeledPrice, InlineKeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from database import get_chat_settings
from utils import require_admin, get_config, is_chat_pro

router = Router()
_GROUP = F.chat.type.in_({"group", "supergroup"})


def _pro_status_line(settings: dict) -> str:
    if not is_chat_pro(settings):
        return "Статус: <b>обычный чат</b>."
    until = str(settings.get("pro_until") or "")[:10]
    return f"Статус: ⭐ <b>PRO</b> активен до {until}."


@router.message(Command("pro"), _GROUP)
async def cmd_pro(message: Message, bot: Bot) -> None:
    if not await require_admin(message, bot):
        return
    cfg = get_config()
    if not (cfg.pro_chat_enabled and cfg.payments_enabled):
        await message.reply("💤 Pro-подписка временно недоступна.")
        return

    settings = await get_chat_settings(message.chat.id)
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text=f"⭐ 30 дней — {cfg.pro_price_30_stars}",
        callback_data=f"pro:{message.chat.id}:30",
    ))
    kb.row(InlineKeyboardButton(
        text=f"⭐ 90 дней — {cfg.pro_price_90_stars} (выгодно)",
        callback_data=f"pro:{message.chat.id}:90",
    ))
    await message.reply(
        "⭐ <b>PRO-ЧАТ</b>\n\n"
        f"{_pro_status_line(settings)}\n\n"
        "Что даёт Pro:\n"
        f"• 📊 аналитика /modstats за <b>{cfg.pro_analytics_days} дней</b> (вместо 7)\n"
        f"• 🧩 лимит триггеров до <b>{cfg.pro_triggers_limit}</b>\n"
        "• ⭐ Pro-бейдж и приоритет поддержки\n\n"
        "Выбери срок — счёт придёт тебе в ЛС бота:",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("pro:"))
async def cb_pro(call: CallbackQuery, bot: Bot) -> None:
    parts = (call.data or "").split(":")
    if len(parts) != 3 or not parts[1].lstrip("-").isdigit() or not parts[2].isdigit():
        await call.answer()
        return
    chat_id = int(parts[1])
    days = int(parts[2])

    cfg = get_config()
    # Покупать Pro может только админ этого чата.
    from utils import is_chat_admin
    if not await is_chat_admin(bot, chat_id, call.from_user.id):
        await call.answer("Только админ чата может купить Pro.", show_alert=True)
        return

    price = cfg.pro_price_90_stars if days == 90 else cfg.pro_price_30_stars
    try:
        await bot.send_invoice(
            chat_id=call.from_user.id,
            title=f"Pro-чат · {days} дней",
            description=(
                f"Премиум-режим Системы для чата на {days} дней: расширенная "
                f"аналитика, повышенные лимиты, Pro-бейдж."
            ),
            payload=f"pro:{chat_id}:{days}",
            currency="XTR",
            prices=[LabeledPrice(label=f"Pro {days} дн.", amount=price)],
            provider_token="",
        )
        await call.answer("Счёт отправлен тебе в ЛС бота ⭐", show_alert=True)
    except Exception as e:
        logger.warning(f"[PRO] invoice error: {e}")
        await call.answer(
            "Не удалось выставить счёт. Открой бота в ЛС (/start) и повтори.",
            show_alert=True,
        )
