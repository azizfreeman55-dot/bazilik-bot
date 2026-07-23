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
    "breakfast": {"ru": "🌅 Завтраки",      "uz": "🌅 Nonushtalar"},
    "first":   {"ru": "🍲 Первые блюда",   "uz": "🍲 Birinchi taomlar"},
    "main":    {"ru": "🍛 Вторые блюда",   "uz": "🍛 Ikkinchi taomlar"},
    "second":  {"ru": "🍱 Сеты",            "uz": "🍱 Setlar"},
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
    # Универсальные состояния — используются и для постоянного меню (по дню недели),
    # и для редкого разового меню (на конкретную дату). Различаются полем mode в FSM data.
    waiting_category = State()
    waiting_photo = State()
    waiting_name = State()
    waiting_price = State()
    waiting_more = State()


class Broadcast(StatesGroup):
    waiting_message = State()


# ─── Главный экран меню — 7 дней недели со статусами ─────────────────────────

@router.callback_query(F.data == "admin_add_menu")
async def admin_menu_home(callback: CallbackQuery):
    """
    Главный и единственный вход в управление меню.
    Показывает 7 дней недели с пометкой что заполнено / что пусто.
    Это заменяет старое разделение на 'меню на дату' и 'постоянное меню' —
    теперь админ работает только с днями недели, что просто и понятно.
    """
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    summary = await get_all_weekly_menu_summary()

    builder = InlineKeyboardBuilder()
    for day_num, info in summary.items():
        cats = info["categories"]
        if cats:
            icons = ""
            if "breakfast" in cats: icons += "🌅"
            if "first" in cats: icons += "🍲"
            if "main" in cats: icons += "🍛"
            if "second" in cats: icons += "🍱"
            if "salad" in cats: icons += "🥗"
            if "dessert" in cats: icons += "🍰"
            if "drink" in cats: icons += "🥤"
            label = f"✅ {info['day']} {icons}"
        else:
            label = f"⚠️ {info['day']}"
        builder.button(text=label, callback_data=f"menuday_{day_num}")
    builder.adjust(2)

    builder.button(text="📌 Особое меню на дату (праздник/акция)", callback_data="menu_special_date")
    builder.button(text="◀️ Назад", callback_data="back_admin")
    builder.adjust(2, 2, 2, 1, 1, 1)

    await callback.answer()
    await callback.message.edit_text(
        "🍽️ *Управление меню*\n\n"
        "✅ — день заполнен\n"
        "⚠️ — меню пустое, нужно заполнить\n\n"
        "Нажмите на день недели, чтобы посмотреть или изменить меню. "
        "Это меню повторяется автоматически каждую неделю.",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("menuday_"))
async def menu_day_detail(callback: CallbackQuery):
    """Детали конкретного дня — что заполнено, кнопки редактирования по категориям"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    day_num = int(callback.data.replace("menuday_", ""))
    day_name = DAYS_RU[day_num]

    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            """SELECT category, COUNT(*) as cnt FROM weekly_menu
               WHERE day_of_week = $1 AND is_active = 1
               GROUP BY category""",
            day_num
        )
    filled_cats = {r["category"]: r["cnt"] for r in rows}

    text = f"📅 *{day_name}*\n\n"
    builder = InlineKeyboardBuilder()
    for key, names in CATEGORIES.items():
        cnt = filled_cats.get(key)
        if cnt:
            text += f"✅ {names['ru']}: {cnt} позиций\n"
            builder.button(text=f"📋 {names['ru']}", callback_data=f"menylist_{day_num}_{key}")
        else:
            text += f"⚠️ {names['ru']}: пусто\n"
            builder.button(text=f"➕ {names['ru']}", callback_data=f"menyedit_{day_num}_{key}")
    builder.adjust(1)

    if filled_cats:
        builder.button(text="📋 Скопировать на все дни", callback_data=f"menycopyall_{day_num}")
        builder.button(text="🗑 Очистить весь день", callback_data=f"menyclear_{day_num}")
    builder.button(text="◀️ Назад к дням", callback_data="admin_add_menu")
    builder.adjust(1, 1, 1, 1, 1, 1)

    await callback.answer()
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("menycopyall_"))
async def menu_copy_to_all_days(callback: CallbackQuery):
    """Копирует меню одного дня на все остальные 6 дней недели"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    src_day = int(callback.data.replace("menycopyall_", ""))
    src_day_name = DAYS_RU[src_day]

    # Подтверждение — чтобы не скопировать случайно
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, скопировать на все 7 дней", callback_data=f"menycopyconfirm_{src_day}")
    builder.button(text="◀️ Отмена", callback_data=f"menuday_{src_day}")
    builder.adjust(1)

    await callback.answer()
    await callback.message.edit_text(
        f"📋 Скопировать меню *{src_day_name}* на все остальные дни недели?\n\n"
        f"⚠️ Существующее меню в других днях будет *заменено*.",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("menycopyconfirm_"))
