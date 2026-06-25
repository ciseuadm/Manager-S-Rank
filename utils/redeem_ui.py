"""UI для /redeem — вынесено из handlers, чтобы shop мог переиспользовать."""
from aiogram.types import InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.gifts import get_catalog
from utils import format_mana, ce, get_config


def _webapp_shop_url() -> str:
    """Публичный https-адрес витрины Mini App (с открытием сразу на вкладке
    «Магазин»), либо пусто, если Mini App не настроен."""
    cfg = get_config()
    url = (cfg.webapp_url or "").rstrip("/")
    if cfg.webapp_enabled and url.startswith("https://"):
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}tab=shop"
    return ""


def redeem_intro(balance: int, *, private: bool = False) -> str:
    # Подсказку про кнопку-витрину показываем только в личке: web_app-кнопка
    # доступна лишь там (в группах Telegram её не отрисует).
    extra = ""
    if private and _webapp_shop_url():
        extra = (
            f"\n\n{ce('rocket')} <b>Открой витрину наград</b> кнопкой вверху: "
            "все подарки плиткой, цены сразу в руде, обмен в один тап."
        )
    return (
        f"{ce('gift')} <b>ВИТРИНА НАГРАД — ОБМЕН РУДЫ НА ПОДАРКИ TELEGRAM</b>\n\n"
        f"{ce('coin')} Твоя Мана-руда: <b>{format_mana(balance)}</b>\n\n"
        "Выбери подарок — Система мгновенно отправит его прямо в твой Telegram. "
        "Платишь только добытой рудой, звёзды уже посчитаны за тебя."
        f"{extra}\n\n"
        f"<i>{ce('tasks')} Чем больше руды добудешь в заданиях и подземельях — "
        f"тем дороже подарок по силам. {ce('spark')}</i>"
    )


def redeem_keyboard(balance: int, *, private: bool = False) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    # Если Mini App настроен и мы в личке — первой даём кнопку красивой витрины
    # (плитки, как нативная панель подарков Telegram, но в руде).
    shop_url = _webapp_shop_url() if private else ""
    if shop_url:
        b.row(InlineKeyboardButton(
            text="🎁 Открыть витрину наград",
            web_app=WebAppInfo(url=shop_url),
        ))
    # Текстовый каталог (работает всегда, без хостинга): по 2 подарка в ряд —
    # компактнее и ближе к «витрине». Без замочков: обмен открыт всем; если руды
    # не хватает, об этом мягко сообщит обработчик нажатия.
    catalog = get_catalog()
    row: list[InlineKeyboardButton] = []
    for g in catalog:
        price = f"{g.mana_price:,}".replace(",", " ")
        row.append(InlineKeyboardButton(
            text=f"{g.emoji} {g.title} · 🔹 {price}",
            callback_data=f"redeem:{g.key}",
        ))
        if len(row) == 2:
            b.row(*row)
            row = []
    if row:
        b.row(*row)
    return b
