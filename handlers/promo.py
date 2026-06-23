"""
Интерактивные посты-«хабы»: один раздел показан в посте, остальные — по кнопкам.
Тап по кнопке раздела переключает содержимое сообщения (как меню), кнопка
«⬅️ Назад» возвращает к корню. Так большой пост разбит на компактные части.

Работает там, где сообщение отправил сам бот в личном чате (или открыто по
deep-link): у каждого пользователя своя копия — навигация не мешает другим.
Для каналов используем короткий тизер с URL-кнопкой, открывающей хаб в личке
(в общем посте канала callback-навигация недопустима — он один на всех).

Хабы:
  • play  — что умеет бот (модерация / игра / заработок), для владельцев чатов;
  • agent — рефералка (сколько платят / массовость / куда тратить / моя ссылка);
  • ads   — оффер рекламодателю (как работает / оплата / авто-проверка).
"""
from __future__ import annotations

import asyncio

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from utils import ce, get_config, is_owner, escape_html
from utils.media import answer_with_banner, edit_screen

router = Router()


def _u() -> str:
    return (get_config().bot_username or "").lstrip("@")


# ── Контент хабов ────────────────────────────────────────────────────────────
# Каждый хаб: banner, root (текст корня), sections [(key, label, text)],
# cta [(label, payload)] — URL-кнопки-действия (payload 'startgroup' = добавить
# в чат, иначе deep-link ?start=payload).

