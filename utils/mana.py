"""
Helpers for the in-bot currency — Мана-руда (Mana Ore).
Formatting and Russian pluralisation only; balance math lives in services/economy.
"""

MANA_EMOJI = "🔹"


def mana_word(amount: int) -> str:
    """Correct Russian plural form for 'руда'."""
    n = abs(amount) % 100
    if 11 <= n <= 14:
        return "руды"
    d = n % 10
    if d == 1:
        return "руда"
    if 2 <= d <= 4:
        return "руды"
    return "руды"


def format_mana(amount: int) -> str:
    """e.g. 1500 -> '🔹 1 500 руды'. Thousands separated by thin space."""
    sign = "-" if amount < 0 else ""
    grouped = f"{abs(amount):,}".replace(",", " ")
    return f"{MANA_EMOJI} {sign}{grouped} {mana_word(amount)}"
