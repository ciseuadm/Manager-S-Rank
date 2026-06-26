"""
Крипто-выплаты руды через Crypto Pay API (@CryptoBot / @CryptoTestnetBot).

Гибридная ветка вывода: поверх существующих payout_requests добавляем продукт
"crypto:<ASSET>". Перевод идёт методом `transfer` Crypto Pay — деньги уходят
на Telegram-аккаунт охотника (user_id), который хоть раз пользовался @CryptoBot.
Адрес кошелька не нужен и не хранится.

Включается, только когда заданы CRYPTO_WITHDRAW_ENABLED=1 и CRYPTO_BOT_TOKEN.
Пока токена нет — ветка работает в ручном режиме: владелец подтверждает заявку
в /payouts и переводит вручную (вся обвязка экономики и лимитов уже готова).

Курс (mana → USDT):
  Берётся из CryptoBot API (/getExchangeRates) — рыночный, обновляется каждые
  5 минут. Это защита от абуза: если зафиксировать курс в конфиге, а рынок
  пойдёт в другую сторону — игроки смогут бесконечно арбитражить против нас.
  При недоступности API — фолбэк на usd_rub_rate из конфига.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

import aiohttp
from loguru import logger

from utils import get_config


def crypto_enabled() -> bool:
    """Доступен ли крипто-вывод как опция для охотника."""
    return bool(get_config().crypto_withdraw_enabled)


def crypto_auto() -> bool:
    """Есть ли токен для АВТО-перевода (иначе — ручной режим владельца)."""
    cfg = get_config()
    return bool(cfg.crypto_withdraw_enabled and cfg.crypto_bot_token)


# ── Живой курс из CryptoBot API ──────────────────────────────────────────────

_rate_cache: dict[str, object] = {"ts": 0.0, "rates": {}}
_rate_lock = asyncio.Lock()
_RATE_TTL = 300  # секунд: 5 минут


async def _fetch_exchange_rates() -> dict[str, float]:
    """Загрузить курсы из CryptoBot /getExchangeRates.

    Возвращает словарь {f"{source}_{target}": float}, например
    {"USDT_USD": 1.0, "RUB_USD": 0.0111, "TON_USD": 3.45, ...}.
    """
    cfg = get_config()
    if not cfg.crypto_bot_token:
        return {}
    url = f"{cfg.crypto_api_base.rstrip('/')}/getExchangeRates"
    headers = {"Crypto-Pay-API-Token": cfg.crypto_bot_token}
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                data = await resp.json(content_type=None)
        if not data.get("ok"):
            logger.warning(f"[CRYPTO] getExchangeRates not ok: {data}")
            return {}
        result: dict[str, float] = {}
        for item in data.get("result") or []:
            src = item.get("source", "")
            tgt = item.get("target", "")
            rate_str = item.get("rate", "")
            try:
                result[f"{src}_{tgt}"] = float(rate_str)
            except (ValueError, TypeError):
                pass
        logger.debug(f"[CRYPTO] rates refreshed: {len(result)} pairs")
        return result
    except Exception as e:
        logger.warning(f"[CRYPTO] getExchangeRates failed: {e}")
        return {}


async def _live_rates() -> dict[str, float]:
    """Кэшированный снимок курсов (обновляется раз в _RATE_TTL секунд)."""
    async with _rate_lock:
        now = time.time()
        if now - float(_rate_cache.get("ts", 0)) >= _RATE_TTL or not _rate_cache.get("rates"):
            rates = await _fetch_exchange_rates()
            if rates:
                _rate_cache["rates"] = rates
                _rate_cache["ts"] = now
        return dict(_rate_cache.get("rates") or {})  # type: ignore[arg-type]


async def get_asset_per_rub(asset: Optional[str] = None) -> float:
    """Сколько единиц актива (USDT/TON/…) стоит 1 рубль по рыночному курсу.

    Алгоритм:
      asset_per_USD = 1 / USD_per_asset  (или USD_per_asset прямым путём)
      rub_per_USD   = 1 / rates["RUB_USD"]
      asset_per_rub = asset_per_USD / rub_per_USD

    Фолбэк: если курс не загружен — берём usd_rub_rate из конфига (хуже, но
    не ломаем сервис).
    """
    cfg = get_config()
    if asset is None:
        asset = cfg.crypto_asset

    rates = await _live_rates()

    # Прямой путь: asset/RUB или RUB/asset
    if f"{asset}_RUB" in rates:
        # сколько USDT стоит 1 RUB — напрямую
        return float(rates[f"{asset}_RUB"])
    if f"RUB_{asset}" in rates and rates[f"RUB_{asset}"] > 0:
        return 1.0 / float(rates[f"RUB_{asset}"])

    # Через USD: asset→USD и RUB→USD
    asset_usd = rates.get(f"{asset}_USD") or (
        1.0 / rates[f"USD_{asset}"] if rates.get(f"USD_{asset}") else None
    )
    rub_usd = rates.get("RUB_USD") or (
        1.0 / rates["USD_RUB"] if rates.get("USD_RUB") else None
    )
    if asset_usd and rub_usd and rub_usd > 0:
        return asset_usd / rub_usd

    # Фолбэк: фиксированный курс из конфига (защита от недоступности API)
    fallback_usd_rub = max(cfg.usd_rub_rate, 1)
    logger.warning(f"[CRYPTO] live rate unavailable for {asset}/RUB, using config fallback ({fallback_usd_rub})")
    return 1.0 / fallback_usd_rub  # USDT ≈ $1 → просто 1/usd_rub


async def mana_to_crypto_amount_live(mana: int, asset: Optional[str] = None) -> float:
    """Конвертация руды в крипту по ЖИВОМУ рыночному курсу CryptoBot.

    Формула: руда → рубли (mana_per_rub) → актив (рыночный курс).
    Используется везде, где считается итоговая сумма выплаты.
    """
    cfg = get_config()
    rub = mana / max(cfg.mana_per_rub, 1)
    rate = await get_asset_per_rub(asset or cfg.crypto_asset)
    return round(rub * rate, 4)


def mana_to_crypto_amount(mana: int) -> float:
    """Синхронный фолбэк с фиксированным курсом из конфига.

    Оставлен для синхронных контекстов (тексты уведомлений, предварительная
    оценка). Для реальных выплат всегда использовать mana_to_crypto_amount_live.
    """
    cfg = get_config()
    rub = mana / max(cfg.mana_per_rub, 1)
    usd = rub / max(cfg.usd_rub_rate, 1)
    return round(usd, 4)


async def transfer(user_id: int, amount: float, spend_id: str, comment: str = "") -> tuple[bool, str]:
    """Перевести `amount` актива пользователю через Crypto Pay `transfer`.

    spend_id — идемпотентный ключ (один и тот же spend_id не спишется дважды).
    Возвращает (ok, info) — info это transfer_id при успехе или текст ошибки.
    """
    cfg = get_config()
    if not cfg.crypto_bot_token:
        return False, "no_token"

    url = f"{cfg.crypto_api_base.rstrip('/')}/transfer"
    headers = {"Crypto-Pay-API-Token": cfg.crypto_bot_token}
    payload = {
        "user_id": user_id,
        "asset": cfg.crypto_asset,
        "amount": f"{amount:.4f}",
        "spend_id": spend_id,
        "comment": comment or "S-Rank payout",
    }
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                data = await resp.json(content_type=None)
    except Exception as e:
        logger.warning(f"[CRYPTO] transfer request failed user={user_id}: {e}")
        return False, str(e)

    if data.get("ok"):
        tid = str((data.get("result") or {}).get("transfer_id", ""))
        logger.info(f"[CRYPTO] transfer ok user={user_id} {amount} {cfg.crypto_asset} id={tid}")
        return True, tid
    err = data.get("error") or data
    logger.warning(f"[CRYPTO] transfer error user={user_id}: {err}")
    return False, str(err)
