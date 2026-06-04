import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from database.db import init_db
from handlers import register_all_handlers
from scheduler.jobs import setup_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    await init_db()
    logger.info("✅ База данных инициализирована")

    register_all_handlers(dp)
    logger.info("✅ Хендлеры зарегистрированы")

    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("✅ Планировщик запущен")

    logger.info("🚀 Бот запущен!")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())