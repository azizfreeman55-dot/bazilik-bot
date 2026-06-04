code = open("handlers/registration.py", "r", encoding="utf-8").read()

# Убираем шаг waiting_contact
code = code.replace(
    "    waiting_address = State()\n    waiting_contact = State()",
    "    waiting_address = State()"
)

# После адреса сразу завершаем регистрацию
old = '''    await state.update_data(address=address)
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
    await message.answer(
        f"🎉 *Регистрация завершена!*\\n\\n"
        f"👤 Имя: {user['full_name']}\\n"
        f"📱 Телефон: +{data.get('phone', '—')}\\n"
        f"🏢 Компания: {company_name}\\n"
        f"📍 Адрес: {data.get('address', '—')}\\n"
        f"🔑 Ваш реферальный код: `{referral_code}`\\n"
        f"💰 Баллы: {user['points']}"
        f"{bonus_text}\\n\\n"
        f"Каждый день в *10:00* вы будете получать меню на завтра.\\n"
        f"Заказы принимаются до *20:00*!",'''

new = '''    await state.update_data(address=address)
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
        f"Заказы принимаются до *20:00*!",'''

code = code.replace(old, new)

with open("handlers/registration.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ Готово!")