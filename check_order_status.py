"""Проверяет статус заказов в БД"""
import asyncio
import asyncpg
import os

async def check():
    db = await asyncpg.connect(os.getenv('DATABASE_URL'))
    
    rows = await db.fetch("""
        SELECT o.id, o.status, o.order_date, m.name, u.telegram_id
        FROM orders o
        JOIN users u ON o.user_id = u.id
        JOIN menus m ON o.menu_id = m.id
        WHERE u.telegram_id = 7796034681
        ORDER BY o.id DESC
        LIMIT 10
    """)
    
    for r in rows:
        print(f"ID={r['id']} status='{r['status']}' date={r['order_date']} name={r['name']}")
    
    await db.close()

asyncio.run(check())
