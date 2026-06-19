"""
Реклама от спонсоров.

Публично:
  /advertise — мастер заявки (канал → описание → сколько подписчиков → тип).
               Заявка анонимна для пользователей: в заданиях виден только канал
               и краткое описание, кто оплатил — не показывается.

Владельцу (в личке):
  /adreqs            — заявки на модерацию (с кнопками одобрить/отклонить)
  /endsponsor <id>   — отменить спонсорство задания (снимается из заданий,
                       ещё 7 дней держится гарантия неотписки, затем свобода)
"""
from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from database import list_ad_requests, get_ad_request
from services import submit_ad_request, approve_ad_request, reject_ad_request, end_sponsorship
from services.sponsors import _to_chat_ref
from utils import escape_html, is_owner, get_config

router = Router()

# Награда охотнику за подписку на канал спонсора (= 100 опыта за задание).
_SPONSOR_TASK_REWARD = 100


class AdRequest(StatesGroup):
    channel = State()
    description = State()
    target = State()
    sponsor_type = State()


ADVERTISE_INTRO = (
    "📣 <b>РЕКЛАМА В СИСТЕМЕ S-RANK</b>\n\n"
    "Приведём живых подписчиков на твой канал руками охотников.\n"
    "Подписки <b>гарантируются от отписки</b> (временный пакет — до 7 дней, "
    "постоянный — пока ты спонсор + 7 дней после).\n\n"
    "<b>Шаг 1/4.</b> Пришли <b>@username</b> или ссылку на публичный канал.\n"
    "⚠️ Бота нужно будет добавить в канал администратором (чтобы засчитывать подписки).\n\n"
    "Отмена: /cancel"
)


@router.message(Command("advertise", "sponsor"), F.chat.type == "private")
async def cmd_advertise(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AdRequest.channel)
    await message.answer(ADVERTISE_INTRO, parse_mode="HTML", disable_web_page_preview=True)


@router.message(Command("cancel"), StateFilter(
    AdRequest.channel, AdRequest.description, AdRequest.target, AdRequest.sponsor_type))
