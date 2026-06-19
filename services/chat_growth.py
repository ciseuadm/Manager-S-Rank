"""
Chat acquisition (owner-рефералка) — главный рычаг роста.

Логика обработки `my_chat_member`: когда бота добавляют/повышают/удаляют в чате.
Регистрирует чат, приветствует, награждает того, кто привёл бота (когда бот
получил админку), считает вехи и чистит БД при удалении.
"""
from aiogram import Bot
from aiogram.types import ChatMemberUpdated
from loguru import logger

from database import (
    record_chat_referral, get_chat_referral, set_chat_referral_admin,
    mark_chat_referral_rewarded, mark_chat_referral_left,
    count_active_chats_brought, get_recruit_blocks_paid, set_recruit_blocks_paid,
    set_chat_title, remove_chat, add_mana,
)
from utils import (
    get_config, format_mana, escape_html,
    BOT_ADDED_WELCOME, BOT_NEEDS_ADMIN_MSG, CHAT_OWNER_REWARD_MSG,
    CHAT_RECRUIT_MILESTONE_MSG,
)

# Статусы, означающие, что участник присутствует в чате.
_PRESENT = {"member", "administrator", "creator", "restricted"}


def _present(status: str) -> bool:
    return status in _PRESENT


async def _send_chat(bot: Bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id, text, parse_mode="HTML",
                               disable_web_page_preview=True)
    except Exception as e:
        logger.warning(f"[GROWTH] chat msg {chat_id} failed: {e}")


async def _dm(bot: Bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text, parse_mode="HTML",
                               disable_web_page_preview=True)
    except Exception:
        pass


def progress_line(active: int, block: int) -> str:
    """Строка прогресса до следующей вехи привлечения чатов."""
    base = f"🏰 Подземелий под охраной: <b>{active}</b>"
    if block <= 0:
        return base
    remainder = active % block
    to_next = block - remainder if remainder else (0 if active else block)
    if to_next:
        return base + f" · до вехи (+бонус): ещё <b>{to_next}</b>"
    return base


async def _check_recruit_milestone(bot: Bot, owner_id: int, active_count: int) -> None:
    """Веховые бонусы за каждые N приведённых активных чатов (одноразово на веху)."""
    cfg = get_config()
    block = cfg.chat_recruit_block
    if block <= 0:
        return
    blocks = active_count // block
    paid = await get_recruit_blocks_paid(owner_id)
    if blocks <= paid:
        return
    amount = (blocks - paid) * cfg.chat_recruit_block_reward
    await set_recruit_blocks_paid(owner_id, blocks)
    if amount > 0:
        await add_mana(owner_id, amount, "chat_recruit_milestone", ref_id=str(active_count))
        await _dm(
            bot, owner_id,
            CHAT_RECRUIT_MILESTONE_MSG.format(
                count=active_count, reward=format_mana(amount),
                next_goal=(blocks + 1) * block,
            ),
        )


async def _maybe_reward(bot: Bot, chat_id: int, chat_title: str) -> None:
    """Выдать награду за приведённый чат, когда бот стал админом. Один раз на чат."""
    ref = await get_chat_referral(chat_id)
    if not ref or ref.get("rewarded"):
        return
    inviter_id = ref.get("inviter_id") or 0
    # Помечаем выданным ДО начисления — защита от гонок (повторный my_chat_member).
    await mark_chat_referral_rewarded(chat_id)
    if not inviter_id:
        return

    cfg = get_config()
    bonus = cfg.mana_chat_owner_bonus
    if bonus > 0:
        await add_mana(inviter_id, bonus, "chat_owner", ref_id=str(chat_id))

    active = await count_active_chats_brought(inviter_id)
    await _dm(
        bot, inviter_id,
        CHAT_OWNER_REWARD_MSG.format(
            chat=escape_html(chat_title or "без названия"),
            reward=format_mana(bonus),
            progress=progress_line(active, cfg.chat_recruit_block),
        ),
    )
    await _check_recruit_milestone(bot, inviter_id, active)
    logger.info(f"[GROWTH] rewarded {inviter_id} for chat {chat_id} (active={active})")


async def handle_bot_membership(bot: Bot, event: ChatMemberUpdated) -> None:
    """Единая точка обработки изменения статуса САМОГО бота в чате."""
    chat = event.chat
    if chat.type not in ("group", "supergroup"):
        return

    old = event.old_chat_member.status
    new = event.new_chat_member.status
    actor = event.from_user
    title = chat.title or ""

    became_present = (not _present(old)) and _present(new)
    became_absent = _present(old) and (not _present(new))
    is_admin_now = new == "administrator"

    if became_absent:
        await mark_chat_referral_left(chat.id)
        await remove_chat(chat.id)
        logger.info(f"[GROWTH] bot removed from {chat.id}")
        return

    if became_present:
        await set_chat_title(chat.id, title)
        # Кто добавил бота — он и привёл чат (игнорируем ботов как инвайтеров).
        valid_inviter = actor.id if (actor and not actor.is_bot) else 0
        await record_chat_referral(chat.id, valid_inviter, title)
        await _send_chat(bot, chat.id, BOT_ADDED_WELCOME if is_admin_now else BOT_NEEDS_ADMIN_MSG)

    if is_admin_now:
        await set_chat_referral_admin(chat.id, True)
        # Повышение до админа уже присутствующего бота — поприветствуем один раз.
        if not became_present and old != "administrator":
            await _send_chat(bot, chat.id, BOT_ADDED_WELCOME)
        await _maybe_reward(bot, chat.id, title)
    elif old == "administrator" and _present(new):
        # Бота разжаловали из админов — модерация невозможна, фиксируем.
        await set_chat_referral_admin(chat.id, False)
