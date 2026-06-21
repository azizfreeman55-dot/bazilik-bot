"""
Скрипт для диагностики — показывает что реально лежит в weekly_menu.
Загрузите в корень репозитория и выполните в Shell: python3 check_weekly_menu.py
"""
import asyncio
import asyncpg
import os

async def check():
    db = await asyncpg.connect(os.getenv('DATABASE_URL'))

    print("=" * 60)
    print("СОДЕРЖИМОЕ ТАБЛИЦЫ weekly_menu (постоянное меню):")
    print("=" * 60)

    rows = await db.fetch("""
        SELECT day_of_week, item_number, name, price, category, is_active
        FROM weekly_menu
        ORDER BY day_of_week, category, item_number
    """)

    if not rows:
        print("Таблица ПУСТАЯ — ничего не сохранено!")
    else:
        days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        for r in rows:
            day = days[r['day_of_week']]
            active = "✅" if r['is_active'] else "❌ (неактивно)"
            print(f"{day} | {r['category']:8} | #{r['item_number']} | {r['name']:20} | {r['price']:>7} сум | {active}")

    print()
    print("=" * 60)
    print("СОДЕРЖИМОЕ ТАБЛИЦЫ menus (разовое/скопированное меню) за последние 10 записей:")
    print("=" * 60)

    rows2 = await db.fetch("""
        SELECT menu_date, item_number, name, price, category, is_active
        FROM menus
        ORDER BY menu_date DESC, category, item_number
        LIMIT 20
    """)

    if not rows2:
        print("Таблица menus ПУСТАЯ")
    else:
        for r in rows2:
            active = "✅" if r['is_active'] else "❌ (неактивно)"
            print(f"{r['menu_date']} | {r['category']:8} | #{r['item_number']} | {r['name']:20} | {r['price']:>7} сум | {active}")

    await db.close()

asyncio.run(check())
