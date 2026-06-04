code = open("handlers/registration.py", "r", encoding="utf-8").read()

old = '''    await state.update_data(ref_code=ref_code)
    await state.set_state(Registration.waiting_name)
    await message.answer(
        "👋 Добро пожаловать в систему обедов!\\n\\n"
        "Для регистрации введите ваше *полное имя* (Имя Фамилия):",
        parse_mode="Markdown"
    )'''

new = '''    await state.update_data(ref_code=ref_code)
    await state.set_state(Registration.waiting_name)
    await message.answer_photo(
        photo="AgACAgIAAxkDAAIBO2ofQk41gxtkh-eUj9vSRqnLWHnlAAIgImsb7_X4SFTotJtbHrfgAQADAgADeAADOwQ",
        caption=(
            "🌿 *Добро пожаловать в Bazilik!*\\n\\n"
            "🍱 Мы доставляем свежие домашние обеды\\n"
            "прямо в ваш офис каждый день\\n\\n"
            "✅ Выбирайте из 3 блюд ежедневно\\n"
            "✅ Заказывайте до 20:00\\n"
            "✅ Получайте обед с 12:00 до 13:00\\n"
            "✅ Копите баллы и получайте бонусы\\n\\n"
            "📝 Для начала введите ваше *полное имя*:"
        ),
        parse_mode="Markdown"
    )'''

code = code.replace(old, new)

with open("handlers/registration.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ Готово!")