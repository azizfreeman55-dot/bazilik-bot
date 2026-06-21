"""Очищает тестовые заказы для конкретного пользователя на конкретную дату"""
import asyncio
import asyncpg
import os

async def clear():
    db = await asyncpg.connect(os.getenv('DATABASE_URL'))
    
    telegram_id = 7796034681  # ваш ID
    order_date = "2026-06-22"  # завтра
    
    result = await db.fetch(
        """UPDATE orders SET status = 'cancelled'
           WHERE user_id = (SELECT id FROM users WHERE telegram_id = $1)
           AND order_date = $2
           RETURNING id""",
        telegram_id, order_date
    )
    print(f"Отменено заказов: {len(result)}")
    
    await db.close()

asyncio.run(clear())
