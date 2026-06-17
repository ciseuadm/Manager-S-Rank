"""
Tasks handlers.

Пользователь:
  /tasks   — доступные задания (подписки на каналы) с проверкой и наградой
  /redeem  — обмен заработанной заданиями руды на подарок

Владелец (в ЛС):
  /addtask  — мастер добавления задания-подписки
  /tasklist — список заданий со статистикой
  /deltask  — выключить задание
  /payouts  — заявки на вывод, /approve <id>, /reject <id>
"""
from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from database import (
    list_tasks, set_task_active, create_task,
    task_completions_count, list_payout_requests,
    get_payout_request, set_payout_status, get_user_achievements,
)
from services import (
    list_available_tasks, check_and_credit_subscription, request_payout,
    refund_payout, mana_to_usd_cents, balance_of,
    user_streak, streak_multiplier,
)
from utils import is_owner, get_config, format_mana, mention_html_raw

router = Router()


# ── Клавиатуры ───────────────────────────────────────────────────────────────

def _tasks_keyboard(tasks: list[dict]) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    for t in tasks:
        if t.get("done"):
            b.row(InlineKeyboardButton(
                text=f"✅ {(t['title'] or 'Задание')[:32]} (+{t['reward']})",
                callback_data=f"task:done:{t['id']}",
            ))
        else:
            url = t.get("url") or (
                f"https://t.me/{t['channel_username']}" if t.get("channel_username") else None
            )
            if url:
                b.row(InlineKeyboardButton(text=f"➡️ {(t['title'] or 'Канал')[:32]}", url=url))
            b.row(InlineKeyboardButton(
                text=f"🔍 Проверить и забрать +{t['reward']} руды",
                callback_data=f"task:check:{t['id']}",
            ))
    b.row(InlineKeyboardButton(text="🔄 Обновить", callback_data="task:list"))
    return b


def _redeem_tiers() -> list[tuple[int, str]]:
    cfg = get_config()
    m = cfg.redeem_min
    return [
        (m, "🎁 Подарок Telegram"),
        (m * 2, "🎁 Премиум-подарок"),
        (m * 4, "👑 Telegram Premium"),
    ]


def _redeem_keyboard(balance: int) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    for amount, label in _redeem_tiers():
        ok = balance >= amount
        prefix = "" if ok else "🔒 "
        b.row(InlineKeyboardButton(
            text=f"{prefix}{label} — {format_mana(amount)}",
            callback_data=f"redeem:{amount}",
        ))
    b.row(InlineKeyboardButton(text="✖ Закрыть", callback_data="redeem:close"))
    return b


# ── /tasks ───────────────────────────────────────────────────────────────────

async def _render_tasks(user_id: int) -> tuple[str, InlineKeyboardBuilder]:
    tasks = await list_available_tasks(user_id)
    balance = await balance_of(user_id)
    if not tasks:
        text = (
            "📋 <b>ЗАДАНИЯ ГИЛЬДИИ</b>\n\n"
            "Сейчас активных заданий нет. Загляни позже — Система регулярно "
            "присылает новые подземелья для добычи Мана-руды.\n\n"
            f"🔹 Твой баланс: <b>{format_mana(balance)}</b>"
        )
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="🔄 Обновить", callback_data="task:list"))
        return text, b

    done = sum(1 for t in tasks if t.get("done"))
    streak = await user_streak(user_id)
    mult = streak_multiplier(streak)
    mult_line = (
        f"🔥 Стрик подписок: <b>{streak}</b> → множитель награды <b>×{mult:.1f}</b>\n"
        if streak > 0 else
        "🔥 Каждая сохранённая подписка повышает множитель будущих наград!\n"
    )
    text = (
        "📋 <b>ЗАДАНИЯ ГИЛЬДИИ</b>\n"
        "<i>Выполняй задания — добывай руду, которую можно обменять на подарки.</i>\n\n"
        f"✅ Выполнено: <b>{done}/{len(tasks)}</b>\n"
        f"🔹 Твой баланс: <b>{format_mana(balance)}</b>\n"
        f"{mult_line}\n"
        "1. Подпишись на канал по кнопке.\n"
        "2. Нажми «Проверить» — Система начислит руду (с учётом множителя).\n"
        "3. Оставайся подписан на ВСЕ каналы: при отписке награда и стрик падают.\n\n"
        "Обменять руду на подарок: /redeem · Достижения: /achievements"
    )
    return text, _tasks_keyboard(tasks)


