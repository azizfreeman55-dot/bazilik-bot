from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import date, timedelta
from database.db import get_pool
from config import ADMIN_IDS
from aiogram.fsm.context import FSMContext

router = Router()


async def get_analytics() -> dict:
    pool = await get_pool()
    async with pool.acquire() as db:
        general = await db.fetchrow(
            "SELECT COUNT(*) as total_users, SUM(total_orders) as total_orders_all FROM users"
        )
        tomorrow = str(date.today() + timedelta(days=1))
        today_orders = await db.fetchrow(
            "SELECT COUNT(*) as count, COUNT(*) * 35000 as revenue FROM orders WHERE order_date = $1 AND status != 'cancelled'",
            tomorrow
        )
        month_stats = await db.fetchrow(
            "SELECT COUNT(*) as orders, COUNT(*) * 35000 as revenue FROM orders WHERE status != 'cancelled'"
        )
        top_meals = await db.fetch(
            """SELECT m.name, COUNT(*) as count FROM orders o
               JOIN menus m ON o.menu_id = m.id
               WHERE o.status != 'cancelled'
               GROUP BY m.name ORDER BY count DESC LIMIT 3"""
        )
        top_companies = await db.fetch(
            """SELECT c.name, COUNT(*) as count FROM orders o
               JOIN users u ON o.user_id = u.id
               JOIN companies c ON u.company_id = c.id
               WHERE o.status != 'cancelled'
               GROUP BY c.name ORDER BY count DESC LIMIT 5"""
        )
    return {
        "general": dict(general),
        "today": dict(today_orders),
        "month": dict(month_stats),
        "top_meals": [dict(r) for r in top_meals],
        "top_companies": [dict(r) for r in top_companies]
    }


async def get_delivery_routes() -> list:
    tomorrow = str(date.today() + timedelta(days=1))
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            """SELECT c.name as company, COUNT(*) as count,
               COALESCE(c.maps_link, '') as maps_link
               FROM orders o
               JOIN users u ON o.user_id = u.id
               JOIN companies c ON u.company_id = c.id
               WHERE o.order_date = $1 AND o.status != 'cancelled'
               GROUP BY c.id, c.name, c.maps_link ORDER BY count DESC""",
            tomorrow
        )
        return [dict(r) for r in rows]


def analytics_keyboard() -> object:
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Общая статистика", callback_data="analytics_general")
    builder.button(text="🍽️ Топ блюда", callback_data="analytics_meals")
    builder.button(text="💰 Выручка", callback_data="analytics_revenue")
    builder.button(text="🚚 Маршруты доставки", callback_data="analytics_routes")
    builder.adjust(2)
    return builder.as_markup()


