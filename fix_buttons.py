code = open("handlers/orders.py", "r", encoding="utf-8").read()

old = '''@router.callback_query(F.data.startswith("order_"))
async def process_order_selection(callback: CallbackQuery):
    if not is_orders_open():
        await callback.answer("❌ Приём заказов закрыт в 20:00!", show_alert=True)
        return

    menu_id = int(callback.data.split("_")[1])
    tomorrow = get_tomorrow_date()

    order = await create_order(callback.from_user.id, menu_id, tomorrow)
    user = await get_user(callback.from_user.id)'''

new = '''@router.callback_query(F.data.startswith("order_"))
async def process_order_selection(callback: CallbackQuery):
    if not is_orders_open():
        await callback.answer("❌ Приём заказов закрыт в 20:00!", show_alert=True)
        return

    menu_id = int(callback.data.split("_")[1])
    tomorrow = get_tomorrow_date()

    order = await create_order(callback.from_user.id, menu_id, tomorrow)
    user = await get_user(callback.from_user.id)
    if not order:
        await callback.answer("❌ Ошибка при создании заказа", show_alert=True)
        return'''

code = code.replace(old, new)

# Исправляем edit_text на answer когда есть фото
old2 = '''    await callback.message.edit_text(
        f"✅ *Заказ принят! Спасибо!*\\n\\n"
        f"🍱 {order['meal_name']}\\n"
        f"📅 Доставка: завтра с 12:00 до 13:00\\n\\n"
        f"💰 Баллы: {user['points']} (+5)\\n"
        f"📦 Всего заказов: {user['total_orders']}\\n"
        f"🔥 Серия: {user['streak_days']} дней подряд"
        f"{reward_text}",
        parse_mode="Markdown",
        reply_markup=order_actions_keyboard(True)
    )'''

new2 = '''    text = (
        f"✅ *Заказ принят! Спасибо!*\\n\\n"
        f"🍱 {order['meal_name']}\\n"
        f"📅 Доставка: завтра с 12:00 до 13:00\\n\\n"
        f"💰 Баллы: {user['points']} (+5)\\n"
        f"📦 Всего заказов: {user['total_orders']}\\n"
        f"🔥 Серия: {user['streak_days']} дней подряд"
        f"{reward_text}"
    )
    try:
        await callback.message.edit_text(
            text, parse_mode="Markdown",
            reply_markup=order_actions_keyboard(True)
        )
    except Exception:
        await callback.message.answer(
            text, parse_mode="Markdown",
            reply_markup=order_actions_keyboard(True)
        )'''

code = code.replace(old2, new2)

with open("handlers/orders.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ Готово!")