"""
Крипто-выплаты руды через Crypto Pay API (@CryptoBot / @CryptoTestnetBot).

Гибридная ветка вывода: поверх существующих payout_requests добавляем продукт
"crypto:<ASSET>". Перевод идёт методом `transfer` Crypto Pay — деньги уходят
на Telegram-аккаунт охотника (user_id), который хоть раз пользовался @CryptoBot.
Адрес кошелька не нужен и не хранится.

Включается, только когда заданы CRYPTO_WITHDRAW_ENABLED=1 и CRYPTO_BOT_TOKEN.
Пока токена нет — ветка работает в ручном режиме: владелец подтверждает заявку
в /payouts и переводит вручную (вся обвязка экономики и лимитов уже готова).
"""
from __future__ import annotations

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


def mana_to_crypto_amount(mana: int) -> float:
    """Сколько крипто-актива соответствует руде.

    Курс: руда → ₽ (mana_per_rub) → $ (usd_rub_rate). Для USDT/USDC 1 ед. ≈ $1.
    Для других активов (TON и т.п.) потребуется отдельный курс — здесь
    возвращаем долларовый эквивалент (для USDT он же — сумма перевода).
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
