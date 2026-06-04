# Исправляем orders.py - все ответы на нужном языке
code = open("handlers/orders.py", "r", encoding="utf-8").read()

old = '''from database.db import (
    get_user, get_menu, get_today_order,
    create_order, cancel_order
)'''

new = '''from database.db import (
    get_user, get_menu, get_today_order,
    create_order, cancel_order, get_user_lang
)
from langs import t'''

code = code.replace(old, new)

# Заказать обед
old2 = '''    if not is_orders_open():
        await message.answer(
            "⏰ Приём заказов закрыт!\\n\\n"
            "Заказы принимаются до *20:00*.\\n"
            "Завтра в 10:00 вы получите новое меню 🍽️",
            parse_mode="Markdown"
        )
        return'''

new2 = '''    lang = await get_user_lang(message.from_user.id)
    if not is_orders_open():
        await message.answer(t(lang, "orders_closed"), parse_mode="Markdown")
        return'''

code = code.replace(old2, new2)

# Нет меню
old3 = '''    if not menu:
        await message.answer(
            "😔 Меню на завтра ещё не добавлено.\\nОжидайте уведомление в 10:00!"
        )
        return'''

new3 = '''    if not menu:
        await message.answer(t(lang, "no_menu"))
        return'''

code = code.replace(old3, new3)

# Текст меню
old4 = '''    if has_photos:
        text = f"🍽️ *Меню на {day_name}* ({tomorrow}):\\n\\n"
        for item in menu:
            text += f"{item['item_number']}. {item['name']} — {item['price']:,} сум\\n"
        text += "\\n🚚 Доставка бесплатно\\nВыберите блюдо 👇"'''

new4 = '''    if has_photos:
        text = f"{t(lang, 'menu_title')} {day_name}* ({tomorrow}):\\n\\n"
        for item in menu:
            text += f"{item['item_number']}. {item['name']} — {item['price']:,} сум\\n"
        text += f"\\n{t(lang, 'free_delivery')}\\n{t(lang, 'choose_dish')}"'''

code = code.replace(old4, new4)

old5 = '''        text = f"🍽️ *Меню на {day_name}* ({tomorrow}):\\n\\n"
        for item in menu:
            text += f"{item['item_number']}. {item['name']}\\n"
            if item.get("description"):
                text += f"   _{item['description']}_\\n"
            text += f"   💰 {item['price']:,} сум\\n\\n"
        text += "🚚 Доставка бесплатно\\nВыберите блюдо:"
        await message.answer(text, parse_mode="Markdown", reply_markup=menu_keyboard(menu))'''

new5 = '''        text = f"{t(lang, 'menu_title')} {day_name}* ({tomorrow}):\\n\\n"
        for item in menu:
            text += f"{item['item_number']}. {item['name']}\\n"
            if item.get("description"):
                text += f"   _{item['description']}_\\n"
            text += f"   💰 {item['price']:,} сум\\n\\n"
        text += f"{t(lang, 'free_delivery')}\\n{t(lang, 'choose_dish')}"
        await message.answer(text, parse_mode="Markdown", reply_markup=menu_keyboard(menu))'''

code = code.replace(old5, new5)

# Заказ принят
old6 = '''    text = (
        f"✅ *Заказ принят! Спасибо!*\\n\\n"
        f"🍱 {order['meal_name']}\\n"
        f"📅 Доставка: завтра с 12:00 до 13:00\\n\\n"
        f"💰 Баллы: *{user['points']}* (+5)\\n"
        f"📦 Всего заказов: {user['total_orders']}"
        f"{reward_text}"
    )'''

new6 = '''    text = (
        f"{t(lang, 'order_accepted')}\\n\\n"
        f"🍱 {order['meal_name']}\\n"
        f"{t(lang, 'delivery_time')}\\n\\n"
        f"{t(lang, 'points')}: *{user['points']}* (+5)\\n"
        f"{t(lang, 'orders')}: {user['total_orders']}"
        f"{reward_text}"
    )'''

code = code.replace(old6, new6)

# Мой заказ - нет заказа
old7 = '''    if not order:
        text = f"📋 Заказ на {day_name} не оформлен\\n\\n"
        if is_orders_open():
            text += "Нажмите *🍱 Заказать обед* чтобы выбрать блюдо"
        else:
            text += "Приём заказов закрыт до завтра (10:00)"
        await message.answer(text, parse_mode="Markdown")
        return'''

