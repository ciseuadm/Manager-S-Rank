"""
Матчинг триггеров чата в потоке сообщений.

Чтобы не бить в БД на каждое сообщение, держим кэш триггеров по чату с коротким
TTL и явной инвалидацией при изменении (add/remove). Матчинг — чистая функция
над текстом; вызывается из потока модерации (handlers/moderation.py).
"""
import re
import time
from typing import Optional

from database import list_triggers

_CACHE: dict[int, tuple[float, list[dict]]] = {}
_TTL = 300.0  # сек


def invalidate(chat_id: int) -> None:
    _CACHE.pop(chat_id, None)


async def _triggers_for(chat_id: int) -> list[dict]:
    now = time.monotonic()
    cached = _CACHE.get(chat_id)
    if cached and now - cached[0] < _TTL:
        return cached[1]
    rows = await list_triggers(chat_id)
    _CACHE[chat_id] = (now, rows)
    return rows


def _matches(text_lower: str, pattern: str, match_type: str) -> bool:
    if match_type == "exact":
        return text_lower.strip() == pattern
    if match_type == "word":
        return re.search(rf"(?<!\w){re.escape(pattern)}(?!\w)", text_lower) is not None
    return pattern in text_lower  # contains


async def match_trigger(chat_id: int, text: str) -> Optional[str]:
    """Первый сработавший ответ-триггер для сообщения, иначе None."""
    if not text:
        return None
    triggers = await _triggers_for(chat_id)
    if not triggers:
        return None
    low = text.lower()
    for t in triggers:
        if _matches(low, t["pattern"], t.get("match_type", "contains")):
            return t["response"]
    return None
