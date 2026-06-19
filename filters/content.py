"""
Content analysis: detects NSFW, insults, political content,
spam patterns, flood, forbidden links, and custom blacklist words.
"""
import re
from typing import Optional


# ── Profanity / Insult word lists ─────────────────────────────────────────────

_NSFW_PATTERNS = re.compile(
    r"\b("
    r"порно|порнуха|секс(?!уальн)|еб[ао]|ебать|ебл[ао]|ёб|еб[её]т|"
    r"fuck|shit|porn|xxx|nsfw|onlyfans|эротик|хентай|hentai|"
    r"18\+|adult.?content|naked|nude|nudes|leaks|слив.*фото|"
    r"сиськи|жопа|пизд|хуй|член|залупа|дрочить|мастурб|"
    r"проститутк|шлюх|блядь|бляд[её]|бл[яе]д|бл[яе]|"
    r"cunt|dick|cock|pussy|tits|ass(?:hole)?|boobs?"
    r")\b",
    re.IGNORECASE | re.UNICODE,
)

_INSULT_PATTERNS = re.compile(
    r"\b("
    r"идиот|тупица|тупой|дебил|дурак|мудак|урод|ублюдок|придурок|"
    r"педик|педо|пидор|гей(?:\s+мразь)?|лох|чмо|ничтожество|"
    r"скотина|животное|свинья|тварь|гандон|ёбаный|бомж|нищеброд|"
    r"retard|loser|moron|idiot|stupid|dumb(?:ass)?|asshole|bastard|"
    r"faggot|nigger|racist|hate\s+you|go\s+die|kill\s+yourself|"
    r"сдохни|иди\s+нахуй|пошёл\s+нахуй|ты\s+дно|мразь|гнида"
    r")\b",
    re.IGNORECASE | re.UNICODE,
)

_POLITICS_PATTERNS = re.compile(
    r"\b("
    r"путин.*(?:убийца|вор|фашист|нацист|педофил)|"
    r"(?:убийца|вор|фашист|нацист).*путин|"
    r"зеленский.*(?:нацист|наркоман|предатель)|"
    r"слава\s+украине|смерть\s+(?:украине|России|русским)|"
    r"убей\s+(?:русских|украинцев|евреев|мусульман)|"
    r"нацистская\s+украина|фашистская\s+россия|"
    r"(?:жиды|евреи)\s+(?:правят|виноваты|уничтожают)|"
    r"мигранты\s+убивают|понаехали|черные\s+(?:убивают|воруют)|"
    r"ватник|укроп|хохол(?!\s+пшеничн)|москаль|колорад(?:ский\s+жук)?|"
    r"isis|игил|хайль|adolf.*hitler|nazi\s+germany"
    r")\b",
    re.IGNORECASE | re.UNICODE,
)

_SPAM_PATTERNS = re.compile(
    r"("
    r"(?:присоединяйся|вступай|заходи).*(?:канал|чат|группу)|"
    r"(?:earn|заработ).*(?:\$|\d+)\s*(?:per|в)\s*(?:day|день)|"
    r"(?:click here|нажми\s+(?:сюда|здесь)).*(?:free|бесплатно)|"
    r"(?:crypto|крипто|bitcoin|биткоин).*(?:x\d+|\d+%|прибыл)|"
    r"(?:FREE|БЕСПЛАТНО|FREE\s+MONEY|ХАЛЯВА)|"
    r"(?:подпишись|subscribe).*бесплатно|"
    r"@\w+\s+@\w+\s+@\w+"
    r")",
    re.IGNORECASE | re.UNICODE,
)

