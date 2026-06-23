"""Проверяет сохранён ли телефон у тестового пользователя"""
import asyncio
import asyncpg
import os

async def check():
    db = await asyncpg.connect(os.getenv('DATABASE_URL'))
    
    rows = await db.fetch("""
        SELECT id, telegram_id, full_name, phone
        FROM users
        ORDER BY id
    """)
    for r in rows:
        print(dict(r))
    
    await db.close()

asyncio.run(check())
