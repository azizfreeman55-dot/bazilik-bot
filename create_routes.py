# Добавляем маршруты в analytics.py
with open("handlers/analytics.py", "a", encoding="utf-8") as f:
    f.write('''

async def get_delivery_routes() -> list:
    from database.db import get_daily_summary
    from datetime import date, timedelta
    tomorrow = str(date.today() + timedelta(days=1))
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT c.name as company, COUNT(*) as count
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
        text = f"🚚 *Маршруты на {tomorrow}*\\n\\nЗаказов пока нет"
    else:
        text = f"🚚 *Маршруты доставки на {tomorrow}*\\n\\n"
        total = 0
        for i, r in enumerate(routes, 1):
            text += f"{i}. *{r['company']}* — {r['count']} обедов\\n"
            total += r["count"]
        text += f"\\n📦 Итого: *{total} обедов*\\n⏰ Доставка: 12:00 – 13:00"
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data="analytics_main")
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())
    await callback.answer()
''')

# Обновляем админ панель с кнопкой маршруты
import re
with open("handlers/analytics.py", "r", encoding="utf-8") as f:
    content = f.read()

old = '    builder.button(text="📈 Аналитика", callback_data="analytics_main")\n    builder.adjust(2)'
new = '    builder.button(text="📈 Аналитика", callback_data="analytics_main")\n    builder.button(text="🚚 Маршруты", callback_data="analytics_routes")\n    builder.adjust(2)'
content = content.replace(old, new)

# Обновляем analytics_keyboard
old2 = '    builder.button(text="💰 Выручка", callback_data="analytics_revenue")\n    builder.adjust(1)'
new2 = '    builder.button(text="💰 Выручка", callback_data="analytics_revenue")\n    builder.button(text="🚚 Маршруты доставки", callback_data="analytics_routes")\n    builder.adjust(1)'
content = content.replace(old2, new2)

with open("handlers/analytics.py", "w", encoding="utf-8") as f:
    f.write(content)

print("✅ Маршруты добавлены!")