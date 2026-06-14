"""
Economy commands: /wallet (/balance), /transfer, /manatop.
The /shop lives here too but exchange-to-gifts is gated as "coming soon".
"""
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message

from database import get_top_mana, get_or_create_user
from services.economy import wallet_of, transfer_mana, balance_of
from utils import (
    mention_html, mention_html_raw, format_mana, get_config,
    WALLET_MSG, TRANSFER_OK_MSG, TRANSFER_HELP, MANA_TOP_MSG,
)

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
            name = chat.full_name or chat.username or str(t["user_id"])
        except Exception:
            name = str(t["user_id"])
        lines.append(
            f"{MEDALS[i]} {i + 1}. <b>{name}</b> — {format_mana(t['mana'])}"
        )
    await message.answer("\n".join(lines), parse_mode="HTML")
