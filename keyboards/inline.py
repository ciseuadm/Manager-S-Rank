from urllib.parse import quote

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def settings_keyboard(settings: dict) -> InlineKeyboardMarkup:
    def toggle(val: int) -> str:
        return "✅" if val else "❌"

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=f"{toggle(settings['filter_nsfw'])} NSFW / 18+",
            callback_data="toggle:filter_nsfw",
        ),
        InlineKeyboardButton(
            text=f"{toggle(settings['filter_insults'])} Оскорбления",
            callback_data="toggle:filter_insults",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=f"{toggle(settings['filter_politics'])} Политика",
            callback_data="toggle:filter_politics",
        ),
        InlineKeyboardButton(
            text=f"{toggle(settings['filter_spam'])} Спам",
            callback_data="toggle:filter_spam",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=f"{toggle(settings['filter_links'])} Ссылки",
            callback_data="toggle:filter_links",
        ),
        InlineKeyboardButton(
            text=f"{toggle(settings['filter_stickers'])} Стикеры",
            callback_data="toggle:filter_stickers",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=f"{toggle(settings['antiflood'])} Антифлуд",
            callback_data="toggle:antiflood",
        ),
        InlineKeyboardButton(
            text=f"{toggle(settings['filter_caps'])} Капс",
            callback_data="toggle:filter_caps",
        ),
    )
    warn_limit = settings.get("warn_limit", 3)
    mute_time = settings.get("mute_time", 60)
    mute_label = f"{mute_time // 60}ч" if mute_time >= 60 else f"{mute_time}м"
    builder.row(
        InlineKeyboardButton(
            text=f"⚠️ Варны: {warn_limit}", callback_data="set:warn_limit"
        ),
        InlineKeyboardButton(
            text=f"🔇 Мут: {mute_label}", callback_data="set:mute_time"
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=f"{toggle(settings.get('delete_service_msgs', 1))} Чистить вход/выход",
            callback_data="toggle:delete_service_msgs",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=f"{toggle(settings.get('antiraid', 0))} Антирейд",
            callback_data="toggle:antiraid",
        ),
        InlineKeyboardButton(
            text=f"{toggle(settings.get('cas_ban', 0))} CAS-бан спам-ботов",
            callback_data="toggle:cas_ban",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=f"{toggle(settings.get('night_mode', 0))} Ночной режим",
            callback_data="toggle:night_mode",
        ),
        InlineKeyboardButton(
            text=f"{toggle(settings.get('block_forwards', 0))} Блок пересылок",
            callback_data="toggle:block_forwards",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="📝 Приветствие", callback_data="set:welcome_msg"),
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Обновить", callback_data="settings:refresh"),
        InlineKeyboardButton(text="✖ Закрыть", callback_data="settings:close"),
    )
    return builder.as_markup()


def invite_keyboard(link: str, share_text: str) -> InlineKeyboardMarkup:
    """A 'share to friends' button — the core viral/marketing hook."""
    builder = InlineKeyboardBuilder()
    share_url = (
        f"https://t.me/share/url?url={quote(link, safe='')}"
        f"&text={quote(share_text, safe='')}"
    )
    builder.row(
        InlineKeyboardButton(text="📣 Позвать друзей", url=share_url),
    )
    builder.row(
        InlineKeyboardButton(text="🔗 Открыть чат", url=link),
    )
    return builder.as_markup()


