from datetime import date, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Filter
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.db import (
    get_daily_summary, get_all_users_for_notification,
    close_orders_for_date, get_pool, set_menu,
    set_weekly_menu, get_all_weekly_menu_summary,
    delete_weekly_menu_day, get_weekly_menu_categories
)
from keyboards.keyboards import admin_keyboard
from config import ADMIN_IDS

router = Router()

CATEGORIES = {
    "main":    {"ru": "🍱 Основные блюда",  "uz": "🍱 Asosiy taomlar"},
    "salad":   {"ru": "🥗 Салаты",           "uz": "🥗 Salatlar"},
    "dessert": {"ru": "🍰 Десерты",          "uz": "🍰 Desertlar"},
    "drink":   {"ru": "🥤 Напитки",          "uz": "🥤 Ichimliklar"},
}

DAYS_RU = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
DAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


class IsAdmin(Filter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user.id in ADMIN_IDS


class AddMenu(StatesGroup):
    # Разовое меню по дате
    waiting_category = State()
    waiting_photo = State()
    waiting_name = State()
    waiting_price = State()
    waiting_more = State()
    # Постоянное меню по дням недели
    waiting_weekly_day = State()
    waiting_weekly_category = State()
    waiting_weekly_photo = State()
    waiting_weekly_name = State()
    waiting_weekly_price = State()
    waiting_weekly_more = State()


class Broadcast(StatesGroup):
    waiting_message = State()


# ─── Сводка заказов ───────────────────────────────────────────────────────────

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


# ─── Разовое меню по дате ─────────────────────────────────────────────────────

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
        "🍽️ *Добавление меню на конкретную дату*\n\nВыберите день:",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("menu_date_"))
