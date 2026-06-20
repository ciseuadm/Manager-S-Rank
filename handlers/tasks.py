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
    list_tasks, set_task_active, create_task, set_task_priority,
    task_completions_count, list_payout_requests,
    get_payout_request, set_payout_status, get_user_achievements,
    list_pending_completions, get_completion_by_id, get_task,
)
from services import (
    daily_tasks_view, check_and_credit_subscription, check_and_credit_task,
    watch_claim, credit_pending_completion, reject_pending_completion,
    request_payout, request_crypto_payout,
    refund_payout, mana_to_usd_cents, mana_to_rub, balance_of,
    user_streak, streak_multiplier, find_unsubscribed_channels, resubscribe_keyboard,
)
from services.crypto import crypto_enabled, crypto_auto, mana_to_crypto_amount, transfer as crypto_transfer
from services.gifts import get_catalog, send_telegram_gift, offer_from_product
from utils.redeem_ui import redeem_intro, redeem_keyboard
from utils import (
    is_owner, get_config, format_mana, mention_html_raw, ce, escape_html,
    get_rank_label, has_privileges, rank_perks,
)
from utils.media import answer_with_banner, edit_screen

router = Router()


# ── Клавиатуры ───────────────────────────────────────────────────────────────

def _tasks_nav(b: InlineKeyboardBuilder) -> InlineKeyboardBuilder:
    """Низ экрана заданий: «Обновить» + «Назад» (в главное меню).

    Кнопки общие для всех вариантов экрана и для входа из /tasks и из /menu —
    поэтому при «Обновить» навигация и премиум-эмодзи не теряются.
    """
    b.row(InlineKeyboardButton(text="🔄 Обновить", callback_data="task:list"))
    b.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:root"))
    return b


_TYPE_ICON = {
    "channel_sub": "📣", "chat_join": "👥", "watch": "▶️",
    "quiz": "❓", "bot_start": "🤖", "react": "👍", "boost": "🚀", "external": "🌐",
}