# Известные TLD — чтобы не ловить ложные «node.js», «file.txt», «и т.д.».
# Включает кириллические зоны (.рф/.укр) и латинские домены с кириллицей в теле.
_TLDS = (
    r"com|net|org|info|biz|xyz|top|online|site|club|shop|store|app|dev|io|me|"
    r"ru|su|ua|by|kz|uz|am|ge|md|tj|kg|рф|укр|tv|cc|pro|link|live|space|fun|"
    r"win|vip|gg|to|ws|cn|in|tr|de|fr|es|it|pl|co|uk"
)
_LINK_PATTERN = re.compile(
    r"("
    r"https?://[^\s]+|"
    r"www\.[^\s]+|"
    r"t\.me/[^\s]+|"
    r"telegram\.me/[^\s]+|"
    r"(?:[a-zA-Zа-яёА-ЯЁ0-9\-]+\.)+(?:" + _TLDS + r")\b(?:/[^\s]*)?"
    r")",
    re.IGNORECASE | re.UNICODE,
)

_TELEGRAM_INVITE = re.compile(
    r"(t\.me/\+|t\.me/joinchat|telegram\.me/joinchat)",
    re.IGNORECASE,
)

_CAPS_THRESHOLD = 0.7
_CAPS_MIN_LEN = 10

_ARABIC_PATTERN = re.compile(r"[\u0600-\u06FF\u0750-\u077F]{5,}")


def check_nsfw(text: str) -> Optional[str]:
    m = _NSFW_PATTERNS.search(text)
    return m.group() if m else None


def check_insult(text: str) -> Optional[str]:
    m = _INSULT_PATTERNS.search(text)
    return m.group() if m else None


def check_politics(text: str) -> Optional[str]:
    m = _POLITICS_PATTERNS.search(text)
    return m.group() if m else None


def check_spam(text: str) -> Optional[str]:
    m = _SPAM_PATTERNS.search(text)
    return m.group() if m else None


def check_links(text: str) -> bool:
    return bool(_LINK_PATTERN.search(text))


def check_telegram_invite(text: str) -> bool:
    return bool(_TELEGRAM_INVITE.search(text))


def check_caps(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if len(letters) < _CAPS_MIN_LEN:
        return False
    caps_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    return caps_ratio >= _CAPS_THRESHOLD


def check_blacklist(text: str, words: list[str]) -> Optional[str]:
    lower = text.lower()
    for word in words:
        if word in lower:
            return word
    return None


def analyze_message(
    text: str,
    words: list[str],
    settings: dict,
    whitelist: Optional[list[str]] = None,
) -> list[tuple[str, str]]:
    """
    Returns a list of (violation_type, matched_word) tuples.
    violation_type: 'nsfw' | 'insult' | 'politics' | 'spam' | 'links' | 'invite' | 'caps' | 'blacklist'

    whitelist — слова, которые НЕ считаются нарушением (гасят ложные срабатывания
    антимата/NSFW; не влияют на ссылки/инвайты/blacklist).
    """
    violations: list[tuple[str, str]] = []
    if not text:
        return violations

    wl = {w.lower() for w in (whitelist or [])}

    def _wl_ok(matched: str) -> bool:
        """True, если совпадение разрешено белым списком."""
        m = (matched or "").lower()
        return m in wl or any(w in m or m in w for w in wl)

    if settings.get("filter_nsfw", 1):
        match = check_nsfw(text)
        if match and not _wl_ok(match):
            violations.append(("nsfw", match))

    if settings.get("filter_insults", 1):
        match = check_insult(text)
        if match and not _wl_ok(match):
            violations.append(("insult", match))

    if settings.get("filter_politics", 1):
        match = check_politics(text)
        if match and not _wl_ok(match):
            violations.append(("politics", match))

    if settings.get("filter_spam", 1):
        match = check_spam(text)
        if match and not _wl_ok(match):
            violations.append(("spam", match))

    if settings.get("filter_links", 0):
        if check_links(text):
            violations.append(("links", "URL"))

    # Always block Telegram invite links
    if check_telegram_invite(text):
        violations.append(("invite", "t.me invite"))

    if settings.get("filter_caps", 0):
        if check_caps(text):
            violations.append(("caps", "CAPS LOCK"))

    match = check_blacklist(text, words)
    if match:
        violations.append(("blacklist", match))

    return violations
