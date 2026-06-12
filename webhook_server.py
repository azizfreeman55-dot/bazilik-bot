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

# Singleton pool — создаётся один раз при старте
_pool = None


async def get_pool():
    global _pool
    if _pool is None:
        import asyncpg
        _pool = await asyncpg.create_pool(DATABASE_URL)
    return _pool


async def add_balance(user_db_id: int, amount: int, description: str, click_trans_id: str):
    """
    Начисляет баланс пользователю.
    Защита от дублей: проверяем click_trans_id в таблице транзакций.
    Возвращает True если начислено, False если уже было начислено ранее.
    """
    pool = await get_pool()
    async with pool.acquire() as db:
        # Проверяем — не было ли уже такой транзакции
        existing = await db.fetchrow(
            "SELECT id FROM balance_transactions WHERE description LIKE $1",
            f"%click_trans:{click_trans_id}%"
        )
        if existing:
            logger.warning(f"Duplicate click_trans_id={click_trans_id}, skipping")
            return False

        await db.execute(
            """INSERT INTO user_balance (user_id, balance)
               VALUES ($1, $2)
               ON CONFLICT (user_id) DO UPDATE SET balance = user_balance.balance + $2,
               updated_at = CURRENT_TIMESTAMP""",
            user_db_id, amount
        )
        await db.execute(
            """INSERT INTO balance_transactions (user_id, amount, type, description)
               VALUES ($1, $2, 'credit', $3)""",
            user_db_id, amount,
            f"{description} | click_trans:{click_trans_id}"
        )
    return True


async def notify_user(telegram_id: int, amount: int, lang: str = "ru"):
    """Отправляет уведомление пользователю о пополнении баланса"""
    try:
        bot = Bot(token=BOT_TOKEN)
        if lang == "uz":
            text = (
                f"✅ *Hisob toʻldirildi!*\n\n"
                f"💰 *+{amount:,} so'm*\n\n"
                f"Click orqali toʻlov uchun rahmat! 🎉"
            )
        else:
            text = (
                f"✅ *Баланс пополнен!*\n\n"
                f"💰 *+{amount:,} сум*\n\n"
                f"Спасибо за оплату через Click! 🎉"
            )
        await bot.send_message(telegram_id, text, parse_mode="Markdown")
        await bot.session.close()
    except Exception as e:
        logger.error(f"Notify error for telegram_id={telegram_id}: {e}")


async def handle_health(request):
    return web.Response(text="OK")


async def handle_click_prepare(request):
    """
    Click Prepare (action=1) — проверяем что заказ существует и можем его принять.
    Click вызывает это ПЕРЕД тем как списать деньги с пользователя.
    """
    if request.method == "GET":
        return web.Response(text="Click Prepare endpoint OK")

    try:
        data = await request.json()
        logger.info(f"[PREPARE] Received: {data}")

        click_trans_id = data.get("click_trans_id")
        service_id = data.get("service_id")
        merchant_trans_id = data.get("merchant_trans_id")  # наш order_id
        amount = float(data.get("amount", 0))
        sign_time = data.get("sign_time")
        sign_string = data.get("sign_string")

        # Проверяем подпись (action=1 для Prepare)
        my_sign = hashlib.md5(
            f"{click_trans_id}{service_id}{CLICK_SECRET_KEY}{merchant_trans_id}{amount}{1}{sign_time}".encode()
        ).hexdigest()

        logger.info(f"[PREPARE] Sign: mine={my_sign}, received={sign_string}")

        if my_sign != sign_string:
            logger.error(f"[PREPARE] Sign mismatch!")
            return web.json_response({
                "error": -1,
                "error_note": "SIGN CHECK FAILED!"
            })

        # Проверяем что merchant_trans_id корректный формат
        parts = str(merchant_trans_id).split("_")
        if len(parts) < 3 or parts[0] != "balance":
            return web.json_response({
                "error": -5,
                "error_note": "User does not exist"
            })

        return web.json_response({
            "click_trans_id": int(click_trans_id),
            "merchant_trans_id": merchant_trans_id,
            "merchant_prepare_id": merchant_trans_id,
            "error": 0,
            "error_note": "Success"
        })

    except Exception as e:
        logger.error(f"[PREPARE] Exception: {e}")
        return web.json_response({"error": -9, "error_note": str(e)})


