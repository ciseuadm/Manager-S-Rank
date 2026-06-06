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
    builder.row(
        InlineKeyboardButton(text="⚠️ Лимит варнов", callback_data="set:warn_limit"),
        InlineKeyboardButton(text="🔇 Время мута", callback_data="set:mute_time"),
    )
    builder.row(
        InlineKeyboardButton(text="📝 Приветствие", callback_data="set:welcome_msg"),
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Обновить", callback_data="settings:refresh"),
        InlineKeyboardButton(text="✖ Закрыть", callback_data="settings:close"),
    )
    return builder.as_markup()


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
