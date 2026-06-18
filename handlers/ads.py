"""
Advertising control panel (owner only, private chat).

  /newad     — wizard to create a campaign (content → button → days)
  /ads       — list campaigns + global stats
  /pausead   — pause a campaign
  /resumead  — resume a campaign
  /deletead  — delete an obsolete campaign
  /sendads   — force-send all due campaigns now

Chat-side toggle (/ads on|off in a group) lives in handlers/settings.py.
"""
from aiogram import Router, F, Bot
from aiogram.filters import Command, BaseFilter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from database import (
    create_campaign, get_all_campaigns, get_campaign, set_campaign_status,
    delete_campaign, campaign_stats, ads_global_stats,
)
from services import send_campaign_now, send_due_ads
from utils import escape_html, is_owner

router = Router()


class IsOwner(BaseFilter):
    async def __call__(self, event) -> bool:
        u = getattr(event, "from_user", None)
        return is_owner(u.id if u else None)


# Whole router is owner-only and private-only for management commands.
router.message.filter(IsOwner())
router.callback_query.filter(IsOwner())


class NewAd(StatesGroup):
    content = State()
    button = State()
    days = State()


_STATUS_ICON = {"active": "🟢", "paused": "⏸", "done": "✅"}


# ── /newad wizard ────────────────────────────────────────────────────────────

