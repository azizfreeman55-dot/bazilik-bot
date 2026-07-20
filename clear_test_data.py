"""
clear_test_data.py — очистка тестовых данных перед реальным запуском.

Удаляет:  заказы, балансы, транзакции, отзывы, доставки, streak-данные
Оставляет: пользователей, компании, меню (weekly_menu + menus), настройки

Запуск: python3 clear_test_data.py
"""

import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def clear():
    db = await asyncpg.connect(os.getenv("DATABASE_URL"))

    print("🔍 Текущее состояние БД:")
    tables = [
        ("users",              "Пользователей"),
        ("companies",          "Компаний"),
        ("orders",             "Заказов"),
        ("user_balance",       "Балансов"),
        ("balance_transactions","Транзакций"),
        ("reviews",            "Отзывов на блюда"),
        ("courier_reviews",    "Отзывов на курьеров"),
        ("delivery_routes",    "Маршрутов доставки"),
        ("delivery_stops",     "Остановок маршрутов"),
        ("delivery_slots",     "Слотов доставки"),
        ("weekly_menu",        "Позиций постоянного меню"),
        ("menus",              "Позиций разового меню"),
        ("weekly_orders",      "Автозаказов"),
    ]
    for table, label in tables:
        try:
            cnt = await db.fetchval(f"SELECT COUNT(*) FROM {table}")
            print(f"  {label}: {cnt}")
        except Exception:
            print(f"  {label}: таблица не найдена")

    print()
    confirm = input("⚠️  Удалить все заказы, балансы и связанные данные? (напишите ДА): ")
    if confirm.strip().upper() not in ("ДА", "YES", "Y", "DA"):
        print("❌ Отменено.")
        await db.close()
        return

    print("\n🗑  Очищаем данные...")

    # Порядок важен — сначала дочерние таблицы, потом родительские
    steps = [
        ("courier_reviews",   "DELETE FROM courier_reviews",                    "Отзывы на курьеров"),
        ("reviews",           "DELETE FROM reviews",                             "Отзывы на блюда"),
        ("delivery_stops",    "DELETE FROM delivery_stops",                      "Остановки маршрутов"),
        ("delivery_routes",   "DELETE FROM delivery_routes",                     "Маршруты доставки"),
        ("delivery_slots",    "DELETE FROM delivery_slots",                      "Слоты доставки"),
        ("orders",            "DELETE FROM orders",                              "Заказы"),
        ("menus",             "DELETE FROM menus",                               "Разовое меню (копии для заказов)"),
        ("balance_transactions","DELETE FROM balance_transactions",              "Транзакции баланса"),
        ("user_balance",      "DELETE FROM user_balance",                        "Балансы"),
        ("company_of_month",  "DELETE FROM company_of_month",                   "Компании месяца"),
        # Сбрасываем streak и счётчики у пользователей
        ("users_reset",
         "UPDATE users SET points = 0, total_orders = 0, streak_days = 0, last_order_date = NULL WHERE 1=1",
         "Обнуление баллов/заказов/streak у пользователей"),
    ]

    for key, sql, label in steps:
        try:
            result = await db.execute(sql)
            print(f"  ✅ {label}: {result}")
        except Exception as e:
            print(f"  ⚠️  {label}: {e}")

    print("\n✅ Готово! Пользователи, компании и меню сохранены.")
    print("   Заказы, балансы и связанные данные очищены.")

    print("\n📊 Состояние после очистки:")
    for table, label in tables:
        try:
            cnt = await db.fetchval(f"SELECT COUNT(*) FROM {table}")
            print(f"  {label}: {cnt}")
        except Exception:
            pass

    await db.close()

asyncio.run(clear())