async def menu_copy_confirm(callback: CallbackQuery):
    """Выполняет копирование меню на все дни"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    src_day = int(callback.data.replace("menycopyconfirm_", ""))

    pool = await get_pool()
    async with pool.acquire() as db:
        # Берём все позиции исходного дня
        src_items = await db.fetch(
            """SELECT item_number, name, description, price, photo_id, category
               FROM weekly_menu WHERE day_of_week = $1 AND is_active = 1
               ORDER BY category, item_number""",
            src_day
        )

        if not src_items:
            await callback.answer("⚠️ Исходный день пустой!", show_alert=True)
            return

        copied_days = 0
        for target_day in range(7):
            if target_day == src_day:
                continue
            # Удаляем старое меню целевого дня
            await db.execute(
                "DELETE FROM weekly_menu WHERE day_of_week = $1", target_day
            )
            # Копируем позиции
            for item in src_items:
                await db.execute(
                    """INSERT INTO weekly_menu
                       (day_of_week, item_number, name, description, price, photo_id, category)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                    target_day, item["item_number"], item["name"],
                    item["description"] or "", item["price"],
                    item["photo_id"], item["category"]
                )
            copied_days += 1

    src_day_name = DAYS_RU[src_day]
    await callback.answer(f"✅ Скопировано на {copied_days} дней!", show_alert=True)

    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ К управлению меню", callback_data="admin_add_menu")
    await callback.message.edit_text(
        f"✅ *Готово!*\n\n"
        f"Меню *{src_day_name}* скопировано на все остальные {copied_days} дней недели.\n\n"
        f"Теперь у вас одинаковое меню на каждый день.",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("menylist_"))
async def menu_category_list(callback: CallbackQuery):
    """Показывает список отдельных позиций категории — можно отредактировать каждую точечно"""
    parts = callback.data.replace("menylist_", "").split("_")
    day_num = int(parts[0])
    category = parts[1]
    day_name = DAYS_RU[day_num]
    cat_name = CATEGORIES[category]["ru"]

    pool = await get_pool()
    async with pool.acquire() as db:
        items = await db.fetch(
            """SELECT id, item_number, name, price FROM weekly_menu
               WHERE day_of_week = $1 AND category = $2 AND is_active = 1
               ORDER BY item_number""",
            day_num, category
        )

    text = f"📅 *{day_name} — {cat_name}*\n\nНажмите на позицию чтобы изменить:\n\n"
    builder = InlineKeyboardBuilder()
    for item in items:
        text += f"{item['item_number']}. {item['name']} — {item['price']:,} сум\n"
        builder.button(
            text=f"✏️ {item['item_number']}. {item['name']}",
            callback_data=f"itemedit_{item['id']}_{day_num}_{category}"
        )
    builder.adjust(1)

    builder.button(text="➕ Добавить новую позицию", callback_data=f"menyaddone_{day_num}_{category}")
    builder.button(text="🔄 Переписать всю категорию", callback_data=f"menyedit_{day_num}_{category}")
    builder.button(text="◀️ Назад", callback_data=f"menuday_{day_num}")
    builder.adjust(1, 1, 1, 1)

    await callback.answer()
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())


class EditItem(StatesGroup):
    waiting_field = State()
    waiting_new_name = State()
    waiting_new_price = State()
    waiting_new_photo = State()