HUBS: dict[str, dict] = {
    "play": {
        "banner": "start",
        "root": (
            f"{ce('spark')} <b>S-РАНГ МЕНЕДЖЕР — ЧТО Я УМЕЮ</b>\n"
            "Модерация 24/7 и игра, из которой не хочется выходить.\n\n"
            f"{ce('rocket')} Жми кнопку — раскрою раздел. «⬅️ Назад» вернёт сюда."
        ),
        "sections": [
            ("mod", "🛡 Модерация", (
                f"{ce('shield')} <b>МОДЕРАЦИЯ 24/7 — БЕСПЛАТНО</b>\n\n"
                f"{ce('cross')} Вычищаю спам, оскорбления, NSFW и чужую рекламу — "
                "мгновенно, даже замаскированное (п0рн0, б л я, cyka).\n"
                f"{ce('warn')} Мягкая эскалация: предупреждение → мут → бан. "
                "Сначала по-доброму, наказания — в крайнем случае.\n"
                f"{ce('check')} Админов и владельца не трогаю.\n"
                f"{ce('bulb')} Любой может пожаловаться на сообщение командой /report — "
                "я перепроверю."
            )),
            ("game", "🎮 Игра и ранги", (
                f"{ce('trophy')} <b>ИГРА SOLO LEVELING</b>\n\n"
                f"Ранги E → D → C → B → A → S → SS → {ce('crown')} SSS.\n"
                f"{ce('coin')} <b>Мана-руда</b> — валюта Системы: копится за активность.\n"
                f"{ce('fire')} Подземелья, задания, стрики, дуэли, рейды, топы.\n"
                f"{ce('premium')} Высокие ранги (S+) открывают VIP-зал и бонусы."
            )),
            ("earn", "🪙 Заработок", (
                f"{ce('coin')} <b>КАК ДОБЫВАТЬ РУДУ</b>\n\n"
                f"{ce('tasks')} <b>/tasks</b> — задания-подписки: +100 руды за канал.\n"
                f"{ce('dungeon')} <b>/dungeon</b> — подземелье: до 50 руды/день.\n"
                f"{ce('agent')} Зови друзей — доход за каждое их повышение ранга.\n\n"
                f"{ce('gift')} Руду меняешь на <b>настоящие Telegram-подарки</b>: "
                "1000 руды = подарок за 15⭐, реально за пару дней."
            )),
        ],
        "cta": [("➕ Добавить бота в свой чат", "startgroup")],
    },
    "agent": {
        "banner": "earn",
        "root": (
            f"{ce('coin')} <b>ДРУЗЬЯ = ТВОЙ ДОХОД</b>\n"
            "Приводишь охотников — Система платит тебе за их рост.\n\n"
            f"{ce('rocket')} Жми кнопку — покажу цифры. «⬅️ Назад» вернёт сюда."
        ),
        "sections": [
            ("rew", "💰 Сколько платят", (
                f"{ce('chartup')} <b>ПЛАТИМ ЗА РОСТ РЕКРУТА</b>\n\n"
                "Не разово за вход, а на <b>каждом</b> его повышении ранга:\n"
                f"{ce('check')} D <b>+50</b> · C <b>+100</b> · B <b>+200</b>\n"
                f"{ce('check')} A <b>+400</b> · S <b>+800</b> руды\n\n"
                "Один охотник до S = <b>1550 руды</b>, и тебе ничего не делать — "
                f"он играет, ты получаешь. {ce('fire')}"
            )),
            ("mass", "👑 Бонусы за массовость", (
                f"{ce('crown')} <b>АРМИЯ СИЛЬНЫХ = БОЛЬШЕ РУДЫ</b>\n\n"
                f"{ce('trophy')} За каждые <b>10</b> твоих игроков ранга SS — <b>+2000 руды</b>.\n"
                f"{ce('crown')} За каждые <b>10</b> ранга SSS — <b>+4000 руды</b>.\n\n"
                f"{ce('spark')} Собирай сильных охотников — и руда потечёт сама."
            )),
            ("spend", "🎁 Куда тратить", (
                f"{ce('gift')} <b>РУДА — НЕ ФАНТИКИ</b>\n\n"
                f"{ce('gift')} Меняй на <b>настоящие Telegram-подарки</b> (от 15⭐).\n"
                f"{ce('star')} Покупай VIP-доступ и привилегии.\n"
                f"{ce('coin')} Крипто-вывод — уже на подходе."
            )),
            ("link", "🔗 Моя ссылка", "__link__"),  # динамика: персональная ссылка
        ],
        "cta": [("⚡ Открыть Систему", "menu")],
    },
    "ads": {
        "banner": "ads_offer",
        "root": (
            f"{ce('megaphone')} <b>ЖИВЫЕ ПОДПИСЧИКИ — БЕЗ НАКРУТКИ</b>\n"
            "Реальные игроки S-Rank подписываются сами ради наград. Платишь "
            "только за результат.\n\n"
            f"{ce('rocket')} Жми кнопку — раскрою детали. Готов? Закажи рекламу."
        ),
        "sections": [
            ("how", "⚙️ Как это работает", (
                f"{ce('spark')} <b>КАК ЭТО РАБОТАЕТ</b>\n\n"
                f"{ce('check')} Заявка за 2 минуты: /advertise → канал, описание, "
                "сколько подписчиков, формат.\n"
                f"{ce('check')} Канал попадает в задания игроков.\n"
                f"{ce('check')} Игроки подписываются ради награды — проверка авто.\n"
                f"{ce('shield')} <b>Гарантия неотписки:</b> отписавшихся мягко возвращаем.\n"
                f"{ce('check')} Набрал цель — задание само останавливается."
            )),
            ("pay", "💳 Оплата и гарантии", (
                f"{ce('star')} <b>ОПЛАТА И ГАРАНТИИ</b>\n\n"
                f"{ce('star')} Оплата в Telegram Stars — без внешних кошельков.\n"
                f"{ce('shield')} Деньги в <b>эскроу</b>: отклонили заявку — вернём полностью.\n"
                f"{ce('coin')} Платишь только за <b>результат</b> — за подписчика.\n"
                f"{ce('chart')} Прозрачная статистика по заявке."
            )),
            ("auto", "🤝 Авто-проверка (ботам/играм)", (
                f"{ce('spark')} <b>АВТО-ПРОВЕРКА ДЕЙСТВИЙ</b>\n\n"
                "Подписки на каналы проверяет бот-админ. Действия в ботах/играх — "
                "через постбэк (S2S):\n"
                f"{ce('check')} игрок переходит по ссылке с токеном;\n"
                f"{ce('check')} твой бот дёргает наш <code>/cb/task</code>;\n"
                f"{ce('check')} Система сама начисляет, подделать нельзя.\n\n"
                f"{ce('tasks')} Памятка: <code>/taskcb &lt;id&gt;</code>."
            )),
        ],
        "cta": [("🚀 Заказать рекламу", "advertise")],
    },
}


