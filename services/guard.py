"""
Функции доверия для модерации новичков (включаются админом чата):
  • CAS-бан — авто-бан известных спам-ботов по глобальной базе cas.chat;
  • анти-рейд — при всплеске входов временный режим «только чтение» для новичков;
  • капча — кнопка «я не бот», до прохождения новичок не может писать.

Бизнес-логика; раздаёт побочные эффекты через bot. Состояние рейда/капчи —
в памяти процесса (этого достаточно: данные эфемерны и не критичны к рестарту).
"""
import asyncio
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta

import aiohttp
from aiogram import Bot
from aiogram.types import ChatMemberUpdated, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from database import get_chat_settings, ban_user, increment_stat
from utils import mention_html_raw, CAPTCHA_PROMPT, CAS_BANNED_MSG, RAID_MSG
from utils.tg_safe import safe_ban, safe_mute, safe_unmute, safe_kick

# ── Anti-raid ────────────────────────────────────────────────────────────────
_RAID_WINDOW = 30        # окно наблюдения, сек
_RAID_THRESHOLD = 5      # столько входов за окно → рейд
_RAID_LOCKDOWN = 180     # сколько секунд держим новичков в «только чтение»
_raid_joins: dict[int, deque] = defaultdict(deque)
_raid_until: dict[int, float] = {}
_raid_notified: dict[int, float] = {}


def _register_join(chat_id: int) -> int:
    now = time.monotonic()
    dq = _raid_joins[chat_id]
    dq.append(now)
    while dq and now - dq[0] > _RAID_WINDOW:
        dq.popleft()
    return len(dq)


def _raid_active(chat_id: int) -> bool:
    return time.monotonic() < _raid_until.get(chat_id, 0.0)


# ── CAS (Combot Anti-Spam) ────────────────────────────────────────────────────
async def cas_banned(user_id: int) -> bool:
    """True, если пользователь в глобальном чёрном списке спам-ботов CAS."""
    url = f"https://api.cas.chat/check?user_id={user_id}"
    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get(url) as r:
                if r.status != 200:
                    return False
                data = await r.json()
                return bool(data.get("ok"))
    except Exception:
        return False


# ── Captcha ───────────────────────────────────────────────────────────────────
CAPTCHA_TIMEOUT = 120
# (chat_id, user_id) -> message_id капчи
_pending_captcha: dict[tuple[int, int], int] = {}


def _captcha_keyboard(chat_id: int, user_id: int):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="✅ Я не бот", callback_data=f"captcha:{chat_id}:{user_id}",
    ))
    return b.as_markup()


async def _captcha_timeout(bot: Bot, chat_id: int, user_id: int) -> None:
    await asyncio.sleep(CAPTCHA_TIMEOUT)
    msg_id = _pending_captcha.pop((chat_id, user_id), None)
    if msg_id is None:
        return  # уже решена
    await safe_kick(bot, chat_id, user_id)
    try:
        await bot.delete_message(chat_id, msg_id)
    except Exception:
        pass
    logger.info(f"[GUARD] captcha timeout: kicked {user_id} from {chat_id}")


async def _start_captcha(bot: Bot, chat_id: int, user) -> None:
    if not await safe_mute(bot, chat_id, user.id):
        return  # нет прав ограничивать — капчу не навязываем
    try:
        m = await bot.send_message(
            chat_id,
            CAPTCHA_PROMPT.format(
                mention=mention_html_raw(user.id, user.full_name),
                seconds=CAPTCHA_TIMEOUT,
            ),
            parse_mode="HTML",
            reply_markup=_captcha_keyboard(chat_id, user.id),
        )
    except Exception:
        await safe_unmute(bot, chat_id, user.id)
        return
    _pending_captcha[(chat_id, user.id)] = m.message_id
    asyncio.create_task(_captcha_timeout(bot, chat_id, user.id))


async def solve_captcha(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Новичок нажал «Я не бот». Снимаем мут и убираем сообщение капчи."""
    if (chat_id, user_id) not in _pending_captcha:
        return False
    msg_id = _pending_captcha.pop((chat_id, user_id))
    await safe_unmute(bot, chat_id, user_id)
    try:
        await bot.delete_message(chat_id, msg_id)
    except Exception:
        pass
    return True


# ── Единая точка скрининга новичка ─────────────────────────────────────────────
async def screen_newcomer(bot: Bot, event: ChatMemberUpdated) -> bool:
    """
    Проверяет нового участника фильтрами доверия (если включены в чате).
    Возвращает True, если вход обработан (бан/рейд-мут/капча) и обычное
    приветствие показывать НЕ нужно.
    """
    chat = event.chat
    user = event.new_chat_member.user
    settings = await get_chat_settings(chat.id)

    # 1) CAS-бан известных спам-ботов.
    if settings.get("cas_ban", 0) and await cas_banned(user.id):
        if await safe_ban(bot, chat.id, user.id):
            await ban_user(user.id, chat.id, 0, "CAS spam ban")
            await increment_stat(chat.id, "bans")
            try:
                await bot.send_message(chat.id, CAS_BANNED_MSG, parse_mode="HTML")
            except Exception:
                pass
        return True

    # 2) Анти-рейд: всплеск входов → новички в «только чтение» на пару минут.
    if settings.get("antiraid", 0):
        count = _register_join(chat.id)
        if count >= _RAID_THRESHOLD or _raid_active(chat.id):
            _raid_until[chat.id] = time.monotonic() + _RAID_LOCKDOWN
            until = datetime.utcnow() + timedelta(seconds=_RAID_LOCKDOWN)
            await safe_mute(bot, chat.id, user.id, until_date=until)
            # Уведомляем чат об активации режима не чаще раза в lockdown-окно.
            now = time.monotonic()
            if now - _raid_notified.get(chat.id, 0.0) > _RAID_LOCKDOWN:
                _raid_notified[chat.id] = now
                try:
                    await bot.send_message(chat.id, RAID_MSG, parse_mode="HTML")
                except Exception:
                    pass
            return True

    # 3) Капча «я не бот».
    if settings.get("captcha", 0):
        await _start_captcha(bot, chat.id, user)
        return True

    return False
