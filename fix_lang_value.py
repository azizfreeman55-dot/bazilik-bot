"""Исправляет устаревшее значение lang='uz' на правильное lang='ru' (или uz_latin по желанию)"""
import asyncio
import asyncpg
import os

async def fix():
    db = await asyncpg.connect(os.getenv('DATABASE_URL'))
    
    # Меняем устаревшее 'uz' на 'ru' для вашего тестового аккаунта,
    # так как весь остальной интерфейс у вас фактически был на русском
    result = await db.execute(
        "UPDATE users SET lang = 'ru' WHERE lang = 'uz'"
    )
    print("Обновлено:", result)
    
    rows = await db.fetch("SELECT id, telegram_id, full_name, lang FROM users ORDER BY id")
    for r in rows:
        print(dict(r))
    
    await db.close()

asyncio.run(fix())
