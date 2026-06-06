from aiogram.types import Message, User


# ── Owner state (set once on startup) ───────────────────────────────────────────

_OWNER_ID: int = 0


def set_owner_id(owner_id: int) -> None:
    global _OWNER_ID
    _OWNER_ID = owner_id


def get_owner_id() -> int:
    return _OWNER_ID


def is_owner(user_id: int | None) -> bool:
    return bool(user_id) and _OWNER_ID != 0 and user_id == _OWNER_ID


def mention_html(user: User) -> str:
    name = user.full_name or user.username or str(user.id)
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def mention_html_raw(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{name}</a>'


def parse_time_arg(arg: str) -> int:
    """Parse '30m', '2h', '1d' or plain integer (minutes). Returns minutes."""
    if not arg:
        return 60
    arg = arg.strip().lower()
    try:
        if arg.endswith("d"):
            return int(arg[:-1]) * 1440
        if arg.endswith("h"):
            return int(arg[:-1]) * 60
        if arg.endswith("m"):
            return int(arg[:-1])
        return int(arg)
    except ValueError:
        return 60


async def get_target_user(message: Message) -> tuple[int, str] | None:
    """
    Returns (user_id, full_name) from reply or first @mention / id argument.
    """
    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        return u.id, u.full_name

    args = (message.text or "").split()[1:]
    if args:
        arg = args[0]
        if arg.startswith("@"):
            return None  # Can't resolve username to id without API call
        if arg.lstrip("-").isdigit():
            return int(arg), str(arg)
    return None


def is_admin_permission(status: str) -> bool:
    return status in ("administrator", "creator")
