# Обновляем registration.py - добавляем адрес и контакт компании
code = open("handlers/registration.py", "r", encoding="utf-8").read()

# Добавляем новые состояния
code = code.replace(
    "class Registration(StatesGroup):\n    waiting_name = State()\n    waiting_phone = State()\n    waiting_company = State()",
    "class Registration(StatesGroup):\n    waiting_name = State()\n    waiting_phone = State()\n    waiting_company = State()\n    waiting_address = State()\n    waiting_contact = State()"
)

# Меняем process_company чтобы спрашивал адрес
old = '''    is_admin = message.from_user.id in ADMIN_IDS
    await state.clear()
    await message.answer('''

new = '''    await state.update_data(company_name=company_name, company_id=company_id)
    await state.set_state(Registration.waiting_address)
    await message.answer(
        "📍 Введите *адрес вашей компании*:\\n"
        "Например: _ул. Амира Темура 15, офис 301_",
        parse_mode="Markdown"
    )


@router.message(Registration.waiting_address)
async def process_address(message: Message, state: FSMContext):
    address = message.text.strip()
    await state.update_data(address=address)
    await state.set_state(Registration.waiting_contact)
    await message.answer(
        "📞 Введите *имя и номер ответственного* за получение обедов:\\n"
        "Например: _Sardor +998901234567_",
        parse_mode="Markdown"
    )


@router.message(Registration.waiting_contact)
async def process_contact(message: Message, state: FSMContext):
    contact = message.text.strip()
    data = await state.get_data()
    company_name = data["company_name"]
    company_id = data["company_id"]
    referral_code = generate_referral_code(data["name"])

    # Сохраняем адрес и контакт компании
    import aiosqlite
    from config import DATABASE_URL
    async with aiosqlite.connect(DATABASE_URL) as db:
        try:
            await db.execute("ALTER TABLE companies ADD COLUMN address TEXT")
            await db.execute("ALTER TABLE companies ADD COLUMN contact TEXT")
            await db.commit()
        except Exception:
            pass
        await db.execute(
            "UPDATE companies SET address = ?, contact = ? WHERE id = ?",
            (data.get("address", ""), contact, company_id)
        )
        await db.commit()

    await save_user_phone(message.from_user.id, data.get("phone", ""))

    user = await create_user(
        telegram_id=message.from_user.id,
        full_name=data["name"],
        username=message.from_user.username or "",
        company_id=company_id,
        referral_code=referral_code,
        referred_by_code=data.get("ref_code")
    )

    bonus_text = ""
    if data.get("ref_code"):
        bonus_text = "\\n🎁 *+10 баллов* за приглашение друга!"

    is_admin = message.from_user.id in ADMIN_IDS
    await state.clear()
    await message.answer('''

code = code.replace(old, new)

# Обновляем финальное сообщение регистрации
old2 = '''        f"🎉 *Регистрация завершена!*\\n\\n"
        f"👤 Имя: {user['full_name']}\\n"
        f"📱 Телефон: +{data.get('phone', '—')}\\n"
        f"🏢 Компания: {company_name}\\n"
        f"🔑 Ваш реферальный код: `{referral_code}`\\n"
        f"💰 Баллы: {user['points']}"
        f"{bonus_text}\\n\\n"
        f"Каждый день в *10:00* вы будете получать меню на завтра.\\n"
        f"Заказы принимаются до *20:00*!",'''

new2 = '''        f"🎉 *Регистрация завершена!*\\n\\n"
        f"👤 Имя: {user['full_name']}\\n"
        f"📱 Телефон: +{data.get('phone', '—')}\\n"
        f"🏢 Компания: {company_name}\\n"
        f"📍 Адрес: {data.get('address', '—')}\\n"
        f"🔑 Ваш реферальный код: `{referral_code}`\\n"
        f"💰 Баллы: {user['points']}"
        f"{bonus_text}\\n\\n"
        f"Каждый день в *10:00* вы будете получать меню на завтра.\\n"
        f"Заказы принимаются до *20:00*!",'''

code = code.replace(old2, new2)

with open("handlers/registration.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ registration.py обновлён!")

# Обновляем маршруты в analytics.py - добавляем адрес и контакт
analytics = open("handlers/analytics.py", "r", encoding="utf-8").read()

old3 = '''            SELECT c.name as company, COUNT(*) as count
            FROM orders o
            JOIN users u ON o.user_id = u.id
            JOIN companies c ON u.company_id = c.id
            WHERE o.order_date = ? AND o.status != 'cancelled'
            GROUP BY c.id ORDER BY count DESC'''

new3 = '''            SELECT c.name as company, COUNT(*) as count,
            COALESCE(c.address, 'Адрес не указан') as address,
            COALESCE(c.contact, 'Контакт не указан') as contact
            FROM orders o
            JOIN users u ON o.user_id = u.id
            JOIN companies c ON u.company_id = c.id
            WHERE o.order_date = ? AND o.status != 'cancelled'
            GROUP BY c.id ORDER BY count DESC'''

analytics = analytics.replace(old3, new3)

old4 = '''        text = f"🚚 *Маршруты доставки на {tomorrow}*\\\\n\\\\n"
        total = 0
        for i, r in enumerate(routes, 1):
            text += f"{i}. *{r['company']}* — {r['count']} обедов\\\\n"
            total += r["count"]
        text += f"\\\\n📦 Итого: *{total} обедов*\\\\n⏰ Доставка: 12:00 – 13:00"'''

new4 = '''        text = f"🚚 *Маршруты доставки на {tomorrow}*\\\\n\\\\n"
        total = 0
        for i, r in enumerate(routes, 1):
            maps_link = f"https://yandex.uz/maps/?text={r['address'].replace(' ', '+')}"
            text += f"{i}. *{r['company']}* — {r['count']} обедов\\\\n"
            text += f"   📍 {r['address']}\\\\n"
            text += f"   📞 {r['contact']}\\\\n"
            text += f"   🗺 [Открыть карту]({maps_link})\\\\n\\\\n"
            total += r["count"]
        text += f"📦 Итого: *{total} обедов*\\\\n⏰ Доставка: 12:00 – 13:00"'''

analytics = analytics.replace(old4, new4)

with open("handlers/analytics.py", "w", encoding="utf-8") as f:
    f.write(analytics)

print("✅ analytics.py обновлён — адреса и карты добавлены!")