from datetime import date, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Filter
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.db import (
    get_daily_summary, get_all_users_for_notification,
    close_orders_for_date, get_pool, set_menu
)
from keyboards.keyboards import admin_keyboard
from config import ADMIN_IDS

router = Router()

CATEGORIES = {
    "main":    {"ru": "🍱 Основные блюда",  "uz": "🍱 Asosiy taomlar",   "emoji": "🍱"},
    "salad":   {"ru": "🥗 Салаты",           "uz": "🥗 Salatlar",          "emoji": "🥗"},
    "dessert": {"ru": "🍰 Десерты",          "uz": "🍰 Desertlar",         "emoji": "🍰"},
    "drink":   {"ru": "🥤 Напитки",          "uz": "🥤 Ichimliklar",       "emoji": "🥤"},
}


class IsAdmin(Filter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user.id in ADMIN_IDS


class AddMenu(StatesGroup):
    waiting_category = State()
    waiting_photo = State()
    waiting_name = State()
    waiting_price = State()
    waiting_more = State()


class Broadcast(StatesGroup):
    waiting_message = State()


@router.callback_query(F.data == "admin_summary")
async def admin_summary(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    tomorrow = str(date.today() + timedelta(days=1))
    summary = await get_daily_summary(tomorrow)

    if not summary["items"]:
        await callback.answer()
        await callback.message.edit_text(
            f"📊 Сводка на {tomorrow}\n\nЗаказов пока нет",
            reply_markup=admin_keyboard()
        )
        return

    text = f"📊 *Сводка заказов на {tomorrow}:*\n\n"

    # Группируем по категории
    by_category = {}
    for item in summary["items"]:
        cat = item.get("category", "main")
        by_category.setdefault(cat, []).append(item)

    for cat, items in by_category.items():
        cat_name = CATEGORIES.get(cat, {}).get("ru", cat)
        text += f"*{cat_name}:*\n"
        for item in items:
            text += f"  • {item['name']}: *{item['count']} шт.*\n"
        text += "\n"

    text += f"📦 Всего: *{summary['total']} позиций*"

    await callback.answer()
    await callback.message.edit_text(
        text, parse_mode="Markdown", reply_markup=admin_keyboard()
    )


@router.callback_query(F.data == "admin_add_menu")
async def admin_add_menu_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    today = date.today()
    for i in range(7):
        d = today + timedelta(days=i)
        label = "Сегодня" if i == 0 else "Завтра" if i == 1 else days[d.weekday()]
        builder.button(text=f"📅 {label} ({d.strftime('%d.%m')})", callback_data=f"menu_date_{d}")
    builder.adjust(2)
    await callback.answer()
    await callback.message.edit_text(
        "🍽️ *Добавление меню*\n\nВыберите день:",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("menu_date_"))
async def admin_menu_date_selected(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    menu_date = callback.data.replace("menu_date_", "")
    await state.update_data(menu_date=menu_date, items=[], item_number=1)
    await state.set_state(AddMenu.waiting_category)

    builder = InlineKeyboardBuilder()
    for key, names in CATEGORIES.items():
        builder.button(
            text=names["ru"],
            callback_data=f"menu_cat_{key}"
        )
    builder.adjust(2)

    await callback.answer()
    await callback.message.edit_text(
        f"📅 *Дата: {menu_date}*\n\nВыберите категорию для добавления:",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("menu_cat_"))
async def admin_category_selected(callback: CallbackQuery, state: FSMContext):
    category = callback.data.replace("menu_cat_", "")
    cat_name = CATEGORIES.get(category, {}).get("ru", category)

    await state.update_data(category=category, items=[], item_number=1)
    await state.set_state(AddMenu.waiting_photo)

    await callback.answer()
    await callback.message.answer(
        f"*Категория: {cat_name}*\n\n"
        f"*Позиция 1:*\n📸 Отправьте фото или напишите *нет*:",
        parse_mode="Markdown"
    )


@router.message(AddMenu.waiting_photo)
async def process_menu_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    if message.photo:
        photo_id = message.photo[-1].file_id
    elif message.text and message.text.lower() in ("нет", "yo'q", "-"):
        photo_id = None
    else:
        await message.answer("📸 Отправьте фото или напишите *нет*", parse_mode="Markdown")
        return

    await state.update_data(current_photo=photo_id)
    await state.set_state(AddMenu.waiting_name)
    await message.answer(
        f"📝 Введите *название* позиции {data['item_number']}:",
        parse_mode="Markdown"
    )


@router.message(AddMenu.waiting_name)
async def process_menu_name(message: Message, state: FSMContext):
    await state.update_data(current_name=message.text.strip())
    await state.set_state(AddMenu.waiting_price)

    data = await state.get_data()
    cat = data.get("category", "main")

    # Подсказка по цене в зависимости от категории
    hints = {
        "main":    "стандарт = 35 000 сум",
        "salad":   "стандарт = 15 000 сум",
        "dessert": "стандарт = 12 000 сум",
        "drink":   "стандарт = 8 000 сум",
    }
    hint = hints.get(cat, "стандарт = 35 000 сум")

    await message.answer(
        f"💰 Введите *цену* (в сумах):\n_({hint} — напишите 'стандарт')_",
        parse_mode="Markdown"
    )


@router.message(AddMenu.waiting_price)
async def process_menu_price(message: Message, state: FSMContext):
    text = message.text.strip().lower()
    data = await state.get_data()
    cat = data.get("category", "main")

    default_prices = {"main": 35000, "salad": 15000, "dessert": 12000, "drink": 8000}

    if text == "стандарт":
        price = default_prices.get(cat, 35000)
    else:
        try:
            price = int(text.replace(" ", "").replace(",", ""))
        except ValueError:
            await message.answer("❌ Введите число. Например: 15000")
            return

    items = data.get("items", [])
    items.append({
        "item_number": data["item_number"],
        "name": data["current_name"],
        "price": price,
        "photo_id": data.get("current_photo")
    })
    await state.update_data(items=items)
    await state.set_state(AddMenu.waiting_more)

    cat_name = CATEGORIES.get(cat, {}).get("ru", cat)
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить ещё позицию", callback_data="menu_add_more")
    builder.button(text="✅ Сохранить категорию", callback_data="menu_save")
    builder.button(text="📂 Добавить другую категорию", callback_data="menu_add_category")
    builder.adjust(1)

    await message.answer(
        f"✅ *Добавлено в {cat_name}:*\n"
        f"• {data['current_name']} — {price:,} сум\n\n"
        f"Всего в категории: {len(items)} позиций\n\n"
        f"Что дальше?",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data == "menu_add_more")
async def menu_add_more(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    next_num = data["item_number"] + 1
    await state.update_data(item_number=next_num)
    await state.set_state(AddMenu.waiting_photo)
    await callback.answer()
    await callback.message.answer(
        f"*Позиция {next_num}:*\n📸 Отправьте фото или напишите *нет*:",
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "menu_save")
async def menu_save(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    menu_date = data["menu_date"]
    items = data["items"]
    category = data.get("category", "main")
    cat_name = CATEGORIES.get(category, {}).get("ru", category)

    await set_menu(menu_date, items, category)
    await state.clear()

    text = f"✅ *{cat_name} на {menu_date} сохранены!*\n\n"
    for item in items:
        photo_text = "📸" if item.get("photo_id") else "  "
        text += f"{photo_text} {item['item_number']}. {item['name']} — {item['price']:,} сум\n"

    await callback.answer()
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=admin_keyboard())


@router.callback_query(F.data == "menu_add_category")
async def menu_add_another_category(callback: CallbackQuery, state: FSMContext):
    """Сохраняем текущую категорию и предлагаем добавить следующую"""
    data = await state.get_data()
    menu_date = data["menu_date"]
    items = data["items"]
    category = data.get("category", "main")

    # Сохраняем текущую категорию
    await set_menu(menu_date, items, category)

    # Предлагаем выбрать следующую
    await state.update_data(items=[], item_number=1)
    await state.set_state(AddMenu.waiting_category)

    builder = InlineKeyboardBuilder()
    for key, names in CATEGORIES.items():
        builder.button(text=names["ru"], callback_data=f"menu_cat_{key}")
    builder.button(text="✅ Всё готово", callback_data="menu_all_done")
    builder.adjust(2)

    await callback.answer()
    await callback.message.answer(
        f"✅ Сохранено!\n\n📅 *{menu_date}* — выберите следующую категорию:",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data == "menu_all_done")
async def menu_all_done(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await callback.message.answer(
        "✅ *Меню полностью сохранено!*",
        parse_mode="Markdown",
        reply_markup=admin_keyboard()
    )


@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    await state.set_state(Broadcast.waiting_message)
    await callback.answer()
    await callback.message.answer("📨 Введите сообщение для рассылки всем пользователям:")


@router.message(Broadcast.waiting_message)
async def process_broadcast(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    users = await get_all_users_for_notification()
    success = 0
    failed = 0

    await message.answer(f"📨 Начинаю рассылку для {len(users)} пользователей...")

    for user_id in users:
        try:
            await message.bot.send_message(user_id, message.text)
            success += 1
        except Exception:
            failed += 1

    await state.clear()
    await message.answer(
        f"✅ Рассылка завершена!\n• Успешно: {success}\n• Ошибок: {failed}",
        reply_markup=admin_keyboard()
    )


@router.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    pool = await get_pool()
    async with pool.acquire() as db:
        users = await db.fetch("""
            SELECT u.full_name, u.phone, u.total_orders, u.points,
            u.status, u.created_at,
            c.name as company_name
            FROM users u
            LEFT JOIN companies c ON u.company_id = c.id
            ORDER BY u.total_orders DESC
        """)

    if not users:
        await callback.answer()
        await callback.message.edit_text("👥 Пользователей пока нет", reply_markup=admin_keyboard())
        return

    text = f"👥 *Все пользователи ({len(users)} чел.)*\n\n"
    for i, u in enumerate(users, 1):
        phone = f"+{u['phone']}" if u.get('phone') else "—"
        text += (
            f"{i}. *{u['full_name']}*\n"
            f"   📱 {phone}\n"
            f"   🏢 {u.get('company_name') or '—'}\n"
            f"   📦 {u['total_orders']} заказов | 💰 {u['points']} баллов\n"
            f"   🏅 {u['status']}\n\n"
        )

    if len(text) > 4000:
        text = text[:4000] + "\n...и другие"

    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data="back_admin")
    await callback.answer()
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())


@router.callback_query(F.data == "back_admin")
async def back_admin(callback: CallbackQuery):
    await callback.message.edit_text(
        "🔧 *Панель администратора*",
        parse_mode="Markdown",
        reply_markup=admin_keyboard()
    )
    await callback.answer()
