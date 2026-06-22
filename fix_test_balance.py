"""Исправляет некорректный баланс тестового пользователя после бага"""
import asyncio
import asyncpg
import os

async def fix():
    db = await asyncpg.connect(os.getenv('DATABASE_URL'))
    
    # user_id=5, сейчас 45000, должно быть -45000
    await db.execute(
        "UPDATE user_balance SET balance = -45000 WHERE user_id = 5"
    )
    print("Баланс исправлен")
    
    row = await db.fetchrow("SELECT * FROM user_balance WHERE user_id = 5")
    print(dict(row))
    
    await db.close()

asyncio.run(fix())
