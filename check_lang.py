import asyncio
import aiosqlite

async def main():
    async with aiosqlite.connect("lunch_bot.db") as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT telegram_id, full_name, lang FROM users") as cursor:
            users = await cursor.fetchall()
            for u in users:
                print(f"{u['full_name']} — lang: {u['lang']}")

asyncio.run(main())