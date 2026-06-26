"""
Бэкенд Telegram Mini App (WebApp): aiohttp-сервер в том же процессе, что и бот.

Безопасность: каждый запрос несёт Telegram initData, который мы проверяем по
HMAC с токеном бота (спец Telegram WebApp). Это надёжно подтверждает user_id —
никаких отдельных паролей/сессий не нужно. Просроченный initData отвергаем.

Эндпоинты переиспользуют services/* (никакой дубль-логики):
  POST /api/state          — кошелёк, ранг, стрик, задания на сегодня
  POST /api/task/check     — проверить подписку/вступление и начислить
  POST /api/task/watch     — таймер просмотра (старт/ожидание/зачёт)
  POST /api/task/quiz      — ответ на квиз
  POST /api/leaderboard    — топ по руде
  POST /api/shop           — каталог подарков + баланс
  POST /api/redeem         — обмен руды на подарок (+ авто-отправка)
  POST /api/payout_crypto  — заявка на крипто-вывод

Включается флагом WEBAPP_ENABLED; кнопка web_app в меню показывается только при
заданном публичном https WEBAPP_URL (требование Telegram).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.parse
from pathlib import Path
from typing import Optional

from aiogram import Bot
from aiohttp import web
from loguru import logger

from utils import get_config

_WEBAPP_DIR = Path(__file__).resolve().parent.parent / "webapp"
_MAX_AGE = 24 * 3600  # initData старше суток считаем просроченным


# ── Проверка Telegram initData ───────────────────────────────────────────────

def validate_init_data(init_data: str) -> Optional[dict]:
    """Проверяет подпись initData и возвращает разобранные поля или None.

    Алгоритм Telegram WebApp: secret = HMAC_SHA256("WebAppData", bot_token),
    затем сверяем HMAC_SHA256(secret, data_check_string) с полем hash.
    """
    if not init_data:
        return None
    cfg = get_config()
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None

    data_check = "\n".join(f"{k}={parsed[k]}" for k in sorted(parsed))
    secret = hmac.new(b"WebAppData", cfg.token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received_hash):
        return None

    # Свежесть: отвергаем устаревший initData (защита от повторов).
    try:
        if time.time() - int(parsed.get("auth_date", "0")) > _MAX_AGE:
            return None
    except ValueError:
        return None
    return parsed


def _user_from(parsed: dict) -> Optional[dict]:
    try:
        return json.loads(parsed.get("user", ""))
    except (json.JSONDecodeError, TypeError):
        return None


async def _auth(request: web.Request) -> tuple[Optional[int], Optional[dict], Optional[dict]]:
    """Разбирает тело запроса, валидирует initData. Возвращает (user_id, body, tg_user)."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    parsed = validate_init_data(body.get("initData", ""))
    if not parsed:
        return None, body, None
    tg_user = _user_from(parsed)
    if not tg_user or "id" not in tg_user:
        return None, body, None
    return int(tg_user["id"]), body, tg_user


def _unauth() -> web.Response:
    return web.json_response({"ok": False, "error": "unauthorized"}, status=401)


# ── Эндпоинты ────────────────────────────────────────────────────────────────

async def api_state(request: web.Request) -> web.Response:
    user_id, _body, tg_user = await _auth(request)
    if user_id is None:
        return _unauth()

    from database import get_wallet
    from services import daily_tasks_view, user_streak
    from utils import calculate_rank, get_rank_label

    wallet = await get_wallet(user_id)
    view = await daily_tasks_view(user_id)
    streak = await user_streak(user_id)
    rank = view["rank"]

    tasks = [{
        "id": t["id"],
        "type": t.get("type"),
        "verify_mode": t.get("verify_mode") or "membership",
        "title": t.get("title") or "Задание",
        "reward": t.get("reward", 0),
        "duration_sec": t.get("duration_sec", 0),
        "url": t.get("url") or (
            f"https://t.me/{t['channel_username']}" if t.get("channel_username") else ""
        ),
    } for t in view["tasks"]]

    return web.json_response({
        "ok": True,
        "user": {"id": user_id, "name": (tg_user or {}).get("first_name", "Охотник")},
        "balance": wallet.get("mana", 0),
        "total_earned": wallet.get("total_earned", 0),
        "rank": rank,
        "rank_label": get_rank_label(rank),
        "xp": wallet.get("xp", 0),
        "streak": streak,
        "limit": view["limit"],
        "done_today": view["done_today"],
        "remaining": view["remaining"],
        "pool_size": view["pool_size"],
        "tasks": tasks,
    })


