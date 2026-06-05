from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import date, timedelta
import aiosqlite
from config import DATABASE_URL, ADMIN_IDS

router = Router()


async def get_analytics() -> dict:
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT COUNT(*) as total_users, SUM(total_orders) as total_orders_all FROM users"
        ) as c:
            general = dict(await c.fetchone())
        tomorrow = str(date.today() + timedelta(days=1))
        async with db.execute(
            "SELECT COUNT(*) as count, COUNT(*) * 35000 as revenue FROM orders WHERE order_date = ? AND status != 'cancelled'",
            (tomorrow,)
        ) as c:
            today_orders = dict(await c.fetchone())
        async with db.execute(
            "SELECT COUNT(*) as orders, COUNT(*) * 35000 as revenue FROM orders WHERE status != 'cancelled'"
        ) as c:
            month_stats = dict(await c.fetchone())
    return {"general": general, "today": today_orders, "month": month_stats}


def analytics_keyboard() -> object:
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Общая статистика", callback_data="analytics_general")
    builder.button(text="💰 Выручка", callback_data="analytics_revenue")
    builder.button(text="🚚 Маршруты доставки", callback_data="analytics_routes")
    builder.adjust(1)
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
    builder.adjust(2)
    await message.answer("🔧 *Панель администратора*", parse_mode="Markdown", reply_markup=builder.as_markup())


@router.callback_query(F.data == "analytics_main")
async def analytics_main(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.edit_text("📈 *Аналитика*", parse_mode="Markdown", reply_markup=analytics_keyboard())
    await callback.answer()


@router.callback_query(F.data == "analytics_general")
async def analytics_general(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    data = await get_analytics()
    g = data["general"]
    t = data["today"]
    text = (
        "📊 *Общая статистика*\n\n"
        f"👥 Всего пользователей: *{g['total_users']}*\n"
        f"📦 Всего заказов: *{g['total_orders_all'] or 0}*\n\n"
        f"📦 Заказов на завтра: *{t['count']}*\n"
        f"💰 Выручка завтра: *{t['revenue']:,} сум*"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data="analytics_main")
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "analytics_revenue")
async def analytics_revenue(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    data = await get_analytics()
    m = data["month"]
    t = data["today"]
    text = (
        "💰 *Финансовая статистика*\n\n"
        f"📦 Всего заказов: *{m['orders']}*\n"
        f"💰 Общая выручка: *{m['revenue']:,} сум*\n\n"
        f"📆 Завтра (прогноз):\n"
        f"• Заказов: *{t['count']}*\n"
        f"• Выручка: *{t['revenue']:,} сум*"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data="analytics_main")
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())
    await callback.answer()


async def get_delivery_routes() -> list:
    from database.db import get_daily_summary
    from datetime import date, timedelta
    tomorrow = str(date.today() + timedelta(days=1))
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT c.name as company, COUNT(*) as count,
            COALESCE(c.maps_link, '') as maps_link
            FROM orders o
            JOIN users u ON o.user_id = u.id
            JOIN companies c ON u.company_id = c.id
            WHERE o.order_date = ? AND o.status != 'cancelled'
            GROUP BY c.id ORDER BY count DESC
        """, (tomorrow,)) as cursor:
            return [dict(r) for r in await cursor.fetchall()]


@router.callback_query(F.data == "analytics_routes")
async def analytics_routes(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    from datetime import date, timedelta
    routes = await get_delivery_routes()
    tomorrow = str(date.today() + timedelta(days=1))
    if not routes:
        text = f"🚚 *Маршруты на {tomorrow}*\n\nЗаказов пока нет"
    else:
        text = f"🚚 *Маршруты доставки на {tomorrow}*\n\n"
        total = 0
        for i, r in enumerate(routes, 1):
            text += f"{i}. *{r['company']}* — {r['count']} обедов\n"
            total += r["count"]
        text += f"\n📦 Итого: *{total} обедов*\n⏰ Доставка: 12:00 – 13:00"
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data="analytics_main")
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())
    await callback.answer()
