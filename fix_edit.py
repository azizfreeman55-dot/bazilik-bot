code = open("handlers/orders.py", "r", encoding="utf-8").read()

old = '''    if first_photo:
            await message.answer_photo(
                photo=first_photo["photo_id"],
                caption=text,
                parse_mode="Markdown",
                reply_markup=menu_keyboard(menu)
            )'''

new = '''    if first_photo:
            await message.answer_photo(
                photo=first_photo["photo_id"],
                caption=text,
                parse_mode="Markdown",
                reply_markup=menu_keyboard(menu)
            )
            return'''

code = code.replace(old, new)

with open("handlers/orders.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ Готово!")