code = open("handlers/admin.py", "r", encoding="utf-8").read()

old = '''@router.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    import aiosqlite
    from config import DATABASE_URL
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT COUNT(*) as total,
               SUM(CASE WHEN last_order_date = date('now') THEN 1 ELSE 0 END) as active_today
               FROM users"""
        ) as cursor:
            stats = dict(await cursor.fetchone())

        async with db.execute(
            """SELECT SUM(o.id) as today_orders,
               COUNT(DISTINCT o.user_id) as ordering_users
               FROM orders o WHERE o.order_date = date('now', '+1 day')"""
        ) as cursor:
            order_stats = dict(await cursor.fetchone())

    await callback.answer()
    await callback.message.edit_text(
        f"👥 *Статистика пользователей:*\\n\\n"
        f"• Всего пользователей: {stats['total']}\\n"
        f"• Активны сегодня: {stats['active_today'] or 0}\\n"
        f"• Заказов на завтра: {order_stats['today_orders'] or 0}\\n"
        f"• Заказывают: {order_stats['ordering_users'] or 0} чел.",
        parse_mode="Markdown",
        reply_markup=admin_keyboard()
    )'''

new = '''@router.callback_query(F.data == "admin_users")
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

    text = f"👥 *Все пользователи ({len(users)} чел.)*\\n\\n"
    for i, u in enumerate(users, 1):
        phone = f"+{u['phone']}" if u.get('phone') else "Не указан"
        text += (
            f"{i}. *{u['full_name']}*\\n"
            f"   📱 {phone}\\n"
            f"   🏢 {u.get('company_name') or 'Не указана'}\\n"
            f"   📍 {u['address']}\\n"
            f"   📦 Заказов: {u['total_orders']} | 💰 {u['points']} баллов\\n"
            f"   🏅 {u['status']} | 🔥 {u['streak_days']} дней подряд\\n\\n"
        )

    # Telegram ограничение 4096 символов
    if len(text) > 4000:
        text = text[:4000] + "\\n...и другие"

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data="back_admin")
    await callback.answer()
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())


@router.callback_query(F.data == "back_admin")
async def back_admin(callback: CallbackQuery):
    await callback.message.edit_text("🔧 *Панель администратора*", parse_mode="Markdown", reply_markup=admin_keyboard())
    await callback.answer()'''

code = code.replace(old, new)

with open("handlers/admin.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ admin.py обновлён!")