def _tasks_keyboard(tasks: list[dict]) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    for t in tasks:
        icon = _TYPE_ICON.get(t.get("type"), "📌")
        mode = t.get("verify_mode") or "membership"
        url = t.get("url") or (
            f"https://t.me/{t['channel_username']}" if t.get("channel_username") else None
        )
        title = (t.get("title") or "Задание")[:32]
        if url:
            b.row(InlineKeyboardButton(text=f"{icon} {title}", url=url))
        reward = t["reward"]
        if mode == "membership":
            b.row(InlineKeyboardButton(
                text=f"🔍 Проверить и забрать +{reward} руды",
                callback_data=f"task:check:{t['id']}"))
        elif mode == "timer":
            secs = t.get("duration_sec", 30) or 30
            b.row(InlineKeyboardButton(
                text=f"✅ Я посмотрел ({secs}с) → +{reward}",
                callback_data=f"task:watch:{t['id']}"))
        elif mode == "quiz":
            b.row(InlineKeyboardButton(
                text=f"✍️ Ответить → +{reward} руды",
                callback_data=f"task:quizinfo:{t['id']}"))
        else:  # proof
            b.row(InlineKeyboardButton(
                text=f"📤 Отправить пруф → +{reward} руды",
                callback_data=f"task:proofinfo:{t['id']}"))
    return _tasks_nav(b)


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
        f"{ce('fire')} Стрик подписок: <b>{streak}</b> → множитель награды <b>×{mult:.1f}</b>\n"
        if streak > 0 else
        f"{ce('fire')} Каждая сохранённая подписка повышает множитель будущих наград!\n"
    )

    # Привилегия ранга: надбавка к награде за задание (S/SS/SSS).
    perk = rank_perks(rank)
    perk_line = ""
    if has_privileges(rank) and perk["task_reward_pct"]:
        perk_line = (
            f"{ce('premium')} Привилегия {get_rank_label(rank)}: "
            f"<b>+{perk['task_reward_pct']}% к награде</b>\n"
        )

    limit_line = f"{ce('tasks')} Заданий сегодня: <b>{done_today}/{limit}</b>\n"

    ref_line = (
        f"{ce('agent')} Зови охотников по своей ссылке — Система платит рудой за "
        "<b>каждое</b> их повышение ранга. Открой «Доход / друзья» в /menu.\n"
    )

    # Лимит исчерпан — на сегодня всё.
    if remaining <= 0:
        text = (
            f"{ce('tasks')} <b>ЗАДАНИЯ ГИЛЬДИИ</b>\n\n"
            f"{ce('check')} Дневной лимит выполнен: <b>{done_today}/{limit}</b> заданий.\n"
            f"{ce('coin')} Твой баланс: <b>{format_mana(balance)}</b>\n"
            f"{perk_line}"
            f"\n{ce('alarm')} Новые задания откроются завтра. Подними ранг (S/SS/SSS) — "
            "и за каждое задание будешь получать больше руды.\n\n"
            f"{ref_line}"
        )
        return text, _tasks_nav(InlineKeyboardBuilder())

    # Лимит ещё есть, но активных невыполненных заданий нет.
    if not tasks:
        text = (
            f"{ce('tasks')} <b>ЗАДАНИЯ ГИЛЬДИИ</b>\n\n"
            f"{ce('alarm')} Сейчас новых заданий для тебя нет — ты выполнил всё доступное. "
            "Система регулярно присылает новые подземелья, загляни позже.\n\n"
            f"{limit_line}"
            f"{ce('coin')} Твой баланс: <b>{format_mana(balance)}</b>\n"
            f"{perk_line}"
            f"\n{ref_line}"
        )
        return text, _tasks_nav(InlineKeyboardBuilder())

    text = (
        f"{ce('tasks')} <b>ЗАДАНИЯ ГИЛЬДИИ</b>\n"
        f"<i>{ce('spark')} Твой личный подбор на сегодня — без повторов. Выполняй и добывай руду.</i>\n\n"
        f"{limit_line}"
        f"{ce('coin')} Твой баланс: <b>{format_mana(balance)}</b>\n"
        f"{mult_line}"
        f"{perk_line}\n"
        f"{ce('check')} Подпишись на канал по кнопке.\n"
        f"{ce('check')} Нажми «Проверить» — Система начислит руду.\n"
        f"{ce('spark')} Оставайся в каналах заданий — пока ты подписан, Система "
        "открывает новые задания (руду не забираем).\n\n"
        f"{ref_line}"
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
    await edit_screen(call.message, text, reply_markup=kb.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("task:done:"))
async def cb_task_done(call: CallbackQuery) -> None:
    await call.answer("Это задание уже выполнено ✅", show_alert=True)


@router.callback_query(F.data.startswith("task:check:"))
async def cb_task_check(call: CallbackQuery, bot: Bot) -> None:
    task_id = int(call.data.split(":")[2])
    code, reward = await check_and_credit_task(bot, call.from_user.id, task_id)

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
            "Ранг S/SS/SSS даёт больше руды за каждое задание.",
            show_alert=True,
        )
        text, kb = await _render_tasks(call.from_user.id)
        await edit_screen(call.message, text, reply_markup=kb.as_markup())
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
        await edit_screen(call.message, text, reply_markup=kb.as_markup())


# ── Задание-просмотр (timer) ─────────────────────────────────────────────────

@router.callback_query(F.data.startswith("task:watch:"))
async def cb_task_watch(call: CallbackQuery, bot: Bot) -> None:
    task_id = int(call.data.split(":")[2])
    code, val = await watch_claim(bot, call.from_user.id, task_id)
    if code == "watch_started":
        await call.answer(
            f"⏳ Таймер пошёл! Посмотри материал {val} сек и нажми кнопку снова.",
            show_alert=True)
    elif code == "watch_wait":
        await call.answer(f"⏳ Ещё рано. Подожди ~{val} сек и нажми снова.", show_alert=True)
    elif code == "credited":
        await call.answer(f"✅ +{val} руды зачислено!", show_alert=True)
        text, kb = await _render_tasks(call.from_user.id)
        await edit_screen(call.message, text, reply_markup=kb.as_markup())
    elif code == "already":
        await call.answer("Награда за это задание уже получена.", show_alert=True)
    elif code == "daily_limit":
        await call.answer("📅 На сегодня лимит заданий исчерпан. Новые откроются завтра.", show_alert=True)
    elif code == "locked":
        await call.answer("⏳ Сначала вернись на каналы прошлых заданий.", show_alert=True)
    else:
        await call.answer("Задание недоступно.", show_alert=True)


# ── Задание-квиз ──────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("task:quizinfo:"))
async def cb_task_quizinfo(call: CallbackQuery) -> None:
    task_id = int(call.data.split(":")[2])
    await call.answer(
        f"✍️ Чтобы ответить, отправь команду:\n/ans {task_id} твой_ответ",
        show_alert=True)