async def api_task_check(request: web.Request) -> web.Response:
    user_id, body, _ = await _auth(request)
    if user_id is None:
        return _unauth()
    from services import check_and_credit_task
    from database import get_wallet_balance
    task_id = int(body.get("task_id", 0) or 0)
    code, reward = await check_and_credit_task(request.app["bot"], user_id, task_id)
    bal = await get_wallet_balance(user_id)
    return web.json_response({"ok": True, "code": code, "reward": reward, "balance": bal})


async def api_task_watch(request: web.Request) -> web.Response:
    user_id, body, _ = await _auth(request)
    if user_id is None:
        return _unauth()
    from services import watch_claim
    from database import get_wallet_balance
    task_id = int(body.get("task_id", 0) or 0)
    code, value = await watch_claim(request.app["bot"], user_id, task_id)
    bal = await get_wallet_balance(user_id)
    return web.json_response({"ok": True, "code": code, "value": value, "balance": bal})


async def api_task_quiz(request: web.Request) -> web.Response:
    user_id, body, _ = await _auth(request)
    if user_id is None:
        return _unauth()
    from services import check_and_credit_task
    from database import get_wallet_balance
    task_id = int(body.get("task_id", 0) or 0)
    answer = str(body.get("answer", ""))
    code, reward = await check_and_credit_task(request.app["bot"], user_id, task_id, payload=answer)
    bal = await get_wallet_balance(user_id)
    return web.json_response({"ok": True, "code": code, "reward": reward, "balance": bal})


async def api_leaderboard(request: web.Request) -> web.Response:
    user_id, _body, _ = await _auth(request)
    if user_id is None:
        return _unauth()
    from database import get_top_mana
    top = await get_top_mana(20)
    rows = [{
        "rank": i + 1,
        "user_id": r["user_id"],
        "mana": r["mana"],
        "is_me": r["user_id"] == user_id,
    } for i, r in enumerate(top)]
    return web.json_response({"ok": True, "top": rows})


async def api_shop(request: web.Request) -> web.Response:
    user_id, _body, _ = await _auth(request)
    if user_id is None:
        return _unauth()
    from services.gifts import get_live_catalog
    from database import get_wallet_balance
    bal = await get_wallet_balance(user_id)
    # Живой каталог: наличие синхронизировано с Telegram (getAvailableGifts).
    catalog = [{
        "key": g.key, "title": g.title, "subtitle": g.subtitle,
        "emoji": g.emoji, "stars": g.stars, "mana_price": g.mana_price,
        "collectible": g.collectible, "remaining": g.remaining,
        "affordable": bal >= g.mana_price,
    } for g in await get_live_catalog(request.app["bot"])]
    cfg = get_config()
    return web.json_response({
        "ok": True, "balance": bal, "catalog": catalog,
        "crypto_enabled": cfg.crypto_withdraw_enabled,
        "crypto_asset": cfg.crypto_asset,
        "crypto_min": cfg.crypto_min_mana,
    })


async def api_redeem(request: web.Request) -> web.Response:
    user_id, body, _ = await _auth(request)
    if user_id is None:
        return _unauth()
    from services import request_payout
    from services.gifts import get_live_catalog, send_telegram_gift
    from database import get_wallet_balance, set_payout_status

    key = str(body.get("key", ""))
    offer = next((g for g in await get_live_catalog(request.app["bot"]) if g.key == key), None)
    if not offer:
        return web.json_response({"ok": False, "error": "offer_not_found"})
    ok, req_id, err = await request_payout(user_id, offer.mana_price, f"gift:{offer.key}")
    if not ok:
        return web.json_response({"ok": False, "error": err})

    sent = False
    if req_id:
        gift_ok, _msg = await send_telegram_gift(request.app["bot"], user_id, offer)
        if gift_ok:
            await set_payout_status(req_id, "approved", note="auto_send_gift")
            sent = True
        else:
            await _notify_owner_payout(request.app["bot"], req_id, user_id, offer)
    bal = await get_wallet_balance(user_id)
    return web.json_response({"ok": True, "sent": sent, "req_id": req_id, "balance": bal})


