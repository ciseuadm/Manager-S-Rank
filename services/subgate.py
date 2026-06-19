"""
Обязательная подписка на канал бота (gate доступа).

Без подписки на канал @Manager_Rank_S (config.sub_gate_channel) в ЛИЧКЕ бота
доступен только /start: Система показывает сообщение с кнопкой «Подписаться».
В группах гейт НЕ действует — модерация и работа в чатах не должны зависеть от
подписки конкретного участника.

Бот обязан быть админом канала, иначе get_chat_member не сработает. Если проверка
по какой-то причине падает (бот не админ, временная ошибка) — пользователя НЕ
блокируем, чтобы не закрыть бота полностью из-за сбоя.
"""
from time import time

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from utils import get_config, ce

GATE_CALLBACK = "subgate:check"

# Кэш подтверждённых подписок: user_id → время истечения. Чтобы не дёргать
# get_chat_member на каждое сообщение (экономия Telegram API при масштабе).
# Кэшируем только положительный результат; отписку ловит ежедневная ре-проверка
# заданий и TTL ниже.
_PASS_TTL = 600  # секунд
_pass_cache: dict[int, float] = {}


def invalidate_gate_cache(user_id: int) -> None:
    _pass_cache.pop(user_id, None)

GATE_TEXT = (
    f"{ce('lock')} <b>СИСТЕМА: ДОСТУП ЗАКРЫТ</b>\n\n"
    f"{ce('key')} Прежде чем войти в подземелье, охотник обязан вступить в "
    "<b>гильдию Системы</b> — официальный канал бота.\n\n"
    f"{ce('megaphone')} Там — анонсы, награды и секреты прокачки.\n\n"
    f"{ce('check')} <b>1.</b> Нажми «Вступить в гильдию» и подпишись.\n"
    f"{ce('check')} <b>2.</b> Вернись и нажми «✅ Я подписался».\n\n"
    f"<i>{ce('spark')} После этого Система откроет тебе все возможности.</i>"
)

GATE_RECHECK_FAIL = (
    f"{ce('cross')} Подписка не найдена. Подпишись на канал и нажми «✅ Я подписался» снова."
)


def _is_subscribed(member) -> bool:
    """member из get_chat_member → реально ли подписан (учитывая enum-статусы)."""
    status = getattr(member, "status", None)
    status = getattr(status, "value", status)
    if status in ("creator", "administrator", "member"):
        return True
    if status == "restricted":
        return bool(getattr(member, "is_member", False))
    return False


async def is_gate_passed(bot: Bot, user_id: int) -> bool:
    """True, если охотник может пользоваться ботом (подписан / гейт выключен / владелец)."""
    cfg = get_config()
    if not cfg.sub_gate_enabled or not cfg.sub_gate_channel:
        return True
    if cfg.owner_id and user_id == cfg.owner_id:
        return True

    now = time()
    exp = _pass_cache.get(user_id)
    if exp and exp > now:
        return True  # недавно подтверждали подписку — не дёргаем API

    try:
        member = await bot.get_chat_member(cfg.sub_gate_channel, user_id)
    except Exception as e:
        # Не блокируем при сбое проверки — иначе можно закрыть бота целиком.
        logger.warning(f"[SUBGATE] get_chat_member failed user={user_id}: {e}")
        return True

    ok = _is_subscribed(member)
    if ok:
        _pass_cache[user_id] = now + _PASS_TTL
    else:
        _pass_cache.pop(user_id, None)
    return ok


def gate_keyboard():
    cfg = get_config()
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📢 Вступить в гильдию", url=cfg.sub_gate_channel_url))
    b.row(InlineKeyboardButton(text="✅ Я подписался", callback_data=GATE_CALLBACK))
    return b.as_markup()


async def send_gate(message: Message) -> None:
    """Показать сообщение с требованием подписки (с баннером, если есть)."""
    from utils.media import answer_with_banner
    try:
        await answer_with_banner(
            message, "start", GATE_TEXT, reply_markup=gate_keyboard(),
        )
    except Exception as e:
        logger.warning(f"[SUBGATE] send_gate failed: {e}")
