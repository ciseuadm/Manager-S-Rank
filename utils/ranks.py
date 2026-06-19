"""
Solo Leveling rank system.
E → D → C → B → A → S → SS → SSS

Ранг определяется накопленным ОПЫТОМ (хранится в wallets.xp). Опыт начисляется
за «честную добычу»: задания-подписки (+100 за канал) и ежедневное подземелье
(+руда = +опыт). Флуд в чатах, покупки руды за Stars и переводы опыт НЕ дают —
ранг отражает реальный вклад. Трата руды на подарки опыт не уменьшает.

Пороговые значения опыта эквивалентны старой шкале заданий (1 задание = 100):
3/10/30/90/180/360/720 заданий → 300/1000/3000/9000/18000/36000/72000 опыта.
"""

# Опыт за одно выполненное задание (= награда руды за подписку).
XP_PER_TASK = 100

# (rank_id, порог в ОПЫТЕ, метка, звание)
RANKS = [
    ("E", 0,      "⬛ E-Ранг",   "Новый охотник"),
    ("D", 300,    "🟫 D-Ранг",   "Начинающий охотник"),
    ("C", 1000,   "🟦 C-Ранг",   "Опытный охотник"),
    ("B", 3000,   "🟩 B-Ранг",   "Элитный охотник"),
    ("A", 9000,   "🟨 A-Ранг",   "Высший охотник"),
    ("S", 18000,  "🟥 S-Ранг",   "Монарх теней"),
    ("SS", 36000, "💎 SS-Ранг",  "Национальный охотник"),
    ("SSS", 72000,"👑 SSS-Ранг", "Избранный Монарха"),
]

_RANK_MAP = {r[0]: r for r in RANKS}
_RANK_IDS = [r[0] for r in RANKS]


def calculate_rank(xp: int) -> str:
    """xp = накопленный опыт (wallets.xp)."""
    current_rank = "E"
    for rank_id, threshold, _, _ in RANKS:
        if xp >= threshold:
            current_rank = rank_id
        else:
            break
    return current_rank


def rank_index(rank_id: str) -> int:
    """Порядковый номер ранга (E=0 … SSS=7); −1, если ранг неизвестен."""
    return _RANK_IDS.index(rank_id) if rank_id in _RANK_IDS else -1


def get_rank_info(rank_id: str) -> tuple:
    return _RANK_MAP.get(rank_id, RANKS[0])


def get_rank_label(rank_id: str) -> str:
    return get_rank_info(rank_id)[2]


def get_rank_title(rank_id: str) -> str:
    return get_rank_info(rank_id)[3]


def get_next_rank(rank_id: str) -> tuple | None:
    if rank_id not in _RANK_IDS:
        return None
    idx = _RANK_IDS.index(rank_id)
    if idx + 1 < len(RANKS):
        return RANKS[idx + 1]
    return None


def score_to_next_rank(xp: int, current_rank: str) -> int | None:
    """Сколько ещё опыта до следующего ранга (None — максимум достигнут)."""
    next_r = get_next_rank(current_rank)
    if next_r is None:
        return None
    return max(0, next_r[1] - xp)


# Обратная совместимость со старым именем (теперь аргумент — опыт).
messages_to_next_rank = score_to_next_rank


def rank_progress_bar(xp: int, current_rank: str) -> str:
    next_r = get_next_rank(current_rank)
    if next_r is None:
        return "▓▓▓▓▓▓▓▓▓▓ MAX"
    curr_threshold = get_rank_info(current_rank)[1]
    next_threshold = next_r[1]
    progress = (xp - curr_threshold) / max(1, next_threshold - curr_threshold)
    progress = min(max(progress, 0.0), 1.0)
    filled = int(progress * 10)
    bar = "▓" * filled + "░" * (10 - filled)
    pct = int(progress * 100)
    return f"{bar} {pct}%"