@router.callback_query(F.data.startswith("itemedit_"))
async def item_edit_menu(callback: CallbackQuery, state: FSMContext):
    """Меню редактирования одной позиции — выбор что менять"""
    parts = callback.data.replace("itemedit_", "").split("_")
    item_id = int(parts[0])
    day_num = int(parts[1])
    category = parts[2]

    pool = await get_pool()
    async with pool.acquire() as db:
        item = await db.fetchrow("SELECT * FROM weekly_menu WHERE id = $1", item_id)

    if not item:
        await callback.answer("❌ Позиция не найдена", show_alert=True)
        return

    await state.update_data(edit_item_id=item_id, edit_day=day_num, edit_category=category)

    text = (
        f"✏️ *Редактирование позиции*\n\n"
        f"№{item['item_number']}. {item['name']}\n"
        f"💰 {item['price']:,} сум\n"
        f"📸 {'Фото есть' if item['photo_id'] else 'Без фото'}\n\n"
        f"Что изменить?"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Название", callback_data="itemfield_name")
    builder.button(text="💰 Цену", callback_data="itemfield_price")
    builder.button(text="📸 Фото", callback_data="itemfield_photo")
    builder.button(text="🗑 Удалить позицию", callback_data="itemfield_delete")
    builder.button(text="◀️ Назад", callback_data=f"menylist_{day_num}_{category}")
    builder.adjust(1)

    await callback.answer()
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())


@router.callback_query(F.data == "itemfield_name")
async def item_edit_name_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditItem.waiting_new_name)
    await callback.answer()
    await callback.message.answer("📝 Введите новое *название* позиции:", parse_mode="Markdown")


@router.message(EditItem.waiting_new_name)
async def item_edit_name_save(message: Message, state: FSMContext):
    if message.text and message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Редактирование отменено.")
        return

    new_name = message.text.strip() if message.text else ""
    if not new_name:
        await message.answer("❌ Отправьте текстовое название")
        return

    data = await state.get_data()
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE weekly_menu SET name = $1 WHERE id = $2",
            new_name, data["edit_item_id"]
        )
    await state.clear()
    await message.answer(f"✅ Название изменено на: *{new_name}*", parse_mode="Markdown", reply_markup=admin_keyboard())


@router.callback_query(F.data == "itemfield_price")
async def item_edit_price_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditItem.waiting_new_price)
    await callback.answer()
    await callback.message.answer("💰 Введите новую *цену* (сум):", parse_mode="Markdown")


@router.message(EditItem.waiting_new_price)
async def item_edit_price_save(message: Message, state: FSMContext):
    if message.text and message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Редактирование отменено.")
        return

    text = message.text.strip().replace(" ", "").replace(",", "")
    try:
        price = int(text)
    except ValueError:
        await message.answer("❌ Введите число. Например: 25000")
        return

    data = await state.get_data()
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE weekly_menu SET price = $1 WHERE id = $2",
            price, data["edit_item_id"]
        )
    await state.clear()
    await message.answer(f"✅ Цена изменена на: *{price:,} сум*", parse_mode="Markdown", reply_markup=admin_keyboard())


@router.callback_query(F.data == "itemfield_photo")
async def item_edit_photo_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditItem.waiting_new_photo)
    await callback.answer()
    await callback.message.answer("📸 Отправьте новое фото для этой позиции:")


@router.message(EditItem.waiting_new_photo, F.photo)
async def item_edit_photo_save(message: Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    data = await state.get_data()
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE weekly_menu SET photo_id = $1 WHERE id = $2",
            photo_id, data["edit_item_id"]
        )
    await state.clear()
    await message.answer("✅ Фото обновлено", reply_markup=admin_keyboard())


@router.message(EditItem.waiting_new_photo)
async def item_edit_photo_invalid(message: Message):
    if message.text and message.text.startswith("/"):
        return
    await message.answer("❌ Отправьте именно фото (изображение)")


