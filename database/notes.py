"""Заметки чата: быстрый FAQ/правила/мемы по ключу (/save -> /note)."""
from typing import Optional

from .db import get_db


async def save_note(chat_id: int, name: str, content: str, created_by: int = 0) -> bool:
    name = (name or "").strip().lower().lstrip("#")
    content = (content or "").strip()
    if not name or not content:
        return False
    db = await get_db()
    await db.execute(
        """INSERT INTO chat_notes (chat_id, name, content, created_by)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(chat_id, name) DO UPDATE SET
               content = excluded.content, created_by = excluded.created_by""",
        (chat_id, name, content, created_by),
    )
    await db.commit()
    return True


async def get_note(chat_id: int, name: str) -> Optional[dict]:
    name = (name or "").strip().lower().lstrip("#")
    db = await get_db()
    async with db.execute(
        "SELECT * FROM chat_notes WHERE chat_id = ? AND name = ?", (chat_id, name)
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def delete_note(chat_id: int, name: str) -> bool:
    name = (name or "").strip().lower().lstrip("#")
    db = await get_db()
    cur = await db.execute(
        "DELETE FROM chat_notes WHERE chat_id = ? AND name = ?", (chat_id, name)
    )
    await db.commit()
    return (cur.rowcount or 0) > 0


async def list_notes(chat_id: int) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT name FROM chat_notes WHERE chat_id = ? ORDER BY name", (chat_id,)
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]
