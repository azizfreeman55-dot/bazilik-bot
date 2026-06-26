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
        # В системе используются lang='uz_latin' / 'uz_cyrillic' (см. langs.py),
        # а не просто 'uz'. Проверяем по префиксу, чтобы не дублировать рассинхрон
        # с функцией t() в langs.py, где простое 'uz' не существует как ключ
        # и поэтому случайно скатывается на русский текст по умолчанию.
        if lang and lang.startswith("uz"):
            text = (
                f"✅ *Hisob to'ldirildi!*\n\n"
                f"💰 *+{amount:,} so'm*\n\n"
                f"Click orqali to'lov uchun rahmat! 🎉"
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


WEBHOOK_BASE_URL = "https://bazilik-webhook.onrender.com"


def build_photo_url(photo_id: str | None) -> str | None:
    """Строит URL для proxy-эндпоинта /api/photo/{photo_id}, если photo_id есть."""
    if not photo_id:
        return None
    return f"{WEBHOOK_BASE_URL}/api/photo/{photo_id}"


async def handle_health(request):
    return web.Response(text="OK")


async def parse_click_request_data(request) -> dict:
    """
    Click Shop API отправляет данные как application/x-www-form-urlencoded,
    НЕ как JSON (несмотря на то, что в документации указан Content-Type: application/json
    для других продуктов Click — для классического Prepare/Complete вебхука это form-data).
    Эта функция надёжно читает оба варианта.
    """
    content_type = request.headers.get("Content-Type", "")
    raw_body = await request.read()
    logger.info(
        f"[CLICK DEBUG] Content-Type={content_type!r} "
        f"Query={dict(request.query)!r} "
        f"Raw body ({len(raw_body)} bytes)={raw_body[:500]!r}"
    )

    if raw_body:
        if "application/json" in content_type:
            try:
                import json
                return json.loads(raw_body)
            except Exception:
                pass
        try:
            from urllib.parse import parse_qsl
            parsed = dict(parse_qsl(raw_body.decode("utf-8")))
            if parsed:
                return parsed
        except Exception:
            pass

    # Click может прислать параметры через query string (GET-style) даже у POST-запроса
    if request.query:
        return dict(request.query)

    return {}


async def handle_click_prepare(request):
    if request.method == "GET":
        return web.Response(text="Click Prepare endpoint OK")
    try:
        data = await parse_click_request_data(request)
        logger.info(f"[PREPARE] Received: {data}")
        click_trans_id = data.get("click_trans_id")
        service_id = data.get("service_id")
        merchant_trans_id = data.get("merchant_trans_id")
        amount_raw = data.get("amount", "0")  # строка как пришла от Click — важно для подписи!
        sign_time = data.get("sign_time")
        sign_string = data.get("sign_string")

        my_sign = hashlib.md5(
            f"{click_trans_id}{service_id}{CLICK_SECRET_KEY}{merchant_trans_id}{amount_raw}{0}{sign_time}".encode()
        ).hexdigest()

        if my_sign != sign_string:
            logger.warning(
                f"[PREPARE] Sign mismatch. computed={my_sign} received={sign_string} "
                f"amount_raw={amount_raw!r}"
            )
            return web.json_response({"error": -1, "error_note": "SIGN CHECK FAILED!"})

        parts = str(merchant_trans_id).split("_")
        if len(parts) < 3 or parts[0] != "balance":
            return web.json_response({"error": -5, "error_note": "User does not exist"})

        # merchant_prepare_id должен быть ЧИСЛОМ (уникальный ID этой подготовки
        # платежа в нашей системе), а не строкой merchant_trans_id.
        # Используем сам click_trans_id — он уникален для каждой попытки оплаты
        # и уже числовой, поэтому отдельная таблица/счётчик не нужны.
        merchant_prepare_id = int(click_trans_id)

        response_data = {
            "click_trans_id": int(click_trans_id),
            "merchant_trans_id": merchant_trans_id,
            "merchant_prepare_id": merchant_prepare_id,
            "error": 0,
            "error_note": "Success"
        }
        logger.info(f"[PREPARE] Responding: {response_data}")
        return web.json_response(response_data)
    except Exception as e:
        logger.error(f"[PREPARE] Exception: {e}")
        return web.json_response({"error": -9, "error_note": str(e)})


async def handle_click_complete(request):
    if request.method == "GET":
        return web.Response(text="Click Complete endpoint OK")
    try:
        data = await parse_click_request_data(request)
        logger.info(f"[COMPLETE] Received: {data}")
        click_trans_id = str(data.get("click_trans_id"))
        service_id = data.get("service_id")
        merchant_trans_id = data.get("merchant_trans_id")
        merchant_prepare_id = data.get("merchant_prepare_id")
        amount_raw = data.get("amount", "0")  # строка как пришла от Click — важно для подписи!
        sign_time = data.get("sign_time")
        sign_string = data.get("sign_string")
        error = int(data.get("error", 0))

        my_sign = hashlib.md5(
            f"{click_trans_id}{service_id}{CLICK_SECRET_KEY}{merchant_trans_id}{merchant_prepare_id}{amount_raw}{1}{sign_time}".encode()
        ).hexdigest()

        if my_sign != sign_string:
            logger.warning(
                f"[COMPLETE] Sign mismatch. computed={my_sign} received={sign_string} "
                f"amount_raw={amount_raw!r}"
            )
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
            amount_sum = int(float(amount_raw))
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
    """
    Достаёт init_data из заголовка X-Init-Data.
    Используется всеми /api/* эндпоинтами Mini App — фронтенд всегда
    кладёт initData именно в этот заголовок (см. apiCall() в index.html).
    """
    return request.headers.get("X-Init-Data", "")


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
            day_num = date.fromisoformat(tomorrow).weekday()

            # Разовые позиции, которые уже реально существуют в menus на эту дату
            # (например, потому что кто-то уже сделал заказ — позиция автоматически
            # копируется из weekly_menu в menus в момент создания заказа).
            menu_rows = await db.fetch(
                """SELECT id, item_number, name, price, photo_id, category
                   FROM menus WHERE menu_date = $1::text AND is_active = 1
                   ORDER BY category, item_number""",
                tomorrow
            )
            existing_by_key = {(r["item_number"], r["category"]): r for r in menu_rows}

            # Полное постоянное меню на этот день недели — показываем ВСЕГДА,
            # независимо от того, сколько позиций уже скопировано в menus.
            # Раньше тут была ошибка: если в menus была хотя бы одна позиция
            # (потому что кто-то уже заказал), весь остальной weekly_menu пропадал
            # из каталога — и при попытке изменить заказ клиент видел только то,
            # что уже заказано.
            weekly_rows = await db.fetch(
                """SELECT item_number, name, price, photo_id, category
                   FROM weekly_menu WHERE day_of_week = $1 AND is_active = 1
                   ORDER BY category, item_number""",
                day_num
            )

            categories = {"first": [], "second": [], "salad": [], "dessert": [], "drink": []}

            if weekly_rows:
                for row in weekly_rows:
                    cat = row["category"] or "second"
                    key = (row["item_number"], cat)
                    existing = existing_by_key.get(key)
                    categories.setdefault(cat, []).append({
                        "id": existing["id"] if existing else f"weekly_{day_num}_{row['item_number']}_{cat}",
                        "item_number": row["item_number"],
                        "name": existing["name"] if existing else row["name"],
                        "price": existing["price"] if existing else row["price"],
                        "photo_url": build_photo_url(existing["photo_id"] if existing else row["photo_id"])
                    })
            else:
                # Нет постоянного меню на этот день недели вообще — показываем
                # только то, что реально есть в разовом menus (старое поведение).
                for row in menu_rows:
                    cat = row["category"] or "second"
                    categories.setdefault(cat, []).append({
                        "id": row["id"],
                        "item_number": row["item_number"],
                        "name": row["name"],
                        "price": row["price"],
                        "photo_url": build_photo_url(row["photo_id"])
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
        init_data = await get_init_data_from_request(request)
        body = await request.json()
        items = body.get("items", [])
        payment_method = body.get("payment_method", "auto")  # balance | cash | auto

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
                        """INSERT INTO orders (user_id, menu_id, order_date, status, payment_method)
                           VALUES ($1, $2, $3::text, 'pending', $4)""",
                        user_db_id, real_menu_id, tomorrow, payment_method
                    )
                    orders_created += 1

                total_amount += item_price * qty
                order_summaries.append(f"{item_name} x{qty}")

            streak_bonus_info = None
            if orders_created > 0:
                from datetime import date as date_cls, timedelta as td_cls
                today_str = str(date_cls.today())
                yesterday_str = str(date_cls.today() - td_cls(days=1))

                # Узнаём текущий streak ДО обновления, чтобы посчитать новый
                streak_row = await db.fetchrow(
                    "SELECT streak_days, last_order_date, last_streak_bonus FROM users WHERE id = $1",
                    user_db_id
                )
                current_streak = streak_row["streak_days"] or 0
                last_order = streak_row["last_order_date"]
                last_bonus_milestone = streak_row["last_streak_bonus"] or 0

                if last_order == yesterday_str:
                    new_streak = current_streak + 1
                elif last_order == today_str:
                    new_streak = current_streak
                else:
                    new_streak = 1

                await db.execute(
                    """UPDATE users SET total_orders = total_orders + 1, points = points + 5,
                       last_order_date = $1, streak_days = $2
                       WHERE id = $3""",
                    today_str, new_streak, user_db_id
                )
                if user["company_id"]:
                    await db.execute(
                        "UPDATE companies SET total_orders = total_orders + 1 WHERE id = $1",
                        user["company_id"]
                    )

                STREAK_MILESTONES = [5, 10, 20, 50]
                STREAK_BONUS_POINTS = {5: 15, 10: 30, 20: 60, 50: 150}
                for milestone in STREAK_MILESTONES:
                    if new_streak >= milestone and last_bonus_milestone < milestone:
                        bonus_points = STREAK_BONUS_POINTS[milestone]
                        await db.execute(
                            "UPDATE users SET points = points + $1, last_streak_bonus = $2 WHERE id = $3",
                            bonus_points, milestone, user_db_id
                        )
                        await db.execute(
                            """INSERT INTO balance_transactions (user_id, amount, type, description)
                               VALUES ($1, $2, 'credit', $3)""",
                            user_db_id, bonus_points, f"🔥 Бонус за серию {milestone} дней"
                        )
                        streak_bonus_info = {"milestone": milestone, "points": bonus_points}
                        break

            balance_row = await db.fetchrow(
                "SELECT balance FROM user_balance WHERE user_id = $1", user_db_id
            )
            current_balance = balance_row["balance"] if balance_row else 0

            # Баланс списывается ТОЛЬКО при доставке (курьер нажимает "Заказ доставлен"),
            # а не в момент оформления заказа. Здесь просто запоминаем выбранный
            # способ оплаты — реальное списание происходит в courier_bot.py → mark_delivered.
            if payment_method == "balance":
                deducted = current_balance >= total_amount and total_amount > 0
            else:
                deducted = False

        try:
            bot = Bot(token=BOT_TOKEN)
            items_text = "\n".join(f"• {s}" for s in order_summaries)

            payment_labels = {
                "balance": "💳 С баланса (списание при доставке)",
                "cash": "💵 Наличными при получении",
            }
            balance_text = f"\n{payment_labels.get(payment_method, payment_labels['balance'])}: {total_amount:,} сум"

            streak_text = ""
            if streak_bonus_info:
                streak_text = (
                    f"\n\n🔥 *Серия {streak_bonus_info['milestone']} дней подряд!*\n"
                    f"🎁 Бонус: +{streak_bonus_info['points']} баллов"
                )
            await bot.send_message(
                telegram_id,
                f"✅ *Заказ оформлен через Mini App!*\n\n{items_text}{balance_text}{streak_text}\n\n"
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

        if cancelled_count > 0:
            try:
                bot = Bot(token=BOT_TOKEN)
                refund_text = (
                    f"\n💳 +{refund_amount:,} сум возвращено на баланс" if refund_amount > 0 else ""
                )
                await bot.send_message(
                    telegram_id,
                    f"❌ *Заказ на {tomorrow} отменён через Mini App*{refund_text}",
                    parse_mode="Markdown"
                )
                await bot.session.close()
            except Exception as e:
                logger.error(f"Cancel notify error: {e}")

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

        if not amount or amount < 100:
            return web.json_response({"error": "Минимальная сумма — 100 сум"}, headers=cors_headers())

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
    """POST /api/gifts — список подарков + прогресс streak + статус компании месяца"""
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        pool = await get_pool()
        async with pool.acquire() as db:
            user = await db.fetchrow(
                """SELECT u.points, u.streak_days, u.last_streak_bonus, u.company_id,
                   c.name as company_name
                   FROM users u LEFT JOIN companies c ON u.company_id = c.id
                   WHERE u.telegram_id = $1""",
                telegram_id
            )
            if not user:
                return web.json_response({"error": "User not registered"}, status=404, headers=cors_headers())

            # Текущее место компании пользователя в рейтинге месяца
            company_rank = None
            company_orders = 0
            if user["company_id"]:
                ranking = await db.fetch(
                    """SELECT c.id, c.name,
                       (SELECT COUNT(*) FROM orders o
                        JOIN users u2 ON o.user_id = u2.id
                        WHERE u2.company_id = c.id
                        AND to_char(o.created_at, 'YYYY-MM') = to_char(NOW(), 'YYYY-MM')
                        AND o.status != 'cancelled') as month_orders
                       FROM companies c
                       ORDER BY month_orders DESC"""
                )
                for i, row in enumerate(ranking, 1):
                    if row["id"] == user["company_id"]:
                        company_rank = i
                        company_orders = row["month_orders"]
                        break

        points = user["points"]
        streak = user["streak_days"] or 0
        last_milestone = user["last_streak_bonus"] or 0

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

        streak_milestones = [
            {"days": 5, "bonus": 15},
            {"days": 10, "bonus": 30},
            {"days": 20, "bonus": 60},
            {"days": 50, "bonus": 150},
        ]
        for m in streak_milestones:
            m["unlocked"] = last_milestone >= m["days"]

        next_milestone = next((m for m in streak_milestones if not m["unlocked"]), None)

        return web.json_response({
            "points": points,
            "gifts": gifts,
            "streak": {
                "current": streak,
                "milestones": streak_milestones,
                "next_milestone": next_milestone,
                "days_to_next": (next_milestone["days"] - streak) if next_milestone else 0
            },
            "company": {
                "name": user["company_name"],
                "rank": company_rank,
                "orders_this_month": company_orders,
                "reward_points": 50
            } if user["company_id"] else None
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


async def handle_webapp_autoorder_get(request):
    """POST /api/autoorder — настройки автозаказа: для каждого дня — список выбранных
    блюд по всем категориям (main/salad/dessert/drink), а не только одно блюдо."""
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        pool = await get_pool()
        async with pool.acquire() as db:
            user = await db.fetchrow(
                "SELECT id, auto_order FROM users WHERE telegram_id = $1", telegram_id
            )
            if not user:
                return web.json_response({"error": "User not registered"}, status=404, headers=cors_headers())

            weekly_rows = await db.fetch(
                """SELECT day_of_week, menu_item, category FROM weekly_orders
                   WHERE user_id = $1 AND is_active = 1""",
                user["id"]
            )

            # Для каждого (день, категория) получаем детали блюда из weekly_menu
            week_days = {}
            for row in weekly_rows:
                day_num = row["day_of_week"]
                item_number = row["menu_item"]
                category = row["category"]

                dish = await db.fetchrow(
                    """SELECT name, price FROM weekly_menu
                       WHERE day_of_week = $1 AND item_number = $2 AND category = $3""",
                    day_num, item_number, category
                )
                if not dish:
                    continue

                week_days.setdefault(day_num, []).append({
                    "item_number": item_number,
                    "category": category,
                    "name": dish["name"],
                    "price": dish["price"]
                })

        return web.json_response({
            "auto_order": bool(user["auto_order"]),
            "week_days": week_days
        }, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_autoorder_get error: {e}")
        return web.json_response({"error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_autoorder_copy_last_week(request):
    """POST /api/autoorder/copy-last-week — копирует выбор прошлой недели как есть (no-op заглушка,
    так как weekly_orders уже хранит постоянный выбор без понятия 'недель'. Эндпоинт оставлен
    для совместимости и просто возвращает текущие настройки)."""
    return await handle_webapp_autoorder_get(request)


async def handle_webapp_full_settings(request):
    """POST /api/full-settings — расширенные настройки: профиль, ДР, язык, уведомления"""
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        pool = await get_pool()
        async with pool.acquire() as db:
            row = await db.fetchrow(
                """SELECT full_name, phone, lang, birthday,
                   notify_reminder, notify_delivery, notify_marketing, company_id
                   FROM users WHERE telegram_id = $1""",
                telegram_id
            )
            if not row:
                return web.json_response({"error": "User not registered"}, status=404, headers=cors_headers())

            company_name = None
            company_address = None
            if row["company_id"]:
                company = await db.fetchrow(
                    "SELECT name, address FROM companies WHERE id = $1", row["company_id"]
                )
                if company:
                    company_name = company["name"]
                    company_address = company["address"]

        return web.json_response({
            "full_name": row["full_name"],
            "phone": row["phone"],
            "lang": row["lang"] or "ru",
            "birthday": row["birthday"].isoformat() if row["birthday"] else None,
            "notify_reminder": bool(row["notify_reminder"]) if row["notify_reminder"] is not None else True,
            "notify_delivery": bool(row["notify_delivery"]) if row["notify_delivery"] is not None else True,
            "notify_marketing": bool(row["notify_marketing"]) if row["notify_marketing"] is not None else True,
            "company_name": company_name,
            "company_address": company_address
        }, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_full_settings error: {e}")
        return web.json_response({"error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_update_profile(request):
    """POST /api/update-profile — обновить имя или телефон"""
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"success": False, "error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        body = await request.json()
        field = body.get("field")
        value = body.get("value", "").strip()

        if field not in ("full_name", "phone"):
            return web.json_response({"success": False, "error": "Недопустимое поле"}, headers=cors_headers())

        if field == "full_name" and len(value) < 3:
            return web.json_response({"success": False, "error": "Имя слишком короткое"}, headers=cors_headers())

        if field == "phone":
            value = value.replace("+", "").replace(" ", "").replace("-", "")
            if not value.isdigit() or len(value) < 9:
                return web.json_response({"success": False, "error": "Неверный формат телефона"}, headers=cors_headers())

        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute(
                f"UPDATE users SET {field} = $1 WHERE telegram_id = $2",
                value, telegram_id
            )

        return web.json_response({"success": True}, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_update_profile error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_update_order_location(request):
    """
    POST /api/update-order-location — обновляет локацию компании на основе
    геопозиции клиента в момент оформления заказа. Полезно для случаев когда
    клиент зарегистрировался из дома (например, увидев рекламу вечером),
    а реально работает в офисе — локация на момент заказа точнее.
    """
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"success": False, "error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        body = await request.json()
        lat = body.get("latitude")
        lon = body.get("longitude")

        if lat is None or lon is None:
            return web.json_response({"success": False, "error": "Координаты не переданы"}, headers=cors_headers())

        maps_link = f"https://maps.google.com/?q={lat},{lon}"

        pool = await get_pool()
        async with pool.acquire() as db:
            user = await db.fetchrow("SELECT company_id FROM users WHERE telegram_id = $1", telegram_id)
            if not user or not user["company_id"]:
                return web.json_response({"success": False, "error": "Компания не найдена"}, headers=cors_headers())
            await db.execute(
                "UPDATE companies SET maps_link = $1 WHERE id = $2",
                maps_link, user["company_id"]
            )

        return web.json_response({"success": True}, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_update_order_location error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_update_company_address(request):
    """POST /api/update-company-address — обновить адрес компании"""
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"success": False, "error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        body = await request.json()
        address = body.get("address", "").strip()

        if len(address) < 3:
            return web.json_response({"success": False, "error": "Введите корректный адрес"}, headers=cors_headers())

        pool = await get_pool()
        async with pool.acquire() as db:
            user = await db.fetchrow("SELECT company_id FROM users WHERE telegram_id = $1", telegram_id)
            if not user or not user["company_id"]:
                return web.json_response({"success": False, "error": "Компания не найдена"}, headers=cors_headers())
            await db.execute(
                "UPDATE companies SET address = $1 WHERE id = $2",
                address, user["company_id"]
            )

        return web.json_response({"success": True}, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_update_company_address error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_update_birthday(request):
    """POST /api/update-birthday — установить дату рождения"""
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"success": False, "error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        body = await request.json()
        birthday_str = body.get("birthday")  # формат YYYY-MM-DD

        from datetime import date as date_cls
        try:
            birthday = date_cls.fromisoformat(birthday_str)
        except (ValueError, TypeError):
            return web.json_response({"success": False, "error": "Неверный формат даты"}, headers=cors_headers())

        today = date_cls.today()
        age = (today - birthday).days // 365
        if age < 10 or age > 100:
            return web.json_response({"success": False, "error": "Проверьте дату рождения"}, headers=cors_headers())

        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute(
                "UPDATE users SET birthday = $1 WHERE telegram_id = $2",
                birthday, telegram_id
            )

        return web.json_response({"success": True}, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_update_birthday error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_update_lang(request):
    """POST /api/update-lang — сменить язык интерфейса (ru/uz)"""
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"success": False, "error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        body = await request.json()
        lang = body.get("lang")

        if lang not in ("ru", "uz", "uz_latin", "uz_cyrillic"):
            return web.json_response({"success": False, "error": "Недопустимый язык"}, headers=cors_headers())

        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute(
                "UPDATE users SET lang = $1 WHERE telegram_id = $2",
                lang, telegram_id
            )

        return web.json_response({"success": True}, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_update_lang error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_toggle_notification(request):
    """POST /api/toggle-notification — переключить тип уведомлений"""
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"success": False, "error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        body = await request.json()
        notify_type = body.get("notify_type")

        allowed = {"notify_reminder", "notify_delivery", "notify_marketing"}
        if notify_type not in allowed:
            return web.json_response({"success": False, "error": "Недопустимый тип"}, headers=cors_headers())

        pool = await get_pool()
        async with pool.acquire() as db:
            current = await db.fetchrow(
                f"SELECT {notify_type} as val FROM users WHERE telegram_id = $1", telegram_id
            )
            if current is None:
                return web.json_response({"success": False, "error": "User not found"}, status=404, headers=cors_headers())
            new_value = 0 if current["val"] else 1
            await db.execute(
                f"UPDATE users SET {notify_type} = $1 WHERE telegram_id = $2",
                new_value, telegram_id
            )

        return web.json_response({"success": True, "value": bool(new_value)}, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_toggle_notification error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500, headers=cors_headers())


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
        category = body.get("category", "second")

        pool = await get_pool()
        async with pool.acquire() as db:
            user = await db.fetchrow("SELECT id FROM users WHERE telegram_id = $1", telegram_id)
            if not user:
                return web.json_response({"success": False, "error": "User not found"}, status=404, headers=cors_headers())

            if item_number is None:
                await db.execute(
                    "UPDATE weekly_orders SET is_active = 0 WHERE user_id = $1 AND day_of_week = $2 AND category = $3",
                    user["id"], day_of_week, category
                )
            else:
                await db.execute(
                    """INSERT INTO weekly_orders (user_id, day_of_week, menu_item, category, is_active)
                       VALUES ($1, $2, $3, $4, 1)
                       ON CONFLICT (user_id, day_of_week, category) DO UPDATE SET menu_item = $3, is_active = 1""",
                    user["id"], day_of_week, item_number, category
                )

        return web.json_response({"success": True}, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_settings_set_weekly error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500, headers=cors_headers())


async def handle_photo_proxy(request):
    """
    GET /api/photo/{photo_id} — проксирует фото блюда из Telegram.
    Telegram file_id нельзя использовать как прямую ссылку в браузере,
    поэтому сервер сам скачивает файл через Bot API и отдаёт его байты.
    """
    photo_id = request.match_info.get("photo_id")
    if not photo_id:
        return web.Response(status=404)

    try:
        bot = Bot(token=BOT_TOKEN)
        file = await bot.get_file(photo_id)
        file_bytes_io = await bot.download_file(file.file_path)
        file_bytes = file_bytes_io.read()
        await bot.session.close()

        return web.Response(
            body=file_bytes,
            content_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"}
        )
    except Exception as e:
        logger.error(f"photo_proxy error for {photo_id}: {e}")
        return web.Response(status=404)


async def handle_webapp_dashboard(request):
    """POST /api/dashboard — статистика для админ-дашборда (только для ADMIN_IDS)"""
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        import os
        admin_ids_str = os.getenv("ADMIN_IDS", "")
        admin_ids = [int(x.strip()) for x in admin_ids_str.split(",") if x.strip()]
        if telegram_id not in admin_ids:
            return web.json_response({"error": "Доступ только для администраторов"}, status=403, headers=cors_headers())

        from datetime import date as date_cls, timedelta as td_cls
        today = date_cls.today()
        week_ago = today - td_cls(days=6)

        pool = await get_pool()
        async with pool.acquire() as db:
            # Динамика заказов за последние 7 дней (по дате доставки order_date)
            daily_rows = await db.fetch(
                """SELECT o.order_date, COUNT(*) as cnt, COALESCE(SUM(m.price), 0) as revenue
                   FROM orders o
                   JOIN menus m ON o.menu_id = m.id
                   WHERE o.order_date >= $1::text AND o.order_date <= $2::text
                   AND o.status != 'cancelled'
                   GROUP BY o.order_date
                   ORDER BY o.order_date""",
                str(week_ago), str(today)
            )
            daily_map = {r["order_date"]: {"count": r["cnt"], "revenue": r["revenue"]} for r in daily_rows}

            daily_stats = []
            for i in range(7):
                d = str(week_ago + td_cls(days=i))
                entry = daily_map.get(d, {"count": 0, "revenue": 0})
                daily_stats.append({
                    "date": d,
                    "count": entry["count"],
                    "revenue": entry["revenue"]
                })

            total_orders_week = sum(d["count"] for d in daily_stats)
            total_revenue_week = sum(d["revenue"] for d in daily_stats)

            # Топ-5 блюд за последние 30 дней
            top_dishes = await db.fetch(
                """SELECT m.name, m.category, COUNT(*) as cnt
                   FROM orders o
                   JOIN menus m ON o.menu_id = m.id
                   WHERE o.order_date >= $1::text
                   AND o.status != 'cancelled'
                   GROUP BY m.name, m.category
                   ORDER BY cnt DESC
                   LIMIT 5""",
                str(today - td_cls(days=30))
            )

            # Общая статистика
            total_users = await db.fetchval("SELECT COUNT(*) FROM users")
            total_companies = await db.fetchval("SELECT COUNT(*) FROM companies")
            total_all_orders = await db.fetchval(
                "SELECT COUNT(*) FROM orders WHERE status != 'cancelled'"
            )
            avg_rating = await db.fetchval("SELECT AVG(rating) FROM reviews")

            # Статистика курьеров
            courier_rows = await db.fetch(
                """SELECT c.id, c.full_name,
                   COUNT(DISTINCT dr.id) FILTER (WHERE dr.status = 'finished') as routes_finished,
                   COUNT(DISTINCT ds.id) FILTER (WHERE ds.status = 'delivered') as stops_delivered,
                   AVG(EXTRACT(EPOCH FROM (dr.finished_at - dr.started_at)) / 60)
                       FILTER (WHERE dr.finished_at IS NOT NULL AND dr.started_at IS NOT NULL) as avg_minutes,
                   (SELECT AVG(rating) FROM courier_reviews cr WHERE cr.courier_id = c.id) as avg_rating,
                   (SELECT COUNT(*) FROM courier_reviews cr WHERE cr.courier_id = c.id) as review_count
                   FROM couriers c
                   LEFT JOIN delivery_routes dr ON dr.courier_id = c.id
                   LEFT JOIN delivery_stops ds ON ds.route_id = dr.id
                   WHERE c.is_active = TRUE
                   GROUP BY c.id, c.full_name
                   ORDER BY routes_finished DESC"""
            )
            couriers_stats = []
            for r in courier_rows:
                couriers_stats.append({
                    "id": r["id"],
                    "full_name": r["full_name"],
                    "routes_finished": r["routes_finished"] or 0,
                    "stops_delivered": r["stops_delivered"] or 0,
                    "avg_minutes": round(float(r["avg_minutes"]), 1) if r["avg_minutes"] else None,
                    "avg_rating": round(float(r["avg_rating"]), 1) if r["avg_rating"] else None,
                    "review_count": r["review_count"] or 0
                })

        return web.json_response({
            "daily_stats": daily_stats,
            "total_orders_week": total_orders_week,
            "total_revenue_week": total_revenue_week,
            "top_dishes": [dict(r) for r in top_dishes],
            "total_users": total_users,
            "total_companies": total_companies,
            "total_all_orders": total_all_orders,
            "avg_rating": round(float(avg_rating), 1) if avg_rating else None,
            "couriers_stats": couriers_stats
        }, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_dashboard error: {e}")
        return web.json_response({"error": str(e)}, status=500, headers=cors_headers())


async def handle_options(request):
    return web.Response(headers=cors_headers())


async def handle_webapp_static(request):
    """Отдаёт любой файл из папки webapp/ с заголовками no-cache.
    Текстовые файлы (html/js/css) читаются как текст с no-cache,
    изображения — как бинарные данные с кэшированием (они не меняются часто)."""
    webapp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp")
    filename = request.match_info.get("filename", "index.html")
    if not filename:
        filename = "index.html"
    file_path = os.path.join(webapp_dir, filename)

    if not os.path.isfile(file_path):
        return web.Response(text="Not found", status=404)

    image_types = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".gif": "image/gif",
        ".svg": "image/svg+xml", ".webp": "image/webp",
    }
    ext = os.path.splitext(filename)[1].lower()

    if ext in image_types:
        with open(file_path, "rb") as f:
            data = f.read()
        return web.Response(
            body=data,
            content_type=image_types[ext],
            headers={"Cache-Control": "public, max-age=86400"}
        )

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
    app.router.add_post("/api/dashboard", handle_webapp_dashboard)
    app.router.add_post("/api/autoorder", handle_webapp_autoorder_get)
    app.router.add_post("/api/full-settings", handle_webapp_full_settings)
    app.router.add_post("/api/update-profile", handle_webapp_update_profile)
    app.router.add_post("/api/update-company-address", handle_webapp_update_company_address)
    app.router.add_post("/api/update-birthday", handle_webapp_update_birthday)
    app.router.add_post("/api/update-lang", handle_webapp_update_lang)
    app.router.add_post("/api/toggle-notification", handle_webapp_toggle_notification)
    app.router.add_post("/api/update-order-location", handle_webapp_update_order_location)

    for path in ["/api/menu", "/api/order", "/api/my-order", "/api/cancel-order",
                 "/api/profile", "/api/rating", "/api/balance-history", "/api/topup",
                 "/api/gifts", "/api/referral", "/api/settings",
                 "/api/settings/toggle-auto", "/api/settings/weekly-menu", "/api/settings/set-weekly",
                 "/api/dashboard", "/api/autoorder", "/api/full-settings", "/api/update-profile",
                 "/api/update-company-address", "/api/update-birthday", "/api/update-lang",
                 "/api/toggle-notification", "/api/update-order-location"]:
        app.router.add_route("OPTIONS", path, handle_options)

    app.router.add_get("/api/photo/{photo_id}", handle_photo_proxy)

    app.router.add_get("/webapp/{filename}", handle_webapp_static)
    app.router.add_get("/webapp/", handle_webapp_static)

    return app


if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    loop = asyncio.get_event_loop()
    app = loop.run_until_complete(create_app())
    logger.info(f"🚀 Webhook server starting on port {port}")
    web.run_app(app, host="0.0.0.0", port=port)
