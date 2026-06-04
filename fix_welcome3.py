code = open("handlers/registration.py", "r", encoding="utf-8").read()

old = '''        caption=(
            "🌿 *Bazilik — Since 2025*\\n\\n"
            "🍱 Свежие домашние обеды в ваш офис!\\n"
            "🍱 Ofisингизга yangi uy taomlari!\\n\\n"
            "✅ 3 та блюдо ежедневно / 3 ta taom har kuni\\n"
            "✅ Заказ до 20:00 / Buyurtma 20:00 gacha\\n"
            "✅ Доставка 12:00–13:00\\n\\n"
            "🌐 Выберите язык / Tilni tanlang:"
        ),'''

new = '''        caption=(
            "🌿 *Bazilik — Since 2025*\\n\\n"
            "🍱 *Что умеет этот бот?*\\n"
            "• Заказ обедов в офис каждый день\\n"
            "• Меню из 3 блюд на выбор ежедневно\\n"
            "• Система баллов и бонусов\\n\\n"
            "📞 +998 77 181 50 00\\n"
            "⏰ Пн-Вс: 10:00 — 14:00\\n\\n"
            "🌐 Выберите язык / Tilni tanlang:"
        ),'''

code = code.replace(old, new)

with open("handlers/registration.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ Готово!")