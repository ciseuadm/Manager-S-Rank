"""Белый список к антимату: слова, которые НЕ считаются нарушением."""
from .db import get_db


async def add_whitelist_word(chat_id: int, word: str, added_by: int = 0) -> bool:
    word = (word or "").strip().lower()
    if not word:
        return False
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO antimat_whitelist (chat_id, word, added_by) VALUES (?, ?, ?)",
            (chat_id, word, added_by),
        )
        await db.commit()
        return True
    except Exception:
        return False


async def remove_whitelist_word(chat_id: int, word: str) -> bool:
    word = (word or "").strip().lower()
    db = await get_db()
    cur = await db.execute(
        "DELETE FROM antimat_whitelist WHERE chat_id = ? AND word = ?", (chat_id, word)
    )
    await db.commit()
    return (cur.rowcount or 0) > 0


async def get_whitelist_words(chat_id: int) -> list[str]:
    db = await get_db()
    async with db.execute(
        "SELECT word FROM antimat_whitelist WHERE chat_id = ?", (chat_id,)
    ) as cur:
        rows = await cur.fetchall()
    return [r["word"] for r in rows]
