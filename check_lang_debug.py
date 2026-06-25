"""Проверяет реальный lang в БД для пользователей"""
import asyncio
import asyncpg
import os

async def check():
    db = await asyncpg.connect(os.getenv('DATABASE_URL'))
    
    rows = await db.fetch("""
        SELECT id, telegram_id, full_name, lang
        FROM users
        ORDER BY id
    """)
    for r in rows:
        print(dict(r))
    
    await db.close()

asyncio.run(check())