async def handle_click_complete(request):
    """
    Click Complete (action=2) — деньги списаны, начисляем баланс пользователю.
    Click вызывает это ПОСЛЕ успешной оплаты.
    """
    if request.method == "GET":
        return web.Response(text="Click Complete endpoint OK")

    try:
        data = await request.json()
        logger.info(f"[COMPLETE] Received: {data}")

        click_trans_id = str(data.get("click_trans_id"))
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

        logger.info(f"[COMPLETE] Sign: mine={my_sign}, received={sign_string}")

        if my_sign != sign_string:
            logger.error(f"[COMPLETE] Sign mismatch!")
            return web.json_response({
                "error": -1,
                "error_note": "SIGN CHECK FAILED!"
            })

        # Если оплата отменена или ошибка — не начисляем
        if error < 0:
            logger.info(f"[COMPLETE] Payment cancelled/error: {error}")
            return web.json_response({
                "click_trans_id": int(click_trans_id),
                "merchant_trans_id": merchant_trans_id,
                "merchant_confirm_id": 1,
                "error": 0,
                "error_note": "Payment cancelled by user"
            })

        # Парсим merchant_trans_id: "balance_{user_db_id}_{amount}"
        parts = str(merchant_trans_id).split("_")
        logger.info(f"[COMPLETE] Transaction parts: {parts}")

        if len(parts) >= 3 and parts[0] == "balance":
            user_db_id = int(parts[1])
            amount_sum = int(float(amount))

            # Начисляем баланс (с защитой от дублей)
            added = await add_balance(
                user_db_id, amount_sum,
                "Пополнение через Click",
                click_trans_id
            )

            if added:
                logger.info(f"[COMPLETE] Balance +{amount_sum} added to user_db_id={user_db_id}")

                # Получаем telegram_id и язык для уведомления
                try:
                    pool = await get_pool()
                    async with pool.acquire() as db:
                        row = await db.fetchrow(
                            "SELECT telegram_id, lang FROM users WHERE id = $1",
                            user_db_id
                        )
                    if row:
                        await notify_user(row["telegram_id"], amount_sum, row.get("lang", "ru"))
                except Exception as e:
                    logger.error(f"[COMPLETE] Notify error: {e}")
            else:
                logger.info(f"[COMPLETE] Duplicate transaction, already processed")
        else:
            logger.error(f"[COMPLETE] Invalid merchant_trans_id format: {merchant_trans_id}")
            return web.json_response({"error": -5, "error_note": "User does not exist"})

        return web.json_response({
            "click_trans_id": int(click_trans_id),
            "merchant_trans_id": merchant_trans_id,
            "merchant_confirm_id": 1,
            "error": 0,
            "error_note": "Success"
        })

    except Exception as e:
        logger.error(f"[COMPLETE] Exception: {e}")
        return web.json_response({"error": -9, "error_note": str(e)})


async def create_app():
    app = web.Application()

    # Health check
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)

    # Click endpoints — поддерживаем и GET и POST
    app.router.add_get("/click/prepare", handle_click_prepare)
    app.router.add_post("/click/prepare", handle_click_prepare)
    app.router.add_get("/click/complete", handle_click_complete)
    app.router.add_post("/click/complete", handle_click_complete)

    return app


if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    loop = asyncio.get_event_loop()
    app = loop.run_until_complete(create_app())
    logger.info(f"🚀 Webhook server starting on port {port}")
    web.run_app(app, host="0.0.0.0", port=port)
