import asyncio

from aiogram import Bot
from aiogram.types import Message, User


# ── Owner state (set once on startup) ───────────────────────────────────────────

_OWNER_ID: int = 0
_CONFIG = None  # set once on startup, type: config.Config


def set_owner_id(owner_id: int) -> None:
    global _OWNER_ID
    _OWNER_ID = owner_id


def get_owner_id() -> int:
    return _OWNER_ID


def set_config(config) -> None:
    """Store the loaded Config so services/handlers can read it without imports."""
    global _CONFIG
    _CONFIG = config


def get_config():
    """Return the global Config. Raises if accessed before startup."""
    if _CONFIG is None:
        raise RuntimeError("Config not initialised. Call set_config() on startup.")
    return _CONFIG


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


# ── Admin guards ────────────────────────────────────────────────────────────────

async def is_chat_admin(bot: Bot, chat_id: int, user_id: int | None) -> bool:
    """Owner is always admin. Otherwise checks Telegram chat status."""
    if is_owner(user_id):
        return True
    if not user_id:
        return False
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except Exception:
        return False
    return member.status in ("administrator", "creator")


async def is_chat_staff(bot: Bot, chat_id: int, user_id: int | None) -> bool:
    """
    True for owner / Telegram admins / creators OR users holding an in-bot role
    (moderator/admin earned via referral goals). Used for soft moderation
    commands (warn/mute/del).
    """
    if await is_chat_admin(bot, chat_id, user_id):
        return True
    if not user_id:
        return False
    from database import get_chat_role
    role = await get_chat_role(user_id, chat_id)
    return role in ("moderator", "admin")


async def require_admin(
    message: Message, bot: Bot, *, silent: bool = False, allow_staff: bool = False
) -> bool:
    """
    Gatekeeper for admin-only commands.
    Returns True for owner/admins. For everyone else it removes the command
    message (so the chat stays clean) and, unless `silent`, shows a short
    self-destructing notice instead of leaving permanent "no rights" spam.

    `allow_staff=True` also admits in-bot moderators/admins (earned via referral
    goals) — use it for soft moderation commands like warn/mute/del.
    """
    user = message.from_user
    if user:
        ok = (
            await is_chat_staff(bot, message.chat.id, user.id)
            if allow_staff
            else await is_chat_admin(bot, message.chat.id, user.id)
        )
        if ok:
            return True
    try:
        await message.delete()
    except Exception:
        pass
    if not silent:
        try:
            notice = await message.answer(
                "🔒 Эта команда доступна только администраторам."
            )
            await asyncio.sleep(4)
            await notice.delete()
        except Exception:
            pass
    return False
