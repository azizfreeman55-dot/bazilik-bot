code = open("handlers/registration.py", "r", encoding="utf-8").read()

# Убираем waiting_address из состояний
old = '''class Registration(StatesGroup):
    waiting_lang = State()
    waiting_name = State()
    waiting_phone = State()
    waiting_company = State()
    waiting_address = State()'''

new = '''class Registration(StatesGroup):
    waiting_lang = State()
    waiting_name = State()
    waiting_phone = State()
    waiting_company = State()
    waiting_location = State()'''

code = code.replace(old, new)

# Меняем запрос адреса на запрос локации
old2 = '''    await state.update_data(company_name=company_name, company_id=company_id)
    await state.set_state(Registration.waiting_address)
    data2 = await state.get_data()
    lang = data2.get("lang", "ru")
    from langs import t
    await message.answer(
        t(lang, "enter_address"),
        parse_mode="Markdown"
    )'''

new2 = '''    await state.update_data(company_name=company_name, company_id=company_id)
    await state.set_state(Registration.waiting_location)
    data2 = await state.get_data()
    lang = data2.get("lang", "ru")

    from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
    loc_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(
            text="📍 Отправить локацию" if lang == "ru" else "📍 Joylashuvni yuborish",
            request_location=True
        )]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    text = (
        "📍 Отправьте *локацию вашей компании*\\n"
        "Нажмите кнопку ниже 👇"
        if lang == "ru" else
        "📍 *Kompaniya joylashuvingizni* yuboring\\n"
        "Quyidagi tugmani bosing 👇"
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=loc_kb)'''

code = code.replace(old2, new2)

# Меняем обработчик адреса на обработчик локации
old3 = '''@router.message(Registration.waiting_address)
async def process_address(message: Message, state: FSMContext):
    address = message.text.strip()
    await state.update_data(address=address)
    data = await state.get_data()
    company_name = data["company_name"]
    company_id = data["company_id"]
    referral_code = generate_referral_code(data["name"])

    import aiosqlite
    from config import DATABASE_URL
    async with aiosqlite.connect(DATABASE_URL) as db:
        try:
            await db.execute("ALTER TABLE companies ADD COLUMN address TEXT")
            await db.commit()
        except Exception:
            pass
        await db.execute(
            "UPDATE companies SET address = ? WHERE id = ?",
            (address, company_id)
        )
        await db.commit()

    lang = data.get("lang", "ru")
    await save_user_phone(message.from_user.id, data.get("phone", ""))

    # Сохраняем язык пользователя
    import aiosqlite
    from config import DATABASE_URL as DB_URL
    async with aiosqlite.connect(DB_URL) as db:
        try:
            await db.execute("ALTER TABLE users ADD COLUMN lang TEXT DEFAULT 'ru'")
            await db.commit()
        except Exception:
            pass

    user = await create_user('''

new3 = '''@router.message(Registration.waiting_location, F.location)
async def process_location(message: Message, state: FSMContext):
    lat = message.location.latitude
    lon = message.location.longitude
    address = f"{lat},{lon}"
    maps_link = f"https://maps.google.com/?q={lat},{lon}"

    await state.update_data(address=address, maps_link=maps_link)
    data = await state.get_data()
    company_name = data["company_name"]
    company_id = data["company_id"]
    referral_code = generate_referral_code(data["name"])

    import aiosqlite
    from config import DATABASE_URL
    async with aiosqlite.connect(DATABASE_URL) as db:
        try:
            await db.execute("ALTER TABLE companies ADD COLUMN address TEXT")
            await db.execute("ALTER TABLE companies ADD COLUMN maps_link TEXT")
            await db.commit()
        except Exception:
            pass
        await db.execute(
            "UPDATE companies SET address = ?, maps_link = ? WHERE id = ?",
            (address, maps_link, company_id)
        )
        await db.commit()

    lang = data.get("lang", "ru")
    await save_user_phone(message.from_user.id, data.get("phone", ""))

    import aiosqlite
    from config import DATABASE_URL as DB_URL
    async with aiosqlite.connect(DB_URL) as db:
        try:
            await db.execute("ALTER TABLE users ADD COLUMN lang TEXT DEFAULT 'ru'")
            await db.commit()
        except Exception:
            pass

    user = await create_user('''

code = code.replace(old3, new3)

# Финальное сообщение - убираем адрес добавляем карту
old4 = '''        f"{t(lang, 'reg_done')}\\n\\n"
        f"{t(lang, 'name_label')}: {user['full_name']}\\n"
        f"{t(lang, 'phone_label')}: +{data.get('phone', '—')}\\n"
        f"{t(lang, 'company_label')}: {company_name}\\n"
        f"{t(lang, 'address_label')}: {address}\\n"
        f"{t(lang, 'code_label')}: `{referral_code}`\\n"
        f"{t(lang, 'points_label')}: {user['points']}"
        f"{bonus_text}\\n\\n"
        f"{t(lang, 'daily_info')}",'''

new4 = '''        f"{t(lang, 'reg_done')}\\n\\n"
        f"{t(lang, 'name_label')}: {user['full_name']}\\n"
        f"{t(lang, 'phone_label')}: +{data.get('phone', '—')}\\n"
        f"{t(lang, 'company_label')}: {company_name}\\n"
        f"📍 [Lokatsiya / Локация]({data.get('maps_link', '')})\\n"
        f"{t(lang, 'code_label')}: `{referral_code}`\\n"
        f"{t(lang, 'points_label')}: {user['points']}"
        f"{bonus_text}\\n\\n"
        f"{t(lang, 'daily_info')}",'''

code = code.replace(old4, new4)

with open("handlers/registration.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ Готово!")

# Обновляем маршруты - показываем ссылку на карту
code2 = open("handlers/analytics.py", "r", encoding="utf-8").read()

old5 = '''            SELECT c.name as company, COUNT(*) as count,
            COALESCE(c.address, 'Адрес не указан') as address'''

new5 = '''            SELECT c.name as company, COUNT(*) as count,
            COALESCE(c.address, '') as address,
            COALESCE(c.maps_link, '') as maps_link'''

code2 = code2.replace(old5, new5)

old6 = '''            maps_link = f"https://yandex.uz/maps/?text={r['address'].replace(' ', '+')}"
            text += f"{i}. *{r['company']}* — {r['count']} обедов\\\\n"
            text += f"   📍 {r['address']}\\\\n"
            text += f"   🗺 [Открыть карту]({maps_link})\\\\n\\\\n"'''

new6 = '''            maps_link = r.get('maps_link', '')
            text += f"{i}. *{r['company']}* — {r['count']} обедов\\\\n"
            if maps_link:
                text += f"   🗺 [Открыть карту]({maps_link})\\\\n\\\\n"
            else:
                text += "\\\\n"'''

code2 = code2.replace(old6, new6)

with open("handlers/analytics.py", "w", encoding="utf-8") as f:
    f.write(code2)

print("✅ analytics.py обновлён!")