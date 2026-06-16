import asyncio
import asyncpg
import os

async def fix():
    db = await asyncpg.connect(os.getenv('DATABASE_URL'))
    
    # Удаляем старый constraint
    await db.execute("""
        ALTER TABLE menus DROP CONSTRAINT IF EXISTS menus_menu_date_item_number_key
    """)
    print("Старый constraint удалён")
    
    # Добавляем новый
    await db.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint 
                WHERE conname = 'menus_menu_date_item_number_category_key'
            ) THEN
                ALTER TABLE menus ADD CONSTRAINT menus_menu_date_item_number_category_key 
                UNIQUE (menu_date, item_number, category);
            END IF;
        END
        $$;
    """)
    print("Новый constraint добавлен!")
    await db.close()

asyncio.run(fix())
