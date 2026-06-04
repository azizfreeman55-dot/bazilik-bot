import os

# ===== handlers/weekly.py =====
with open("handlers/weekly.py", "w", encoding="utf-8") as f:
    f.write('''from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.db import get_user, get_menu
from datetime import date, timedelta
import aiosqlite
from config import DATABASE_URL

router = Router()

DAYS_RU = {
    0: "Понедельник", 1: "Вторник", 2: "Среда",
    3: "Четверг", 4: "Пятница"
}


async def get_weekly_orders(user_id: int) -> dict:
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT day_of_week, menu_item FROM weekly_orders WHERE user_id = ? AND is_active = 1",
            (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return {row["day_of_week"]: row["menu_item"] for row in rows}


async def save_weekly_order(user_id: int, day: int, item: int):
    async with aiosqlite.connect(DATABASE_URL) as db:
        await db.execute(
            """INSERT OR REPLACE INTO weekly_orders (user_id, day_of_week, menu_item, is_active)
               VALUES (?, ?, ?, 1)""",
            (user_id, day, item)
        )
        await db.commit()


async def delete_weekly_order(user_id: int, day: int):
    async with aiosqlite.connect(DATABASE_URL) as db:
        await db.execute(
            "UPDATE weekly_orders SET is_active = 0 WHERE user_id = ? AND day_of_week = ?",
            (user_id, day)
        )
        await db.commit()


def weekly_menu_keyboard(weekly: dict) -> object:
    builder = InlineKeyboardBuilder()
    for day_num, day_name in DAYS_RU.items():
        item = weekly.get(day_num)
        if item:
            text = f"✅ {day_name} — блюдо {item}"
        else:
            text = f"➕ {day_name}"
        builder.button(text=text, callback_data=f"weekly_day_{day_num}")
    builder.button(text="❌ Очистить всё", callback_data="weekly_clear_all")
    builder.button(text="◀️ Назад", callback_data="weekly_back")
    builder.adjust(1)
    return builder.as_markup()


def day_items_keyboard(day: int, current_item: int = None) -> object:
    builder = InlineKeyboardBuilder()
    for i in range(1, 4):
        check = "✅ " if current_item == i else ""
        builder.button(text=f"{check}Блюдо {i}", callback_data=f"weekly_set_{day}_{i}")
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
        "📅 *Меню на неделю*\\n\\nВыберите день и укажите блюдо!\\n\\n✅ — уже настроено\\n➕ — нажми чтобы выбрать",
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
    await callback.message.edit_text(
        f"📅 *{day_name}*\\n\\nВыберите блюдо:",
        parse_mode="Markdown",
        reply_markup=day_items_keyboard(day, current)
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
        "📅 *Меню на неделю*\\n\\n✅ — уже настроено\\n➕ — нажми чтобы выбрать",
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
        "📅 *Меню на неделю*\\n\\n✅ — уже настроено\\n➕ — нажми чтобы выбрать",
        parse_mode="Markdown",
        reply_markup=weekly_menu_keyboard(weekly)
    )


@router.callback_query(F.data == "weekly_clear_all")
async def weekly_clear_all(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    async with aiosqlite.connect(DATABASE_URL) as db:
        await db.execute("UPDATE weekly_orders SET is_active = 0 WHERE user_id = ?", (user["id"],))
        await db.commit()
    await callback.answer("🗑 Все дни очищены")
    await callback.message.edit_text(
        "📅 *Меню на неделю*\\n\\n✅ — уже настроено\\n➕ — нажми чтобы выбрать",
        parse_mode="Markdown",
        reply_markup=weekly_menu_keyboard({})
    )


@router.callback_query(F.data == "weekly_back")
async def weekly_back(callback: CallbackQuery):
    from keyboards.keyboards import settings_keyboard
    user = await get_user(callback.from_user.id)
    await callback.message.edit_text("⚙️ *Настройки*", parse_mode="Markdown",
        reply_markup=settings_keyboard(bool(user.get("auto_order"))))
    await callback.answer()


@router.callback_query(F.data == "weekly_back_list")
async def weekly_back_list(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    weekly = await get_weekly_orders(user["id"])
    await callback.message.edit_text(
        "📅 *Меню на неделю*\\n\\n✅ — уже настроено\\n➕ — нажми чтобы выбрать",
        parse_mode="Markdown",
        reply_markup=weekly_menu_keyboard(weekly)
    )
    await callback.answer()
''')

# ===== handlers/__init__.py =====
with open("handlers/__init__.py", "w", encoding="utf-8") as f:
    f.write('''from aiogram import Dispatcher
from .registration import router as registration_router
from .orders import router as orders_router
from .profile import router as profile_router
from .admin import router as admin_router
from .weekly import router as weekly_router
from .analytics import router as analytics_router


def register_all_handlers(dp: Dispatcher):
    dp.include_router(registration_router)
    dp.include_router(analytics_router)
    dp.include_router(orders_router)
    dp.include_router(profile_router)
    dp.include_router(admin_router)
    dp.include_router(weekly_router)
''')

print("✅ Все файлы созданы!")