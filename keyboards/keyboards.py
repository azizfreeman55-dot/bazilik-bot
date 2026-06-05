from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_keyboard(is_admin: bool = False, lang: str = "ru") -> ReplyKeyboardMarkup:
    from langs import t
    buttons = [
        [KeyboardButton(text=t(lang, "btn_order")), KeyboardButton(text=t(lang, "btn_my_order"))],
        [KeyboardButton(text=t(lang, "btn_profile")), KeyboardButton(text=t(lang, "btn_rating"))],
        [KeyboardButton(text=t(lang, "btn_invite")), KeyboardButton(text=t(lang, "btn_settings"))],
    ]
    if is_admin:
        buttons.append([KeyboardButton(text=t(lang, "btn_admin"))])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def menu_keyboard(menu_items: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in menu_items:
        builder.button(
            text=f"{item['item_number']}. {item['name']} — {item['price']:,} сум",
            callback_data=f"order_{item['id']}"
        )
    builder.adjust(1)
    return builder.as_markup()


def order_actions_keyboard(has_order: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if has_order:
        builder.button(text="✏️ Изменить", callback_data="change_order")
        builder.button(text="❌ Отменить заказ", callback_data="cancel_order")
    builder.adjust(2)
    return builder.as_markup()


def confirm_cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, отменить", callback_data="confirm_cancel")
    builder.button(text="◀️ Назад", callback_data="back_to_order")
    builder.adjust(2)
    return builder.as_markup()


def settings_keyboard(auto_order: bool) -> InlineKeyboardMarkup:
    auto_text = "🟢 Автозаказ: ВКЛ" if auto_order else "🔴 Автозаказ: ВЫКЛ"
    builder = InlineKeyboardBuilder()
    builder.button(text=auto_text, callback_data="toggle_auto_order")
    builder.button(text="📅 Меню на неделю", callback_data="weekly_menu")
    builder.adjust(1)
    return builder.as_markup()


def admin_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Сводка заказов", callback_data="admin_summary")
    builder.button(text="🍽️ Добавить меню", callback_data="admin_add_menu")
    builder.button(text="📨 Рассылка", callback_data="admin_broadcast")
    builder.button(text="👥 Все пользователи", callback_data="admin_users")
    builder.adjust(2)
    return builder.as_markup()


def back_keyboard(callback: str = "back_main") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data=callback)
    return builder.as_markup()