@router.message(Command("newad"), F.chat.type == "private")
async def cmd_newad(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(NewAd.content)
    await message.answer(
        "📢 <b>НОВАЯ РЕКЛАМНАЯ КАМПАНИЯ</b>\n\n"
        "Шаг 1/3. Пришли <b>контент</b> рекламы:\n"
        "• просто текст (можно с HTML-разметкой), или\n"
        "• перешли / отправь готовый пост (фото, видео, и т.д.)\n\n"
        "Отмена: /cancel",
        parse_mode="HTML",
    )


@router.message(Command("cancel"), F.chat.type == "private", ~StateFilter(None))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Создание кампании отменено.")


@router.message(NewAd.content, F.chat.type == "private")
async def newad_content(message: Message, state: FSMContext) -> None:
    if message.text and not message.entities and message.content_type == "text":
        await state.update_data(
            content_type="text", payload=message.html_text,
            from_chat_id=0, from_msg_id=0,
        )
    elif message.content_type == "text":
        # текст с разметкой — сохраняем html_text
        await state.update_data(
            content_type="text", payload=message.html_text,
            from_chat_id=0, from_msg_id=0,
        )
    else:
        # медиа/пересланный пост — будем копировать его при рассылке
        await state.update_data(
            content_type="copy", payload="",
            from_chat_id=message.chat.id, from_msg_id=message.message_id,
        )
    await state.set_state(NewAd.button)
    await message.answer(
        "Шаг 2/3. Добавить <b>кнопку-ссылку</b>?\n"
        "Пришли в формате <code>Текст кнопки | https://ссылка</code>\n"
        "или /skip, чтобы без кнопки.",
        parse_mode="HTML",
    )


@router.message(Command("skip"), NewAd.button, F.chat.type == "private")
async def newad_skip_button(message: Message, state: FSMContext) -> None:
    await state.update_data(button_text="", button_url="")
    await _ask_days(message, state)


@router.message(NewAd.button, F.chat.type == "private")
async def newad_button(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if "|" in text:
        label, url = [p.strip() for p in text.split("|", 1)]
        if url.startswith("http"):
            await state.update_data(button_text=label[:64], button_url=url)
        else:
            await message.answer("⚠️ Ссылка должна начинаться с http(s). Попробуй ещё раз или /skip.")
            return
    else:
        await message.answer("⚠️ Формат: <code>Текст | https://ссылка</code> или /skip.", parse_mode="HTML")
        return
    await _ask_days(message, state)


async def _ask_days(message: Message, state: FSMContext) -> None:
    await state.set_state(NewAd.days)
    await message.answer(
        "Шаг 3/3. Сколько <b>дней</b> крутить кампанию?\n"
        "Пришли число (например, <code>7</code>). Реклама уходит раз в день.",
        parse_mode="HTML",
    )


@router.message(NewAd.days, F.chat.type == "private")
async def newad_days(message: Message, state: FSMContext) -> None:
    txt = (message.text or "").strip()
    if not txt.isdigit() or int(txt) < 1:
        await message.answer("⚠️ Пришли положительное число дней.")
        return
    days = min(int(txt), 365)
    data = await state.get_data()
    await state.clear()

    title = (data.get("payload") or "медиа-пост")[:40]
    cid = await create_campaign(
        owner_id=message.from_user.id,
        title=title,
        content_type=data["content_type"],
        payload=data.get("payload", ""),
        from_chat_id=data.get("from_chat_id", 0),
        from_msg_id=data.get("from_msg_id", 0),
        button_text=data.get("button_text", ""),
        button_url=data.get("button_url", ""),
        target="all",
        days_total=days,
    )

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📤 Разослать сейчас", callback_data=f"adsend:{cid}"))
    b.row(InlineKeyboardButton(text="📋 Все кампании", callback_data="adlist"))
    await message.answer(
        f"✅ <b>Кампания #{cid} создана</b>\n\n"
        f"Дней: <b>{days}</b>\n"
        f"Тип: <b>{data['content_type']}</b>\n"
        f"Кнопка: {data.get('button_text') or '—'}\n\n"
        f"Реклама будет уходить раз в день автоматически.\n"
        f"Можешь разослать прямо сейчас 👇",
        parse_mode="HTML",
        reply_markup=b.as_markup(),
    )


# ── /ads — список и статистика ───────────────────────────────────────────────

async def _ads_overview() -> str:
    g = await ads_global_stats()
    camps = await get_all_campaigns(limit=15)
    lines = [
        "📢 <b>РЕКЛАМНЫЕ КАМПАНИИ</b>\n",
        f"Всего: <b>{g.get('campaigns', 0)}</b> | активных: <b>{g.get('active', 0)}</b> | "
        f"показов: <b>{g.get('impressions', 0)}</b>\n",
    ]
    if not camps:
        lines.append("\n<i>Кампаний пока нет. Создай: /newad</i>")
        return "\n".join(lines)
    for c in camps:
        st = await campaign_stats(c["id"])
        icon = _STATUS_ICON.get(c["status"], "•")
        title = escape_html((c["title"] or "—")[:24])
        lines.append(
            f"{icon} <code>#{c['id']}</code> «{title}» — "
            f"дней {c['days_done']}/{c['days_total']}, показов {st.get('sent') or 0}"
        )
    lines.append(
        "\n⏸ Пауза: /pausead &lt;id&gt;  ▶️ /resumead &lt;id&gt;  "
        "🗑 Удалить: /deletead &lt;id&gt;  📤 /sendads"
    )
    return "\n".join(lines)


@router.message(Command("ads"), F.chat.type == "private")
async def cmd_ads(message: Message) -> None:
    await message.answer(await _ads_overview(), parse_mode="HTML")


@router.message(Command("pausead"), F.chat.type == "private")
async def cmd_pausead(message: Message) -> None:
    args = (message.text or "").split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: <code>/pausead 3</code>", parse_mode="HTML")
        return
    if not await set_campaign_status(int(args[1]), "paused"):
        await message.answer(f"❌ Кампания #{args[1]} не найдена или уже удалена.")
        return
    await message.answer(f"⏸ Кампания #{args[1]} на паузе.")


@router.message(Command("resumead"), F.chat.type == "private")
async def cmd_resumead(message: Message) -> None:
    args = (message.text or "").split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: <code>/resumead 3</code>", parse_mode="HTML")
        return
    if not await set_campaign_status(int(args[1]), "active"):
        await message.answer(f"❌ Кампания #{args[1]} не найдена или уже удалена.")
        return
    await message.answer(f"▶️ Кампания #{args[1]} снова активна.")


@router.message(Command("deletead", "delad"), F.chat.type == "private")
async def cmd_deletead(message: Message) -> None:
    args = (message.text or "").split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: <code>/deletead 3</code>", parse_mode="HTML")
        return

    campaign_id = int(args[1])
    camp = await get_campaign(campaign_id)
    if not camp:
        await message.answer(f"❌ Кампания #{campaign_id} не найдена или уже удалена.")
        return

    if not await delete_campaign(campaign_id):
        await message.answer(f"❌ Кампания #{campaign_id} не найдена или уже удалена.")
        return

    title = escape_html((camp.get("title") or "—")[:60])
    await message.answer(
        f"🗑 Кампания <code>#{campaign_id}</code> «{title}» удалена из активного списка.",
        parse_mode="HTML",
    )


@router.message(Command("sendads"), F.chat.type == "private")
async def cmd_sendads(message: Message, bot: Bot) -> None:
    status = await message.answer("📤 Рассылаю активные кампании…")
    res = await send_due_ads(bot)
    await status.edit_text(
        f"✅ <b>Готово</b>\n\n"
        f"Кампаний: <b>{res.get('campaigns', 0)}</b>\n"
        f"Доставлено: <b>{res.get('sent', 0)}</b>\n"
        f"Ошибок: <b>{res.get('failed', 0)}</b>\n"
        f"Удалено мёртвых чатов: <b>{res.get('removed', 0)}</b>",
        parse_mode="HTML",
    )


# ── Callbacks ────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adsend:"))
async def cb_adsend(call: CallbackQuery, bot: Bot) -> None:
    cid = int(call.data.split(":")[1])
    await call.answer("Рассылаю…")
    res = await send_campaign_now(bot, cid)
    if res.get("error"):
        await call.message.answer("❌ Кампания не найдена.")
        return
    await call.message.answer(
        f"✅ Кампания #{cid} разослана.\n"
        f"Доставлено: <b>{res.get('sent', 0)}</b>, ошибок: <b>{res.get('failed', 0)}</b>, "
        f"удалено мёртвых: <b>{res.get('removed', 0)}</b>",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "adlist")
async def cb_adlist(call: CallbackQuery) -> None:
    await call.message.answer(await _ads_overview(), parse_mode="HTML")
    await call.answer()
