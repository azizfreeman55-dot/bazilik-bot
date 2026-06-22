"""Диагностика - смотрим заказы и состояние paid/payment_method"""
import asyncio
import asyncpg
import os

async def check():
    db = await asyncpg.connect(os.getenv('DATABASE_URL'))
    
    print("=== Заказы на 2026-06-23 ===")
    rows = await db.fetch("""
        SELECT o.id, o.user_id, o.status, o.payment_method, o.paid,
               m.name, m.price, u.telegram_id, u.full_name, u.company_id
        FROM orders o
        JOIN users u ON o.user_id = u.id
        JOIN menus m ON o.menu_id = m.id
        WHERE o.order_date = '2026-06-23'
        ORDER BY o.id
    """)
    for r in rows:
        print(dict(r))
    
    print()
    print("=== Балансы ===")
    bal = await db.fetch("SELECT * FROM user_balance")
    for b in bal:
        print(dict(b))
    
    print()
    print("=== Последние транзакции ===")
    tx = await db.fetch("""
        SELECT * FROM balance_transactions 
        ORDER BY created_at DESC LIMIT 10
    """)
    for t in tx:
        print(dict(t))
    
    await db.close()

asyncio.run(check())
