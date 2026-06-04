# Обновляем orders.py - добавляем узбекские кнопки
code = open("handlers/orders.py", "r", encoding="utf-8").read()

old = '@router.message(F.text == "🍽️ Заказать обед")'
new = '@router.message(F.text.in_({"🍽️ Заказать обед", "🍽️ Tushlik buyurtma qilish"}))'
code = code.replace(old, new)

old2 = '@router.message(F.text == "📝 Мой заказ")'
new2 = '@router.message(F.text.in_({"📝 Мой заказ", "📝 Mening buyurtmam"}))'
code = code.replace(old2, new2)

with open("handlers/orders.py", "w", encoding="utf-8") as f:
    f.write(code)
print("✅ orders.py обновлён!")

# Обновляем profile.py
code2 = open("handlers/profile.py", "r", encoding="utf-8").read()

old3 = '@router.message(F.text == "🪪 Мой профиль")'
new3 = '@router.message(F.text.in_({"🪪 Мой профиль", "🪪 Mening profilim"}))'
code2 = code2.replace(old3, new3)

old4 = '@router.message(F.text == "👥 Пригласить коллегу")'
new4 = '@router.message(F.text.in_({"👥 Пригласить коллегу", "👥 Hamkasbni taklif qilish"}))'
code2 = code2.replace(old4, new4)

old5 = '@router.message(F.text == "🏆 Рейтинг")'
new5 = '@router.message(F.text.in_({"🏆 Рейтинг", "🏆 Reyting"}))'
code2 = code2.replace(old5, new5)

old6 = '@router.message(F.text == "⚙️ Настройки")'
new6 = '@router.message(F.text.in_({"⚙️ Настройки", "⚙️ Sozlamalar"}))'
code2 = code2.replace(old6, new6)

with open("handlers/profile.py", "w", encoding="utf-8") as f:
    f.write(code2)
print("✅ profile.py обновлён!")

# Обновляем analytics.py
code3 = open("handlers/analytics.py", "r", encoding="utf-8").read()

old7 = '@router.message(F.text == "🖥️ Админ панель")'
new7 = '@router.message(F.text.in_({"🖥️ Админ панель", "🖥️ Admin panel"}))'
code3 = code3.replace(old7, new7)

with open("handlers/analytics.py", "w", encoding="utf-8") as f:
    f.write(code3)
print("✅ analytics.py обновлён!")

print("\n✅ Все кнопки работают на двух языках!")