new7 = '''    lang = await get_user_lang(message.from_user.id)
    if not order:
        text = f"{t(lang, 'no_order')}\\n\\n"
        if is_orders_open():
            text += f"*{t(lang, 'btn_order')}* " + ("чтобы выбрать блюдо" if lang == "ru" else "tugmasini bosing")
        else:
            text += "20:00" 
        await message.answer(text, parse_mode="Markdown")
        return'''

code = code.replace(old7, new7)

# Отмена заказа
old8 = '''    await callback.message.edit_text(
        "❓ Вы уверены, что хотите отменить заказ?\\n\\n"
        "⚠️ Баллы за этот заказ будут сняты.",
        reply_markup=confirm_cancel_keyboard()
    )'''

new8 = '''    from database.db import get_user_lang
    from langs import t
    lang = await get_user_lang(callback.from_user.id)
    await callback.message.edit_text(
        f"{t(lang, 'confirm_cancel')}",
        reply_markup=confirm_cancel_keyboard()
    )'''

code = code.replace(old8, new8)

old9 = '''    await callback.message.edit_text(
        "✅ Заказ отменён.\\n\\n"
        "Вы можете оформить новый заказ до 20:00 🍱"
    )
    await callback.answer("Заказ отменён")'''

new9 = '''    from database.db import get_user_lang
    from langs import t
    lang = await get_user_lang(callback.from_user.id)
    await callback.message.edit_text(t(lang, "order_cancelled"))
    await callback.answer()'''

code = code.replace(old9, new9)

with open("handlers/orders.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ orders.py обновлён!")

# Исправляем profile.py
code2 = open("handlers/profile.py", "r", encoding="utf-8").read()

old10 = '''from database.db import get_user, get_company_ranking'''
new10 = '''from database.db import get_user, get_company_ranking, get_user_lang
from langs import t'''

code2 = code2.replace(old10, new10)

old11 = '''@router.message(F.text.in_({"🪪 Мой профиль", "🪪 Mening profilim"}))
async def my_profile(message: Message):
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("❌ Сначала зарегистрируйтесь: /start")
        return'''

new11 = '''@router.message(F.text.in_({"🪪 Мой профиль", "🪪 Mening profilim"}))
async def my_profile(message: Message):
    user = await get_user(message.from_user.id)
    lang = await get_user_lang(message.from_user.id)
    if not user:
        await message.answer("❌ Сначала зарегистрируйтесь: /start")
        return'''

code2 = code2.replace(old11, new11)

old12 = '''    loyalty_text = get_loyalty_progress(user['points'])
    next_milestone = next(
        (m for m in sorted(LOYALTY_LEVELS.keys()) if m > user['points']), None
    )
    next_text = f"До следующей награды: *{next_milestone - user['points']} баллов*" if next_milestone else "🎉 Все награды получены!"

    await message.answer(
        f"👤 *{user['full_name']}*\\n"
        f"🏅 Статус: {user['status']}\\n"
        f"🏢 Компания: {user.get('company_name', 'Не указана')}\\n\\n"
        f"📦 Заказов: {user['total_orders']}\\n"
        f"💰 Баллы: *{user['points']}*\\n\\n"
        f"🎯 *Система лояльности:*\\n{loyalty_text}\\n"
        f"📍 {next_text}\\n\\n"
        f"🔑 Ваш код: `{user['referral_code']}`",
        parse_mode="Markdown"
    )'''

new12 = '''    loyalty_text = get_loyalty_progress(user['points'])
    next_milestone = next(
        (m for m in sorted(LOYALTY_LEVELS.keys()) if m > user['points']), None
    )
    next_text = f"{t(lang, 'next_reward')} *{next_milestone - user['points']}*" if next_milestone else t(lang, 'all_rewards')

    await message.answer(
        f"👤 *{user['full_name']}*\\n"
        f"{t(lang, 'status')}: {user['status']}\\n"
        f"{t(lang, 'company_label') if lang != 'ru' else '🏢 Компания'}: {user.get('company_name', '—')}\\n\\n"
        f"{t(lang, 'orders')}: {user['total_orders']}\\n"
        f"{t(lang, 'points')}: *{user['points']}*\\n\\n"
        f"{t(lang, 'loyalty_title')}\\n{loyalty_text}\\n"
        f"📍 {next_text}\\n\\n"
        f"{t(lang, 'code_label')}: `{user['referral_code']}`",
        parse_mode="Markdown"
    )'''

code2 = code2.replace(old12, new12)

with open("handlers/profile.py", "w", encoding="utf-8") as f:
    f.write(code2)

print("✅ profile.py обновлён!")
print("\n✅ Готово! Запускай: python main.py")