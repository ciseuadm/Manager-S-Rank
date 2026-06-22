"""
Подписанные токены для постбэк-проверки заданий (S2S callback / CPA-модель).

Зачем: Telegram НЕ даёт боту А проверить «нажал ли юзер старт в боте Б» или
«набрал ли N очков в чужой игре» — боты изолированы. Универсальное и безопасное
решение (как у CPA-сетей и партнёрок) — постбэк:

  1. Мы выдаём охотнику deep-link на бота рекламодателя с подписанным токеном:
       t.me/<их_бот>?start=<token>     (token = подпись по user_id+task_id)
  2. Бот рекламодателя читает start-payload и при ВЫПОЛНЕНИИ действия дёргает
       GET https://<наш_хост>/cb/task?token=<token>
  3. Мы проверяем подпись, достаём (user_id, task_id) и начисляем награду.

Безопасность: токен подписан НАШИМ секретом, поэтому рекламодатель может лишь
вернуть тот токен, что мы выдали реальному перешедшему пользователю — подделать
зачёт на произвольный user_id нельзя. Повтор безвреден (зачёт идемпотентен).
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Optional

from utils.helpers import get_config


def _secret() -> bytes:
    cfg = get_config()
    raw = cfg.task_callback_secret or ("taskcb:" + cfg.token)
    return raw.encode()


def _sig(payload: str) -> str:
    return hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()[:20]


def sign_task_token(user_id: int, task_id: int) -> str:
    """Подписанный токен для deep-link/постбэка: '<uid>.<tid>.<sig>'."""
    payload = f"{user_id}.{task_id}"
    return f"{payload}.{_sig(payload)}"


def verify_task_token(token: str) -> Optional[tuple[int, int]]:
    """Проверяет токен и возвращает (user_id, task_id) или None."""
    if not token or token.count(".") != 2:
        return None
    uid_s, tid_s, sig = token.split(".")
    if not (uid_s.lstrip("-").isdigit() and tid_s.isdigit()):
        return None
    if not hmac.compare_digest(_sig(f"{uid_s}.{tid_s}"), sig):
        return None
    return int(uid_s), int(tid_s)


def bot_username_from_url(url: str) -> Optional[str]:
    """Достаёт @username бота/канала из ссылки t.me/<name>(?...)."""
    if not url:
        return None
    if "t.me/" not in url:
        ref = url.lstrip("@")
        return ref or None
    name = url.split("t.me/", 1)[1].strip("/").split("/")[0].split("?")[0]
    if name and not name.startswith("+") and name.lower() != "joinchat":
        return name
    return None


def deeplink_with_token(url: str, token: str) -> Optional[str]:
    """Строит ссылку t.me/<bot>?start=<token> из исходного url задания."""
    name = bot_username_from_url(url)
    if not name:
        return None
    return f"https://t.me/{name}?start={token}"


def public_base_url() -> str:
    """Публичный https-адрес нашего сервера (для постбэк-URL), без хвостового /."""
    cfg = get_config()
    base = (cfg.webhook_url or cfg.webapp_url or "").rstrip("/")
    return base


def postback_url_template(task_id: int) -> str:
    """Шаблон постбэк-URL для рекламодателя (он подставит выданный токен)."""
    base = public_base_url() or "https://<твой-публичный-адрес>"
    return f"{base}/cb/task?token=<TOKEN_ИЗ_START>"
