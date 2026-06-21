import asyncio
import hashlib
import hmac
import json
import logging
import os
from datetime import date, timedelta

from aiohttp import web
from aiogram import Bot
from dotenv import load_dotenv
from init_data_py import InitData

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CLICK_SECRET_KEY = os.getenv("CLICK_SECRET_KEY")
CLICK_SERVICE_ID = os.getenv("CLICK_SERVICE_ID")
CLICK_MERCHANT_ID = os.getenv("CLICK_MERCHANT_ID")
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


# ─── Mini App: авторизация ─────────────────────────────────────────────────────

async def verify_telegram_init_data(init_data: str, bot_token: str) -> dict | None:
    """Проверяет подпись initData используя проверенную библиотеку init-data-py."""
    try:
        if not init_data or not init_data.strip():
            logger.warning("initData is empty")
            return None
        parsed_init_data = InitData.parse(init_data)
        is_valid = parsed_init_data.validate(bot_token, lifetime=86400)
        if not is_valid:
            logger.warning("initData validation failed")
            return None
        if not parsed_init_data.user:
            return None
        return {
            "id": parsed_init_data.user.id,
            "first_name": parsed_init_data.user.first_name,
            "last_name": parsed_init_data.user.last_name or "",
        }
    except Exception as e:
        logger.error(f"initData verification error: {e} | init_data preview: {init_data[:80]!r}")
        return None


def cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, X-Init-Data",
    }


async def get_init_data_from_request(request) -> str:
    """Достаёт init_data либо из заголовка X-Init-Data, либо из тела (text/plain)"""
    header_val = request.headers.get("X-Init-Data", "")
    if header_val:
        return header_val
    raw = await request.read()
    return raw.decode("utf-8")


# ─── Mini App: меню ─────────────────────────────────────────────────────────────

