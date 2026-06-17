"""
Связь с Cursor (owner-only, в личке бота).

  /cursor        — включить мост и открыть панель (выбор модели, статус)
  /cursoroff     — выключить мост
  /cursormodels  — показать реальные ID доступных моделей

Когда мост включён, ЛЮБОЕ обычное текстовое сообщение владельца (не команда)
уходит задачей агенту Cursor в этот проект. По завершении ответ возвращается
сюда же с подписью «Ответ от Курсора». Агент держит один диалог на сессию —
кнопка «Новый диалог» начинает с чистого листа.
"""
import asyncio

from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter, BaseFilter
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from services.cursor_bridge import bridge, MODEL_CHOICES, MODEL_LABELS
from utils import is_owner, get_config

router = Router()

# Держим ссылки на фоновые задачи, чтобы их не собрал GC.
_tasks: set[asyncio.Task] = set()


# ── Доступ: всё в этом роутере — только владелец и только в личке ──────────────

class OwnerPrivate(BaseFilter):
    async def __call__(self, event) -> bool:
        u = getattr(event, "from_user", None)
        chat = getattr(event, "message", event)
        chat = getattr(chat, "chat", None)
        if not is_owner(u.id if u else None):
            return False
        return chat is not None and chat.type == "private"


router.message.filter(OwnerPrivate())
router.callback_query.filter(OwnerPrivate())


# ── Клавиатура панели ─────────────────────────────────────────────────────────

def _panel_kb() -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    for ch in MODEL_CHOICES:
        mark = "✅ " if bridge.model_choice == ch else ""
        b.button(text=f"{mark}{MODEL_LABELS[ch]}", callback_data=f"cur:model:{ch}")
    b.adjust(1)
    b.row(
        InlineKeyboardButton(text="🆕 Новый диалог", callback_data="cur:new"),
        InlineKeyboardButton(text="⛔️ Выключить", callback_data="cur:off"),
    )
    b.row(InlineKeyboardButton(text="✖ Закрыть", callback_data="cur:close"))
    return b


def _panel_text() -> str:
    return (
        "🛰 <b>СВЯЗЬ С КУРСОРОМ</b>\n\n"
        + bridge.status_text()
        + "\n\n<i>Пиши задачу обычным сообщением — она уйдёт агенту в этот проект. "
        "Ответ вернётся сюда с подписью «Ответ от Курсора».</i>\n"
        "Команды можно слать как обычно (начинаются с «/»), они мост не трогают."
    )


# ── /cursor — включить и открыть панель ────────────────────────────────────────

@router.message(Command("cursor", "курсор"))
async def cmd_cursor(message: Message) -> None:
    cfg = get_config()
    bridge.configure(cfg.cursor_api_key, cfg.cursor_model_sonnet, cfg.cursor_model_opus)

    if not bridge.available():
        await message.answer(
            "🛰 <b>СВЯЗЬ С КУРСОРОМ</b>\n\n" + bridge.status_text(),
            parse_mode="HTML", disable_web_page_preview=True,
        )
        return

    bridge.start_session()
    await message.answer(
        _panel_text(), parse_mode="HTML",
        reply_markup=_panel_kb().as_markup(), disable_web_page_preview=True,
    )


@router.message(Command("cursoroff"))
async def cmd_cursoroff(message: Message) -> None:
    await bridge.stop_session()
    await message.answer("⛔️ Cursor-мост выключен. Сообщения снова обычные.")


@router.message(Command("cursormodels"))
async def cmd_cursormodels(message: Message) -> None:
    cfg = get_config()
    bridge.configure(cfg.cursor_api_key, cfg.cursor_model_sonnet, cfg.cursor_model_opus)
    if not bridge.available():
        await message.answer(bridge.status_text(), parse_mode="HTML", disable_web_page_preview=True)
        return
    status = await message.answer("🤖 Запрашиваю список моделей…")
    text = await bridge.list_models_text()
    try:
        await status.edit_text(text, parse_mode="HTML")
    except Exception:
        await message.answer(text, parse_mode="HTML")


# ── Callbacks панели ───────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("cur:model:"))
async def cb_model(call: CallbackQuery) -> None:
    choice = call.data.split(":")[2]
    await bridge.set_model(choice)
    try:
        await call.message.edit_text(
            _panel_text(), parse_mode="HTML",
            reply_markup=_panel_kb().as_markup(), disable_web_page_preview=True,
        )
    except Exception:
        pass
    await call.answer(f"Модель: {MODEL_LABELS.get(choice, choice)}")


@router.callback_query(F.data == "cur:new")
async def cb_new(call: CallbackQuery) -> None:
    await bridge.new_dialog()
    await call.answer("🆕 Начат новый диалог", show_alert=True)


@router.callback_query(F.data == "cur:off")
async def cb_off(call: CallbackQuery) -> None:
    await bridge.stop_session()
    try:
        await call.message.edit_text("⛔️ Cursor-мост выключен. Сообщения снова обычные.")
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data == "cur:close")
async def cb_close(call: CallbackQuery) -> None:
    try:
        await call.message.delete()
    except Exception:
        pass
    await call.answer()


# ── Пересылка сообщений в агента ────────────────────────────────────────────────

class BridgeInbox(BaseFilter):
    """Срабатывает только когда мост активен и это обычный текст (не команда)."""
    async def __call__(self, message: Message) -> bool:
        if not bridge.active:
            return False
        txt = message.text or message.caption or ""
        return bool(txt) and not txt.lstrip().startswith("/")


async def _send_chunked(message: Message, header: str, body: str) -> None:
    body = body or "(пусто)"
    full = f"{header}\n\n{body}"
    # Telegram лимит ~4096; режем с запасом и шлём простым текстом (без HTML),
    # чтобы код/разметка из ответа не ломали отправку.
    LIMIT = 3900
    for i in range(0, len(full), LIMIT):
        try:
            await message.answer(full[i:i + LIMIT])
        except Exception as e:
            logger.warning(f"[CURSOR] reply send failed: {e}")
            break


async def _process(message: Message, prompt: str) -> None:
    ok, text = await bridge.run_task(prompt)
    header = "🤖 <b>Ответ от Курсора</b>" if ok else "⚠️ <b>Курсор: ошибка</b>"
    # header идёт первым сообщением с HTML, тело — простым текстом.
    try:
        await message.answer(header, parse_mode="HTML")
    except Exception:
        pass
    await _send_chunked(message, "—", text)


@router.message(BridgeInbox(), StateFilter(None), F.chat.type == "private")
async def on_bridge_message(message: Message) -> None:
    prompt = (message.text or message.caption or "").strip()
    if not prompt:
        return
    if bridge.busy:
        await message.answer("⏳ Агент ещё работает над прошлой задачей. Дождись ответа.")
        return
    await message.answer(
        "🛰 Передал Курсору, работаю над задачей… ответ пришлю сюда.\n"
        "<i>Можно подождать — крупные задачи идут дольше.</i>",
        parse_mode="HTML",
    )
    task = asyncio.create_task(_process(message, prompt))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
