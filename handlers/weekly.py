from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database.db import get_user, get_menu, get_pool
from datetime import date, timedelta

router = Router()

DAYS_RU = {
    0: "Понедельник", 1: "Вторник", 2: "Среда",
    3: "Четверг", 4: "Пятница", 5: "Суббота", 6: "Воскресенье"
}


async def get_weekly_orders(user_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            "SELECT day_of_week, menu_item FROM weekly_orders WHERE user_id = $1 AND is_active = 1",
            user_id
        )
        return {row["day_of_week"]: row["menu_item"] for row in rows}


async def save_weekly_order(user_id: int, day: int, item: int):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            """INSERT INTO weekly_orders (user_id, day_of_week, menu_item, is_active)
               VALUES ($1, $2, $3, 1)
               ON CONFLICT (user_id, day_of_week) DO UPDATE SET menu_item = $3, is_active = 1""",
            user_id, day, item
        )


async def delete_weekly_order(user_id: int, day: int):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE weekly_orders SET is_active = 0 WHERE user_id = $1 AND day_of_week = $2",
            user_id, day
        )


def weekly_menu_keyboard(weekly: dict) -> object:
    builder = InlineKeyboardBuilder()
    for day_num, day_name in DAYS_RU.items():
        item = weekly.get(day_num)
        text = f"✅ {day_name} — блюдо {item}" if item else f"➕ {day_name}"
        builder.button(text=text, callback_data=f"weekly_day_{day_num}")
    builder.button(text="❌ Очистить всё", callback_data="weekly_clear_all")
    builder.button(text="◀️ Назад", callback_data="weekly_back")
    builder.adjust(1)
    return builder.as_markup()


def day_items_keyboard(day: int, menu_items: list, current_item: int = None) -> object:
    builder = InlineKeyboardBuilder()
    for item in menu_items:
        check = "✅ " if current_item == item["item_number"] else ""
        builder.button(
            text=f"{check}{item['item_number']}. {item['name']}",
            callback_data=f"weekly_set_{day}_{item['item_number']}"
        )
    if not menu_items:
        builder.button(text="❌ Меню не добавлено", callback_data="weekly_no_menu")
    if current_item:
        builder.button(text="🗑 Убрать этот день", callback_data=f"weekly_del_{day}")
    builder.button(text="◀️ Назад", callback_data="weekly_back_list")
    builder.adjust(1)
    return builder.as_markup()


@router.callback_query(F.data == "weekly_menu")
async def weekly_menu(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    weekly = await get_weekly_orders(user["id"])
    await callback.message.edit_text(
        "📅 *Меню на неделю*\n\nВыберите день:\n✅ — настроено\n➕ — нажми чтобы выбрать",
        parse_mode="Markdown",
        reply_markup=weekly_menu_keyboard(weekly)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("weekly_day_"))
async def weekly_day_select(callback: CallbackQuery):
    day = int(callback.data.split("_")[2])
    day_name = DAYS_RU[day]
    user = await get_user(callback.from_user.id)
    weekly = await get_weekly_orders(user["id"])
    current = weekly.get(day)

    today = date.today()
    days_ahead = (day - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    target_date = str(today + timedelta(days=days_ahead))
    menu_items = await get_menu(target_date)

    await callback.message.edit_text(
        f"📅 *{day_name}* ({target_date})\n\nВыберите блюдо:",
        parse_mode="Markdown",
        reply_markup=day_items_keyboard(day, menu_items, current)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("weekly_set_"))
async def weekly_set_item(callback: CallbackQuery):
    parts = callback.data.split("_")
    day = int(parts[2])
    item = int(parts[3])
    day_name = DAYS_RU[day]
    user = await get_user(callback.from_user.id)
    await save_weekly_order(user["id"], day, item)
    weekly = await get_weekly_orders(user["id"])
    await callback.answer(f"✅ {day_name} — Блюдо {item} сохранено!")
    await callback.message.edit_text(
        "📅 *Меню на неделю*\n\n✅ — настроено\n➕ — нажми чтобы выбрать",
        parse_mode="Markdown",
        reply_markup=weekly_menu_keyboard(weekly)
    )


@router.callback_query(F.data.startswith("weekly_del_"))
async def weekly_del_item(callback: CallbackQuery):
    day = int(callback.data.split("_")[2])
    day_name = DAYS_RU[day]
    user = await get_user(callback.from_user.id)
    await delete_weekly_order(user["id"], day)
    weekly = await get_weekly_orders(user["id"])
    await callback.answer(f"🗑 {day_name} удалён")
    await callback.message.edit_text(
        "📅 *Меню на неделю*\n\n✅ — настроено\n➕ — нажми чтобы выбрать",
        parse_mode="Markdown",
        reply_markup=weekly_menu_keyboard(weekly)
    )


@router.callback_query(F.data == "weekly_clear_all")
async def weekly_clear_all(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE weekly_orders SET is_active = 0 WHERE user_id = $1", user["id"]
        )
    await callback.answer("🗑 Все дни очищены")
    await callback.message.edit_text(
        "📅 *Меню на неделю*\n\n✅ — настроено\n➕ — нажми чтобы выбрать",
        parse_mode="Markdown",
        reply_markup=weekly_menu_keyboard({})
    )


@router.callback_query(F.data == "weekly_back")
async def weekly_back(callback: CallbackQuery):
    from keyboards.keyboards import settings_keyboard
    user = await get_user(callback.from_user.id)
    from database.db import get_user_lang
    lang = await get_user_lang(callback.from_user.id)
    from langs import t
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t(lang, "btn_auto_on") if user.get("auto_order") else t(lang, "btn_auto_off"),
        callback_data="toggle_auto_order"
    )
    builder.button(text=t(lang, "btn_weekly"), callback_data="weekly_menu")
    builder.adjust(1)
    await callback.message.edit_text("⚙️ *Настройки*", parse_mode="Markdown", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "weekly_back_list")
async def weekly_back_list(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    weekly = await get_weekly_orders(user["id"])
    await callback.message.edit_text(
        "📅 *Меню на неделю*\n\n✅ — настроено\n➕ — нажми чтобы выбрать",
        parse_mode="Markdown",
        reply_markup=weekly_menu_keyboard(weekly)
    )
    await callback.answer()


@router.callback_query(F.data == "weekly_no_menu")
async def weekly_no_menu(callback: CallbackQuery):
    await callback.answer("❌ Меню на этот день ещё не добавлено!", show_alert=True)