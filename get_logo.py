import asyncio
from aiogram import Bot
from aiogram.types import FSInputFile
from dotenv import load_dotenv
import os

load_dotenv()

async def main():
    bot = Bot(token=os.getenv("BOT_TOKEN"))
    photo = await bot.send_photo(
        chat_id=int(os.getenv("ADMIN_IDS")),
        photo=FSInputFile("logo.jpg")
    )
    print("LOGO_ID =", photo.photo[-1].file_id)
    await bot.session.close()

asyncio.run(main())