@router.message(F.text.in_({"🖥️ Админ панель", "🖥️ Admin panel"}))
async def admin_panel_updated(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Сводка заказов", callback_data="admin_summary")
    builder.button(text="🍽️ Добавить меню", callback_data="admin_add_menu")
    builder.button(text="📨 Рассылка", callback_data="admin_broadcast")
    builder.button(text="👥 Все пользователи", callback_data="admin_users")
    builder.button(text="📈 Аналитика", callback_data="analytics_main")
    builder.button(text="🚚 Маршруты", callback_data="analytics_routes")
    builder.button(text="🎁 Фото подарков", callback_data="admin_gift_photos")
    builder.adjust(2)
    await message.answer(
        "🔧 *Панель администратора*",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data == "analytics_main")
async def analytics_main(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await callback.message.edit_text(
        "📈 *Аналитика*\n\nВыберите раздел:",
        parse_mode="Markdown",
        reply_markup=analytics_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "analytics_general")
async def analytics_general(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    data = await get_analytics()
    g = data["general"]
    t = data["today"]
    text = (
        f"📊 *Общая статистика*\n\n"
        f"👥 Всего пользователей: *{g['total_users']}*\n"
        f"📦 Всего заказов: *{g['total_orders_all'] or 0}*\n\n"
        f"📦 Заказов на завтра: *{t['count']}*\n"
        f"💰 Выручка завтра: *{t['revenue']:,} сум*"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data="analytics_main")
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "analytics_meals")
async def analytics_meals(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    data = await get_analytics()
    medals = ["🥇", "🥈", "🥉"]
    text = "🍽️ *Топ популярных блюд:*\n\n"
    for i, meal in enumerate(data["top_meals"]):
        text += f"{medals[i]} {meal['name']} — {meal['count']} заказов\n"
    if not data["top_meals"]:
        text += "Данных пока нет"
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data="analytics_main")
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "analytics_revenue")
async def analytics_revenue(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    data = await get_analytics()
    m = data["month"]
    t = data["today"]
    text = (
        f"💰 *Финансовая статистика*\n\n"
        f"📦 Всего заказов: *{m['orders']}*\n"
        f"💰 Общая выручка: *{m['revenue']:,} сум*\n\n"
        f"📆 Завтра (прогноз):\n"
        f"• Заказов: *{t['count']}*\n"
        f"• Выручка: *{t['revenue']:,} сум*\n\n"
        f"🏢 *Топ компании:*\n"
    )
    medals = ["🥇", "🥈", "🥉", "4.", "5."]
    for i, c in enumerate(data["top_companies"]):
        text += f"{medals[i]} {c['name']} — {c['count']} заказов\n"
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data="analytics_main")
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "analytics_routes")
async def analytics_routes(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    routes = await get_delivery_routes()
    tomorrow = str(date.today() + timedelta(days=1))
    if not routes:
        text = f"🚚 *Маршруты на {tomorrow}*\n\nЗаказов пока нет"
    else:
        text = f"🚚 *Маршруты доставки на {tomorrow}*\n\n"
        total = 0
        for i, r in enumerate(routes, 1):
            text += f"{i}. *{r['company']}* — {r['count']} обедов\n"
            if r.get("maps_link"):
                text += f"   🗺 [Открыть карту]({r['maps_link']})\n\n"
            total += r["count"]
        text += f"📦 Итого: *{total} обедов*\n⏰ Доставка: 12:00 – 13:00"
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data="analytics_main")
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())
    await callback.answer()
@router.callback_query(F.data == "admin_gift_photos")
async def admin_gift_photos(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    gifts = [
        ("drink", "🥤 Напиток"),
        ("dessert", "🍰 Десерт"),
        ("lunch", "🍱 Бесплатный обед"),
        ("vip", "👑 VIP статус"),
    ]
    for gift_id, name in gifts:
        builder.button(text=f"📸 {name}", callback_data=f"set_gift_photo_{gift_id}")
    builder.button(text="◀️ Назад", callback_data="back_admin")
    builder.adjust(1)

    await callback.message.edit_text(
        "🎁 *Фото подарков*\n\nВыберите подарок чтобы загрузить фото:",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_gift_photo_"))
async def set_gift_photo_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    gift_id = callback.data.replace("set_gift_photo_", "")
    await state.update_data(gift_id=gift_id)

    names = {
        "drink": "Напиток 🥤",
        "dessert": "Десерт 🍰",
        "lunch": "Бесплатный обед 🍱",
        "vip": "VIP статус 👑"
    }
    await callback.message.answer(
        f"📸 Отправьте фото для *{names.get(gift_id, gift_id)}*:",
        parse_mode="Markdown"
    )
    await state.set_state("waiting_gift_photo")
    await callback.answer()


@router.message(F.photo)
async def save_gift_photo(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    current_state = await state.get_state()
    if current_state != "waiting_gift_photo":
        return

    data = await state.get_data()
    gift_id = data.get("gift_id")
    if not gift_id:
        return

    photo_id = message.photo[-1].file_id
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS gift_photos (
                gift_id TEXT PRIMARY KEY,
                photo_id TEXT
            )
        """)
        await db.execute(
            """INSERT INTO gift_photos (gift_id, photo_id)
               VALUES ($1, $2)
               ON CONFLICT (gift_id) DO UPDATE SET photo_id = $2""",
            gift_id, photo_id
        )

    await state.clear()
    names = {
        "drink": "Напиток 🥤",
        "dessert": "Десерт 🍰",
        "lunch": "Бесплатный обед 🍱",
        "vip": "VIP статус 👑"
    }
    await message.answer(
        f"✅ Фото для *{names.get(gift_id, gift_id)}* сохранено!",
        parse_mode="Markdown"
    )