async def cmd_cancel_ad(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Заявка на рекламу отменена.")


@router.message(AdRequest.channel, F.chat.type == "private")
async def adreq_channel(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if _to_chat_ref(raw) is None:
        await message.answer(
            "⚠️ Нужен публичный канал: <code>@username</code> или "
            "<code>https://t.me/username</code>. Попробуй ещё раз или /cancel.",
            parse_mode="HTML",
        )
        return
    await state.update_data(channel_url=raw, channel_username=_to_chat_ref(raw).lstrip("@"))
    await state.set_state(AdRequest.description)
    await message.answer(
        "<b>Шаг 2/4.</b> Опиши канал <b>двумя-тремя словами</b> "
        "(например: «новости крипты» или «мемы и юмор»).",
        parse_mode="HTML",
    )


@router.message(AdRequest.description, F.chat.type == "private")
async def adreq_description(message: Message, state: FSMContext) -> None:
    desc = (message.text or "").strip()
    if not (2 <= len(desc) <= 60):
        await message.answer("⚠️ Описание — от 2 до 60 символов. Попробуй ещё раз.")
        return
    await state.update_data(description=desc)
    await state.set_state(AdRequest.target)
    await message.answer(
        "<b>Шаг 3/4.</b> Сколько <b>подписчиков</b> хочешь привести? Пришли число "
        "(например, <code>1000</code>).",
        parse_mode="HTML",
    )


@router.message(AdRequest.target, F.chat.type == "private")
async def adreq_target(message: Message, state: FSMContext) -> None:
    txt = (message.text or "").strip().replace(" ", "")
    if not txt.isdigit() or not (1 <= int(txt) <= 10_000_000):
        await message.answer("⚠️ Пришли положительное число подписчиков.")
        return
    await state.update_data(target_subs=int(txt))
    await state.set_state(AdRequest.sponsor_type)
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔁 Постоянный (трафик регулярно)", callback_data="adtype:permanent"))
    b.row(InlineKeyboardButton(text="⏳ Разовый (привести и всё)", callback_data="adtype:temporary"))
    await message.answer(
        "<b>Шаг 4/4.</b> Какой формат спонсорства?\n\n"
        "🔁 <b>Постоянный</b> — регулярный трафик, канал держится в заданиях, "
        "гарантия неотписки максимальная.\n"
        "⏳ <b>Разовый</b> — нужно привести аудиторию один раз; гарантия неотписки до 7 дней.\n\n"
        "<i>Детали и условия пришлём лично после одобрения заявки.</i>",
        parse_mode="HTML",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data.startswith("adtype:"), AdRequest.sponsor_type)
async def adreq_type(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    sponsor_type = call.data.split(":", 1)[1]
    data = await state.get_data()
    await state.clear()
    user = call.from_user

    req_id = await submit_ad_request(
        advertiser_id=user.id,
        advertiser_name=user.full_name or user.username or str(user.id),
        channel_url=data.get("channel_url", ""),
        channel_username=data.get("channel_username", ""),
        description=data.get("description", ""),
        target_subs=data.get("target_subs", 0),
        sponsor_type=sponsor_type,
    )
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(
        "✅ <b>Заявка отправлена на модерацию!</b>\n\n"
        f"Канал: <code>@{escape_html(data.get('channel_username',''))}</code>\n"
        f"Подписчиков: <b>{data.get('target_subs', 0)}</b>\n"
        f"Формат: <b>{'постоянный' if sponsor_type=='permanent' else 'разовый'}</b>\n\n"
        "Мы свяжемся для оплаты и запуска. Спасибо!",
        parse_mode="HTML",
    )
    await call.answer()
    await _notify_owner_new_request(bot, req_id)


async def _notify_owner_new_request(bot: Bot, req_id: int) -> None:
    cfg = get_config()
    req = await get_ad_request(req_id)
    if not req or not cfg.owner_id:
        return
    text = (
        "📥 <b>НОВАЯ ЗАЯВКА НА РЕКЛАМУ</b>\n\n"
        f"🆔 <code>#{req['id']}</code>\n"
        f"📣 Канал: <code>@{escape_html(req.get('channel_username') or '')}</code>\n"
        f"🔗 {escape_html(req.get('channel_url') or '')}\n"
        f"📝 Описание: {escape_html(req.get('description') or '')}\n"
        f"🎯 Хочет подписчиков: <b>{req.get('target_subs', 0)}</b>\n"
        f"📦 Формат: <b>{'постоянный' if req.get('sponsor_type')=='permanent' else 'разовый'}</b>\n"
        f"👤 От: {escape_html(req.get('advertiser_name') or '')} "
        f"(<code>{req.get('advertiser_id')}</code>)\n\n"
        "⚠️ Перед одобрением убедись, что бот — <b>админ</b> в канале."
    )
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="✅ Одобрить", callback_data=f"adreq_ok:{req_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adreq_no:{req_id}"),
    )
    try:
        await bot.send_message(cfg.owner_id, text, parse_mode="HTML",
                               reply_markup=b.as_markup(), disable_web_page_preview=True)
    except Exception:
        pass


# ── Владелец: модерация ──────────────────────────────────────────────────────

@router.message(Command("adreqs"), F.chat.type == "private")
async def cmd_adreqs(message: Message) -> None:
    if not is_owner(message.from_user.id):
        return
    reqs = await list_ad_requests("pending", limit=20)
    if not reqs:
        await message.answer("📥 Заявок на рекламу нет.")
        return
    for req in reqs:
        await _notify_owner_card(message.answer, req)


async def _notify_owner_card(answer, req: dict) -> None:
    text = (
        f"📥 Заявка <code>#{req['id']}</code>\n"
        f"📣 <code>@{escape_html(req.get('channel_username') or '')}</code> — "
        f"{escape_html(req.get('description') or '')}\n"
        f"🎯 {req.get('target_subs', 0)} подп. · "
        f"{'постоянный' if req.get('sponsor_type')=='permanent' else 'разовый'}\n"
        f"👤 <code>{req.get('advertiser_id')}</code>"
    )
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="✅ Одобрить", callback_data=f"adreq_ok:{req['id']}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adreq_no:{req['id']}"),
    )
    await answer(text, parse_mode="HTML", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("adreq_ok:"))
async def cb_adreq_ok(call: CallbackQuery, bot: Bot) -> None:
    if not is_owner(call.from_user.id):
        await call.answer("Только владелец.", show_alert=True)
        return
    req_id = int(call.data.split(":", 1)[1])
    await call.answer("Проверяю канал…")
    ok, msg, task_id = await approve_ad_request(
        bot, req_id, reward=_SPONSOR_TASK_REWARD, owner_id=call.from_user.id
    )
    icon = "✅" if ok else "⚠️"
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.message.answer(f"{icon} {msg}", parse_mode="HTML")


@router.callback_query(F.data.startswith("adreq_no:"))
async def cb_adreq_no(call: CallbackQuery, bot: Bot) -> None:
    if not is_owner(call.from_user.id):
        await call.answer("Только владелец.", show_alert=True)
        return
    req_id = int(call.data.split(":", 1)[1])
    ok, msg = await reject_ad_request(bot, req_id)
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.answer(msg, show_alert=True)
    await call.message.answer(f"❌ {msg}")


@router.message(Command("endsponsor"), F.chat.type == "private")
async def cmd_endsponsor(message: Message) -> None:
    if not is_owner(message.from_user.id):
        return
    args = (message.text or "").split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer(
            "Использование: <code>/endsponsor 12</code> (id задания).\n"
            "Задание снимется из активных, ещё 7 дней держится гарантия неотписки, "
            "затем охотники свободны.",
            parse_mode="HTML",
        )
        return
    await end_sponsorship(int(args[1]))
    await message.answer(
        f"🛑 Спонсорство задания <code>#{args[1]}</code> остановлено.\n"
        "Канал убран из заданий. Гарантия неотписки действует ещё 7 дней.",
        parse_mode="HTML",
    )
