"""
Главное кнопочное меню (/menu) — единая точка входа в ЛС бота.

Цель: максимум комфорта. Вместо десятка команд через «/» — один пост с
кнопками и подкнопками. Навигация редактирует одно и то же сообщение
(drill-down), у каждого подэкрана есть «⬅️ В меню» и «✖ Закрыть».
"""
from urllib.parse import quote

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton

from database import get_or_create_user
from services import rank_card, balance_of, vip_status, AGENT_REWARDS
from services.economy import wallet_of
from keyboards import main_menu_keyboard, menu_nav_keyboard, shop_keyboard
from utils import (
    mention_html, format_mana, get_config, ce, perks_lines, escape_html,
    SHOP_MSG, HELP_MSG,
)
from utils.media import edit_screen, answer_with_banner

router = Router()


def _root_text(name: str) -> str:
    return (
        f"{ce('sword')} <b>СИСТЕМА S-РАНГ — ГЛАВНОЕ МЕНЮ</b>\n\n"
        f"Приветствую, <b>{escape_html(name)}</b>. Управляй всем через кнопки — "
        "команды учить не нужно.\n\n"
        f"{ce('person')} Профиль и ранг охотника\n"
        f"{ce('wallet')} Кошелёк Мана-руды\n"
        f"{ce('tasks')} Задания — основной заработок руды\n"
        f"{ce('gift')} Обмен руды на подарки Telegram\n"
        f"{ce('agent')} Доход с приглашённых друзей\n\n"
        "<i>Выбери раздел ниже 👇</i>"
    )


def _bot_ref_link(username: str, user_id: int) -> str:
    return f"https://t.me/{username}?start=ref_{user_id}"


# ── /menu ─────────────────────────────────────────────────────────────────────

@router.message(Command("menu", "меню", "hub"))
async def cmd_menu(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    await get_or_create_user(user.id, message.chat.id, full_name=user.full_name)
    await answer_with_banner(
        message, "start", _root_text(user.first_name or "охотник"),
        reply_markup=main_menu_keyboard(),
    )


@router.callback_query(F.data == "menu:close")
async def cb_menu_close(call: CallbackQuery) -> None:
    try:
        await call.message.delete()
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data == "menu:root")
async def cb_menu_root(call: CallbackQuery) -> None:
    await edit_screen(
        call.message, _root_text(call.from_user.first_name or "охотник"),
        reply_markup=main_menu_keyboard(),
    )
    await call.answer()


# ── Профиль ───────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:profile")
async def cb_menu_profile(call: CallbackQuery) -> None:
    card = await rank_card(call.from_user.id)
    next_line = (
        f"\n{ce('target')} До следующего ранга: <b>{card['xp_to_next']}</b> опыта"
        if card["xp_to_next"] is not None
        else f"\n{ce('crown')} <b>МАКСИМАЛЬНЫЙ РАНГ ДОСТИГНУТ!</b>"
    )
    perks = perks_lines(card["rank"])
    perks_block = (
        f"\n\n{ce('crown')} <b>Привилегии ранга:</b>\n" + "\n".join(f"• {p}" for p in perks)
        if perks else ""
    )
    text = (
        f"{ce('person')} <b>КАРТОЧКА ОХОТНИКА</b>\n\n"
        f"👤 {mention_html(call.from_user)}\n"
        f"{ce('trophy')} Ранг: <b>{card['label']}</b>\n"
        f"🎖 Звание: <i>{card['title']}</i>\n"
        f"{ce('star')} Опыт: <b>{card['xp']}</b>\n\n"
        f"{ce('chart')} Прогресс: {card['progress']}{next_line}{perks_block}\n\n"
        f"<i>Опыт даётся за задания и подземелье.</i>"
    )
    await edit_screen(call.message, text, reply_markup=menu_nav_keyboard())
    await call.answer()


# ── Кошелёк ───────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:wallet")
async def cb_menu_wallet(call: CallbackQuery) -> None:
    w = await wallet_of(call.from_user.id)
    text = (
        f"{ce('wallet')} <b>ХРАНИЛИЩЕ МАНА-РУДЫ</b>\n\n"
        f"👤 {mention_html(call.from_user)}\n"
        f"{ce('gem')} Баланс: <b>{format_mana(w.get('mana', 0))}</b>\n"
        f"⛏ Всего добыто: <b>{format_mana(w.get('total_earned', 0))}</b>\n"
        f"🔥 Потрачено: <b>{format_mana(w.get('total_spent', 0))}</b>\n\n"
        "<i>Больше всего руды дают задания. Трать в магазине или меняй на подарки.</i>"
    )
    extra = [
        InlineKeyboardButton(text="📋 Задания", callback_data="menu:tasks"),
        InlineKeyboardButton(text="🛒 Магазин", callback_data="menu:shop"),
    ]
    await edit_screen(call.message, text, reply_markup=menu_nav_keyboard(extra))
    await call.answer()


