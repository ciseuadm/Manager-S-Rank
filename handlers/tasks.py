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
    get_xp,
)
from services import (
    daily_tasks_view, check_and_credit_subscription, request_payout,
    refund_payout, mana_to_usd_cents, mana_to_rub, balance_of,
    user_streak, streak_multiplier, find_unsubscribed_channels, resubscribe_keyboard,
)
from services.gifts import get_catalog, send_telegram_gift, offer_from_product
from utils.redeem_ui import redeem_intro, redeem_keyboard
from utils import (
    is_owner, get_config, format_mana, mention_html_raw,
    get_rank_label, perks_lines, has_privileges,
    rank_perks, calculate_rank,
)
from utils.media import answer_with_banner

router = Router()


# ── Клавиатуры ───────────────────────────────────────────────────────────────

def _tasks_keyboard(tasks: list[dict]) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    for t in tasks:
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


def _redeem_keyboard(balance: int) -> InlineKeyboardBuilder:
    return redeem_keyboard(balance)


def _redeem_intro(balance: int) -> str:
    return redeem_intro(balance)


# ── /tasks ───────────────────────────────────────────────────────────────────

async def _render_tasks(user_id: int) -> tuple[str, InlineKeyboardBuilder]:
    view = await daily_tasks_view(user_id)
    balance = await balance_of(user_id)
    tasks = view["tasks"]
    rank = view["rank"]
    done_today, limit, remaining = view["done_today"], view["limit"], view["remaining"]

    streak = await user_streak(user_id)
    mult = streak_multiplier(streak)
    mult_line = (
        f"🔥 Стрик подписок: <b>{streak}</b> → множитель награды <b>×{mult:.1f}</b>\n"
        if streak > 0 else
        "🔥 Каждая сохранённая подписка повышает множитель будущих наград!\n"
    )

    # Привилегия ранга: надбавка к награде за задание (S/SS/SSS).
    perk = rank_perks(rank)
    perk_line = ""
    if has_privileges(rank) and perk["task_reward_pct"]:
        perk_line = (
            f"👑 Привилегия {get_rank_label(rank)}: "
            f"<b>+{perk['task_reward_pct']}% к награде</b>\n"
        )

    limit_line = f"📅 Заданий сегодня: <b>{done_today}/{limit}</b>\n"

    # Лимит исчерпан — на сегодня всё.
    if remaining <= 0:
        text = (
            "📋 <b>ЗАДАНИЯ ГИЛЬДИИ</b>\n\n"
            f"✅ Дневной лимит выполнен: <b>{done_today}/{limit}</b> заданий.\n"
            f"🔹 Твой баланс: <b>{format_mana(balance)}</b>\n"
            f"{perk_line}"
            "\n⏳ Новые задания откроются завтра. Подними ранг (S/SS/SSS) — "
            "и за каждое задание будешь получать больше руды: /privileges\n\n"
            "Обменять руду на подарок: /redeem · Достижения: /achievements"
        )
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="🔄 Обновить", callback_data="task:list"))
        return text, b

    # Лимит ещё есть, но активных невыполненных заданий нет.
    if not tasks:
        text = (
            "📋 <b>ЗАДАНИЯ ГИЛЬДИИ</b>\n\n"
            "Сейчас новых заданий для тебя нет — ты выполнил всё доступное. "
            "Система регулярно присылает новые подземелья, загляни позже.\n\n"
            f"📅 Сегодня можно ещё: <b>{remaining}</b> из <b>{limit}</b>\n"
            f"🔹 Твой баланс: <b>{format_mana(balance)}</b>\n"
            f"{perk_line}"
        )
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="🔄 Обновить", callback_data="task:list"))
        return text, b

    text = (
        "📋 <b>ЗАДАНИЯ ГИЛЬДИИ</b>\n"
        "<i>Твой личный подбор на сегодня — без повторов. Выполняй и добывай руду.</i>\n\n"
        f"{limit_line}"
        f"🔹 Твой баланс: <b>{format_mana(balance)}</b>\n"
        f"{mult_line}"
        f"{perk_line}\n"
        "1. Подпишись на канал по кнопке.\n"
        "2. Нажми «Проверить» — Система начислит руду (с учётом множителей).\n"
        "3. <b>Не отписывайся</b> от каналов — иначе руда отзывается, стрик сбрасывается.\n"
        "   При отписке придёт сообщение с кнопками «вернуться на канал».\n\n"
        "Обменять руду на подарок: /redeem · Привилегии: /privileges"
    )
    return text, _tasks_keyboard(tasks)


