import asyncio
import hashlib
import hmac
import json
import logging
import os
from datetime import date, timedelta
from urllib.parse import parse_qsl

from aiohttp import web
from aiogram import Bot
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CLICK_SECRET_KEY = os.getenv("CLICK_SECRET_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_pool = None


async def get_pool():
    global _pool
    if _pool is None:
        import asyncpg
        _pool = await asyncpg.create_pool(DATABASE_URL)
    return _pool


async def add_balance(user_db_id: int, amount: int, description: str, click_trans_id: str):
    pool = await get_pool()
    async with pool.acquire() as db:
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
    if request.method == "GET":
        return web.Response(text="Click Prepare endpoint OK")

    try:
        data = await request.json()
        logger.info(f"[PREPARE] Received: {data}")

        click_trans_id = data.get("click_trans_id")
        service_id = data.get("service_id")
        merchant_trans_id = data.get("merchant_trans_id")
        amount = float(data.get("amount", 0))
        sign_time = data.get("sign_time")
        sign_string = data.get("sign_string")

        my_sign = hashlib.md5(
            f"{click_trans_id}{service_id}{CLICK_SECRET_KEY}{merchant_trans_id}{amount}{1}{sign_time}".encode()
        ).hexdigest()

        if my_sign != sign_string:
            logger.error(f"[PREPARE] Sign mismatch!")
            return web.json_response({"error": -1, "error_note": "SIGN CHECK FAILED!"})

        parts = str(merchant_trans_id).split("_")
        if len(parts) < 3 or parts[0] != "balance":
            return web.json_response({"error": -5, "error_note": "User does not exist"})

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

        my_sign = hashlib.md5(
            f"{click_trans_id}{service_id}{CLICK_SECRET_KEY}{merchant_trans_id}{merchant_prepare_id}{amount}{2}{sign_time}".encode()
        ).hexdigest()

        if my_sign != sign_string:
            logger.error(f"[COMPLETE] Sign mismatch!")
            return web.json_response({"error": -1, "error_note": "SIGN CHECK FAILED!"})

        if error < 0:
            return web.json_response({
                "click_trans_id": int(click_trans_id),
                "merchant_trans_id": merchant_trans_id,
                "merchant_confirm_id": 1,
                "error": 0,
                "error_note": "Payment cancelled by user"
            })

        parts = str(merchant_trans_id).split("_")
        if len(parts) >= 3 and parts[0] == "balance":
            user_db_id = int(parts[1])
            amount_sum = int(float(amount))

            added = await add_balance(user_db_id, amount_sum, "Пополнение через Click", click_trans_id)

            if added:
                logger.info(f"[COMPLETE] Balance +{amount_sum} added to user_db_id={user_db_id}")
                try:
                    pool = await get_pool()
                    async with pool.acquire() as db:
                        row = await db.fetchrow(
                            "SELECT telegram_id, lang FROM users WHERE id = $1", user_db_id
                        )
                    if row:
                        await notify_user(row["telegram_id"], amount_sum, row.get("lang", "ru"))
                except Exception as e:
                    logger.error(f"[COMPLETE] Notify error: {e}")
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


# ─── Mini App API ───────────────────────────────────────────────────────────

async def verify_telegram_init_data(init_data: str, bot_token: str) -> dict | None:
    """
    Проверяет подпись initData от Telegram WebApp (классический HMAC метод).
    ВАЖНО: из data_check_string исключаются оба поля — 'hash' и 'signature'
    (signature — это Ed25519 подпись для нового метода верификации,
    она не участвует в HMAC-проверке и должна быть удалена перед проверкой).
    """
    try:
        if not init_data:
            return None

        parsed = dict(parse_qsl(init_data))
        received_hash = parsed.pop("hash", None)
        parsed.pop("signature", None)  # не участвует в HMAC data_check_string

        if not received_hash:
            return None

        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed.items())
        )

        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        computed_hash = hmac.new(
            secret_key, data_check_string.encode(), hashlib.sha256
        ).hexdigest()

        if computed_hash != received_hash:
            logger.warning(
                f"initData hash mismatch.\n"
                f"  data_check_string={data_check_string!r}\n"
                f"  computed={computed_hash}\n"
                f"  received={received_hash}"
            )
            return None

        user_data = json.loads(parsed.get("user", "{}"))
        return user_data
    except Exception as e:
        logger.error(f"initData verification error: {e}")
        return None


def cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, X-Init-Data",
    }


