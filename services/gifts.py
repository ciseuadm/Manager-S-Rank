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


_gift_id_cache: dict[int, str] = {}
_cache_lock = asyncio.Lock()


def get_catalog() -> list[GiftOffer]:
    cfg = get_config()
    return build_gift_catalog(
        mana_per_rub=cfg.mana_per_rub,
        usd_cents_per_1000=cfg.stars_usd_cents_per_1000,
        usd_rub=cfg.usd_rub_rate,
        margin_pct=cfg.redeem_margin_pct,
    )


async def resolve_gift_id(bot: Bot, stars: int) -> Optional[str]:
    """Найти gift_id по цене в ⭐ (кэш на сессию)."""
    async with _cache_lock:
        if stars in _gift_id_cache:
            return _gift_id_cache[stars]

    try:
        gifts = await bot.get_available_gifts()
    except Exception as e:
        logger.warning(f"[GIFTS] get_available_gifts failed: {e}")
        return None

    items = getattr(gifts, "gifts", None) or []
    # Берём самый дешёвый подарок с нужной star_count (не sold out).
    candidates = [
        g for g in items
        if getattr(g, "star_count", 0) == stars
        and (getattr(g, "remaining_count", 1) or 1) > 0
    ]
    if not candidates:
        # Fallback: ближайший по цене (если TG изменил номиналы).
        candidates = sorted(
            [g for g in items if (getattr(g, "remaining_count", 1) or 1) > 0],
            key=lambda g: abs(getattr(g, "star_count", 0) - stars),
        )
    if not candidates:
        return None

    gid = str(getattr(candidates[0], "id", ""))
    if gid:
        _gift_id_cache[stars] = gid
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
    gift_id = await resolve_gift_id(bot, offer.stars)
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