# ── Привилегии ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:perks")
async def cb_menu_perks(call: CallbackQuery) -> None:
    cfg = get_config()
    lines = [
        f"{ce('crown')} <b>ПРИВИЛЕГИИ ВЫСОКИХ РАНГОВ</b>\n",
        "Достигай ранга S и выше — Система даёт бонусы:\n",
        f"{ce('trophy')} <b>S</b> — +10% к награде за задание, −2% комиссии перевода",
        f"{ce('trophy')} <b>SS</b> — +20% к награде, −3% комиссии",
        f"{ce('crown')} <b>SSS</b> — +35% к награде, −5% комиссии\n",
        f"{ce('warn')} Дневной лимит заданий одинаков для всех — "
        f"<b>{cfg.tasks_daily_limit}/день</b>. Ранг повышает НАГРАДУ, а не лимит.",
    ]
    await edit_screen(call.message, "\n".join(lines), reply_markup=menu_nav_keyboard())
    await call.answer()


# ── Помощь ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:help")
async def cb_menu_help(call: CallbackQuery) -> None:
    await edit_screen(call.message, HELP_MSG, reply_markup=menu_nav_keyboard())
    await call.answer()


# ── Магазин (из меню) ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:shop")
async def cb_menu_shop(call: CallbackQuery) -> None:
    bal = await balance_of(call.from_user.id)
    _, _, is_vip = await vip_status(call.from_user.id)
    await edit_screen(
        call.message, SHOP_MSG.format(balance=format_mana(bal)),
        reply_markup=shop_keyboard(is_vip, from_menu=True),
    )
    await call.answer()


# ── Обмен на подарки (из меню) ────────────────────────────────────────────────

@router.callback_query(F.data == "menu:gifts")
async def cb_menu_gifts(call: CallbackQuery) -> None:
    from utils.redeem_ui import redeem_intro, redeem_keyboard
    bal = await balance_of(call.from_user.id)
    kb = redeem_keyboard(bal)
    kb.row(
        InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:root"),
        InlineKeyboardButton(text="✖ Закрыть", callback_data="menu:close"),
    )
    await edit_screen(call.message, redeem_intro(bal), reply_markup=kb.as_markup())
    await call.answer()


# ── Задания (из меню) ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:tasks")
async def cb_menu_tasks(call: CallbackQuery) -> None:
    from handlers.tasks import _render_tasks
    text, kb = await _render_tasks(call.from_user.id)
    kb.row(
        InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:root"),
        InlineKeyboardButton(text="✖ Закрыть", callback_data="menu:close"),
    )
    await edit_screen(call.message, text, reply_markup=kb.as_markup())
    await call.answer()


# ── Доход / рефералка (из меню) ───────────────────────────────────────────────

@router.callback_query(F.data == "menu:ref")
async def cb_menu_ref(call: CallbackQuery) -> None:
    cfg = get_config()
    link = _bot_ref_link(cfg.bot_username, call.from_user.id)
    count, threshold, is_vip = await vip_status(call.from_user.id)
    d = AGENT_REWARDS.get("D", cfg.mana_referral_rankup)
    text = (
        f"{ce('agent')} <b>ТВОЙ ДОХОД С ДРУЗЕЙ</b>\n\n"
        "Приглашай охотников по своей ссылке — Система закрепляет их за тобой "
        "<b>навсегда</b> и платит рудой за <b>каждое</b> повышение их ранга:\n"
        f"• D +{d} · C +100 · B +200 · A +400 · S +800 руды\n"
        "Один охотник, раскачанный до S = <b>1550 руды</b>.\n\n"
        f"{ce('link')} Твоя ссылка:\n<code>{escape_html(link)}</code>\n\n"
        f"{ce('people')} Приглашено: <b>{count}</b>"
        + (f" · до VIP осталось <b>{max(0, threshold - count)}</b>" if not is_vip else
           f" · {ce('crown')} <b>VIP открыт</b>")
    )
    share_text = (
        "⚔️ Заходи в Систему S-Ранг — фарми Мана-руду, расти в рангах и меняй "
        "руду на подарки Telegram!"
    )
    share_url = (
        f"https://t.me/share/url?url={quote(link, safe='')}"
        f"&text={quote(share_text, safe='')}"
    )
    extra = [InlineKeyboardButton(text="📣 Позвать друзей", url=share_url)]
    await edit_screen(call.message, text, reply_markup=menu_nav_keyboard(extra))
    await call.answer()
