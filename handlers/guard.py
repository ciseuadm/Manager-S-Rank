"""
Колбэк капчи новичков («я не бот»). Логика — в services/guard.py.
"""
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery

from services import solve_captcha

router = Router()


@router.callback_query(F.data.startswith("captcha:"))
async def cb_captcha(call: CallbackQuery, bot: Bot) -> None:
    parts = call.data.split(":")
    if len(parts) < 3 or not parts[1].lstrip("-").isdigit() or not parts[2].isdigit():
        await call.answer()
        return
    chat_id, user_id = int(parts[1]), int(parts[2])
    if call.from_user.id != user_id:
        await call.answer("Эта проверка не для тебя 🙃", show_alert=True)
        return
    if await solve_captcha(bot, chat_id, user_id):
        await call.answer("✅ Проверка пройдена. Добро пожаловать, охотник!")
    else:
        await call.answer("Проверка уже неактуальна.")
