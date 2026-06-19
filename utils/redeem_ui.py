"""UI для /redeem — вынесено из handlers, чтобы shop мог переиспользовать."""
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.gifts import get_catalog
from utils import get_config, format_mana, ce
from utils.economy_rates import tasks_to_gift


def redeem_intro(balance: int) -> str:
    cfg = get_config()
    catalog = get_catalog()
    cheapest = catalog[0] if catalog else None
    lines = [
        f"{ce('gift')} <b>ОБМЕН РУДЫ НА ПОДАРКИ TELEGRAM</b>\n",
        f"{ce('coin')} Баланс: <b>{format_mana(balance)}</b>",
        f"{ce('chart')} Курс: <b>{cfg.mana_per_rub} руды = 1 ₽</b>",
        f"{ce('tasks')} Задание-подписка: <b>+{cfg.task_reward_subscribe}</b> руды (~1 ₽ тебе)\n",
    ]
    if cheapest:
        subs = tasks_to_gift(cheapest, cfg.task_reward_subscribe)
        lines.append(
            f"{ce('target')} Первый подарок ({cheapest.stars} {ce('star')}): "
            f"<b>{format_mana(cheapest.mana_price)}</b> (≈ {subs} подписок)\n"
        )
    lines.append(
        f"{ce('rocket')} Выбери подарок ниже — Система отправит его в Telegram.\n"
        f"<i>{ce('warn')} Не отписывайся от каналов заданий — иначе руда отзывается.</i>"
    )
    return "\n".join(lines)


def redeem_keyboard(balance: int) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    for g in get_catalog():
        ok = balance >= g.mana_price
        prefix = "" if ok else "🔒 "
        b.row(InlineKeyboardButton(
            text=f"{prefix}{g.emoji} {g.title} — {format_mana(g.mana_price)}",
            callback_data=f"redeem:{g.key}",
        ))
    b.row(InlineKeyboardButton(text="✖ Закрыть", callback_data="redeem:close"))
    return b