@router.message(Command("tasks", "task"))
async def cmd_tasks(message: Message) -> None:
    if not message.from_user:
        return
    text, kb = await _render_tasks(message.from_user.id)
    await message.answer(text, parse_mode="HTML", reply_markup=kb.as_markup(),
                         disable_web_page_preview=True)


@router.callback_query(F.data == "task:list")
async def cb_task_list(call: CallbackQuery) -> None:
    text, kb = await _render_tasks(call.from_user.id)
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb.as_markup(),
                                     disable_web_page_preview=True)
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data.startswith("task:done:"))
async def cb_task_done(call: CallbackQuery) -> None:
    await call.answer("Это задание уже выполнено ✅", show_alert=True)


@router.callback_query(F.data.startswith("task:check:"))
async def cb_task_check(call: CallbackQuery, bot: Bot) -> None:
    task_id = int(call.data.split(":")[2])
    code, reward = await check_and_credit_subscription(bot, call.from_user.id, task_id)

    if code == "credited":
        await call.answer(f"✅ +{reward} руды зачислено!", show_alert=True)
    elif code == "already":
        await call.answer("Награда за это задание уже получена.", show_alert=True)
    elif code == "not_subscribed":
        await call.answer(
            "❌ Подписка не найдена. Подпишись на канал и нажми «Проверить» снова.",
            show_alert=True,
        )
    elif code == "inactive":
        await call.answer("Это задание больше не активно.", show_alert=True)
    else:  # misconfig
        await call.answer(
            "⚠️ Задание временно недоступно (проверка не прошла). Попробуй позже.",
            show_alert=True,
        )

    # Обновляем список после успешного начисления.
    if code == "credited":
        text, kb = await _render_tasks(call.from_user.id)
        try:
            await call.message.edit_text(text, parse_mode="HTML",
                                         reply_markup=kb.as_markup(),
                                         disable_web_page_preview=True)
        except Exception:
            pass


# ── /redeem ──────────────────────────────────────────────────────────────────

@router.message(Command("redeem", "withdraw", "exchange"))
async def cmd_redeem(message: Message) -> None:
    if not message.from_user:
        return
    cfg = get_config()
    balance = await balance_of(message.from_user.id)
    text = (
        "🎁 <b>ОБМЕН РУДЫ НА ПОДАРКИ</b>\n\n"
        f"🔹 Твой баланс: <b>{format_mana(balance)}</b>\n\n"
        f"Минимум для обмена: <b>{format_mana(cfg.redeem_min)}</b>.\n"
        "Выбери награду ниже. Заявка уйдёт на подтверждение Системе, "
        "после чего подарок будет отправлен."
    )
    await message.answer(text, parse_mode="HTML",
                         reply_markup=_redeem_keyboard(balance).as_markup())


@router.callback_query(F.data == "redeem:close")
async def cb_redeem_close(call: CallbackQuery) -> None:
    try:
        await call.message.delete()
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data.startswith("redeem:"))
async def cb_redeem(call: CallbackQuery, bot: Bot) -> None:
    part = call.data.split(":")[1]
    if not part.isdigit():
        await call.answer()
        return
    amount = int(part)
    # Подбираем человекочитаемое имя награды.
    label = next((lbl for amt, lbl in _redeem_tiers() if amt == amount), "Подарок")

    ok, req_id, err = await request_payout(call.from_user.id, amount, label)
    if not ok:
        await call.answer(f"❌ {err}", show_alert=True)
        return

    await call.answer("✅ Заявка создана!", show_alert=True)
    try:
        await call.message.edit_text(
            "✅ <b>ЗАЯВКА НА ОБМЕН СОЗДАНА</b>\n\n"
            f"Награда: <b>{label}</b>\n"
            f"Списано: <b>{format_mana(amount)}</b>\n"
            f"Заявка №{req_id} — ожидает подтверждения Системы.\n\n"
            "<i>Как только Монарх подтвердит — подарок будет отправлен. "
            "Если что-то пойдёт не так, руда вернётся на баланс.</i>",
            parse_mode="HTML",
        )
    except Exception:
        pass

    # Уведомляем владельца.
    cfg = get_config()
    if cfg.owner_id:
        try:
            usd = mana_to_usd_cents(amount) / 100
            await bot.send_message(
                cfg.owner_id,
                "🎁 <b>НОВАЯ ЗАЯВКА НА ВЫВОД</b>\n\n"
                f"№{req_id}\n"
                f"Пользователь: <code>{call.from_user.id}</code> "
                f"({mention_html_raw(call.from_user.id, call.from_user.full_name)})\n"
                f"Награда: <b>{label}</b>\n"
                f"Списано руды: <b>{format_mana(amount)}</b>\n"
                f"Себестоимость: <b>~${usd:.2f}</b>\n\n"
                f"Подтвердить: /approve {req_id}\n"
                f"Отклонить: /reject {req_id}",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"[TASKS] owner notify failed: {e}")


