code = open("handlers/orders.py", "r", encoding="utf-8").read()

# Исправляем process_order_selection - добавляем lang
old = '''    order = await create_order(callback.from_user.id, menu_id, tomorrow)
    user = await get_user(callback.from_user.id)
    if not order:
        await callback.answer("❌ Ошибка при создании заказа", show_alert=True)
        return'''

new = '''    order = await create_order(callback.from_user.id, menu_id, tomorrow)
    user = await get_user(callback.from_user.id)
    lang = await get_user_lang(callback.from_user.id)
    if not order:
        await callback.answer("❌ Ошибка при создании заказа", show_alert=True)
        return'''

code = code.replace(old, new)

# Исправляем reward_text на нужный язык
old2 = '''    reward_text = ""
    points = user["points"]
    if points >= 500:
        reward_text = "\\n👑 *Поздравляем! Вы достигли статуса VIP!*"
    elif points >= 200:
        reward_text = "\\n🍱 *Поздравляем! Вы заработали Бесплатный обед!*"
    elif points >= 100:
        reward_text = "\\n🍰 *Поздравляем! Вы заработали Десерт!*"
    elif points >= 50:
        reward_text = "\\n🥤 *Поздравляем! Вы заработали Напиток!*"'''

new2 = '''    reward_text = ""
    points = user["points"]
    if points >= 500:
        reward_text = f"\\n{t(lang, 'reward_vip')}"
    elif points >= 200:
        reward_text = f"\\n{t(lang, 'reward_lunch')}"
    elif points >= 100:
        reward_text = f"\\n{t(lang, 'reward_dessert')}"
    elif points >= 50:
        reward_text = f"\\n{t(lang, 'reward_drink')}"'''

code = code.replace(old2, new2)

# Исправляем my_order
old3 = '''    lang = await get_user_lang(message.from_user.id)
    if not order:
        text = f"{t(lang, 'no_order')}\\n\\n"
        if is_orders_open():
            text += f"*{t(lang, 'btn_order')}* " + ("чтобы выбрать блюдо" if lang == "ru" else "tugmasini bosing")
        else:
            text += "20:00" 
        await message.answer(text, parse_mode="Markdown")
        return'''

new3 = '''    lang = await get_user_lang(message.from_user.id)
    if not order:
        if is_orders_open():
            text = f"{t(lang, 'no_order')}\\n\\n*{t(lang, 'btn_order')}* " + ("нажмите чтобы выбрать" if lang == "ru" else "tugmasini bosing")
        else:
            text = t(lang, "orders_closed")
        await message.answer(text, parse_mode="Markdown")
        return'''

code = code.replace(old3, new3)

# Исправляем статус заказа
old4 = '''    status_emoji = {"pending": "⏳", "confirmed": "✅", "delivered": "🚚", "cancelled": "❌"}
    status_text = {"pending": "Ожидает", "confirmed": "Подтверждён", "delivered": "Доставлен", "cancelled": "Отменён"}
    status = order.get("status", "pending")

    await message.answer(
        f"📋 *Ваш заказ на {day_name}*\\n\\n"
        f"🍱 {order['meal_name']}\\n"
        f"📊 Статус: {status_emoji.get(status, '⏳')} {status_text.get(status, status)}\\n"
        f"🕐 Доставка: 12:00 – 13:00",
        parse_mode="Markdown",
        reply_markup=order_actions_keyboard(status == "pending")
    )'''

new4 = '''    status_emoji = {"pending": "⏳", "confirmed": "✅", "delivered": "🚚", "cancelled": "❌"}
    status_text_ru = {"pending": "Ожидает", "confirmed": "Подтверждён", "delivered": "Доставлен", "cancelled": "Отменён"}
    status_text_uz = {"pending": "Kutilmoqda", "confirmed": "Tasdiqlandi", "delivered": "Yetkazildi", "cancelled": "Bekor qilindi"}
    status = order.get("status", "pending")
    st = status_text_ru if lang == "ru" else status_text_uz

    await message.answer(
        f"{t(lang, 'my_order')} {day_name}*\\n\\n"
        f"🍱 {order['meal_name']}\\n"
        f"📊 {st.get(status, status_emoji.get(status, '⏳'))}\\n"
        f"{t(lang, 'delivery_time')}",
        parse_mode="Markdown",
        reply_markup=order_actions_keyboard(status == "pending")
    )'''

code = code.replace(old4, new4)

with open("handlers/orders.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ orders.py полностью исправлен!")