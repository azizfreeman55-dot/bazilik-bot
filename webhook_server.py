import asyncio
import hashlib
import logging
import os
from aiohttp import web
from aiogram import Bot
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CLICK_SECRET_KEY = os.getenv("CLICK_SECRET_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def get_pool():
    import asyncpg
    return await asyncpg.create_pool(DATABASE_URL)


async def add_balance(user_db_id: int, amount: int, description: str):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            """INSERT INTO user_balance (user_id, balance)
               VALUES ($1, $2)
               ON CONFLICT (user_id) DO UPDATE SET balance = user_balance.balance + $2""",
            user_db_id, amount
        )
        await db.execute(
            """INSERT INTO balance_transactions (user_id, amount, type, description)
               VALUES ($1, $2, 'credit', $3)""",
            user_db_id, amount, description
        )
    await pool.close()


async def handle_health(request):
    return web.Response(text="OK")


async def handle_click_prepare(request):
    if request.method == "GET":
        return web.Response(text="OK")

    try:
        data = await request.json()
        logger.info(f"Click Prepare received: {data}")

        click_trans_id = data.get("click_trans_id")
        service_id = data.get("service_id")
        merchant_trans_id = data.get("merchant_trans_id")
        amount = float(data.get("amount", 0))
        sign_time = data.get("sign_time")
        sign_string = data.get("sign_string")

        # Проверяем подпись (action=1 для Prepare)
        my_sign = hashlib.md5(
            f"{click_trans_id}{service_id}{CLICK_SECRET_KEY}{merchant_trans_id}{amount}{1}{sign_time}".encode()
        ).hexdigest()

        logger.info(f"Prepare sign check: my={my_sign}, received={sign_string}")

        if my_sign != sign_string:
            return web.json_response({
                "error": -1,
                "error_note": "SIGN CHECK FAILED!"
            })

        return web.json_response({
            "click_trans_id": int(click_trans_id),
            "merchant_trans_id": merchant_trans_id,
            "merchant_prepare_id": merchant_trans_id,
            "error": 0,
            "error_note": "Success"
        })

    except Exception as e:
        logger.error(f"Prepare error: {e}")
        return web.json_response({"error": -9, "error_note": str(e)})


async def handle_click_complete(request):
    if request.method == "GET":
        return web.Response(text="OK")

    try:
        data = await request.json()
        logger.info(f"Click Complete received: {data}")

        click_trans_id = data.get("click_trans_id")
        service_id = data.get("service_id")
        merchant_trans_id = data.get("merchant_trans_id")
        merchant_prepare_id = data.get("merchant_prepare_id")
        amount = float(data.get("amount", 0))
        sign_time = data.get("sign_time")
        sign_string = data.get("sign_string")
        error = int(data.get("error", 0))

        # Проверяем подпись (action=2 для Complete)
        my_sign = hashlib.md5(
            f"{click_trans_id}{service_id}{CLICK_SECRET_KEY}{merchant_trans_id}{merchant_prepare_id}{amount}{2}{sign_time}".encode()
        ).hexdigest()

        logger.info(f"Complete sign check: my={my_sign}, received={sign_string}")

        if my_sign != sign_string:
            return web.json_response({
                "error": -1,
                "error_note": "SIGN CHECK FAILED!"
            })

        if error < 0:
            return web.json_response({
                "error": 0,
                "error_note": "Payment cancelled"
            })

        # Парсим transaction_param: "balance_USER_ID_AMOUNT"
        parts = str(merchant_trans_id).split("_")
        logger.info(f"Transaction parts: {parts}")

        if len(parts) >= 3 and parts[0] == "balance":
            user_db_id = int(parts[1])
            amount_sum = int(float(amount))

            await add_balance(user_db_id, amount_sum, "Пополнение через Click")
            logger.info(f"Balance added: user={user_db_id}, amount={amount_sum}")

            # Уведомляем пользователя
            try:
                pool = await get_pool()
                async with pool.acquire() as db:
                    row = await db.fetchrow(
                        "SELECT telegram_id FROM users WHERE id = $1", user_db_id
                    )
                await pool.close()

                if row:
                    bot = Bot(token=BOT_TOKEN)
                    await bot.send_message(
                        row["telegram_id"],
                        f"✅ *Баланс пополнен!*\n\n"
                        f"💰 +{amount_sum:,} сум\n"
                        f"Спасибо за оплату через Click!",
                        parse_mode="Markdown"
                    )
                    await bot.session.close()
            except Exception as e:
                logger.error(f"Notify error: {e}")

        return web.json_response({
            "click_trans_id": int(click_trans_id),
            "merchant_trans_id": merchant_trans_id,
            "merchant_confirm_id": 1,
            "error": 0,
            "error_note": "Success"
        })

    except Exception as e:
        logger.error(f"Complete error: {e}")
        return web.json_response({"error": -9, "error_note": str(e)})


async def create_app():
    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_get("/click/prepare", handle_click_prepare)
    app.router.add_post("/click/prepare", handle_click_prepare)
    app.router.add_get("/click/complete", handle_click_complete)
    app.router.add_post("/click/complete", handle_click_complete)
    return app


if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    loop = asyncio.get_event_loop()
    app = loop.run_until_complete(create_app())
    web.run_app(app, host="0.0.0.0", port=port)