# ── /achievements ────────────────────────────────────────────────────────────

ACHIEVEMENT_NAMES = {
    "rank_a_top100": "👑 Первая сотня ранга A",
}


@router.message(Command("achievements", "ach"))
async def cmd_achievements(message: Message) -> None:
    if not message.from_user:
        return
    codes = await get_user_achievements(message.from_user.id)
    if not codes:
        await message.answer(
            "🏅 <b>ДОСТИЖЕНИЯ</b>\n\n"
            "Пока пусто. Выполняй задания (/tasks), копи руду и попади в историю гильдии — "
            "например, в <b>первую сотню охотников ранга A</b>!",
            parse_mode="HTML",
        )
        return
    lines = ["🏅 <b>ТВОИ ДОСТИЖЕНИЯ</b>\n"]
    for c in codes:
        lines.append(f"• {ACHIEVEMENT_NAMES.get(c, c)}")
    await message.answer("\n".join(lines), parse_mode="HTML")


# ── Owner: мастер добавления задания ─────────────────────────────────────────

class NewTask(StatesGroup):
    channel = State()
    reward = State()
    link = State()


def _resolve_forward_chat(message: Message):
    fchat = getattr(message, "forward_from_chat", None)
    if fchat is None:
        fo = getattr(message, "forward_origin", None)
        if fo is not None:
            fchat = getattr(fo, "chat", None)
    return fchat


@router.message(Command("addtask"), F.chat.type == "private")
async def cmd_addtask(message: Message, state: FSMContext) -> None:
    if not is_owner(message.from_user.id):
        return
    await state.clear()
    await state.set_state(NewTask.channel)
    await message.answer(
        "🆕 <b>НОВОЕ ЗАДАНИЕ-ПОДПИСКА</b>\n\n"
        "Шаг 1/3. Пришли канал одним из способов:\n"
        "• <b>перешли любой пост</b> из канала, или\n"
        "• пришли <code>@username</code> канала, или\n"
        "• пришли числовой <code>-100…</code> ID.\n\n"
        "⚠️ Бот должен быть <b>администратором</b> этого канала, иначе он не сможет "
        "проверять подписку.\n\n"
        "Отмена: /cancel",
        parse_mode="HTML",
    )


@router.message(
    Command("cancel"), F.chat.type == "private",
    StateFilter(NewTask.channel, NewTask.reward, NewTask.link),
)
async def cmd_cancel_task(message: Message, state: FSMContext) -> None:
    if not is_owner(message.from_user.id):
        return
    await state.clear()
    await message.answer("❌ Создание задания отменено.")


