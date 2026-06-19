"""UI для /redeem — вынесено из handlers, чтобы shop мог переиспользовать."""
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.gifts import get_catalog
from utils import format_mana, ce


def redeem_intro(balance: int) -> str:
    return (
        f"{ce('gift')} <b>ОБМЕН РУДЫ НА ПОДАРКИ TELEGRAM</b>\n\n"
        f"{ce('coin')} Твоя Мана-руда: <b>{format_mana(balance)}</b>\n\n"
        "Выбери подарок ниже — Система мгновенно отправит его прямо в твой Telegram.\n\n"
        f"<i>{ce('tasks')} Чем больше руды добудешь в заданиях и подземельях — "
        f"тем ценнее награды. {ce('spark')}</i>"
    )


def redeem_keyboard(balance: int) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    for g in get_catalog():
        ok = balance >= g.mana_price
        prefix = "" if ok else "🔒 "
        b.row(InlineKeyboardButton(
            text=f"{prefix}{g.emoji} {g.title} — {format_mana(g.mana_price)}",
            callback_data=f"redeem:{g.key}",
        ))
    return b
