"""
clear_all_data.py — ПОЛНАЯ очистка всех тестовых данных.

Удаляет ВСЁ: пользователей, компании, заказы, меню, балансы.
Структура таблиц (схема) сохраняется — бот сразу готов к работе.

Запуск: python3 clear_all_data.py
"""

import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def clear_all():
    db = await asyncpg.connect(os.getenv("DATABASE_URL"))

    print("🔍 Текущее состояние БД:")
    tables = [
        ("users",               "Пользователей"),
        ("companies",           "Компаний"),
        ("orders",              "Заказов"),
        ("menus",               "Разового меню"),
        ("weekly_menu",         "Постоянного меню"),
        ("weekly_orders",       "Автозаказов"),
        ("user_balance",        "Балансов"),
        ("balance_transactions","Транзакций"),
        ("reviews",             "Отзывов на блюда"),
        ("courier_reviews",     "Отзывов на курьеров"),
        ("delivery_routes",     "Маршрутов доставки"),
        ("delivery_stops",      "Остановок маршрутов"),
        ("delivery_slots",      "Слотов доставки"),
        ("couriers",            "Курьеров"),
        ("company_of_month",    "Компании месяца"),
        ("migration_flags",     "Флагов миграций"),
    ]

    for table, label in tables:
        try:
            cnt = await db.fetchval(f"SELECT COUNT(*) FROM {table}")
            print(f"  {label}: {cnt}")
        except Exception:
            print(f"  {label}: таблица не найдена")

    print()
    print("⚠️  ВНИМАНИЕ! Это удалит АБСОЛЮТНО ВСЕ данные:")
    print("   пользователи, компании, меню, заказы, балансы — всё.")
    print("   Структура таблиц останется, бот сразу готов к работе.")
    print()
    confirm = input("Напишите УДАЛИТЬ для подтверждения: ")
    if confirm.strip().upper() != "УДАЛИТЬ":
        print("❌ Отменено.")
        await db.close()
        return

    print("\n🗑  Очищаем все данные...")

    # Порядок строгий — сначала дочерние таблицы (с FK), потом родительские
    steps = [
        ("courier_reviews",    "DELETE FROM courier_reviews",     "Отзывы на курьеров"),
        ("reviews",            "DELETE FROM reviews",             "Отзывы на блюда"),
        ("delivery_stops",     "DELETE FROM delivery_stops",      "Остановки маршрутов"),
        ("delivery_routes",    "DELETE FROM delivery_routes",     "Маршруты доставки"),
        ("delivery_slots",     "DELETE FROM delivery_slots",      "Слоты доставки"),
        ("orders",             "DELETE FROM orders",              "Заказы"),
        ("balance_transactions","DELETE FROM balance_transactions","Транзакции баланса"),
        ("user_balance",       "DELETE FROM user_balance",        "Балансы"),
        ("weekly_orders",      "DELETE FROM weekly_orders",       "Автозаказы"),
        ("company_of_month",   "DELETE FROM company_of_month",    "Компании месяца"),
        ("menus",              "DELETE FROM menus",               "Разовое меню"),
        ("weekly_menu",        "DELETE FROM weekly_menu",         "Постоянное меню"),
        ("users",              "DELETE FROM users",               "Пользователи"),
        ("companies",          "DELETE FROM companies",           "Компании"),
        ("couriers",           "DELETE FROM couriers",            "Курьеры"),
        ("migration_flags",    "DELETE FROM migration_flags",     "Флаги миграций"),
    ]

    for _, sql, label in steps:
        try:
            result = await db.execute(sql)
            print(f"  ✅ {label}: {result}")
        except Exception as e:
            print(f"  ⚠️  {label}: {e}")

    # Сбрасываем автоинкременты чтобы ID начинались с 1
    sequences = [
        "users_id_seq", "companies_id_seq", "orders_id_seq",
        "menus_id_seq", "weekly_menu_id_seq", "weekly_orders_id_seq",
        "user_balance_id_seq", "balance_transactions_id_seq",
        "reviews_id_seq", "courier_reviews_id_seq",
        "delivery_routes_id_seq", "delivery_stops_id_seq",
        "delivery_slots_id_seq", "couriers_id_seq",
    ]
    for seq in sequences:
        try:
            await db.execute(f"ALTER SEQUENCE {seq} RESTART WITH 1")
        except Exception:
            pass

    print("\n✅ База данных полностью очищена!")
    print("   Бот готов к реальному запуску.")
    print("   Первый пользователь получит ID = 1.")

    await db.close()

asyncio.run(clear_all())
