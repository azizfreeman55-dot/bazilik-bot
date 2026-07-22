from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo
)
from aiogram.utils.keyboard import InlineKeyboardBuilder


CATEGORY_NAMES = {
    "breakfast": {"ru": "🌅 Завтраки",      "uz": "🌅 Nonushtalar"},
    "first":   {"ru": "🍲 Первые блюда",   "uz": "🍲 Birinchi taomlar"},
    "main":    {"ru": "🍛 Вторые блюда",   "uz": "🍛 Ikkinchi taomlar"},
    "second":  {"ru": "🍱 Сеты",            "uz": "🍱 Setlar"},
    "salad":   {"ru": "🥗 Салаты",           "uz": "🥗 Salatlar"},
    "dessert": {"ru": "🍰 Десерты",          "uz": "🍰 Desertlar"},
    "drink":   {"ru": "🥤 Напитки",          "uz": "🥤 Ichimliklar"},
}

WEBAPP_URL = "https://bazilik-webhook.onrender.com/webapp/index.html"


def main_menu_keyboard(is_admin: bool = False, lang: str = "ru"):
    """
    Главное меню клиента. Mini App теперь открывается через Menu Button
    (кнопка рядом с полем ввода, настроена в BotFather через /setmenubutton) —
    это надёжнее, чем KeyboardButton с web_app, у которой initData
    иногда приходит пустой на некоторых клиентах.

    Для обычного клиента reply-клавиатура не нужна вообще — возвращаем None,
    aiogram в этом случае просто не показывает клавиатуру под полем ввода.
    Админу всё ещё показываем кнопку открытия админ-панели.
    """
    from langs import t
    if not is_admin:
        return None

    buttons = [[KeyboardButton(text=t(lang, "btn_admin"))]]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def category_keyboard(available_categories: list, lang: str = "ru") -> InlineKeyboardMarkup:
    """Оставлено для обратной совместимости — не используется в основном потоке."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✨ Открыть каталог" if lang == "ru" else "✨ Katalogni ochish",
        web_app=WebAppInfo(url=WEBAPP_URL)
    )
    for cat in available_categories:
        name = CATEGORY_NAMES.get(cat, {}).get(lang, cat)
        builder.button(text=name, callback_data=f"menu_category_{cat}")
    builder.adjust(1, 2)
    return builder.as_markup()


def menu_keyboard(menu_items: list, category: str = "second", lang: str = "ru") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in menu_items:
        builder.button(
            text=f"{item['item_number']}. {item['name']} — {item['price']:,} сум",
            callback_data=f"order_{item['id']}"
        )
    builder.button(
        text="◀️ Назад к категориям" if lang == "ru" else "◀️ Kategoriyalarga qaytish",
        callback_data="back_to_categories"
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
    builder.button(text="🍽️ Управление меню", callback_data="admin_add_menu")
    builder.button(text="📨 Рассылка", callback_data="admin_broadcast")
    builder.button(text="👥 Все пользователи", callback_data="admin_users")
    builder.adjust(2)
    return builder.as_markup()


def back_keyboard(callback: str = "back_main") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data=callback)
    return builder.as_markup()