@router.callback_query(F.data == "itemfield_delete")
async def item_delete_confirm(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, удалить", callback_data="itemfield_delete_confirm")
    builder.button(text="◀️ Отмена", callback_data=f"itemedit_{data['edit_item_id']}_{data['edit_day']}_{data['edit_category']}")
    builder.adjust(2)
    await callback.answer()
    await callback.message.edit_text("❓ Удалить эту позицию из меню?", reply_markup=builder.as_markup())


@router.callback_query(F.data == "itemfield_delete_confirm")
async def item_delete_execute(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute("DELETE FROM weekly_menu WHERE id = $1", data["edit_item_id"])
    day_num = data["edit_day"]
    category = data["edit_category"]
    await state.clear()
    await callback.answer("✅ Позиция удалена")

    # Возвращаемся к списку позиций категории
    callback.data = f"menylist_{day_num}_{category}"
    await menu_category_list(callback)


@router.callback_query(F.data.startswith("menyaddone_"))
async def menu_add_one_item(callback: CallbackQuery, state: FSMContext):
    """Добавить одну новую позицию в категорию без переписывания остальных"""
    parts = callback.data.replace("menyaddone_", "").split("_")
    day_num = int(parts[0])
    category = parts[1]

    pool = await get_pool()
    async with pool.acquire() as db:
        max_num = await db.fetchval(
            "SELECT MAX(item_number) FROM weekly_menu WHERE day_of_week = $1 AND category = $2",
            day_num, category
        )
    next_num = (max_num or 0) + 1

    await state.update_data(
        mode="weekly_single", weekly_day=day_num, category=category,
        item_number=next_num
    )
    await state.set_state(AddMenu.waiting_photo)

    cat_name = CATEGORIES[category]["ru"]
    await callback.answer()
    await callback.message.answer(
        f"➕ *Новая позиция {next_num} в категории {cat_name}*\n\n"
        f"📸 Отправьте фото или напишите *нет*:",
        parse_mode="Markdown"
    )


@router.callback_query(F.data.startswith("menyedit_"))
async def menu_day_edit_category(callback: CallbackQuery, state: FSMContext):
    """Начинаем заполнение конкретной категории для дня недели — спрашиваем хотят
    ли заменить существующее (если есть) или добавить."""
    parts = callback.data.replace("menyedit_", "").split("_")
    day_num = int(parts[0])
    category = parts[1]
    day_name = DAYS_RU[day_num]
    cat_name = CATEGORIES[category]["ru"]

    await state.update_data(
        mode="weekly", weekly_day=day_num, category=category, items=[], item_number=1
    )
    await state.set_state(AddMenu.waiting_photo)

    await callback.answer()
    await callback.message.edit_text(
        f"📅 *{day_name} — {cat_name}*\n\n"
        f"_Старые позиции в этой категории будут заменены новыми._\n\n"
        f"*Позиция 1:*\n📸 Отправьте фото или напишите *нет*:",
        parse_mode="Markdown"
    )


@router.callback_query(F.data.startswith("menyclear_") & ~F.data.startswith("menyclear_confirm_"))
async def menu_day_clear_confirm(callback: CallbackQuery):
    day_num = int(callback.data.replace("menyclear_", ""))
    day_name = DAYS_RU[day_num]

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, очистить", callback_data=f"menyclear_confirm_{day_num}")
    builder.button(text="◀️ Отмена", callback_data=f"menuday_{day_num}")
    builder.adjust(2)

    await callback.answer()
    await callback.message.edit_text(
        f"❓ Удалить всё меню для *{day_name}* (все категории)?",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("menyclear_confirm_"))
async def menu_day_clear_execute(callback: CallbackQuery):
    day_num = int(callback.data.replace("menyclear_confirm_", ""))
    day_name = DAYS_RU[day_num]
    await delete_weekly_menu_day(day_num)
    await callback.answer("✅ Меню очищено")
    await menu_day_detail(callback)


# ─── Заполнение позиций (используется и для дня недели, и для разовой даты) ──

@router.message(AddMenu.waiting_photo)
async def process_menu_photo(message: Message, state: FSMContext):
    if message.text and message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Добавление меню отменено командой.")
        return

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
    if message.text and message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Добавление меню отменено командой.")
        return

    name = message.text.strip() if message.text else ""
    if not name:
        await message.answer("❌ Отправьте текстовое название позиции")
        return

    await state.update_data(current_name=name)
    await state.set_state(AddMenu.waiting_price)
    data = await state.get_data()
    cat = data.get("category", "second")
    hints = {"first": "20 000", "second": "35 000", "salad": "15 000", "dessert": "12 000", "drink": "8 000"}
    hint = hints.get(cat, "35 000")
    await message.answer(
        f"💰 Введите *цену* (сум):\n_(стандарт = {hint} сум — напишите 'стандарт')_",
        parse_mode="Markdown"
    )


@router.message(AddMenu.waiting_price)
async def process_menu_price(message: Message, state: FSMContext):
    if message.text and message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Добавление меню отменено командой.")
        return

    text = message.text.strip().lower()
    data = await state.get_data()
    cat = data.get("category", "second")
    default_prices = {"first": 20000, "second": 35000, "salad": 15000, "dessert": 12000, "drink": 8000}

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
    builder.button(text="✅ Сохранить", callback_data="menu_save")
    builder.adjust(1)

    await message.answer(
        f"✅ *Добавлено в {cat_name}:*\n"
        f"• {data['current_name']} — {price:,} сум\n\n"
        f"Всего позиций: {len(items)}\n\nЧто дальше?",
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
    category = data.get("category", "second")
    cat_name = CATEGORIES.get(category, {}).get("ru", category)
    mode = data.get("mode", "weekly")

    if mode == "weekly_single":
        # Добавление ОДНОЙ позиции к существующим, без удаления остальных
        day = data["weekly_day"]
        pool = await get_pool()
        async with pool.acquire() as db:
            for item in items:
                await db.execute(
                    """INSERT INTO weekly_menu
                       (day_of_week, item_number, name, description, price, photo_id, category)
                       VALUES ($1, $2, $3, '', $4, $5, $6)""",
                    day, item["item_number"], item["name"],
                    item["price"], item.get("photo_id"), category
                )
        day_name = DAYS_RU[day]
        header = f"✅ *Позиция добавлена в {cat_name} на {day_name}!*\n\n"
    elif mode == "weekly":
        day = data["weekly_day"]
        await set_weekly_menu(day, items, category)
        day_name = DAYS_RU[day]
        header = f"✅ *{cat_name} на {day_name} сохранены!*\n\n"
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


# ─── Разовое "особое" меню на конкретную дату (праздник/акция) ──────────────

@router.callback_query(F.data == "menu_special_date")
async def menu_special_date_start(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    today = date.today()
    for i in range(7):
        d = today + timedelta(days=i)
        label = "Сегодня" if i == 0 else "Завтра" if i == 1 else DAYS_RU[d.weekday()]
        builder.button(text=f"📅 {label} ({d.strftime('%d.%m')})", callback_data=f"specialdate_{d}")
    builder.button(text="◀️ Назад", callback_data="admin_add_menu")
    builder.adjust(2)

    await callback.answer()
    await callback.message.edit_text(
        "📌 *Особое меню на конкретную дату*\n\n"
        "Используйте для праздников, акций или временной замены обычного меню "
        "на этот один день. В остальные дни будет работать постоянное меню.",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("specialdate_"))
async def menu_special_date_category(callback: CallbackQuery, state: FSMContext):
    menu_date = callback.data.replace("specialdate_", "")
    await state.update_data(mode="date", menu_date=menu_date, items=[], item_number=1)
    await state.set_state(AddMenu.waiting_category)

    builder = InlineKeyboardBuilder()
    for key, names in CATEGORIES.items():
        builder.button(text=names["ru"], callback_data=f"menu_cat_{key}")
    builder.adjust(2)

    await callback.answer()
    await callback.message.edit_text(
        f"📅 *Особое меню на {menu_date}*\n\nВыберите категорию:",
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


# ─── Сводка заказов ───────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_summary")
async def admin_summary(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    # Получаем сегодняшнюю дату
    today = str(date.today())
    summary = await get_daily_summary(today)

    if not summary["items"]:
        await callback.answer()
        await callback.message.edit_text(
            f"📊 Сводка на сегодня — {today}\n\nЗаказов пока нет",
            reply_markup=admin_keyboard()
        )
        return

    text = f"📊 *Сводка заказов на сегодня — {today}:*\n\n"

    by_category = {}

    for item in summary["items"]:
        cat = item.get("category", "second")
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
        text,
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
