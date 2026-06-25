"""
Отправка Telegram-подарков за Мана-руду (Bot API sendGift).
"""
from __future__ import annotations

import asyncio
from typing import Optional

from aiogram import Bot
from loguru import logger

from utils import get_config
from utils.economy_rates import GiftOffer, build_gift_catalog, gift_by_key


_gift_id_cache: dict[str, str] = {}
_cache_lock = asyncio.Lock()


def get_catalog() -> list[GiftOffer]:
    cfg = get_config()
    return build_gift_catalog(
        mana_per_rub=cfg.mana_per_rub,
        usd_cents_per_1000=cfg.stars_usd_cents_per_1000,
        usd_rub=cfg.usd_rub_rate,
        margin_pct=cfg.redeem_margin_pct,
    )


def _gift_emoji(g) -> str:
    return str(getattr(getattr(g, "sticker", None), "emoji", "") or "")


async def resolve_gift_id(bot: Bot, stars: int, emoji: str = "") -> Optional[str]:
    """Найти gift_id по цене в ⭐ и (по возможности) по эмодзи (кэш на сессию).

    Сначала ищем подарок ровно нужного номинала и с тем же эмодзи (Сердечко,
    Роза и т.д.), чтобы пользователь получил именно выбранный подарок. Если
    такого нет — берём любой того же номинала, иначе ближайший по цене.
    """
    cache_key = f"{stars}:{emoji}"
    async with _cache_lock:
        if cache_key in _gift_id_cache:
            return _gift_id_cache[cache_key]

    try:
        gifts = await bot.get_available_gifts()
    except Exception as e:
        logger.warning(f"[GIFTS] get_available_gifts failed: {e}")
        return None

    items = getattr(gifts, "gifts", None) or []

    def available(g) -> bool:
        return (getattr(g, "remaining_count", 1) or 1) > 0

    same_price = [
        g for g in items
        if getattr(g, "star_count", 0) == stars and available(g)
    ]
    chosen = None
    if emoji:
        chosen = next((g for g in same_price if _gift_emoji(g) == emoji), None)
    if chosen is None and same_price:
        chosen = same_price[0]
    if chosen is None:
        # Fallback: ближайший по цене (если TG изменил номиналы).
        nearest = sorted(
            [g for g in items if available(g)],
            key=lambda g: abs(getattr(g, "star_count", 0) - stars),
        )
        chosen = nearest[0] if nearest else None
    if chosen is None:
        return None

    gid = str(getattr(chosen, "id", ""))
    if gid:
        _gift_id_cache[cache_key] = gid
    return gid or None


async def send_telegram_gift(
    bot: Bot,
    user_id: int,
    offer: GiftOffer,
    *,
    text: str = "",
) -> tuple[bool, str]:
    """
    Отправить подарок пользователю. Возвращает (ok, message).
    Бот тратит свои ⭐ с баланса.
    """
    gift_id = await resolve_gift_id(bot, offer.stars, offer.emoji)
    if not gift_id:
        return False, (
            f"Не найден подарок за {offer.stars} ⭐ в каталоге Telegram. "
            "Пополни баланс ⭐ бота и проверь доступные подарки."
        )

    msg = text or (
        f"🎁 <b>СИСТЕМА ВРУЧАЕТ НАГРАДУ</b>\n\n"
        f"Охотник, ты обменял добытую Мана-руду на {offer.title}. "
        "Меньше пары минут — и Система материализовала трофей из подземелья "
        "прямо в твой Telegram. ⚡\n\n"
        "<i>Так работает сильнейший. Возвращайся за новыми наградами — "
        "впереди трофеи дороже. 👑</i>"
    )
    try:
        ok = await bot.send_gift(
            gift_id=gift_id,
            user_id=user_id,
            text=msg,
            text_parse_mode="HTML",
        )
        if ok:
            logger.info(f"[GIFTS] sent {offer.key} ({offer.stars}⭐) → user {user_id}")
            return True, "Подарок отправлен."
        return False, "Telegram вернул ошибку при отправке подарка."
    except Exception as e:
        logger.warning(f"[GIFTS] send_gift failed user={user_id} stars={offer.stars}: {e}")
        return False, f"Не удалось отправить подарок: {e}"


def offer_from_product(product: str) -> GiftOffer | None:
    """Разобрать product из payout_request → GiftOffer."""
    catalog = get_catalog()
    if product.startswith("gift:"):
        return gift_by_key(catalog, product.split(":", 1)[1])
    for g in catalog:
        if g.title in product or str(g.stars) in product:
            return g
    return None
