"""Проверяет содержимое weekly_orders для диагностики проблемы с вторником"""
import asyncio
import asyncpg
import os

async def check():
    db = await asyncpg.connect(os.getenv('DATABASE_URL'))
    
    print("=== Содержимое weekly_orders ===")
    rows = await db.fetch("""
        SELECT w.id, w.user_id, w.day_of_week, w.menu_item, w.category, w.is_active,
               u.full_name, u.telegram_id
        FROM weekly_orders w
        JOIN users u ON w.user_id = u.id
        ORDER BY w.user_id, w.day_of_week, w.category
    """)
    for r in rows:
        print(dict(r))
    
    print()
    print("=== Constraint на таблице weekly_orders ===")
    constraints = await db.fetch("""
        SELECT conname, pg_get_constraintdef(oid) as definition
        FROM pg_constraint
        WHERE conrelid = 'weekly_orders'::regclass
    """)
    for c in constraints:
        print(dict(c))
    
    await db.close()

asyncio.run(check())