async def admin_menu_date_selected(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    menu_date = callback.data.replace("menu_date_", "")
    await state.update_data(menu_date=menu_date, items=[], item_number=1, mode="date")
    await state.set_state(AddMenu.waiting_category)

    builder = InlineKeyboardBuilder()
    for key, names in CATEGORIES.items():
        builder.button(text=names["ru"], callback_data=f"menu_cat_{key}")
    builder.adjust(2)

    await callback.answer()
    await callback.message.edit_text(
        f"📅 *Дата: {menu_date}*\n\nВыберите категорию:",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("menu_cat_"), AddMenu.waiting_category)
async def admin_category_selected(callback: CallbackQuery, state: FSMContext):
    category = callback.data.replace("menu_cat_", "")
    cat_name = CATEGORIES.get(category, {}).get("ru", category)
    await state.update_data(category=category, items=[], item_number=1)
    await state.set_state(AddMenu.waiting_photo)
    await callback.answer()
    await callback.message.answer(
        f"*Категория: {cat_name}*\n\n*Позиция 1:*\n📸 Отправьте фото или напишите *нет*:",
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
    hints = {"main": "35 000", "salad": "15 000", "dessert": "12 000", "drink": "8 000"}
    hint = hints.get(cat, "35 000")
    await message.answer(
        f"💰 Введите *цену* (сум):\n_(стандарт = {hint} сум — напишите 'стандарт')_",
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
        f"Всего в категории: {len(items)} позиций\n\nЧто дальше?",
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
    items = data["items"]
    category = data.get("category", "main")
    cat_name = CATEGORIES.get(category, {}).get("ru", category)

    if data.get("mode") == "weekly":
        day = data["weekly_day"]
        await set_weekly_menu(day, items, category)
        day_name = DAYS_RU[day]
        header = f"✅ *{cat_name} на {day_name} сохранены как постоянное меню!*\n\n"
    else:
        menu_date = data["menu_date"]
        await set_menu(menu_date, items, category)
        header = f"✅ *{cat_name} на {menu_date} сохранены!*\n\n"

    await state.clear()
    text = header
    for item in items:
        photo_text = "📸" if item.get("photo_id") else "  "
        text += f"{photo_text} {item['item_number']}. {item['name']} — {item['price']:,} сум\n"

    await callback.answer()
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=admin_keyboard())


@router.callback_query(F.data == "menu_add_category")
async def menu_add_another_category(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    items = data["items"]
    category = data.get("category", "main")

    if data.get("mode") == "weekly":
        day = data["weekly_day"]
        await set_weekly_menu(day, items, category)
    else:
        menu_date = data["menu_date"]
        await set_menu(menu_date, items, category)

    await state.update_data(items=[], item_number=1)
    await state.set_state(AddMenu.waiting_category)

    builder = InlineKeyboardBuilder()
    for key, names in CATEGORIES.items():
        builder.button(text=names["ru"], callback_data=f"menu_cat_{key}")
    builder.button(text="✅ Всё готово", callback_data="menu_all_done")
    builder.adjust(2)

    await callback.answer()
    await callback.message.answer(
        "✅ Сохранено!\n\nВыберите следующую категорию:",
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


# ─── Постоянное меню по дням недели ──────────────────────────────────────────

@router.callback_query(F.data == "admin_weekly_menu")
async def admin_weekly_menu(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    summary = await get_all_weekly_menu_summary()

    builder = InlineKeyboardBuilder()
    for day_num, info in summary.items():
        cats = info["categories"]
        if cats:
            cat_icons = ""
            if "main" in cats: cat_icons += "🍱"
            if "salad" in cats: cat_icons += "🥗"
            if "dessert" in cats: cat_icons += "🍰"
            if "drink" in cats: cat_icons += "🥤"
            label = f"✅ {info['day']} {cat_icons}"
        else:
            label = f"➕ {info['day']}"
        builder.button(text=label, callback_data=f"weekly_day_{day_num}")
    builder.button(text="◀️ Назад", callback_data="back_admin")
    builder.adjust(2)

    await callback.answer()
    await callback.message.edit_text(
        "📅 *Постоянное меню по дням недели*\n\n"
        "✅ — меню настроено\n"
        "➕ — нажмите чтобы добавить\n\n"
        "Это меню автоматически показывается каждую неделю.\n"
        "Можно перекрыть разовым меню на конкретную дату.",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("weekly_day_"))
async def weekly_day_selected(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    day_num = int(callback.data.replace("weekly_day_", ""))
    day_name = DAYS_RU[day_num]

    # Показываем что уже есть + кнопки действий
    cats = await get_weekly_menu_categories(day_num)
    cat_text = ""
    if cats:
        icons = {"main": "🍱", "salad": "🥗", "dessert": "🍰", "drink": "🥤"}
        for c in cats:
            cat_text += f"  {icons.get(c,'')} {CATEGORIES.get(c,{}).get('ru', c)}\n"

    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить/изменить категорию", callback_data=f"weekly_add_{day_num}")
    if cats:
        builder.button(text="🗑 Удалить всё меню этого дня", callback_data=f"weekly_delete_{day_num}")
    builder.button(text="◀️ Назад", callback_data="admin_weekly_menu")
    builder.adjust(1)

    status = f"*Настроено:*\n{cat_text}" if cats else "_Меню не добавлено_"
    await callback.answer()
    await callback.message.edit_text(
        f"📅 *{day_name}*\n\n{status}",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("weekly_add_"))
async def weekly_add_category(callback: CallbackQuery, state: FSMContext):
    day_num = int(callback.data.replace("weekly_add_", ""))
    day_name = DAYS_RU[day_num]

    await state.update_data(
        weekly_day=day_num, items=[], item_number=1, mode="weekly"
    )
    await state.set_state(AddMenu.waiting_category)

    builder = InlineKeyboardBuilder()
    for key, names in CATEGORIES.items():
        builder.button(text=names["ru"], callback_data=f"menu_cat_{key}")
    builder.adjust(2)

    await callback.answer()
    await callback.message.edit_text(
        f"📅 *Постоянное меню — {day_name}*\n\nВыберите категорию:",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("weekly_delete_"))
async def weekly_delete_confirm(callback: CallbackQuery):
    day_num = int(callback.data.replace("weekly_delete_", ""))
    day_name = DAYS_RU[day_num]

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, удалить", callback_data=f"weekly_delete_confirm_{day_num}")
    builder.button(text="◀️ Отмена", callback_data=f"weekly_day_{day_num}")
    builder.adjust(2)

    await callback.answer()
    await callback.message.edit_text(
        f"❓ Удалить всё постоянное меню для *{day_name}*?",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("weekly_delete_confirm_"))
async def weekly_delete_execute(callback: CallbackQuery):
    day_num = int(callback.data.replace("weekly_delete_confirm_", ""))
    day_name = DAYS_RU[day_num]
    await delete_weekly_menu_day(day_num)
    await callback.answer()
    await callback.message.edit_text(
        f"✅ Постоянное меню для *{day_name}* удалено.",
        parse_mode="Markdown",
        reply_markup=admin_keyboard()
    )


# ─── Рассылка ─────────────────────────────────────────────────────────────────

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


# ─── Пользователи ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    pool = await get_pool()
    async with pool.acquire() as db:
        users = await db.fetch("""
            SELECT u.full_name, u.phone, u.total_orders, u.points,
            u.status, u.created_at, c.name as company_name
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
