code = open("handlers/registration.py", "r", encoding="utf-8").read()

old = '''    await state.update_data(ref_code=ref_code)
    await state.set_state(Registration.waiting_lang)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="🇷🇺 Русский", callback_data="lang_ru")
    builder.button(text="🇺🇿 O\'zbekcha (lotin)", callback_data="lang_uz_latin")
    builder.adjust(1)

    await message.answer_photo(
        photo="AgACAgIAAxkDAAIBO2ofQk41gxtkh-eUj9vSRqnLWHnlAAIgImsb7_X4SFTotJtbHrfgAQADAgADeAADOwQ",
        caption="🌿 *Bazilik*\\n\\n🌐 Выберите язык / Tilni tanlang / Тилни танланг:",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )'''

new = '''    await state.update_data(ref_code=ref_code)
    await state.set_state(Registration.waiting_lang)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="🇷🇺 Русский", callback_data="lang_ru")
    builder.button(text="🇺🇿 O\'zbekcha (lotin)", callback_data="lang_uz_latin")
    builder.adjust(1)

    await message.answer_photo(
        photo="AgACAgIAAxkDAAIBO2ofQk41gxtkh-eUj9vSRqnLWHnlAAIgImsb7_X4SFTotJtbHrfgAQADAgADeAADOwQ",
        caption=(
            "🌿 *Bazilik — Since 2025*\\n\\n"
            "🍱 Свежие домашние обеды в ваш офис!\\n"
            "🍱 Ofisингизга yangi uy taomlari!\\n\\n"
            "✅ 3 та блюдо ежедневно / 3 ta taom har kuni\\n"
            "✅ Заказ до 20:00 / Buyurtma 20:00 gacha\\n"
            "✅ Доставка 12:00–13:00\\n\\n"
            "🌐 Выберите язык / Tilni tanlang:"
        ),
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )'''

code = code.replace(old, new)

with open("handlers/registration.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ Готово!")