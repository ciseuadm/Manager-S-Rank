"""
Content analysis: detects NSFW, insults, political content,
spam patterns, flood, forbidden links, and custom blacklist words.
"""
import re
from typing import Optional


# ── Дедобфускация: ловим маскировку («п0рн0», «х у й», «cyka», «бл*дь») ────────
# Карта гомоглифов/leetspeak: латиница-двойники и цифры → кириллица. Применяется
# к нормализованным копиям текста (исходный текст не меняется), чтобы простые
# обходы фильтра не проходили. Длина сохраняется (посимвольная замена).
_LEET_MAP = {
    # цифры/символы → буквы (распространённый leetspeak)
    "0": "о", "3": "е", "4": "ч", "1": "и", "6": "б", "@": "а", "$": "с",
    # латиница-двойники → кириллица (только сильные визуальные совпадения,
    # чтобы не превращать обычные англ. слова в «мат» по ошибке)
    "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у",
    "k": "к", "m": "м", "t": "т", "h": "н", "b": "в",
}
_LEET_TABLE = {ord(k): v for k, v in _LEET_MAP.items()}

# Разделители, которыми растаскивают буквы внутри слова.
_SEP_RE = re.compile(r"[\s.,_\-*|/\\+~`'\"^:;!?()\[\]{}<>=#№]")
_REPEAT_RE = re.compile(r"(.)\1{2,}")

# Сильные корни мата/NSFW для проверки по «сжатому» тексту (разделители удалены,
# повторы схлопнуты). Без \b — текст уже без границ слов; список намеренно
# консервативный (корни, которые почти не встречаются внутри обычных слов),
# чтобы не плодить ложные срабатывания. Спорные случаи гасит белый список чата.
_SQUEEZE_PATTERNS = re.compile(
    r"("
    r"пизд|бляд|бля[дبц]|нахуй|похуй|ахуе|охуе|хуйн|хуес|хуйл|"
    r"пидор|пидар|муда[кч]|долбоеб|далбоеб|еблан|ебало|выеб|заеб|уеб[аои]|"
    r"порнух|порно|порев|анус|вагин|члено|залуп|дрочи|онанис|"
    r"проститут|шлюх|сучар|гандон|"
    r"сдохни|убейся|"
    r"fuck|porn|sex|xxx|nigger|faggot"
    r")",
    re.IGNORECASE | re.UNICODE,
)


def _deobfuscate(text: str) -> str:
    """Гомоглифы/leet → кириллица + схлопывание длинных повторов (3+ → 2).
    Структура (пробелы) сохраняется, чтобы \\b-паттерны продолжали работать."""
    t = text.lower().translate(_LEET_TABLE)
    return _REPEAT_RE.sub(r"\1\1", t)


def _squeeze(text: str) -> str:
    """Сжатая форма: дедобфускация + удаление разделителей + схлопывание повторов.
    Ловит «с у к а», «б.л.я.д.ь», «п_о_р_н_о»."""
    t = text.lower().translate(_LEET_TABLE)
    t = _SEP_RE.sub("", t)
    return _REPEAT_RE.sub(r"\1", t)


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
    r"сук[аиуе]|сукой|сучка|сучара|"
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

    # Дедобфусцированные копии для устойчивости к маскировке (исходный текст
    # не меняем). \b-паттерны прогоняем по сырому И дедобфусцированному тексту;
    # «сжатую» форму (без разделителей) проверяем сильными корнями.
    deobf = _deobfuscate(text)
    squeezed = _squeeze(text)

    def _check_both(fn) -> Optional[str]:
        """Запускает проверку по сырому и дедобфусцированному тексту."""
        return fn(text) or (fn(deobf) if deobf != text else None)

    if settings.get("filter_nsfw", 1):
        match = _check_both(check_nsfw)
        sq = None if match else (
            _SQUEEZE_PATTERNS.search(squeezed) if squeezed else None
        )
        if sq:
            match = sq.group()
        if match and not _wl_ok(match):
            violations.append(("nsfw", match))

    if settings.get("filter_insults", 1):
        match = _check_both(check_insult)
        if match and not _wl_ok(match):
            violations.append(("insult", match))

    if settings.get("filter_politics", 1):
        match = _check_both(check_politics)
        if match and not _wl_ok(match):
            violations.append(("politics", match))

    if settings.get("filter_spam", 1):
        match = _check_both(check_spam)
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

    match = check_blacklist(text, words) or check_blacklist(deobf, words) \
        or check_blacklist(squeezed, words)
    if match:
        violations.append(("blacklist", match))

    return violations