def _personal_link_text(user_id: int) -> str:
    uname = _u()
    link = f"https://t.me/{uname}?start=ref_{user_id}" if uname else "—"
    return (
        f"{ce('link')} <b>ТВОЯ АГЕНТСКАЯ ССЫЛКА</b>\n\n"
        f"<code>{escape_html(link)}</code>\n\n"
        f"{ce('agent')} Делись ею: каждый, кто придёт по ней, закрепляется за "
        "тобой навсегда. Жми и пересылай друзьям."
    )


def _cta_url(payload: str) -> str | None:
    uname = _u()
    if not uname:
        return None
    if payload == "startgroup":
        return f"https://t.me/{uname}?startgroup=true"
    return f"https://t.me/{uname}?start={payload}"


def _root_kb(hub_id: str, hub: dict):
    b = InlineKeyboardBuilder()
    for key, label, _ in hub["sections"]:
        b.row(InlineKeyboardButton(text=label, callback_data=f"promo:{hub_id}:{key}"))
    for label, payload in hub.get("cta", []):
        url = _cta_url(payload)
        if url:
            b.row(InlineKeyboardButton(text=label, url=url))
    return b.as_markup()


def _section_kb(hub_id: str, hub: dict):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"promo:{hub_id}:root"))
    cta = hub.get("cta", [])
    if cta:
        label, payload = cta[0]
        url = _cta_url(payload)
        if url:
            b.row(InlineKeyboardButton(text=label, url=url))
    return b.as_markup()


def _render(hub_id: str, section: str, user_id: int = 0):
    """Возвращает (banner_key, text, markup) для корня или раздела хаба."""
    hub = HUBS[hub_id]
    if section in ("", "root", None):
        return hub["banner"], hub["root"], _root_kb(hub_id, hub)
    for key, _label, text in hub["sections"]:
        if key == section:
            if text == "__link__":
                text = _personal_link_text(user_id)
            return hub["banner"], text, _section_kb(hub_id, hub)
    return hub["banner"], hub["root"], _root_kb(hub_id, hub)


async def send_hub(message: Message, hub_id: str) -> None:
    """Отправить корень хаба новым сообщением (баннер + кнопки разделов)."""
    if hub_id not in HUBS:
        hub_id = "play"
    banner, text, kb = _render(hub_id, "root")
    await answer_with_banner(message, banner, text, reply_markup=kb)


@router.callback_query(F.data.startswith("promo:"))
async def cb_promo(call: CallbackQuery) -> None:
    parts = call.data.split(":", 2)
    if len(parts) != 3:
        await call.answer()
        return
    _, hub_id, section = parts
    if hub_id not in HUBS:
        await call.answer()
        return
    _banner, text, kb = _render(hub_id, section, user_id=call.from_user.id)
    await edit_screen(call.message, text, reply_markup=kb)
    await call.answer()


# ── /promo — прислать владельцу интерактивные посты ───────────────────────────

@router.message(Command("promo", "posts", "promoposts"), F.chat.type == "private")
async def cmd_promo(message: Message) -> None:
    if not is_owner(message.from_user.id):
        return
    await message.answer(
        f"{ce('rocket')} <b>МАРКЕТИНГ-НАБОР</b>\n\n"
        "Ниже — интерактивные посты: основная мысль в посте, детали раскрываются "
        "по кнопкам (внутри — «⬅️ Назад»). Эти посты бот открывает пользователям "
        "по кнопкам/ссылкам; для канала ставь короткий тизер со ссылкой.\n"
        f"<i>{ce('spark')} Премиум-эмодзи видны при активном Telegram Premium.</i>",
        parse_mode="HTML",
    )
    for hub_id in ("play", "agent", "ads"):
        try:
            await send_hub(message, hub_id)
        except Exception as e:
            logger.warning(f"[PROMO] hub {hub_id} failed: {e}")
        await asyncio.sleep(0.4)