@router.message(Command("tasks", "task"))
async def cmd_tasks(message: Message) -> None:
    if not message.from_user:
        return
    text, kb = await _render_tasks(message.from_user.id)
    await answer_with_banner(
        message, "tasks", text,
        reply_markup=kb.as_markup(),
        disable_web_page_preview=True,
    )


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
    elif code == "locked":
        # Мягкая блокировка: вернись на канал прошлого спонсора (без штрафов).
        missing = await find_unsubscribed_channels(bot, call.from_user.id, exclude_task_id=task_id)
        await call.answer(
            "⏳ Сначала вернись на канал прошлого задания — кнопки ниже.",
            show_alert=True,
        )
        if missing:
            try:
                await call.message.answer(
                    "📌 <b>Вернись на канал, чтобы продолжить</b>\n\n"
                    "Чтобы получать новые задания, нужно оставаться подписанным на "
                    "каналы прошлых спонсоров. Подпишись обратно по кнопкам ниже — "
                    "и снова жми «Проверить». Никаких штрафов: твою руду и опыт мы не трогаем.",
                    parse_mode="HTML",
                    reply_markup=resubscribe_keyboard(missing),
                )
            except Exception:
                pass
    elif code == "daily_limit":
        await call.answer(
            "📅 На сегодня лимит заданий исчерпан. Новые откроются завтра. "
            "Ранг S/SS/SSS даёт больше руды за каждое задание: /privileges",
            show_alert=True,
        )
        text, kb = await _render_tasks(call.from_user.id)
        try:
            await call.message.edit_text(text, parse_mode="HTML",
                                         reply_markup=kb.as_markup(),
                                         disable_web_page_preview=True)
        except Exception:
            pass
    elif code == "not_subscribed":
        await call.answer(
            "❌ Подписка не найдена. Подпишись на канал задания и нажми «Проверить» снова.",
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
    balance = await balance_of(message.from_user.id)
    await message.answer(
        _redeem_intro(balance),
        parse_mode="HTML",
        reply_markup=_redeem_keyboard(balance).as_markup(),
    )


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
    if part == "close":
        await call.answer()
        return

    catalog = get_catalog()
    offer = next((g for g in catalog if g.key == part), None)
    if not offer:
        await call.answer("Подарок не найден.", show_alert=True)
        return

    product = f"gift:{offer.key}"
    ok, req_id, err = await request_payout(call.from_user.id, offer.mana_price, product)
    if not ok:
        await call.answer(f"❌ {err}", show_alert=True)
        return

    await call.answer("✅ Заявка создана!", show_alert=True)

    # Авто-отправка подарка (если на балансе бота есть ⭐).
    sent = False
    send_err = ""
    if req_id:
        gift_ok, gift_msg = await send_telegram_gift(bot, call.from_user.id, offer)
        if gift_ok:
            await set_payout_status(req_id, "approved", note="auto_send_gift")
            sent = True
        else:
            send_err = gift_msg

    if sent:
        body = (
            "🎉 <b>ПОДАРОК ОТПРАВЛЕН!</b>\n\n"
            f"{offer.emoji} <b>{offer.title}</b> ({offer.subtitle})\n"
            f"Списано: <b>{format_mana(offer.mana_price)}</b>\n\n"
            "<i>Проверь профиль Telegram — подарок уже там.</i>"
        )
    else:
        body = (
            "✅ <b>ЗАЯВКА НА ОБМЕН СОЗДАНА</b>\n\n"
            f"{offer.emoji} <b>{offer.title}</b>\n"
            f"Списано: <b>{format_mana(offer.mana_price)}</b>\n"
            f"Заявка №{req_id} — Монарх отправит подарок вручную.\n"
        )
        if send_err:
            body += f"\n<i>(Авто-отправка: {send_err})</i>"

    try:
        await call.message.edit_text(body, parse_mode="HTML")
    except Exception:
        pass

    cfg = get_config()
    if cfg.owner_id and req_id and not sent:
        try:
            rub = mana_to_rub(offer.mana_price)
            await bot.send_message(
                cfg.owner_id,
                "🎁 <b>НОВАЯ ЗАЯВКА НА ПОДАРОК</b>\n\n"
                f"№{req_id}\n"
                f"Пользователь: <code>{call.from_user.id}</code> "
                f"({mention_html_raw(call.from_user.id, call.from_user.full_name)})\n"
                f"Подарок: <b>{offer.title}</b> ({offer.stars} ⭐)\n"
                f"Списано: <b>{format_mana(offer.mana_price)}</b> (~{rub:.0f} ₽)\n\n"
                f"Подтвердить: /approve {req_id}\n"
                f"Отклонить: /reject {req_id}",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"[TASKS] owner notify failed: {e}")


# ── /achievements ────────────────────────────────────────────────────────────

ACHIEVEMENT_NAMES = {
    "rank_a_top100": "👑 Первая сотня ранга A",
    "dungeon_streak_30": "🏆 Покоритель Подземелий (30 дней подряд)",
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


# ── /privileges — привилегии высоких рангов ──────────────────────────────────

@router.message(Command("privileges", "perks", "privilege"))
async def cmd_privileges(message: Message) -> None:
    if not message.from_user:
        return
    cfg = get_config()
    my_rank = calculate_rank(await get_xp(message.from_user.id))

    lines = [
        "👑 <b>ПРИВИЛЕГИИ ОХОТНИКОВ</b>",
        "<i>Чем выше ранг — тем больше зарабатываешь и меньше платишь Системе.</i>\n",
        f"📅 Дневной лимит заданий — <b>{cfg.tasks_daily_limit}/день</b> для всех рангов.\n",
    ]
    # Таблица привилегий по рангам.
    for rank in ("S", "SS", "SSS"):
        p = rank_perks(rank)
        mark = " ← ты здесь" if rank == my_rank else ""
        lines.append(
            f"{get_rank_label(rank)}{mark}\n"
            f"   ⛏ +{p['task_reward_pct']}% к награде за каждое задание\n"
            f"   💸 −{p['transfer_fee_off']}% к комиссии перевода руды"
        )

    my_perks = perks_lines(my_rank)
    if my_perks:
        lines.append(
            f"\n✅ <b>Твои привилегии ({get_rank_label(my_rank)}):</b>\n"
            + "\n".join(f"   {x}" for x in my_perks)
        )
    else:
        lines.append(
            f"\n🔓 У тебя ранг <b>{get_rank_label(my_rank)}</b> — привилегии открываются "
            f"с ранга <b>S</b>. Базовый дневной лимит: <b>{cfg.tasks_daily_limit}</b> задания.\n"
            "Качай ранг заданиями (/tasks) и подземельем (/dungeon)!"
        )

    await message.answer("\n".join(lines), parse_mode="HTML")


# ── Owner: мастер добавления задания ─────────────────────────────────────────

class NewTask(StatesGroup):
    channel = State()
    reward = State()
    revenue = State()
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
        "Шаг 1/4. Пришли канал одним из способов:\n"
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
    StateFilter(NewTask.channel, NewTask.reward, NewTask.revenue, NewTask.link),
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
        f"Шаг 2/4. Сколько <b>руды</b> платим охотнику за подписку?\n"
        f"Пришли число или /skip — по умолчанию <b>{cfg.task_reward_subscribe}</b> "
        f"(≈ 1 ₽ при курсе {cfg.mana_per_rub} руды/₽).",
        parse_mode="HTML",
    )


@router.message(Command("skip"), NewTask.reward, F.chat.type == "private")
async def newtask_skip_reward(message: Message, state: FSMContext) -> None:
    if not is_owner(message.from_user.id):
        return
    await state.update_data(reward=get_config().task_reward_subscribe)
    await _ask_revenue(message, state)


@router.message(NewTask.reward, F.chat.type == "private")
async def newtask_reward(message: Message, state: FSMContext) -> None:
    if not is_owner(message.from_user.id):
        return
    txt = (message.text or "").strip()
    if not txt.isdigit() or int(txt) <= 0:
        await message.answer("⚠️ Пришли положительное число или /skip.")
        return
    await state.update_data(reward=int(txt))
    await _ask_revenue(message, state)


async def _ask_revenue(message: Message, state: FSMContext) -> None:
    cfg = get_config()
    await state.set_state(NewTask.revenue)
    await message.answer(
        f"Шаг 3/4. Сколько <b>₽</b> платит рекламодатель за подписчика?\n"
        f"Пришли число или /skip — по умолчанию <b>{cfg.task_revenue_rub_default}</b> ₽ "
        f"(охотник получает ~половину в руде).",
        parse_mode="HTML",
    )


@router.message(Command("skip"), NewTask.revenue, F.chat.type == "private")
async def newtask_skip_revenue(message: Message, state: FSMContext) -> None:
    if not is_owner(message.from_user.id):
        return
    await state.update_data(revenue_rub=get_config().task_revenue_rub_default)
    await _ask_link(message, state)


@router.message(NewTask.revenue, F.chat.type == "private")
async def newtask_revenue(message: Message, state: FSMContext) -> None:
    if not is_owner(message.from_user.id):
        return
    txt = (message.text or "").strip()
    if not txt.isdigit() or int(txt) <= 0:
        await message.answer("⚠️ Пришли положительное число (₽) или /skip.")
        return
    await state.update_data(revenue_rub=int(txt))
    await _ask_link(message, state)


async def _ask_link(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(NewTask.link)
    hint = ""
    if data.get("channel_username"):
        hint = f"\nИли /skip — возьму <code>https://t.me/{data['channel_username']}</code>."
    await message.answer(
        "Шаг 4/4. Пришли <b>ссылку для подписки</b> (для приватных каналов — "
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
    revenue_rub = int(data.get("revenue_rub", get_config().task_revenue_rub_default))
    revenue_kopecks = revenue_rub * 100

    task_id = await create_task(
        type="channel_sub",
        title=data.get("title", "Канал"),
        channel_id=data["channel_id"],
        channel_username=data.get("channel_username", ""),
        url=url,
        reward=reward,
        revenue_cents=revenue_kopecks,
        daily=0,
        created_by=message.from_user.id,
    )
    margin_rub = max(0, revenue_rub - reward / get_config().mana_per_rub)
    await message.answer(
        f"✅ <b>Задание #{task_id} создано</b>\n\n"
        f"Канал: <b>{data.get('title')}</b>\n"
        f"Награда охотнику: <b>{format_mana(reward)}</b> (~{reward / get_config().mana_per_rub:.1f} ₽)\n"
        f"Доход с рекламодателя: <b>{revenue_rub} ₽</b> · маржа ~<b>{margin_rub:.1f} ₽</b>\n\n"
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

    offer = offer_from_product(req["product"])
    if offer:
        ok, msg = await send_telegram_gift(bot, req["user_id"], offer)
        if not ok:
            await message.answer(
                f"❌ Авто-отправка не удалась: {msg}\n"
                f"Отправь подарок вручную пользователю <code>{req['user_id']}</code>, "
                f"затем повтори /approve {req['id']}.",
                parse_mode="HTML",
            )
            return

    await set_payout_status(req["id"], "approved", note="owner_approve")
    await message.answer(
        f"✅ Заявка #{req['id']} выполнена. "
        f"Подарок «{req['product']}» отправлен пользователю <code>{req['user_id']}</code>."
    )
    try:
        await bot.send_message(
            req["user_id"],
            "🎉 <b>Твоя заявка на обмен выполнена!</b>\n"
            f"Подарок уже в Telegram. Спасибо, охотник!",
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