@router.message(Command("ans", "answer"), F.chat.type == "private")
async def cmd_answer(message: Message, bot: Bot) -> None:
    args = (message.text or "").split(maxsplit=2)
    if len(args) < 3 or not args[1].isdigit():
        await message.answer("✏️ Использование: <code>/ans &lt;id задания&gt; ответ</code>", parse_mode="HTML")
        return
    task_id, answer = int(args[1]), args[2]
    code, reward = await check_and_credit_task(bot, message.from_user.id, task_id, payload=answer)
    if code == "credited":
        await message.answer(f"✅ Верно! +{reward} руды зачислено.")
    elif code == "wrong_answer":
        await message.answer("❌ Неверный ответ. Попробуй ещё раз.")
    elif code == "already":
        await message.answer("Это задание уже выполнено.")
    elif code == "daily_limit":
        await message.answer("📅 На сегодня лимит заданий исчерпан.")
    elif code == "locked":
        await message.answer("⏳ Сначала вернись на каналы прошлых заданий: /tasks")
    else:
        await message.answer("⚠️ Задание недоступно или это не квиз.")


# ── Задание-пруф (ручная модерация) ───────────────────────────────────────────

@router.callback_query(F.data.startswith("task:proofinfo:"))
async def cb_task_proofinfo(call: CallbackQuery) -> None:
    task_id = int(call.data.split(":")[2])
    await call.answer(
        f"📤 Выполни задание и пришли подтверждение:\n"
        f"/proof {task_id} что сделал (можно ответом на скриншот)",
        show_alert=True)


@router.message(Command("proof"), F.chat.type == "private")
async def cmd_proof(message: Message, bot: Bot) -> None:
    args = (message.text or "").split(maxsplit=2)
    if len(args) < 2 or not args[1].isdigit():
        await message.answer(
            "✏️ Использование: <code>/proof &lt;id задания&gt; описание</code>\n"
            "Можно ответить этой командой на свой скриншот.",
            parse_mode="HTML")
        return
    task_id = int(args[1])
    proof_text = args[2] if len(args) >= 3 else ""
    # Скриншот: если команда отправлена ответом на фото — сохраняем file_id.
    if message.reply_to_message and message.reply_to_message.photo:
        proof_text = (proof_text + " [photo:" +
                      message.reply_to_message.photo[-1].file_id + "]").strip()
    elif message.photo:
        proof_text = (proof_text + " [photo:" + message.photo[-1].file_id + "]").strip()
    if not proof_text:
        await message.answer("⚠️ Добавь описание или приложи скриншот.")
        return

    code, _ = await check_and_credit_task(bot, message.from_user.id, task_id, payload=proof_text)
    if code == "proof_submitted":
        await message.answer(
            "📨 Пруф отправлен на проверку. Как только Монарх подтвердит — руда придёт на баланс.")
        cfg = get_config()
        if cfg.owner_id:
            try:
                task = await get_task(task_id)
                await bot.send_message(
                    cfg.owner_id,
                    "📥 <b>НОВЫЙ ПРУФ ПО ЗАДАНИЮ</b>\n\n"
                    f"Задание #{task_id}: «{(task or {}).get('title', '—')}»\n"
                    f"Охотник: {mention_html_raw(message.from_user.id, message.from_user.full_name)} "
                    f"(<code>{message.from_user.id}</code>)\n"
                    f"Пруф: {proof_text[:300]}\n\n"
                    "Очередь: /taskproofs",
                    parse_mode="HTML")
            except Exception:
                pass
    elif code == "proof_pending":
        await message.answer("⏳ Твой пруф по этому заданию уже на проверке.")
    elif code == "already":
        await message.answer("Это задание уже выполнено.")
    elif code == "locked":
        await message.answer("⏳ Сначала вернись на каналы прошлых заданий: /tasks")
    else:
        await message.answer("⚠️ Задание недоступно или не требует пруфа.")


# ── /redeem ──────────────────────────────────────────────────────────────────