@router.message(NewTask.channel, F.chat.type == "private")
async def newtask_channel(message: Message, state: FSMContext, bot: Bot) -> None:
    if not is_owner(message.from_user.id):
        return
    fchat = _resolve_forward_chat(message)
    target = None
    if fchat is not None:
        target = fchat.id
    else:
        txt = (message.text or "").strip()
        if txt.startswith("https://t.me/"):
            txt = "@" + txt.rsplit("/", 1)[-1]
        if txt.startswith("@") or txt.lstrip("-").isdigit():
            target = int(txt) if txt.lstrip("-").isdigit() else txt
    if target is None:
        await message.answer("⚠️ Не понял канал. Перешли пост из канала или пришли @username / -100… ID.")
        return

    try:
        chat = await bot.get_chat(target)
    except Exception as e:
        await message.answer(f"❌ Не удалось открыть канал: {e}\nПопробуй переслать пост из него.")
        return

    # Проверяем, что бот — админ канала (иначе проверка подписки невозможна).
    try:
        me = await bot.get_me()
        cm = await bot.get_chat_member(chat.id, me.id)
        status = getattr(cm.status, "value", cm.status)
        if status not in ("administrator", "creator"):
            await message.answer(
                "⚠️ Бот <b>не админ</b> в этом канале. Добавь бота администратором "
                "и повтори /addtask.", parse_mode="HTML",
            )
            return
    except Exception:
        await message.answer(
            "⚠️ Не удалось проверить права бота в канале. Убедись, что бот — админ канала."
        )
        return

    await state.update_data(
        channel_id=chat.id,
        channel_username=chat.username or "",
        title=chat.title or (f"@{chat.username}" if chat.username else "Канал"),
    )
    await state.set_state(NewTask.reward)
    cfg = get_config()
    await message.answer(
        f"✅ Канал: <b>{chat.title or chat.username}</b>\n\n"
        f"Шаг 2/3. Сколько <b>руды</b> платим за подписку?\n"
        f"Пришли число или /skip для значения по умолчанию "
        f"(<b>{cfg.task_reward_subscribe}</b>).",
        parse_mode="HTML",
    )


@router.message(Command("skip"), NewTask.reward, F.chat.type == "private")
async def newtask_skip_reward(message: Message, state: FSMContext) -> None:
    if not is_owner(message.from_user.id):
        return
    await state.update_data(reward=get_config().task_reward_subscribe)
    await _ask_link(message, state)


@router.message(NewTask.reward, F.chat.type == "private")
async def newtask_reward(message: Message, state: FSMContext) -> None:
    if not is_owner(message.from_user.id):
        return
    txt = (message.text or "").strip()
    if not txt.isdigit() or int(txt) <= 0:
        await message.answer("⚠️ Пришли положительное число или /skip.")
        return
    await state.update_data(reward=int(txt))
    await _ask_link(message, state)


async def _ask_link(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(NewTask.link)
    hint = ""
    if data.get("channel_username"):
        hint = f"\nИли /skip — возьму <code>https://t.me/{data['channel_username']}</code>."
    await message.answer(
        "Шаг 3/3. Пришли <b>ссылку для подписки</b> (для приватных каналов — "
        "пригласительную ссылку)." + hint,
        parse_mode="HTML",
    )


@router.message(Command("skip"), NewTask.link, F.chat.type == "private")
async def newtask_skip_link(message: Message, state: FSMContext) -> None:
    if not is_owner(message.from_user.id):
        return
    data = await state.get_data()
    url = f"https://t.me/{data['channel_username']}" if data.get("channel_username") else ""
    if not url:
        await message.answer("⚠️ У канала нет @username — пришли пригласительную ссылку вручную.")
        return
    await _finish_task(message, state, url)


@router.message(NewTask.link, F.chat.type == "private")
async def newtask_link(message: Message, state: FSMContext) -> None:
    if not is_owner(message.from_user.id):
        return
    url = (message.text or "").strip()
    if not url.startswith("http"):
        await message.answer("⚠️ Ссылка должна начинаться с http(s). Попробуй ещё раз или /skip.")
        return
    await _finish_task(message, state, url)


async def _finish_task(message: Message, state: FSMContext, url: str) -> None:
    data = await state.get_data()
    await state.clear()
    reward = int(data.get("reward", get_config().task_reward_subscribe))

    # Обратно считаем доход для P&L: revenue = reward / (mana_per_usd * ratio/100).
    cfg = get_config()
    denom = cfg.mana_per_usd * cfg.task_payout_ratio / 100
    revenue_cents = int(round(reward / denom * 100)) if denom > 0 else 0

    task_id = await create_task(
        type="channel_sub",
        title=data.get("title", "Канал"),
        channel_id=data["channel_id"],
        channel_username=data.get("channel_username", ""),
        url=url,
        reward=reward,
        revenue_cents=revenue_cents,
        daily=0,
        created_by=message.from_user.id,
    )
    await message.answer(
        f"✅ <b>Задание #{task_id} создано</b>\n\n"
        f"Канал: <b>{data.get('title')}</b>\n"
        f"Награда: <b>{format_mana(reward)}</b>\n"
        f"Оценка дохода: <b>~${revenue_cents / 100:.2f}</b> за подписчика\n\n"
        f"Пользователи увидят его в /tasks. Управление: /tasklist",
        parse_mode="HTML",
    )


# ── Owner: список и удаление заданий ─────────────────────────────────────────

@router.message(Command("tasklist"), F.chat.type == "private")
async def cmd_tasklist(message: Message) -> None:
    if not is_owner(message.from_user.id):
        return
    tasks = await list_tasks(limit=30)
    if not tasks:
        await message.answer("Заданий пока нет. Создай: /addtask")
        return
    lines = ["📋 <b>ВСЕ ЗАДАНИЯ</b>\n"]
    for t in tasks:
        icon = "🟢" if t.get("active") else "⚪️"
        cnt = await task_completions_count(t["id"])
        lines.append(
            f"{icon} <code>#{t['id']}</code> «{(t['title'] or '—')[:24]}» — "
            f"+{t['reward']} руды, выполнили {cnt}"
        )
    lines.append("\n⛔️ Выключить: /deltask &lt;id&gt;")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("deltask"), F.chat.type == "private")
