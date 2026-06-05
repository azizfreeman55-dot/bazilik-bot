from datetime import date, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Filter

from database.db import (
    get_daily_summary, set_menu, get_all_users_for_notification,
    close_orders_for_date
)
from keyboards.keyboards import admin_keyboard
from config import ADMIN_IDS

router = Router()


class IsAdmin(Filter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user.id in ADMIN_IDS


class AddMenu(StatesGroup):
    waiting_date = State()
    waiting_photo = State()
    waiting_name = State()
    waiting_price = State()
    waiting_more = State()


class Broadcast(StatesGroup):
    waiting_message = State()


@router.message(IsAdmin(), F.text == "🖥️ Админ панель")
async def admin_panel(message: Message):
    await message.answer(
        "🔧 *Панель администратора*\n\n"
        "Управление ботом и заказами:",
        parse_mode="Markdown",
        reply_markup=admin_keyboard()
    )


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
            f"📊 Сводка на {tomorrow}\n\n"
            "Заказов пока нет или они не подтверждены",
            reply_markup=admin_keyboard()
        )
        return

    text = f"📊 *Сводка заказов на {tomorrow}:*\n\n"
    for item in summary["items"]:
        text += f"• {item['name']}: *{item['count']} порций*\n"
    text += f"\n📦 Всего: *{summary['total']} обедов*"

    await callback.answer()
    await callback.message.edit_text(
        text, parse_mode="Markdown", reply_markup=admin_keyboard()
    )


@router.callback_query(F.data == "admin_add_menu")
async def admin_add_menu_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from datetime import timedelta
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
    await state.set_state(AddMenu.waiting_photo)
    await state.update_data(menu_date=menu_date, items=[], item_number=1)
    await callback.answer()
    await callback.message.answer(
        f"🍽️ *Добавление меню на {menu_date}*\n\n"
        f"*Блюдо 1:*\n"
        "📸 Отправьте фото блюда:\n"
        "_(или напишите 'нет' если фото нет)_",
        parse_mode="Markdown"
    )


@router.message(AddMenu.waiting_photo)
async def process_menu_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    
    if message.photo:
        photo_id = message.photo[-1].file_id
    else:
        photo_id = None

    await state.update_data(current_photo=photo_id)
    await state.set_state(AddMenu.waiting_name)
    await message.answer(
        f"✅ Фото принято!\n\n"
        f"📝 Введите *название блюда {data['item_number']}*:\n"
        f"Например: _Плов с говядиной + салат + хлеб_",
        parse_mode="Markdown"
    )


@router.message(AddMenu.waiting_name)
async def process_menu_name(message: Message, state: FSMContext):
    await state.update_data(current_name=message.text.strip())
    await state.set_state(AddMenu.waiting_price)
    await message.answer(
        f"💰 Введите *цену* (в сумах):\n"
        f"Например: _35000_\n\n"
        f"_(или напишите 'стандарт' для цены 35000 сум)_",
        parse_mode="Markdown"
    )


@router.message(AddMenu.waiting_price)
async def process_menu_price(message: Message, state: FSMContext):
    text = message.text.strip()
    if text.lower() == "стандарт":
        price = 35000
    else:
        try:
            price = int(text.replace(" ", "").replace(",", ""))
        except:
            await message.answer("❌ Введите число. Например: 35000")
            return

    data = await state.get_data()
    items = data.get("items", [])
    items.append({
        "item_number": data["item_number"],
        "name": data["current_name"],
        "price": price,
        "photo_id": data.get("current_photo")
    })
    await state.update_data(items=items)
    await state.set_state(AddMenu.waiting_more)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить ещё блюдо", callback_data="menu_add_more")
    builder.button(text="✅ Сохранить меню", callback_data="menu_save")
    builder.adjust(1)

    await message.answer(
        f"✅ *Блюдо {data['item_number']} добавлено:*\n"
        f"🍱 {data['current_name']}\n"
        f"💰 {price:,} сум\n\n"
        f"Добавить ещё блюдо или сохранить меню?",
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
        f"*Блюдо {next_num}:*\n"
        f"📸 Отправьте фото блюда:\n"
        f"_(или напишите 'нет' если фото нет)_",
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "menu_save")
async def menu_save(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    menu_date = data["menu_date"]
    items = data["items"]

    # Сохраняем в БД с photo_id
    import aiosqlite
    from config import DATABASE_URL
    async with aiosqlite.connect(DATABASE_URL) as db:
        await db.execute("DELETE FROM menus WHERE menu_date = ?", (menu_date,))
        for item in items:
            try:
                await db.execute("ALTER TABLE menus ADD COLUMN photo_id TEXT")
                await db.commit()
            except:
                pass
            await db.execute(
                """INSERT INTO menus (menu_date, item_number, name, price, photo_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (menu_date, item["item_number"], item["name"],
                 item["price"], item.get("photo_id"))
            )
        await db.commit()

    await state.clear()
    text = f"✅ *Меню на {menu_date} сохранено!*\n\n"
    for item in items:
        photo_text = "📸 с фото" if item.get("photo_id") else "без фото"
        text += f"{item['item_number']}. {item['name']} — {item['price']:,} сум ({photo_text})\n"

    await callback.answer()
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=admin_keyboard())


@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    await state.set_state(Broadcast.waiting_message)
    await callback.answer()
    await callback.message.answer(
        "📨 Введите сообщение для рассылки всем пользователям:"
    )


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
        f"✅ Рассылка завершена!\n"
        f"• Успешно: {success}\n"
        f"• Ошибок: {failed}",
        reply_markup=admin_keyboard()
    )


@router.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    import aiosqlite
    from config import DATABASE_URL
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT u.full_name, u.phone, u.total_orders, u.points,
            u.status, u.streak_days, u.created_at,
            c.name as company_name,
            COALESCE(c.address, 'Не указан') as address
            FROM users u
            LEFT JOIN companies c ON u.company_id = c.id
            ORDER BY u.total_orders DESC
        """) as cursor:
            users = [dict(r) for r in await cursor.fetchall()]

    if not users:
        await callback.answer()
        await callback.message.edit_text("👥 Пользователей пока нет", reply_markup=admin_keyboard())
        return

    text = f"👥 *Все пользователи ({len(users)} чел.)*\n\n"
    for i, u in enumerate(users, 1):
        phone = f"+{u['phone']}" if u.get('phone') else "Не указан"
        text += (
            f"{i}. *{u['full_name']}*\n"
            f"   📱 {phone}\n"
            f"   🏢 {u.get('company_name') or 'Не указана'}\n"
            f"   📍 {u['address']}\n"
            f"   📦 Заказов: {u['total_orders']} | 💰 {u['points']} баллов\n"
            f"   🏅 {u['status']} | 🔥 {u['streak_days']} дней подряд\n\n"
        )

    # Telegram ограничение 4096 символов
    if len(text) > 4000:
        text = text[:4000] + "\n...и другие"

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data="back_admin")
    await callback.answer()
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())


@router.callback_query(F.data == "back_admin")
async def back_admin(callback: CallbackQuery):
    await callback.message.edit_text("🔧 *Панель администратора*", parse_mode="Markdown", reply_markup=admin_keyboard())
    await callback.answer()
