"""
Спонсоры и заявки рекламодателей.

Бизнес-правила:
  • Рекламодатель подаёт анонимную заявку (/advertise): канал, краткое
    описание, желаемое число подписчиков, тип (временный/постоянный).
  • Владелец одобряет → бот резолвит канал (должен быть в нём админом, чтобы
    проверять подписки) и создаёт задание со спонсорскими метаданными.
  • Гарантия неотписки:
      house/permanent — действует, пока задание активно; после отмены
        спонсорства держится ещё post_cancel_grace_days, затем пользователь
        волен отписаться без штрафа;
      temporary — действует guarantee_days от момента подписки конкретного
        пользователя; затем он свободен.
"""
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot
from loguru import logger

from database import (
    create_ad_request, get_ad_request, set_ad_request_status, create_task,
    end_task_sponsorship,
)
from utils import get_config


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "").split(".")[0].replace("T", " "))
    except (ValueError, TypeError):
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            return None


def completion_guaranteed(comp: dict, now: Optional[datetime] = None) -> bool:
    """Действует ли ещё гарантия неотписки для конкретного выполнения.

    comp — строка из get_credited_channel_completions (sponsor_type,
    guarantee_days, ended_at, comp_created_at).
    """
    now = now or datetime.utcnow()
    cfg = get_config()
    sponsor_type = (comp.get("sponsor_type") or "house")
    ended_at = _parse_dt(comp.get("ended_at"))

    if ended_at is not None:
        # Спонсорство отменено — пост-гарантия ещё grace дней.
        return now <= ended_at + timedelta(days=cfg.sponsor_post_cancel_grace_days)

    if sponsor_type in ("house", "permanent"):
        return True  # действует, пока задание активно

    if sponsor_type == "temporary":
        started = _parse_dt(comp.get("comp_created_at")) or now
        gdays = comp.get("guarantee_days") or cfg.sponsor_temp_guarantee_days
        return now <= started + timedelta(days=gdays)

    return True


# ── Заявки ───────────────────────────────────────────────────────────────────

async def submit_ad_request(
    *, advertiser_id: int, advertiser_name: str, channel_url: str,
    channel_username: str, description: str, target_subs: int, sponsor_type: str,
) -> int:
    return await create_ad_request(
        advertiser_id=advertiser_id, advertiser_name=advertiser_name,
        channel_url=channel_url, channel_username=channel_username,
        description=description, target_subs=target_subs, sponsor_type=sponsor_type,
    )


async def approve_ad_request(
    bot: Bot, req_id: int, *, reward: int, owner_id: int,
) -> tuple[bool, str, int]:
    """
    Одобрить заявку: резолвит канал (бот должен быть в нём админом), создаёт
    задание. Возвращает (ok, message, task_id).
    """
    req = await get_ad_request(req_id)
    if not req:
        return False, "Заявка не найдена.", 0
    if req["status"] != "pending":
        return False, f"Заявка уже обработана ({req['status']}).", 0

    cfg = get_config()
    ref = (req.get("channel_username") or req.get("channel_url") or "").strip()

    # Резолвим канал: нужен @username или t.me/<name>. По нему get_chat,
    # затем проверяем, что бот — админ (иначе подписки не проверить).
    chat_ref = _to_chat_ref(ref)
    if not chat_ref:
        return False, (
            "Не удалось определить канал. Нужен публичный @username "
            "(приватные каналы по invite-ссылке пока не поддерживаются)."
        ), 0
    try:
        chat = await bot.get_chat(chat_ref)
    except Exception as e:
        return False, (
            f"Не открыл канал {chat_ref}: {e}. Добавь бота в канал "
            f"<b>администратором</b> и повтори одобрение."
        ), 0
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat.id, me.id)
        if member.status not in ("administrator", "creator"):
            return False, (
                f"Бот не админ в «{chat.title}». Сначала дай боту права "
                f"администратора в канале, затем одобри снова."
            ), 0
    except Exception as e:
        return False, f"Не проверил права бота в канале: {e}", 0

    sponsor_type = req["sponsor_type"] if req["sponsor_type"] in ("temporary", "permanent") else "temporary"
    guarantee_days = cfg.sponsor_temp_guarantee_days if sponsor_type == "temporary" else 0
    username = (chat.username or "").lstrip("@")
    url = f"https://t.me/{username}" if username else (req.get("channel_url") or "")

    task_id = await create_task(
        type="channel_sub",
        title=chat.title or req.get("description") or "Канал спонсора",
        channel_id=chat.id,
        channel_username=username,
        url=url,
        reward=reward,
        revenue_cents=0,
        daily=0,
        created_by=owner_id,
        sponsor_type=sponsor_type,
        advertiser_id=req["advertiser_id"],
        anonymous=1,
        description=req.get("description") or "",
        target_subs=req.get("target_subs") or 0,
        guarantee_days=guarantee_days,
    )
    await set_ad_request_status(req_id, "approved", task_id=task_id)
    logger.info(f"[SPONSOR] approved req={req_id} → task={task_id} ({sponsor_type})")

    # Уведомляем рекламодателя (если когда-то писал боту).
    try:
        await bot.send_message(
            req["advertiser_id"],
            "✅ <b>Ваша заявка одобрена!</b>\n\n"
            f"Канал «{chat.title}» добавлен в задания Системы. "
            f"Тип: <b>{'постоянный' if sponsor_type=='permanent' else 'временный'}</b>.\n"
            f"Охотники начнут подписываться. Спасибо за сотрудничество!",
            parse_mode="HTML",
        )
    except Exception:
        pass

    return True, f"Задание #{task_id} создано для «{chat.title}».", task_id


async def reject_ad_request(bot: Bot, req_id: int, note: str = "") -> tuple[bool, str]:
    req = await get_ad_request(req_id)
    if not req:
        return False, "Заявка не найдена."
    if req["status"] != "pending":
        return False, f"Заявка уже обработана ({req['status']})."
    await set_ad_request_status(req_id, "rejected", note=note)
    try:
        await bot.send_message(
            req["advertiser_id"],
            "❌ <b>Заявка на рекламу отклонена.</b>\n"
            + (f"Причина: {note}\n" if note else "")
            + "Вы можете подать новую заявку: /advertise",
            parse_mode="HTML",
        )
    except Exception:
        pass
    return True, "Заявка отклонена."


async def end_sponsorship(task_id: int) -> None:
    """Отменить спонсорство задания (снять из активных, начать пост-гарантию)."""
    await end_task_sponsorship(task_id)
    logger.info(f"[SPONSOR] ended task={task_id} (grace window started)")


def _to_chat_ref(ref: str) -> Optional[str]:
    """Приводит ссылку/username к виду, понятному bot.get_chat: '@name'."""
    ref = (ref or "").strip()
    if not ref:
        return None
    if ref.startswith("@"):
        return ref
    # t.me/name или https://t.me/name
    if "t.me/" in ref:
        name = ref.split("t.me/", 1)[1].strip("/").split("/")[0].split("?")[0]
        if name and not name.startswith("+") and name.lower() != "joinchat":
            return "@" + name
        return None
    # голый username
    if all(c.isalnum() or c == "_" for c in ref):
        return "@" + ref
    return None
