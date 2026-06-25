"""
Курсы и каталог обмена Мана-руды.

Базовый пег для пользователя: 50 руды = 1 ₽.
Себестоимость Stars (для расчёта подарков):
  1000 ⭐ = $16.20, $1 = 76 ₽  →  1 ⭐ ≈ 1.23 ₽ ≈ 62 руды себестоимости.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# ── Базовые константы (можно переопределить через config / .env) ─────────────

MANA_PER_RUB_DEFAULT = 50
STARS_PER_1000_USD_CENTS_DEFAULT = 1620   # $16.20 за 1000 ⭐
USD_RUB_RATE_DEFAULT = 76
REDEEM_MARGIN_PCT_DEFAULT = 30            # наценка на подарки поверх себестоимости


@dataclass(frozen=True)
class GiftOffer:
    key: str
    stars: int
    mana_price: int
    emoji: str
    title: str
    subtitle: str
    collectible: bool = False
    # Живые данные из getAvailableGifts (заполняются в services.gifts.get_live_catalog):
    gift_id: str = ""             # реальный id подарка в Telegram (для точной отправки)
    remaining: Optional[int] = None   # остаток лимитированного подарка; None = без лимита


def star_rub(stars: int, *, usd_cents_per_1000: int, usd_rub: int) -> float:
    return stars * (usd_cents_per_1000 / 1000 / 100) * usd_rub


def star_mana_cost(
    stars: int,
    *,
    mana_per_rub: int,
    usd_cents_per_1000: int,
    usd_rub: int,
) -> int:
    return int(round(star_rub(stars, usd_cents_per_1000=usd_cents_per_1000, usd_rub=usd_rub) * mana_per_rub))


def mana_with_margin(base: int, margin_pct: int) -> int:
    raw = base * (100 + margin_pct) / 100
    # Округляем до «красивых» сотен вверх.
    step = 100 if raw < 5000 else 500 if raw < 20000 else 1000
    return int((raw + step - 1) // step * step)


def build_gift_catalog(
    *,
    mana_per_rub: int = MANA_PER_RUB_DEFAULT,
    usd_cents_per_1000: int = STARS_PER_1000_USD_CENTS_DEFAULT,
    usd_rub: int = USD_RUB_RATE_DEFAULT,
    margin_pct: int = REDEEM_MARGIN_PCT_DEFAULT,
) -> list[GiftOffer]:
    """Поштучная витрина подарков Telegram (как нативная панель «Отправить
    подарок»), но цены сразу в Мана-руде. Каждый пункт — конкретный подарок:
    при обмене бот подбирает в каталоге Telegram подарок этого номинала ⭐ и,
    по возможности, ровно с этим эмодзи (см. services.gifts.resolve_gift_id).

    collectible=True — «премиальные» дорогие подарки (вкладка «Премиум»)."""
    # (key, stars, emoji, title, collectible)
    items: list[tuple[str, int, str, str, bool]] = [
        ("heart",   15,  "💝", "Сердечко", False),
        ("teddy",   15,  "🧸", "Мишка",    False),
        ("giftbox", 25,  "🎁", "Подарок",  False),
        ("rose",    25,  "🌹", "Роза",     False),
        ("cake",    50,  "🎂", "Торт",     False),
        ("bouquet", 50,  "💐", "Букет",    False),
        ("rocket",  50,  "🚀", "Ракета",   False),
        ("trophy",  100, "🏆", "Кубок",    True),
        ("ring",    100, "💍", "Кольцо",   True),
        ("diamond", 100, "💎", "Алмаз",    True),
    ]
    out: list[GiftOffer] = []
    for key, stars, emoji, title, collectible in items:
        base = star_mana_cost(
            stars,
            mana_per_rub=mana_per_rub,
            usd_cents_per_1000=usd_cents_per_1000,
            usd_rub=usd_rub,
        )
        out.append(GiftOffer(
            key=key,
            stars=stars,
            mana_price=mana_with_margin(base, margin_pct),
            emoji=emoji,
            title=title,
            subtitle=f"Подарок Telegram · {stars} ⭐",
            collectible=collectible,
        ))
    return out


def gift_by_key(catalog: list[GiftOffer], key: str) -> GiftOffer | None:
    return next((g for g in catalog if g.key == key), None)


def gift_by_mana(catalog: list[GiftOffer], mana: int) -> GiftOffer | None:
    return next((g for g in catalog if g.mana_price == mana), None)


def tasks_to_gift(gift: GiftOffer, task_reward: int = 50) -> int:
    """Сколько подписок (~task_reward руды) нужно для подарка."""
    if task_reward <= 0:
        return 0
    return (gift.mana_price + task_reward - 1) // task_reward
