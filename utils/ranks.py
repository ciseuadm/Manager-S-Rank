"""
Solo Leveling rank system.
E → D → C → B → A → S → National Level Hunter
"""

RANKS = [
    ("E", 0,      "⬛ E-Ранг",           "Новый охотник"),
    ("D", 50,     "🟫 D-Ранг",           "Начинающий охотник"),
    ("C", 150,    "🟦 C-Ранг",           "Опытный охотник"),
    ("B", 400,    "🟩 B-Ранг",           "Элитный охотник"),
    ("A", 1000,   "🟨 A-Ранг",           "Высший охотник"),
    ("S", 2500,   "🟥 S-Ранг",           "Монарх теней"),
    ("SS", 5000,  "💎 SS-Ранг",          "Национальный охотник"),
    ("SSS", 10000,"👑 SSS-Ранг",         "Monarchs Chosen"),
]

_RANK_MAP = {r[0]: r for r in RANKS}


def calculate_rank(messages: int) -> str:
    current_rank = "E"
    for rank_id, threshold, _, _ in RANKS:
        if messages >= threshold:
            current_rank = rank_id
        else:
            break
    return current_rank


def get_rank_info(rank_id: str) -> tuple:
    return _RANK_MAP.get(rank_id, RANKS[0])


def get_rank_label(rank_id: str) -> str:
    info = get_rank_info(rank_id)
    return info[2]


def get_rank_title(rank_id: str) -> str:
    info = get_rank_info(rank_id)
    return info[3]


def get_next_rank(rank_id: str) -> tuple | None:
    ids = [r[0] for r in RANKS]
    if rank_id not in ids:
        return None
    idx = ids.index(rank_id)
    if idx + 1 < len(RANKS):
        return RANKS[idx + 1]
    return None


def messages_to_next_rank(messages: int, current_rank: str) -> int | None:
    next_r = get_next_rank(current_rank)
    if next_r is None:
        return None
    return max(0, next_r[1] - messages)


def rank_progress_bar(messages: int, current_rank: str) -> str:
    next_r = get_next_rank(current_rank)
    if next_r is None:
        return "▓▓▓▓▓▓▓▓▓▓ MAX"
    curr_threshold = get_rank_info(current_rank)[1]
    next_threshold = next_r[1]
    progress = (messages - curr_threshold) / max(1, next_threshold - curr_threshold)
    filled = int(progress * 10)
    bar = "▓" * filled + "░" * (10 - filled)
    pct = int(progress * 100)
    return f"{bar} {pct}%"