async def handle_webapp_menu(request):
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        pool = await get_pool()
        async with pool.acquire() as db:
            user = await db.fetchrow("SELECT id FROM users WHERE telegram_id = $1", telegram_id)
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
                day_num = date.fromisoformat(tomorrow).weekday()
                weekly_rows = await db.fetch(
                    """SELECT item_number, name, price, photo_id, category
                       FROM weekly_menu WHERE day_of_week = $1 AND is_active = 1
                       ORDER BY category, item_number""",
                    day_num
                )
                categories = {"main": [], "salad": [], "dessert": [], "drink": []}
                for row in weekly_rows:
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
    try:
        init_data = await get_init_data_from_request(request) if request.headers.get("X-Init-Data") else ""
        if not init_data:
            init_data = request.headers.get("X-Init-Data", "")
        body = await request.json()
        items = body.get("items", [])

        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"success": False, "error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        if not items:
            return web.json_response({"success": False, "error": "Корзина пуста"}, headers=cors_headers())

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
                    "UPDATE users SET total_orders = total_orders + 1, points = points + 5 WHERE id = $1",
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
        return web.json_response({"success": False, "error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_my_order(request):
    """POST /api/my-order — список позиций текущего заказа на завтра"""
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        tomorrow = str(date.today() + timedelta(days=1))

        pool = await get_pool()
        async with pool.acquire() as db:
            rows = await db.fetch(
                """SELECT o.id, o.status, m.name as meal_name, m.category, m.price
                   FROM orders o
                   JOIN users u ON o.user_id = u.id
                   JOIN menus m ON o.menu_id = m.id
                   WHERE u.telegram_id = $1 AND o.order_date = $2::text
                   AND o.status != 'cancelled'
                   ORDER BY m.category, m.item_number""",
                telegram_id, tomorrow
            )

        items = [dict(r) for r in rows]
        total = sum(i["price"] for i in items)

        return web.json_response({
            "items": items,
            "total": total,
            "date_label": tomorrow
        }, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_my_order error: {e}")
        return web.json_response({"error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_cancel_order(request):
    """POST /api/cancel-order — отменить весь заказ на завтра"""
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"success": False, "error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        tomorrow = str(date.today() + timedelta(days=1))

        pool = await get_pool()
        async with pool.acquire() as db:
            user = await db.fetchrow("SELECT id FROM users WHERE telegram_id = $1", telegram_id)
            if not user:
                return web.json_response({"success": False, "error": "User not found"}, status=404, headers=cors_headers())

            debit_marker = f"|{tomorrow}"
            refund_marker = f"REFUND|{tomorrow}"

            already_refunded = await db.fetchrow(
                """SELECT id FROM balance_transactions
                   WHERE user_id = $1 AND type = 'credit'
                   AND description LIKE '%' || $2 || '%'""",
                user["id"], refund_marker
            )
            refund_amount = 0
            if not already_refunded:
                refund_amount = await db.fetchval(
                    """SELECT COALESCE(SUM(amount), 0) FROM balance_transactions
                       WHERE user_id = $1 AND type = 'debit'
                       AND description LIKE '%' || $2""",
                    user["id"], debit_marker
                ) or 0

            cancelled = await db.fetch(
                """UPDATE orders SET status = 'cancelled'
                   WHERE user_id = $1 AND order_date = $2::text AND status = 'pending'
                   RETURNING id""",
                user["id"], tomorrow
            )
            cancelled_count = len(cancelled)

            if cancelled_count > 0:
                await db.execute(
                    "UPDATE users SET total_orders = total_orders - 1, points = points - 5 WHERE id = $1",
                    user["id"]
                )

            if refund_amount > 0:
                await db.execute(
                    """INSERT INTO user_balance (user_id, balance) VALUES ($1, $2)
                       ON CONFLICT (user_id) DO UPDATE SET balance = user_balance.balance + $2""",
                    user["id"], refund_amount
                )
                await db.execute(
                    """INSERT INTO balance_transactions (user_id, amount, type, description)
                       VALUES ($1, $2, 'credit', $3)""",
                    user["id"], refund_amount, f"Возврат за отмену заказа | {refund_marker}"
                )

        return web.json_response({
            "success": True,
            "cancelled_count": cancelled_count,
            "refund_amount": refund_amount
        }, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_cancel_order error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_profile(request):
    """POST /api/profile — профиль пользователя"""
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        pool = await get_pool()
        async with pool.acquire() as db:
            user = await db.fetchrow(
                """SELECT u.*, c.name as company_name FROM users u
                   LEFT JOIN companies c ON u.company_id = c.id
                   WHERE u.telegram_id = $1""",
                telegram_id
            )
            if not user:
                return web.json_response({"error": "User not registered"}, status=404, headers=cors_headers())

            balance_row = await db.fetchrow(
                "SELECT balance FROM user_balance WHERE user_id = $1", user["id"]
            )
            balance = balance_row["balance"] if balance_row else 0

        return web.json_response({
            "full_name": user["full_name"],
            "phone": user["phone"],
            "company_name": user["company_name"],
            "points": user["points"],
            "total_orders": user["total_orders"],
            "status": user["status"],
            "balance": balance,
            "referral_code": user["referral_code"],
        }, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_profile error: {e}")
        return web.json_response({"error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_rating(request):
    """POST /api/rating — топ компаний за месяц"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            rows = await db.fetch(
                """SELECT c.name, c.total_orders,
                   (SELECT COUNT(*) FROM orders o
                    JOIN users u ON o.user_id = u.id
                    WHERE u.company_id = c.id
                    AND to_char(o.created_at, 'YYYY-MM') = to_char(NOW(), 'YYYY-MM')) as month_orders
                   FROM companies c
                   ORDER BY month_orders DESC LIMIT 10"""
            )
        return web.json_response({
            "companies": [dict(r) for r in rows]
        }, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_rating error: {e}")
        return web.json_response({"error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_balance_history(request):
    """POST /api/balance-history — баланс + история транзакций"""
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        pool = await get_pool()
        async with pool.acquire() as db:
            user = await db.fetchrow("SELECT id FROM users WHERE telegram_id = $1", telegram_id)
            if not user:
                return web.json_response({"error": "User not registered"}, status=404, headers=cors_headers())

            balance_row = await db.fetchrow(
                "SELECT balance FROM user_balance WHERE user_id = $1", user["id"]
            )
            balance = balance_row["balance"] if balance_row else 0

            history = await db.fetch(
                """SELECT amount, type, description, created_at FROM balance_transactions
                   WHERE user_id = $1 ORDER BY created_at DESC LIMIT 20""",
                user["id"]
            )

        history_list = []
        for h in history:
            desc = h["description"] or ""
            clean_desc = desc.split("|")[0].strip()
            history_list.append({
                "amount": h["amount"],
                "type": h["type"],
                "description": clean_desc,
                "date": h["created_at"].strftime("%d.%m")
            })

        return web.json_response({
            "balance": balance,
            "history": history_list
        }, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_balance_history error: {e}")
        return web.json_response({"error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_topup(request):
    """POST /api/topup — генерирует ссылку Click для пополнения баланса"""
    try:
        init_data = await get_init_data_from_request(request)
        body = await request.json() if request.has_body else {}
        amount = body.get("amount", 0)

        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"error": "Invalid auth"}, status=401, headers=cors_headers())

        if not amount or amount < 1000:
            return web.json_response({"error": "Минимальная сумма — 1000 сум"}, headers=cors_headers())

        telegram_id = user_data.get("id")
        pool = await get_pool()
        async with pool.acquire() as db:
            user = await db.fetchrow("SELECT id FROM users WHERE telegram_id = $1", telegram_id)
            if not user:
                return web.json_response({"error": "User not registered"}, status=404, headers=cors_headers())

        order_id = f"balance_{user['id']}_{amount}"
        click_link = (
            f"https://my.click.uz/services/pay?"
            f"service_id={CLICK_SERVICE_ID}"
            f"&merchant_id={CLICK_MERCHANT_ID}"
            f"&amount={amount}"
            f"&transaction_param={order_id}"
            f"&return_url=https://t.me/BazilikCateringBot"
        )

        return web.json_response({"click_link": click_link}, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_topup error: {e}")
        return web.json_response({"error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_gifts(request):
    """POST /api/gifts — список подарков с прогрессом по баллам"""
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        pool = await get_pool()
        async with pool.acquire() as db:
            user = await db.fetchrow("SELECT points FROM users WHERE telegram_id = $1", telegram_id)
            if not user:
                return web.json_response({"error": "User not registered"}, status=404, headers=cors_headers())

        points = user["points"]
        gifts = [
            {"id": "drink", "points": 50, "emoji": "🥤", "name": "Напиток",
             "desc": "Освежающий напиток на выбор к вашему обеду!"},
            {"id": "dessert", "points": 100, "emoji": "🍰", "name": "Десерт",
             "desc": "Вкусный десерт — сладкое завершение обеда!"},
            {"id": "lunch", "points": 200, "emoji": "🍱", "name": "Бесплатный обед",
             "desc": "Полноценный обед абсолютно бесплатно!"},
            {"id": "vip", "points": 500, "emoji": "👑", "name": "Статус VIP",
             "desc": "Особый статус с приоритетной доставкой и эксклюзивными бонусами!"},
        ]
        for g in gifts:
            g["unlocked"] = points >= g["points"]

        return web.json_response({
            "points": points,
            "gifts": gifts
        }, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_gifts error: {e}")
        return web.json_response({"error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_referral(request):
    """POST /api/referral — реферальный код + статистика приглашённых"""
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        pool = await get_pool()
        async with pool.acquire() as db:
            user = await db.fetchrow(
                "SELECT id, referral_code FROM users WHERE telegram_id = $1", telegram_id
            )
            if not user:
                return web.json_response({"error": "User not registered"}, status=404, headers=cors_headers())

            invited_count = await db.fetchval(
                "SELECT COUNT(*) FROM users WHERE referred_by = $1", user["id"]
            )

        return web.json_response({
            "referral_code": user["referral_code"],
            "invited_count": invited_count or 0,
            "bot_username": "BazilikCateringBot"
        }, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_referral error: {e}")
        return web.json_response({"error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_settings_get(request):
    """POST /api/settings — текущие настройки автозаказа и меню на неделю"""
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        pool = await get_pool()
        async with pool.acquire() as db:
            user = await db.fetchrow(
                "SELECT id, auto_order, lang FROM users WHERE telegram_id = $1", telegram_id
            )
            if not user:
                return web.json_response({"error": "User not registered"}, status=404, headers=cors_headers())

            weekly_rows = await db.fetch(
                """SELECT day_of_week, menu_item FROM weekly_orders
                   WHERE user_id = $1 AND is_active = 1""",
                user["id"]
            )
            weekly = {r["day_of_week"]: r["menu_item"] for r in weekly_rows}

        return web.json_response({
            "auto_order": bool(user["auto_order"]),
            "lang": user["lang"],
            "weekly": weekly
        }, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_settings_get error: {e}")
        return web.json_response({"error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_settings_toggle_auto(request):
    """POST /api/settings/toggle-auto — переключить автозаказ"""
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"success": False, "error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        pool = await get_pool()
        async with pool.acquire() as db:
            user = await db.fetchrow(
                "SELECT auto_order FROM users WHERE telegram_id = $1", telegram_id
            )
            if not user:
                return web.json_response({"success": False, "error": "User not found"}, status=404, headers=cors_headers())

            new_value = 0 if user["auto_order"] else 1
            await db.execute(
                "UPDATE users SET auto_order = $1 WHERE telegram_id = $2",
                new_value, telegram_id
            )

        return web.json_response({"success": True, "auto_order": bool(new_value)}, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_settings_toggle_auto error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_weekly_menu_for_day(request):
    """POST /api/settings/weekly-menu — меню на конкретный день недели (для выбора блюда)"""
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"error": "Invalid auth"}, status=401, headers=cors_headers())

        body = await request.json()
        day_of_week = body.get("day_of_week")
        if day_of_week is None:
            return web.json_response({"error": "day_of_week required"}, headers=cors_headers())

        from datetime import date as date_cls, timedelta as td_cls
        today = date_cls.today()
        days_ahead = (day_of_week - today.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        target_date = str(today + td_cls(days=days_ahead))

        pool = await get_pool()
        async with pool.acquire() as db:
            rows = await db.fetch(
                """SELECT id, item_number, name, price, category FROM menus
                   WHERE menu_date = $1::text AND is_active = 1
                   ORDER BY category, item_number""",
                target_date
            )
            if not rows:
                day_num = date_cls.fromisoformat(target_date).weekday()
                rows = await db.fetch(
                    """SELECT item_number, name, price, category FROM weekly_menu
                       WHERE day_of_week = $1 AND is_active = 1
                       ORDER BY category, item_number""",
                    day_num
                )

        items = [dict(r) for r in rows]
        return web.json_response({
            "items": items,
            "target_date": target_date
        }, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_weekly_menu_for_day error: {e}")
        return web.json_response({"error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_settings_set_weekly(request):
    """POST /api/settings/set-weekly — сохранить выбор блюда на день недели"""
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"success": False, "error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        body = await request.json()
        day_of_week = body.get("day_of_week")
        item_number = body.get("item_number")

        pool = await get_pool()
        async with pool.acquire() as db:
            user = await db.fetchrow("SELECT id FROM users WHERE telegram_id = $1", telegram_id)
            if not user:
                return web.json_response({"success": False, "error": "User not found"}, status=404, headers=cors_headers())

            if item_number is None:
                await db.execute(
                    "UPDATE weekly_orders SET is_active = 0 WHERE user_id = $1 AND day_of_week = $2",
                    user["id"], day_of_week
                )
            else:
                await db.execute(
                    """INSERT INTO weekly_orders (user_id, day_of_week, menu_item, is_active)
                       VALUES ($1, $2, $3, 1)
                       ON CONFLICT (user_id, day_of_week) DO UPDATE SET menu_item = $3, is_active = 1""",
                    user["id"], day_of_week, item_number
                )

        return web.json_response({"success": True}, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_settings_set_weekly error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500, headers=cors_headers())


async def handle_options(request):
    return web.Response(headers=cors_headers())


async def handle_webapp_static(request):
    """Отдаёт любой файл из папки webapp/ с заголовками no-cache."""
    webapp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp")
    filename = request.match_info.get("filename", "index.html")
    if not filename:
        filename = "index.html"
    file_path = os.path.join(webapp_dir, filename)

    if not os.path.isfile(file_path):
        return web.Response(text="Not found", status=404)

    content_type = "text/html"
    if filename.endswith(".js"):
        content_type = "application/javascript"
    elif filename.endswith(".css"):
        content_type = "text/css"

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    return web.Response(
        text=content,
        content_type=content_type,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )


async def create_app():
    app = web.Application()

    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)

    app.router.add_get("/click/prepare", handle_click_prepare)
    app.router.add_post("/click/prepare", handle_click_prepare)
    app.router.add_get("/click/complete", handle_click_complete)
    app.router.add_post("/click/complete", handle_click_complete)

    app.router.add_post("/api/menu", handle_webapp_menu)
    app.router.add_post("/api/order", handle_webapp_order)
    app.router.add_post("/api/my-order", handle_webapp_my_order)
    app.router.add_post("/api/cancel-order", handle_webapp_cancel_order)
    app.router.add_post("/api/profile", handle_webapp_profile)
    app.router.add_post("/api/rating", handle_webapp_rating)
    app.router.add_post("/api/balance-history", handle_webapp_balance_history)
    app.router.add_post("/api/topup", handle_webapp_topup)
    app.router.add_post("/api/gifts", handle_webapp_gifts)
    app.router.add_post("/api/referral", handle_webapp_referral)
    app.router.add_post("/api/settings", handle_webapp_settings_get)
    app.router.add_post("/api/settings/toggle-auto", handle_webapp_settings_toggle_auto)
    app.router.add_post("/api/settings/weekly-menu", handle_webapp_weekly_menu_for_day)
    app.router.add_post("/api/settings/set-weekly", handle_webapp_settings_set_weekly)

    for path in ["/api/menu", "/api/order", "/api/my-order", "/api/cancel-order",
                 "/api/profile", "/api/rating", "/api/balance-history", "/api/topup",
                 "/api/gifts", "/api/referral", "/api/settings",
                 "/api/settings/toggle-auto", "/api/settings/weekly-menu", "/api/settings/set-weekly"]:
        app.router.add_route("OPTIONS", path, handle_options)

    app.router.add_get("/webapp/{filename}", handle_webapp_static)
    app.router.add_get("/webapp/", handle_webapp_static)

    return app


if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    loop = asyncio.get_event_loop()
    app = loop.run_until_complete(create_app())
    logger.info(f"🚀 Webhook server starting on port {port}")
    web.run_app(app, host="0.0.0.0", port=port)