def welcome_keyboard(
    bot_username: str, extra_text: str = "", extra_url: str = ""
) -> InlineKeyboardMarkup:
    """
    Маркетинговый «крючок» в приветствии новичка: ведём в личку бота,
    чтобы человек начал фармить руду, и даём быстрый доступ к правилам.
    extra_text/extra_url — кастомная кнопка чата (настраивается /setwelcomebtn).
    """
    base = f"https://t.me/{bot_username}"
    builder = InlineKeyboardBuilder()
    if extra_text and extra_url:
        url = extra_url if extra_url.startswith("http") else f"https://{extra_url}"
        builder.row(InlineKeyboardButton(text=extra_text[:48], url=url))
    builder.row(
        InlineKeyboardButton(text="⚡ Открыть Систему", url=f"{base}?start=welcome"),
    )
    builder.row(
        InlineKeyboardButton(
            text="💎 Как заработать руду", url=f"{base}?start=earn"
        ),
    )
    builder.row(
        InlineKeyboardButton(text="📜 Правила", callback_data="welcome:rules"),
    )
    return builder.as_markup()


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главный кнопочный хаб (личка): всё важное в одном сообщении, без команд."""
    b = InlineKeyboardBuilder()
    # Кнопка-витрина Mini App (если задан публичный https-адрес).
    try:
        from utils import get_config
        cfg = get_config()
        if cfg.webapp_enabled and cfg.webapp_url.startswith("https://"):
            from aiogram.types import WebAppInfo
            b.row(InlineKeyboardButton(
                text="🎮 Открыть платформу",
                web_app=WebAppInfo(url=cfg.webapp_url),
            ))
    except Exception:
        pass
    b.row(
        InlineKeyboardButton(text="👤 Профиль", callback_data="menu:profile"),
        InlineKeyboardButton(text="🔹 Кошелёк", callback_data="menu:wallet"),
    )
    b.row(
        InlineKeyboardButton(text="📋 Задания", callback_data="menu:tasks"),
        InlineKeyboardButton(text="🎁 Подарки", callback_data="menu:gifts"),
    )
    b.row(
        InlineKeyboardButton(text="🛒 Магазин", callback_data="menu:shop"),
        InlineKeyboardButton(text="🕴 Доход / друзья", callback_data="menu:ref"),
    )
    b.row(
        InlineKeyboardButton(text="👑 Привилегии", callback_data="menu:perks"),
        InlineKeyboardButton(text="❓ Помощь", callback_data="menu:help"),
    )
    return b.as_markup()


def menu_nav_keyboard(*extra_rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    """Низ подэкрана меню: пользовательские кнопки + «Назад» (в главное меню)."""
    b = InlineKeyboardBuilder()
    for row in extra_rows:
        if row:
            b.row(*row)
    b.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:root"))
    return b.as_markup()


def shop_keyboard(is_vip: bool = False, from_menu: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    # По одной кнопке в ряд: длинные подписи («Обменять на подарки») не обрезаются
    # на узких экранах телефонов.
    builder.row(
        InlineKeyboardButton(text="💎 Купить руду за ⭐", callback_data="shop:buy"),
    )
    builder.row(
        InlineKeyboardButton(text="🎁 Обменять на подарки", callback_data="shop:gifts"),
    )
    builder.row(
        InlineKeyboardButton(
            text="👑 VIP-зал" + (" ✅" if is_vip else ""),
            callback_data="shop:vip",
        ),
    )
    # «Назад»: из меню — в главное меню, как команда — тоже в хаб (а не «закрыть»).
    builder.row(
        InlineKeyboardButton(
            text="⬅️ Назад" if from_menu else "⬅️ В меню",
            callback_data="menu:root",
        ),
    )
    return builder.as_markup()


def shop_back_keyboard(extra: list[InlineKeyboardButton] | None = None) -> InlineKeyboardMarkup:
    """Низ подэкрана магазина: доп.кнопки + «Назад» (в магазин)."""
    b = InlineKeyboardBuilder()
    if extra:
        b.row(*extra)
    b.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="shop:root"))
    return b.as_markup()


def owner_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📊 Глобальная статистика", callback_data="owner:stats"),
    )
    builder.row(
        InlineKeyboardButton(text="💬 Список чатов", callback_data="owner:chats"),
    )
    builder.row(
        InlineKeyboardButton(text="📢 Как сделать рассылку", callback_data="owner:broadcast"),
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Обновить", callback_data="owner:refresh"),
        InlineKeyboardButton(text="✖ Закрыть", callback_data="owner:close"),
    )
    return builder.as_markup()


def confirm_keyboard(action: str, target_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да", callback_data=f"confirm:{action}:{target_id}"),
        InlineKeyboardButton(text="❌ Нет", callback_data="confirm:cancel"),
    )
    return builder.as_markup()


def user_action_keyboard(user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⚠️ Варн", callback_data=f"action:warn:{user_id}"),
        InlineKeyboardButton(text="🔇 Мут 60м", callback_data=f"action:mute:{user_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="🚫 Бан", callback_data=f"action:ban:{user_id}"),
        InlineKeyboardButton(text="👟 Кик", callback_data=f"action:kick:{user_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="✖ Закрыть", callback_data="action:close"),
    )
    return builder.as_markup()
