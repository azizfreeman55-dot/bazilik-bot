code = open("handlers/registration.py", "r", encoding="utf-8").read()

# Исправляем process_phone - берём язык из state
old = '''@router.message(Registration.waiting_phone, F.contact)
async def process_phone_contact(message: Message, state: FSMContext):
    phone = message.contact.phone_number.replace("+", "").strip()
    await state.update_data(phone=phone)
    await state.set_state(Registration.waiting_company)
    await message.answer(
        f"✅ Номер сохранён: +{phone}\\n\\n"
        "🏢 Введите название вашей *компании/организации*:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )'''

new = '''@router.message(Registration.waiting_phone, F.contact)
async def process_phone_contact(message: Message, state: FSMContext):
    phone = message.contact.phone_number.replace("+", "").strip()
    await state.update_data(phone=phone)
    await state.set_state(Registration.waiting_company)
    data = await state.get_data()
    lang = data.get("lang", "ru")
    from langs import t
    await message.answer(
        f"✅ {t(lang, 'phone_saved')} +{phone}\\n\\n"
        f"{t(lang, 'enter_company')}",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )'''

code = code.replace(old, new)

# Исправляем process_phone_text
old2 = '''    await state.update_data(phone=phone)
    await state.set_state(Registration.waiting_company)
    await message.answer(
        f"✅ Номер сохранён: +{phone}\\n\\n"
        "🏢 Введите название вашей *компании/организации*:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )'''

new2 = '''    await state.update_data(phone=phone)
    await state.set_state(Registration.waiting_company)
    data = await state.get_data()
    lang = data.get("lang", "ru")
    from langs import t
    await message.answer(
        f"✅ {t(lang, 'phone_saved')} +{phone}\\n\\n"
        f"{t(lang, 'enter_company')}",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )'''

code = code.replace(old2, new2)

# Исправляем process_company
old3 = '''    await state.update_data(company_name=company_name, company_id=company_id)
    await state.set_state(Registration.waiting_address)
    await message.answer(
        "📍 Введите *адрес вашей компании*:\\n"
        "Например: ул. Амира Темура 15, офис 301",
        parse_mode="Markdown"
    )'''

new3 = '''    await state.update_data(company_name=company_name, company_id=company_id)
    await state.set_state(Registration.waiting_address)
    data2 = await state.get_data()
    lang = data2.get("lang", "ru")
    from langs import t
    await message.answer(
        t(lang, "enter_address"),
        parse_mode="Markdown"
    )'''

code = code.replace(old3, new3)

# Исправляем финальное сообщение регистрации
old4 = '''    bonus_text = ""
    if data.get("ref_code"):
        bonus_text = "\\n🎁 *+10 баллов* за приглашение друга!"

    is_admin = message.from_user.id in ADMIN_IDS
    await state.clear()
    await message.answer(
        f"🎉 *Регистрация завершена!*\\n\\n"
        f"👤 Имя: {user['full_name']}\\n"
        f"📱 Телефон: +{data.get('phone', '—')}\\n"
        f"🏢 Компания: {company_name}\\n"
        f"📍 Адрес: {address}\\n"
        f"🔑 Ваш реферальный код: `{referral_code}`\\n"
        f"💰 Баллы: {user['points']}"
        f"{bonus_text}\\n\\n"
        f"Каждый день в *10:00* вы будете получать меню на завтра.\\n"
        f"Заказы принимаются до *20:00*!",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(is_admin)
    )'''

new4 = '''    bonus_text = ""
    if data.get("ref_code"):
        bonus_text = "\\n🎁 *+10 баллов* за приглашение друга!"

    is_admin = message.from_user.id in ADMIN_IDS
    from langs import t

    # Сохраняем язык пользователя
    from database.db import set_user_lang
    await set_user_lang(message.from_user.id, lang)

    await state.clear()
    await message.answer(
        f"{t(lang, 'reg_done')}\\n\\n"
        f"{t(lang, 'name_label')}: {user['full_name']}\\n"
        f"{t(lang, 'phone_label')}: +{data.get('phone', '—')}\\n"
        f"{t(lang, 'company_label')}: {company_name}\\n"
        f"{t(lang, 'address_label')}: {address}\\n"
        f"{t(lang, 'code_label')}: `{referral_code}`\\n"
        f"{t(lang, 'points_label')}: {user['points']}"
        f"{bonus_text}\\n\\n"
        f"{t(lang, 'daily_info')}",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(is_admin, lang)
    )'''

code = code.replace(old4, new4)

with open("handlers/registration.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ registration.py исправлен!")

# Исправляем /start - welcome back на нужном языке
code2 = open("handlers/registration.py", "r", encoding="utf-8").read()

old5 = '''    if user:
        is_admin = message.from_user.id in ADMIN_IDS
        await message.answer(
            f"👋 С возвращением, {user['full_name']}!\\n\\n"
            f"💰 Баллы: {user['points']} | 📦 Заказов: {user['total_orders']}\\n"
            f"🏅 Статус: {user['status']}",
            reply_markup=main_menu_keyboard(is_admin)
        )
        return'''

new5 = '''    if user:
        is_admin = message.from_user.id in ADMIN_IDS
        from database.db import get_user_lang
        from langs import t
        lang = await get_user_lang(message.from_user.id)
        await message.answer(
            f"{t(lang, 'welcome_back')}, {user['full_name']}!\\n\\n"
            f"{t(lang, 'points')}: {user['points']} | {t(lang, 'orders')}: {user['total_orders']}\\n"
            f"{t(lang, 'status')}: {user['status']}",
            reply_markup=main_menu_keyboard(is_admin, lang)
        )
        return'''

code2 = code2.replace(old5, new5)

with open("handlers/registration.py", "w", encoding="utf-8") as f:
    f.write(code2)

print("✅ Готово! Все тексты на нужном языке!")