async def cmd_deltask(message: Message) -> None:
    if not is_owner(message.from_user.id):
        return
    args = (message.text or "").split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: <code>/deltask 3</code>", parse_mode="HTML")
        return
    await set_task_active(int(args[1]), 0)
    await message.answer(f"⚪️ Задание #{args[1]} выключено.")


# ── Owner: заявки на вывод ───────────────────────────────────────────────────

@router.message(Command("payouts"), F.chat.type == "private")
async def cmd_payouts(message: Message) -> None:
    if not is_owner(message.from_user.id):
        return
    reqs = await list_payout_requests(status="pending", limit=30)
    if not reqs:
        await message.answer("Заявок на вывод нет. ✅")
        return
    lines = ["🎁 <b>ЗАЯВКИ НА ВЫВОД (ожидают)</b>\n"]
    for r in reqs:
        lines.append(
            f"<code>#{r['id']}</code> — user <code>{r['user_id']}</code>, "
            f"<b>{r['product']}</b>, {format_mana(r['amount'])} (~${r['usd_cents'] / 100:.2f})"
        )
    lines.append("\n✅ /approve &lt;id&gt;   ❌ /reject &lt;id&gt;")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("approve"), F.chat.type == "private")
async def cmd_approve(message: Message, bot: Bot) -> None:
    if not is_owner(message.from_user.id):
        return
    args = (message.text or "").split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: <code>/approve 5</code>", parse_mode="HTML")
        return
    req = await get_payout_request(int(args[1]))
    if not req or req["status"] != "pending":
        await message.answer("Заявка не найдена или уже обработана.")
        return
    await set_payout_status(req["id"], "approved")
    await message.answer(
        f"✅ Заявка #{req['id']} подтверждена. Отправь подарок «{req['product']}» "
        f"пользователю <code>{req['user_id']}</code> вручную, затем можно считать выполненной."
    )
    try:
        await bot.send_message(
            req["user_id"],
            "🎉 <b>Твоя заявка на вывод подтверждена!</b>\n"
            f"Награда «{req['product']}» скоро будет у тебя. Спасибо, охотник!",
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.message(Command("reject"), F.chat.type == "private")
async def cmd_reject(message: Message, bot: Bot) -> None:
    if not is_owner(message.from_user.id):
        return
    args = (message.text or "").split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: <code>/reject 5</code>", parse_mode="HTML")
        return
    req = await get_payout_request(int(args[1]))
    if not req or req["status"] != "pending":
        await message.answer("Заявка не найдена или уже обработана.")
        return
    await set_payout_status(req["id"], "rejected")
    await refund_payout(req["user_id"], req["amount"], ref=f"reject_{req['id']}")
    await message.answer(
        f"❌ Заявка #{req['id']} отклонена. Руда ({format_mana(req['amount'])}) "
        f"возвращена пользователю."
    )
    try:
        await bot.send_message(
            req["user_id"],
            "ℹ️ Твоя заявка на вывод отклонена, руда возвращена на баланс. "
            "Если есть вопросы — обратись к администрации.",
        )
    except Exception:
        pass