async def handle_webapp_menu(request):
    """POST /api/menu — отдаёт меню на завтра + баланс пользователя.
    init_data передаётся как RAW текст в теле запроса (Content-Type: text/plain),
    без JSON-обёртки — чтобы избежать изменения экранирования спецсимволов
    (JSON.stringify в браузере может убрать обратные слеши внутри user=,
    что ломает HMAC-подпись при проверке на сервере)."""
    try:
        if request.method == "GET":
            init_data = request.query.get("init_data", "")
        else:
            raw_body = await request.read()
            init_data = raw_body.decode("utf-8")

        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)

        if not user_data:
            return web.json_response({"error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")

        pool = await get_pool()
        async with pool.acquire() as db:
            user = await db.fetchrow(
                "SELECT id FROM users WHERE telegram_id = $1", telegram_id
            )
            if not user:
                return web.json_response(
                    {"error": "User not registered. Напишите /start боту."},
                    status=404, headers=cors_headers()
                )

            user_db_id = user["id"]

            balance_row = await db.fetchrow(
                "SELECT balance FROM user_balance WHERE user_id = $1", user_db_id
            )
            balance = balance_row["balance"] if balance_row else 0

            tomorrow = str(date.today() + timedelta(days=1))

            menu_rows = await db.fetch(
                """SELECT id, item_number, name, price, photo_id, category
                   FROM menus WHERE menu_date = $1::text AND is_active = 1
                   ORDER BY category, item_number""",
                tomorrow
            )

            if not menu_rows:
                from datetime import date as date_cls
                day_num = date_cls.fromisoformat(tomorrow).weekday()
                weekly_rows = await db.fetch(
                    """SELECT item_number, name, price, photo_id, category
                       FROM weekly_menu WHERE day_of_week = $1 AND is_active = 1
                       ORDER BY category, item_number""",
                    day_num
                )
                categories = {"main": [], "salad": [], "dessert": [], "drink": []}
                for i, row in enumerate(weekly_rows):
                    cat = row["category"] or "main"
                    categories.setdefault(cat, []).append({
                        "id": f"weekly_{day_num}_{row['item_number']}_{cat}",
                        "item_number": row["item_number"],
                        "name": row["name"],
                        "price": row["price"],
                        "photo_url": None
                    })
            else:
                categories = {"main": [], "salad": [], "dessert": [], "drink": []}
                for row in menu_rows:
                    cat = row["category"] or "main"
                    categories.setdefault(cat, []).append({
                        "id": row["id"],
                        "item_number": row["item_number"],
                        "name": row["name"],
                        "price": row["price"],
                        "photo_url": None
                    })

        return web.json_response({
            "categories": categories,
            "balance": balance,
            "date_label": tomorrow
        }, headers=cors_headers())

    except Exception as e:
        logger.error(f"webapp_menu error: {e}")
        return web.json_response({"error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_order(request):
    """POST /api/order — принимает заказ из Mini App.
    init_data передаётся в заголовке X-Init-Data (raw, без модификации),
    items — в JSON теле запроса."""
    try:
        init_data = request.headers.get("X-Init-Data", "")
        data = await request.json()
        items = data.get("items", [])

        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response(
                {"success": False, "error": "Invalid auth"}, status=401, headers=cors_headers()
            )

        telegram_id = user_data.get("id")

        if not items:
            return web.json_response(
                {"success": False, "error": "Корзина пуста"}, headers=cors_headers()
            )

        pool = await get_pool()
        tomorrow = str(date.today() + timedelta(days=1))

        async with pool.acquire() as db:
            user = await db.fetchrow(
                "SELECT id, company_id FROM users WHERE telegram_id = $1", telegram_id
            )
            if not user:
                return web.json_response(
                    {"success": False, "error": "Сначала напишите /start боту"},
                    status=404, headers=cors_headers()
                )

            user_db_id = user["id"]
            order_summaries = []
            total_amount = 0
            orders_created = 0

            for entry in items:
                menu_id = entry.get("menu_id")
                qty = entry.get("qty", 1)

                if isinstance(menu_id, str) and menu_id.startswith("weekly_"):
                    _, day_num, item_number, cat = menu_id.split("_")
                    menu_item = await db.fetchrow(
                        """SELECT item_number, name, price, photo_id, category
                           FROM weekly_menu
                           WHERE day_of_week = $1 AND item_number = $2 AND category = $3""",
                        int(day_num), int(item_number), cat
                    )
                    if not menu_item:
                        continue
                    real_row = await db.fetchrow(
                        """INSERT INTO menus (menu_date, item_number, name, description, price, photo_id, category)
                           VALUES ($1, $2, $3, '', $4, $5, $6)
                           ON CONFLICT (menu_date, item_number, category) DO UPDATE SET name = EXCLUDED.name
                           RETURNING id, name, price""",
                        tomorrow, menu_item["item_number"], menu_item["name"],
                        menu_item["price"], menu_item["photo_id"], menu_item["category"]
                    )
                    real_menu_id = real_row["id"]
                    item_name = real_row["name"]
                    item_price = real_row["price"]
                else:
                    menu_item = await db.fetchrow(
                        "SELECT id, name, price FROM menus WHERE id = $1", int(menu_id)
                    )
                    if not menu_item:
                        continue
                    real_menu_id = menu_item["id"]
                    item_name = menu_item["name"]
                    item_price = menu_item["price"]

                for _ in range(qty):
                    await db.execute(
                        """INSERT INTO orders (user_id, menu_id, order_date, status)
                           VALUES ($1, $2, $3::text, 'pending')""",
                        user_db_id, real_menu_id, tomorrow
                    )
                    orders_created += 1

                total_amount += item_price * qty
                order_summaries.append(f"{item_name} x{qty}")

            if orders_created > 0:
                await db.execute(
                    """UPDATE users SET total_orders = total_orders + 1, points = points + 5
                       WHERE id = $1""",
                    user_db_id
                )
                if user["company_id"]:
                    await db.execute(
                        "UPDATE companies SET total_orders = total_orders + 1 WHERE id = $1",
                        user["company_id"]
                    )

            balance_row = await db.fetchrow(
                "SELECT balance FROM user_balance WHERE user_id = $1", user_db_id
            )
            current_balance = balance_row["balance"] if balance_row else 0
            deducted = current_balance >= total_amount and total_amount > 0

            if deducted:
                await db.execute(
                    """INSERT INTO user_balance (user_id, balance) VALUES ($1, $2)
                       ON CONFLICT (user_id) DO UPDATE SET balance = user_balance.balance - $2""",
                    user_db_id, total_amount
                )
                await db.execute(
                    """INSERT INTO balance_transactions (user_id, amount, type, description)
                       VALUES ($1, $2, 'debit', $3)""",
                    user_db_id, total_amount, f"Заказ через Mini App|{tomorrow}"
                )

        try:
            bot = Bot(token=BOT_TOKEN)
            items_text = "\n".join(f"• {s}" for s in order_summaries)
            balance_text = (
                f"\n💳 Списано: {total_amount:,} сум" if deducted
                else f"\n💳 Оплата при получении: {total_amount:,} сум"
            )
            await bot.send_message(
                telegram_id,
                f"✅ *Заказ оформлен через Mini App!*\n\n{items_text}{balance_text}\n\n"
                f"📅 Доставка завтра, {tomorrow}",
                parse_mode="Markdown"
            )
            await bot.session.close()
        except Exception as e:
            logger.error(f"Order notify error: {e}")

        return web.json_response({"success": True}, headers=cors_headers())

    except Exception as e:
        logger.error(f"webapp_order error: {e}")
        return web.json_response(
            {"success": False, "error": str(e)}, status=500, headers=cors_headers()
        )


async def handle_options(request):
    return web.Response(headers=cors_headers())


async def create_app():
    app = web.Application()

    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)

    app.router.add_get("/click/prepare", handle_click_prepare)
    app.router.add_post("/click/prepare", handle_click_prepare)
    app.router.add_get("/click/complete", handle_click_complete)
    app.router.add_post("/click/complete", handle_click_complete)

    app.router.add_get("/api/menu", handle_webapp_menu)
    app.router.add_post("/api/menu", handle_webapp_menu)
    app.router.add_post("/api/order", handle_webapp_order)
    app.router.add_route("OPTIONS", "/api/menu", handle_options)
    app.router.add_route("OPTIONS", "/api/order", handle_options)

    webapp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp")
    if os.path.isdir(webapp_dir):
        app.router.add_static("/webapp/", webapp_dir, show_index=False)
        logger.info(f"✅ Статика Mini App раздаётся из {webapp_dir}")
    else:
        logger.warning(f"⚠️ Папка webapp не найдена: {webapp_dir}")

    return app


if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    loop = asyncio.get_event_loop()
    app = loop.run_until_complete(create_app())
    logger.info(f"🚀 Webhook server starting on port {port}")
    web.run_app(app, host="0.0.0.0", port=port)
