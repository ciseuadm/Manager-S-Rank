"""
Economy commands: /wallet (/balance), /transfer, /manatop.
The /shop lives here too but exchange-to-gifts is gated as "coming soon".
"""
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from aiogram.types import InlineKeyboardButton

from database import get_top_mana, get_or_create_user
from services.economy import wallet_of, transfer_mana, balance_of
from services import vip_rank_status
from keyboards import shop_keyboard, shop_back_keyboard
from utils import (
    mention_html, mention_html_raw, escape_html, format_mana, get_config, ce,
    get_rank_label,
    WALLET_MSG, TRANSFER_OK_MSG, TRANSFER_HELP, MANA_TOP_MSG,
    SHOP_MSG, COMING_SOON_MSG, VIP_PROGRESS_MSG, VIP_OPEN_MSG,
)
from utils.media import answer_with_banner, edit_screen

router = Router()


# ── /wallet ──────────────────────────────────────────────────────────────────

@router.message(Command("wallet", "balance", "mana"))
async def cmd_wallet(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    if message.reply_to_message and message.reply_to_message.from_user:
        user = message.reply_to_message.from_user

    w = await wallet_of(user.id)
    await message.answer(
        WALLET_MSG.format(
            mention=mention_html(user),
            balance=format_mana(w.get("mana", 0)),
            earned=format_mana(w.get("total_earned", 0)),
            spent=format_mana(w.get("total_spent", 0)),
        ),
        parse_mode="HTML",
    )


# ── /transfer ────────────────────────────────────────────────────────────────

@router.message(Command("transfer", "pay"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_transfer(message: Message) -> None:
    cfg = get_config()
    sender = message.from_user
    if not sender:
        return

    reply = message.reply_to_message
    if not reply or not reply.from_user:
        await message.reply(
            TRANSFER_HELP.format(fee_pct=cfg.mana_transfer_fee_pct), parse_mode="HTML"
        )
        return

    receiver = reply.from_user
    if receiver.is_bot:
        await message.reply("🤖 Боту руда без надобности.")
        return

    args = (message.text or "").split()
    amount = 0
    for a in args[1:]:
        if a.lstrip("-").isdigit():
            amount = int(a)
            break
    if amount <= 0:
        await message.reply(
            TRANSFER_HELP.format(fee_pct=cfg.mana_transfer_fee_pct), parse_mode="HTML"
        )
        return

    await get_or_create_user(receiver.id, message.chat.id, full_name=receiver.full_name)
    ok, fee, err = await transfer_mana(sender.id, receiver.id, amount, message.chat.id)
    if not ok:
        await message.reply(f"❌ {err}")
        return

    await message.answer(
        TRANSFER_OK_MSG.format(
            sender=mention_html(sender),
            receiver=mention_html(receiver),
            amount=format_mana(amount),
            fee=format_mana(fee),
            balance=format_mana(await balance_of(sender.id)),
        ),
        parse_mode="HTML",
    )


# ── /manatop ─────────────────────────────────────────────────────────────────

# ── /shop — рынок гильдии ────────────────────────────────────────────────────

@router.message(Command("shop", "market"))
async def cmd_shop(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    balance = await balance_of(user.id)
    _, is_vip = await vip_rank_status(user.id)
    await answer_with_banner(
        message,
        "shop",
        SHOP_MSG.format(balance=format_mana(balance)),
        reply_markup=shop_keyboard(is_vip),
    )


async def _shop_root_markup(user_id: int, from_menu: bool):
    _, is_vip = await vip_rank_status(user_id)
    return shop_keyboard(is_vip, from_menu=from_menu)


@router.callback_query(F.data.startswith("shop:"))
async def cb_shop(call: CallbackQuery) -> None:
    action = call.data.split(":")[1]
    cfg = get_config()
    msg = call.message
    is_private = bool(msg and msg.chat and msg.chat.type == "private")

    if action == "close":
        try:
            await msg.delete()
        except Exception:
            pass
        await call.answer()
        return

    # Корень магазина (вход и кнопка «В магазин» из подэкранов) — правим на месте.
    if action == "root":
        bal = await balance_of(call.from_user.id)
        await edit_screen(
            msg, SHOP_MSG.format(balance=format_mana(bal)),
            reply_markup=await _shop_root_markup(call.from_user.id, is_private),
        )
        await call.answer()
        return

    if action == "buy":
        if not cfg.payments_enabled:
            await edit_screen(msg, COMING_SOON_MSG, reply_markup=shop_back_keyboard())
            await call.answer()
            return

        if is_private:
            # Мы уже в ЛС — продаём пакеты прямо здесь, без «открой в личке».
            from handlers.payments import MANA_PACKS
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            b = InlineKeyboardBuilder()
            for pid, stars, mana in MANA_PACKS:
                b.row(InlineKeyboardButton(
                    text=f"⭐ {stars} → {mana:,} руды".replace(",", " "),
                    callback_data=f"buy:{pid}",
                ))
            b.row(InlineKeyboardButton(text="⬅️ В магазин", callback_data="shop:root"))
            text = (
                f"{ce('coin')} <b>ПОПОЛНЕНИЕ МАНА-РУДЫ</b>\n\n"
                f"Купи руду за Telegram Stars {ce('star')} — быстро и официально, "
                "прямо здесь.\n"
                "Выбери пакет ниже — Система пришлёт счёт на оплату 👇\n\n"
                f"<i>{ce('spark')} Stars списываются внутри Telegram, без внешних "
                "кошельков.</i>"
            )
            await edit_screen(msg, text, reply_markup=b.as_markup())
            await call.answer()
            return

        # В группе — счёт выставить нельзя, ведём в ЛС бота одной кнопкой.
        bot_uname = cfg.bot_username
        extra = None
        if bot_uname:
            extra = [InlineKeyboardButton(
                text="💳 Открыть бота и купить", url=f"https://t.me/{bot_uname}?start=buy"
            )]
        text = (
            f"{ce('coin')} <b>ПОПОЛНЕНИЕ МАНА-РУДЫ</b>\n\n"
            f"Купи руду за Telegram Stars {ce('star')} — быстро и официально.\n"
            "Покупка идёт в личке бота: нажми кнопку ниже и выбери пакет.\n\n"
            "<i>Stars пополняются прямо в Telegram, без внешних кошельков.</i>"
        )
        await edit_screen(msg, text, reply_markup=shop_back_keyboard(extra))
        await call.answer()
        return

    if action == "gifts":
        from utils.redeem_ui import redeem_intro, redeem_keyboard
        bal = await balance_of(call.from_user.id)
        kb = redeem_keyboard(bal)
        kb.row(
            InlineKeyboardButton(text="⬅️ В магазин", callback_data="shop:root"),
            InlineKeyboardButton(text="✖ Закрыть", callback_data="shop:close"),
        )
        await edit_screen(msg, redeem_intro(bal), reply_markup=kb.as_markup())
        await call.answer()
        return

    if action in ("premium", "ads"):
        await edit_screen(msg, COMING_SOON_MSG, reply_markup=shop_back_keyboard())
        await call.answer()
        return

    if action == "vip":
        rank, is_vip = await vip_rank_status(call.from_user.id)
        if is_vip:
            link = cfg.vip_chat_link or "Система откроет вход в ближайшее время."
            text = VIP_OPEN_MSG.format(link=link)
        else:
            text = VIP_PROGRESS_MSG.format(rank=get_rank_label(rank))
        await edit_screen(msg, text, reply_markup=shop_back_keyboard())
        await call.answer()
        return

    await call.answer()


@router.message(Command("manatop", "richest"))
async def cmd_manatop(message: Message, bot: Bot) -> None:
    top = await get_top_mana(limit=10)
    top = [t for t in top if t.get("mana", 0) > 0]
    if not top:
        await message.answer("🔹 Пока никто не добыл Мана-руду. Будь первым — общайся в чате!")
        return

    MEDALS = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    lines = [MANA_TOP_MSG]
    for i, t in enumerate(top):
        try:
            chat = await bot.get_chat(t["user_id"])
            name = escape_html(chat.full_name or chat.username or str(t["user_id"]))
        except Exception:
            name = str(t["user_id"])
        lines.append(
            f"{MEDALS[i]} {i + 1}. <b>{name}</b> — {format_mana(t['mana'])}"
        )
    await message.answer("\n".join(lines), parse_mode="HTML")
