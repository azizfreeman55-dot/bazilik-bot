"""Проверяет есть ли блюда во weekly_menu для вторника (day_of_week=1)"""
import asyncio
import asyncpg
import os

async def check():
    db = await asyncpg.connect(os.getenv('DATABASE_URL'))
    
    print("=== weekly_menu для вторника (day_of_week=1) ===")
    rows = await db.fetch("""
        SELECT item_number, name, category, price, is_active
        FROM weekly_menu
        WHERE day_of_week = 1
        ORDER BY category, item_number
    """)
    for r in rows:
        print(dict(r))
    
    print()
    print("=== Конкретно то что выбрано user_id=5 на вторник ===")
    rows2 = await db.fetch("""
        SELECT w.menu_item, w.category,
               wm.name, wm.price
        FROM weekly_orders w
        LEFT JOIN weekly_menu wm ON wm.day_of_week = w.day_of_week 
            AND wm.item_number = w.menu_item 
            AND wm.category = w.category
        WHERE w.user_id = 5 AND w.day_of_week = 1
    """)
    for r in rows2:
        print(dict(r))
    
    await db.close()

asyncio.run(check())