@router.message(Command("redeem", "withdraw", "exchange"))
async def cmd_redeem(message: Message) -> None:
    if not message.from_user:
        return
    balance = await balance_of(message.from_user.id)
    kb = _redeem_keyboard(balance)
    kb.row(InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:root"))
    await message.answer(
        _redeem_intro(balance),
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )


@router.message(Command("payoutcrypto", "cashout", "crypto"), F.chat.type == "private")
async def cmd_payout_crypto(message: Message, bot: Bot) -> None:
    if not message.from_user:
        return
    cfg = get_config()
    if not crypto_enabled():
        await message.answer(
            "🪙 <b>Крипто-вывод</b>\n\n"
            "Сейчас вывод в крипте отключён. Доступен обмен руды на подарки: /redeem.",
            parse_mode="HTML",
        )
        return

    args = (message.text or "").split()
    amount = next((int(a) for a in args[1:] if a.isdigit()), 0)
    if amount <= 0:
        bal = await balance_of(message.from_user.id)
        await message.answer(
            "🪙 <b>ВЫВОД В КРИПТЕ</b>\n\n"
            f"Актив: <b>{cfg.crypto_asset}</b> (через @CryptoBot).\n"
            f"Курс: {cfg.mana_per_rub} руды = 1 ₽.\n"
            f"Минимум: <b>{format_mana(cfg.crypto_min_mana)}</b>, "
            f"суточный лимит: <b>{format_mana(cfg.crypto_daily_limit_mana)}</b>.\n"
            f"Твой баланс: <b>{format_mana(bal)}</b>\n\n"
            "Использование: <code>/payoutcrypto 5000</code>\n"
            "<i>Деньги придут на твой аккаунт в @CryptoBot — им нужно хоть раз "
            "воспользоваться. Заявку подтверждает Монарх.</i>",
            parse_mode="HTML",
        )
        return

    ok, req_id, err = await request_crypto_payout(message.from_user.id, amount)
    if not ok:
        await message.answer(f"❌ {err}")
        return

    crypto_amt = mana_to_crypto_amount(amount)
    await message.answer(
        "✅ <b>ЗАЯВКА НА КРИПТО-ВЫВОД СОЗДАНА</b>\n\n"
        f"№{req_id}\n"
        f"Списано: <b>{format_mana(amount)}</b> ≈ <b>{crypto_amt:.2f} {cfg.crypto_asset}</b>\n"
        "Монарх подтвердит заявку — деньги придут в @CryptoBot.",
        parse_mode="HTML",
    )
    if cfg.owner_id and req_id:
        try:
            await bot.send_message(
                cfg.owner_id,
                "🪙 <b>НОВАЯ ЗАЯВКА НА КРИПТО-ВЫВОД</b>\n\n"
                f"№{req_id}\n"
                f"Пользователь: <code>{message.from_user.id}</code> "
                f"({mention_html_raw(message.from_user.id, message.from_user.full_name)})\n"
                f"Сумма: <b>{format_mana(amount)}</b> ≈ <b>{crypto_amt:.2f} {cfg.crypto_asset}</b>\n\n"
                f"Подтвердить: /approve {req_id}\n"
                f"Отклонить: /reject {req_id}",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"[TASKS] owner crypto notify failed: {e}")


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
        chat_type=getattr(chat.type, "value", chat.type),
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

    # Группа/супергруппа → задание-вступление (chat_join), канал → подписка.
    is_group = data.get("chat_type") in ("group", "supergroup")
    task_type = "chat_join" if is_group else "channel_sub"

    task_id = await create_task(
        type=task_type,
        verify_mode="membership",
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


@router.message(Command("boosttask"), F.chat.type == "private")
async def cmd_boosttask(message: Message) -> None:
    """Платный приоритет задания в выдаче /tasks.

    Спонсор доплачивает за топ-позицию — владелец вручную поднимает приоритет.
    Без аргумента уровня берётся config.task_boost_priority; 0 — снять буст.
    """
    if not is_owner(message.from_user.id):
        return
    args = (message.text or "").split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer(
            "🚀 <b>Буст задания</b>\n\n"
            "Использование: <code>/boosttask &lt;id&gt; [уровень]</code>\n"
            "Без уровня — стандартный приоритет, <code>0</code> — снять буст.\n"
            "Чем выше приоритет, тем раньше задание в /tasks.",
            parse_mode="HTML",
        )
        return
    task_id = int(args[1])
    task = await get_task(task_id)
    if not task:
        await message.answer("Задание не найдено.")
        return
    level = int(args[2]) if len(args) > 2 and args[2].isdigit() else get_config().task_boost_priority
    await set_task_priority(task_id, level)
    if level > 0:
        await message.answer(
            f"🚀 Задание #{task_id} поднято в выдаче (приоритет {level})."
        )
    else:
        await message.answer(f"⬇️ Буст с задания #{task_id} снят.")


# ── Owner: быстрые создатели заданий новых типов ─────────────────────────────
# Все задания создаёт только владелец — фрод-задания исключены на входе.

@router.message(Command("addwatch"), F.chat.type == "private")
async def cmd_addwatch(message: Message) -> None:
    if not is_owner(message.from_user.id):
        return
    body = (message.text or "").split(maxsplit=1)
    parts = [p.strip() for p in (body[1] if len(body) > 1 else "").split("|")]
    if len(parts) < 4 or not parts[0].startswith("http") or not parts[1].isdigit() or not parts[2].isdigit():
        await message.answer(
            "✏️ Формат: <code>/addwatch ссылка | награда | секунды | заголовок</code>\n"
            "Пример: <code>/addwatch https://youtu.be/x | 30 | 20 | Видео спонсора</code>",
            parse_mode="HTML")
        return
    url, reward, secs, title = parts[0], int(parts[1]), int(parts[2]), parts[3]
    task_id = await create_task(
        type="watch", verify_mode="timer", title=title, channel_id=0,
        channel_username="", url=url, reward=reward, revenue_cents=0, daily=0,
        created_by=message.from_user.id, duration_sec=secs)
    await message.answer(
        f"✅ <b>Задание-просмотр #{task_id}</b>\nНаграда: {reward} руды · смотреть {secs}с\n"
        f"Появилось в /tasks.", parse_mode="HTML")


@router.message(Command("addquiz"), F.chat.type == "private")
async def cmd_addquiz(message: Message) -> None:
    if not is_owner(message.from_user.id):
        return
    body = (message.text or "").split(maxsplit=1)
    parts = [p.strip() for p in (body[1] if len(body) > 1 else "").split("|")]
    if len(parts) < 3 or not parts[0].isdigit():
        await message.answer(
            "✏️ Формат: <code>/addquiz награда | ответ | вопрос</code>\n"
            "Пример: <code>/addquiz 20 | 1998 | В каком году вышло аниме?</code>",
            parse_mode="HTML")
        return
    reward, answer, question = int(parts[0]), parts[1], parts[2]
    task_id = await create_task(
        type="quiz", verify_mode="quiz", title=question, channel_id=0,
        channel_username="", url="", reward=reward, revenue_cents=0, daily=0,
        created_by=message.from_user.id, answer=answer)
    await message.answer(
        f"✅ <b>Квиз #{task_id}</b>\nНаграда: {reward} руды · ответ: <code>{escape_html(answer)}</code>\n"
        f"Игроки отвечают через /ans.", parse_mode="HTML")


@router.message(Command("addproof"), F.chat.type == "private")
async def cmd_addproof(message: Message) -> None:
    if not is_owner(message.from_user.id):
        return
    body = (message.text or "").split(maxsplit=1)
    parts = [p.strip() for p in (body[1] if len(body) > 1 else "").split("|")]
    if len(parts) < 2 or not parts[0].isdigit():
        await message.answer(
            "✏️ Формат: <code>/addproof награда | инструкция | [ссылка] | [тип]</code>\n"
            "Тип: bot_start | react | boost | external (по умолчанию external).\n"
            "Пример: <code>/addproof 25 | Запусти бота и пришли скрин | https://t.me/x?start=1 | bot_start</code>",
            parse_mode="HTML")
        return
    reward = int(parts[0])
    title = parts[1]
    url = parts[2] if len(parts) >= 3 and parts[2].startswith("http") else ""
    ttype = parts[3] if len(parts) >= 4 and parts[3] in ("bot_start", "react", "boost", "external") else "external"
    task_id = await create_task(
        type=ttype, verify_mode="proof", title=title, channel_id=0,
        channel_username="", url=url, reward=reward, revenue_cents=0, daily=0,
        created_by=message.from_user.id)
    await message.answer(
        f"✅ <b>Задание-пруф #{task_id}</b> ({ttype})\nНаграда: {reward} руды\n"
        f"Пруфы прилетят в /taskproofs на ручное подтверждение.", parse_mode="HTML")


# ── Owner: очередь пруфов (ручное подтверждение) ─────────────────────────────

@router.message(Command("taskproofs", "proofs"), F.chat.type == "private")
async def cmd_taskproofs(message: Message) -> None:
    if not is_owner(message.from_user.id):
        return
    rows = await list_pending_completions(limit=30)
    if not rows:
        await message.answer("📭 Очередь пруфов пуста. ✅")
        return
    lines = ["📥 <b>ПРУФЫ НА ПРОВЕРКЕ</b>\n"]
    for r in rows:
        lines.append(
            f"<code>#{r['comp_id']}</code> · задание «{(r['title'] or '—')[:20]}» · "
            f"user <code>{r['user_id']}</code>\n   пруф: {escape_html((r['proof'] or '—')[:120])}")
    lines.append("\n✅ /creditproof &lt;id&gt;   ❌ /rejectproof &lt;id&gt;")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("creditproof"), F.chat.type == "private")
async def cmd_creditproof(message: Message, bot: Bot) -> None:
    if not is_owner(message.from_user.id):
        return
    args = (message.text or "").split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: <code>/creditproof 5</code>", parse_mode="HTML")
        return
    code, uid, reward = await credit_pending_completion(bot, int(args[1]))
    if code != "credited":
        await message.answer("Пруф не найден или уже обработан.")
        return
    await message.answer(f"✅ Пруф #{args[1]} подтверждён. Начислено {reward} руды пользователю {uid}.")
    try:
        await bot.send_message(uid, f"✅ Твой пруф подтверждён! +{reward} руды на баланс. Так держать, охотник!")
    except Exception:
        pass


@router.message(Command("rejectproof"), F.chat.type == "private")
async def cmd_rejectproof(message: Message, bot: Bot) -> None:
    if not is_owner(message.from_user.id):
        return
    args = (message.text or "").split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: <code>/rejectproof 5</code>", parse_mode="HTML")
        return
    code, uid = await reject_pending_completion(int(args[1]))
    if code != "rejected":
        await message.answer("Пруф не найден или уже обработан.")
        return
    await message.answer(f"❌ Пруф #{args[1]} отклонён.")
    try:
        await bot.send_message(uid, "ℹ️ Твой пруф по заданию отклонён. Перепроверь условия и попробуй снова.")
    except Exception:
        pass


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

    # ── Крипто-вывод: авто-перевод через Crypto Pay (или ручной режим) ──
    if str(req["product"]).startswith("crypto:"):
        cfg = get_config()
        crypto_amt = mana_to_crypto_amount(req["amount"])
        if crypto_auto():
            ok, info = await crypto_transfer(
                req["user_id"], crypto_amt,
                spend_id=f"payout_{req['id']}",
                comment=f"S-Rank payout #{req['id']}",
            )
            if not ok:
                await message.answer(
                    f"❌ Авто-перевод не прошёл: <code>{escape_html(info)}</code>\n"
                    f"Проверь токен/баланс Crypto Pay. Заявка #{req['id']} осталась в очереди.",
                    parse_mode="HTML",
                )
                return
            await set_payout_status(req["id"], "fulfilled", note=f"crypto:{info}")
            await message.answer(
                f"✅ Заявка #{req['id']}: переведено "
                f"<b>{crypto_amt:.2f} {cfg.crypto_asset}</b> пользователю "
                f"<code>{req['user_id']}</code> (transfer {escape_html(info)}).",
                parse_mode="HTML",
            )
            try:
                await bot.send_message(
                    req["user_id"],
                    f"🪙 <b>Крипто-вывод выполнен!</b>\n"
                    f"На твой @CryptoBot пришло <b>{crypto_amt:.2f} {cfg.crypto_asset}</b>. "
                    "Спасибо, охотник!",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        else:
            # Токена нет — ручной режим: владелец переводит сам, затем /approve.
            await set_payout_status(req["id"], "approved", note="crypto_manual")
            await message.answer(
                f"✅ Заявка #{req['id']} помечена выполненной (ручной режим).\n"
                f"Переведи <b>{crypto_amt:.2f} {cfg.crypto_asset}</b> пользователю "
                f"<code>{req['user_id']}</code> вручную. "
                "<i>Чтобы переводить автоматически — впиши CRYPTO_BOT_TOKEN.</i>",
                parse_mode="HTML",
            )
            try:
                await bot.send_message(
                    req["user_id"],
                    "🪙 <b>Крипто-вывод одобрен!</b>\n"
                    "Монарх отправит средства в ближайшее время.",
                    parse_mode="HTML",
                )
            except Exception:
                pass
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