async def api_payout_crypto(request: web.Request) -> web.Response:
    user_id, body, tg_user = await _auth(request)
    if user_id is None:
        return _unauth()
    from services import request_crypto_payout
    from services.crypto import mana_to_crypto_amount_live
    from database import get_wallet_balance, get_payout_request, set_payout_status

    amount = int(body.get("amount", 0) or 0)
    bot = request.app["bot"]
    ok, req_id, err = await request_crypto_payout(user_id, amount, bot=bot)
    if not ok:
        return web.json_response({"ok": False, "error": err})

    cfg = get_config()
    crypto_amt = await mana_to_crypto_amount_live(amount)

    # Уведомляем владельца только если заявка ещё pending (авто-вывод мог
    # уже выполнить её внутри request_crypto_payout).
    req = await get_payout_request(req_id) if req_id else None
    if cfg.owner_id and req_id and req and req.get("status") == "pending":
        try:
            await bot.send_message(
                cfg.owner_id,
                "🪙 <b>НОВАЯ ЗАЯВКА НА КРИПТО-ВЫВОД (Mini App)</b>\n\n"
                f"№{req_id}\nПользователь: <code>{user_id}</code>\n"
                f"Сумма: <b>{amount}</b> ≈ <b>{crypto_amt:.4f} {cfg.crypto_asset}</b> "
                f"(живой курс)\n\n"
                f"Подтвердить: /approve {req_id}\nОтклонить: /reject {req_id}",
                parse_mode="HTML",
            )
        except Exception:
            pass
    bal = await get_wallet_balance(user_id)
    return web.json_response({
        "ok": True, "req_id": req_id, "balance": bal, "crypto_amt": crypto_amt,
    })


async def _notify_owner_payout(bot: Bot, req_id: int, user_id: int, offer) -> None:
    cfg = get_config()
    if not cfg.owner_id:
        return
    try:
        await bot.send_message(
            cfg.owner_id,
            "🎁 <b>НОВАЯ ЗАЯВКА НА ПОДАРОК (Mini App)</b>\n\n"
            f"№{req_id}\nПользователь: <code>{user_id}</code>\n"
            f"Подарок: <b>{offer.title}</b> ({offer.stars} ⭐)\n\n"
            f"Подтвердить: /approve {req_id}\nОтклонить: /reject {req_id}",
            parse_mode="HTML",
        )
    except Exception:
        pass


async def cb_task(request: web.Request) -> web.Response:
    """
    Постбэк-зачёт задания (S2S callback). Бот рекламодателя при выполнении
    действия дёргает: GET/POST /cb/task?token=<выданный_в_start_токен>.
    Подпись токена проверяем нашим секретом — подделать чужой зачёт нельзя.
    """
    token = request.query.get("token", "") or request.query.get("data", "")
    if not token and request.method == "POST":
        try:
            body = await request.json()
            token = body.get("token", "") or body.get("data", "")
        except Exception:
            token = ""
    from utils.callbacks import verify_task_token
    res = verify_task_token(token)
    if not res:
        return web.json_response({"ok": False, "error": "bad_token"}, status=403)
    user_id, task_id = res
    from services.tasks import credit_postback
    code, reward = await credit_postback(request.app["bot"], user_id, task_id)
    return web.json_response(
        {"ok": code in ("credited", "already"), "code": code, "reward": reward}
    )


async def index(request: web.Request) -> web.Response:
    f = _WEBAPP_DIR / "index.html"
    if not f.exists():
        return web.Response(text="Mini App не собран.", status=404)
    return web.FileResponse(f)


async def healthz(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


def build_app(bot: Bot) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/", index)
    app.router.add_get("/healthz", healthz)
    app.router.add_post("/api/state", api_state)
    app.router.add_post("/api/task/check", api_task_check)
    app.router.add_post("/api/task/watch", api_task_watch)
    app.router.add_post("/api/task/quiz", api_task_quiz)
    app.router.add_post("/api/leaderboard", api_leaderboard)
    app.router.add_post("/api/shop", api_shop)
    app.router.add_post("/api/redeem", api_redeem)
    app.router.add_post("/api/payout_crypto", api_payout_crypto)
    # Постбэк-проверка заданий (S2S): принимаем и GET, и POST.
    app.router.add_get("/cb/task", cb_task)
    app.router.add_post("/cb/task", cb_task)
    if _WEBAPP_DIR.exists():
        app.router.add_static("/static/", path=str(_WEBAPP_DIR), name="static")
    return app


async def start_webapp(bot: Bot) -> Optional[web.AppRunner]:
    """Поднять встроенный сервер на webapp_port (Mini App + постбэки заданий).
    Запускаем, если включён Mini App ИЛИ задан публичный адрес (нужен для
    постбэк-проверки заданий /cb/task). Возвращает runner для остановки."""
    cfg = get_config()
    if not (cfg.webapp_enabled or cfg.webapp_url or cfg.webhook_url):
        return None
    app = build_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=cfg.webapp_port)
    await site.start()
    logger.info(f"Mini App backend на :{cfg.webapp_port} (url={cfg.webapp_url or '—'})")
    return runner
