"""
Триггеры/кастом-команды чата (липкая фича уровня Iris).

Админ задаёт «ключ -> ответ»: бот сам отвечает в чате на слово/фразу. Это
вовлекает участников и разгружает админов (FAQ, мемы, реакции). Хранится по
чату; матчинг идёт через кэш в services/triggers.py (без запроса на каждое
сообщение).
"""
from typing import Optional

from .db import get_db


async def add_trigger(
    chat_id: int, pattern: str, response: str,
    match_type: str = "contains", created_by: int = 0,
) -> bool:
    """Добавить/обновить триггер. Возвращает False при пустых данных."""
    pattern = (pattern or "").strip().lower()
    response = (response or "").strip()
    if not pattern or not response:
        return False
    if match_type not in ("contains", "exact", "word"):
        match_type = "contains"
    db = await get_db()
    await db.execute(
        """INSERT INTO chat_triggers (chat_id, pattern, response, match_type, created_by)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(chat_id, pattern) DO UPDATE SET
               response = excluded.response,
               match_type = excluded.match_type,
               created_by = excluded.created_by""",
        (chat_id, pattern, response, match_type, created_by),
    )
    await db.commit()
    return True


async def remove_trigger(chat_id: int, pattern: str) -> bool:
    pattern = (pattern or "").strip().lower()
    db = await get_db()
    cur = await db.execute(
        "DELETE FROM chat_triggers WHERE chat_id = ? AND pattern = ?",
        (chat_id, pattern),
    )
    await db.commit()
    return (cur.rowcount or 0) > 0


async def list_triggers(chat_id: int) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM chat_triggers WHERE chat_id = ? ORDER BY pattern", (chat_id,)
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def count_triggers(chat_id: int) -> int:
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) AS c FROM chat_triggers WHERE chat_id = ?", (chat_id,)
    ) as cur:
        row = await cur.fetchone()
    return row["c"] if row else 0
