import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import date, datetime, timedelta, timezone

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

# Заказы принимаются круглосуточно:
# до 15:00 — на сегодня, с 15:00 — на следующий календарный день.
DELIVERY_MINUTES = 60
ORDER_OPEN_TIME  = "00:00"  # принимаем заказы круглосуточно
ORDER_CLOSE_TIME = "23:59"
ORDER_DAY_CUTOFF_HOUR = 15
TASHKENT_TZ = timezone(timedelta(hours=5))

# Категории, скрытые только от клиентов. Данные и управление в админ-панели
# сохраняются, поэтому категорию можно будет вернуть без восстановления базы.
HIDDEN_CLIENT_CATEGORIES = {"main"}  # «Вторые блюда»


def is_orders_open() -> bool:
    return True  # круглосуточно


def tashkent_now() -> datetime:
    return datetime.now(TASHKENT_TZ)


def get_active_order_date(now=None) -> str:
    """Дата нового заказа: сегодня до 15:00, после 15:00 — завтра."""
    current = now or tashkent_now()
    target = current.date()
    if current.hour >= ORDER_DAY_CUTOFF_HOUR:
        target += timedelta(days=1)
    return target.isoformat()


def is_tomorrow_order(order_date: str, now=None) -> bool:
    current = now or tashkent_now()
    return date.fromisoformat(order_date) > current.date()


def get_delivery_time(order_date=None, now=None) -> str:
    """Самое раннее время: через 60 минут сегодня или 08:00 завтра."""
    current = now or tashkent_now()
    target = order_date or get_active_order_date(current)
    if is_tomorrow_order(target, current):
        return "08:00"

    earliest_minutes = max(
        8 * 60,
        current.hour * 60 + current.minute + DELIVERY_MINUTES,
    )
    return f"{earliest_minutes // 60:02d}:{earliest_minutes % 60:02d}"


def resolve_order_date(value, *, require_active: bool = False):
    """
    Проверяет дату, полученную от Mini App.
    Возвращает (дата, ошибка). Для нового заказа дата обязана совпасть
    с актуальной датой, рассчитанной сервером по времени Ташкента.
    """
    active_date = get_active_order_date()
    order_date = value or active_date
    try:
        parsed = date.fromisoformat(order_date)
    except (TypeError, ValueError):
        return None, "Недопустимая дата заказа"

    today = tashkent_now().date()
    if parsed not in (today, today + timedelta(days=1)):
        return None, "Можно выбрать доставку только на сегодня или завтра"
    if require_active and order_date != active_date:
        return None, "Дата заказа изменилась. Обновите меню и выберите время заново."
    return order_date, None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_pool = None
_sales_tables_ready = False
_sales_tables_lock = asyncio.Lock()


async def get_pool():
    global _pool
    if _pool is None:
        import asyncpg
        _pool = await asyncpg.create_pool(DATABASE_URL)
    return _pool


async def add_balance(user_db_id: int, amount: int, description: str, click_trans_id: str):
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.transaction():
            # Click может отправить Complete повторно или одновременно. Advisory
            # lock не позволяет дважды зачислить один и тот же платёж.
            await db.execute(
                "SELECT pg_advisory_xact_lock(hashtext($1))",
                str(click_trans_id)
            )
            existing = await db.fetchrow(
                "SELECT id FROM balance_transactions WHERE description LIKE $1",
                f"%click_trans:{click_trans_id}"
            )
            if existing:
                logger.warning(
                    f"Duplicate click_trans_id={click_trans_id}, skipping"
                )
                return False

            await db.execute(
                """INSERT INTO user_balance (user_id, balance)
                   VALUES ($1, $2)
                   ON CONFLICT (user_id) DO UPDATE
                   SET balance = user_balance.balance + $2,
                       updated_at = CURRENT_TIMESTAMP""",
                user_db_id, amount
            )
            await db.execute(
                """INSERT INTO balance_transactions
                   (user_id, amount, type, description)
                   VALUES ($1, $2, 'credit', $3)""",
                user_db_id, amount,
                f"{description} | click_trans:{click_trans_id}"
            )
    return True


async def notify_user(telegram_id: int, amount: int, lang: str = "ru"):
    bot = Bot(token=BOT_TOKEN)
    try:
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
    except Exception as e:
        logger.error(f"Notify error for telegram_id={telegram_id}: {e}")
    finally:
        await bot.session.close()


def get_admin_ids():
    return [
        int(value.strip())
        for value in os.getenv("ADMIN_IDS", "").split(",")
        if value.strip()
    ]


async def ensure_pending_click_orders_table(db):
    """Хранит корзину до подтверждения оплаты со стороны Click."""
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_click_orders (
            id BIGSERIAL PRIMARY KEY,
            merchant_trans_id TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL REFERENCES users(id),
            order_date TEXT NOT NULL,
            delivery_slot TEXT NOT NULL,
            items_json JSONB NOT NULL,
            total_amount BIGINT NOT NULL,
            topup_amount BIGINT NOT NULL,
            status TEXT NOT NULL DEFAULT 'awaiting_payment',
            click_trans_id TEXT UNIQUE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


async def ensure_sales_features_tables(db):
    """Таблицы второго пакета: избранное и заявки организаций."""
    global _sales_tables_ready
    if _sales_tables_ready:
        return
    async with _sales_tables_lock:
        if _sales_tables_ready:
            return
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_favorites (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                item_name TEXT NOT NULL,
                category TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, item_name, category)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS corporate_requests (
                id BIGSERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                employees INTEGER NOT NULL,
                preferred_time TEXT,
                comment TEXT,
                status TEXT NOT NULL DEFAULT 'new',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        _sales_tables_ready = True


async def notify_admins_click_payment(
    *,
    telegram_id,
    full_name,
    phone,
    company_name,
    amount,
    click_trans_id,
    order_date=None,
    order_total=None,
):
    """Отдельное уведомление администраторам о поступлении денег через Click."""
    text = (
        "💳 ОПЛАТА ЧЕРЕЗ CLICK\n\n"
        f"👤 {full_name or 'Клиент'}\n"
        f"🏢 {company_name or '—'}\n"
        f"📱 {'+' + phone if phone else '—'}\n"
        f"🆔 Telegram ID: {telegram_id}\n\n"
        f"💰 Поступило: {amount:,} сум\n"
        f"🔢 Click transaction: {click_trans_id}"
    )
    if order_date:
        text += f"\n📅 Дата заказа: {order_date}"
    if order_total is not None:
        text += f"\n📦 Сумма заказа: {order_total:,} сум"

    bot = Bot(token=BOT_TOKEN)
    try:
        for admin_id in get_admin_ids():
            try:
                await bot.send_message(admin_id, text)
            except Exception as e:
                logger.warning(
                    f"Не удалось уведомить админа {admin_id} об оплате Click: {e}"
                )
    finally:
        await bot.session.close()


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
        if len(parts) < 3 or parts[0] not in ("balance", "clickorder"):
            return web.json_response({"error": -5, "error_note": "User does not exist"})

        if parts[0] == "clickorder":
            pool = await get_pool()
            async with pool.acquire() as db:
                await ensure_pending_click_orders_table(db)
                pending = await db.fetchrow(
                    """SELECT topup_amount, status
                       FROM pending_click_orders
                       WHERE merchant_trans_id = $1""",
                    merchant_trans_id
                )
            if not pending:
                return web.json_response(
                    {"error": -5, "error_note": "Order does not exist"}
                )
            if pending["status"] not in ("awaiting_payment", "completed"):
                return web.json_response(
                    {"error": -9, "error_note": "Order is not payable"}
                )
            if int(float(amount_raw)) != int(pending["topup_amount"]):
                return web.json_response(
                    {"error": -2, "error_note": "Incorrect amount"}
                )

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


async def complete_pending_click_order(merchant_trans_id, click_trans_id, amount_sum):
    """
    Атомарно зачисляет Click-платёж и создаёт сохранённый до оплаты заказ.
    Повторный callback Click возвращает тот же результат без дублей.
    """
    pool = await get_pool()
    async with pool.acquire() as db:
        await ensure_pending_click_orders_table(db)
        async with db.transaction():
            pending = await db.fetchrow(
                """SELECT * FROM pending_click_orders
                   WHERE merchant_trans_id = $1
                   FOR UPDATE""",
                merchant_trans_id
            )
            if not pending:
                return {"success": False, "error": -5, "error_note": "Order does not exist"}

            if pending["status"] == "completed":
                return {"success": True, "duplicate": True}
            if pending["status"] != "awaiting_payment":
                return {"success": False, "error": -9, "error_note": "Order is not payable"}
            if int(pending["topup_amount"]) != int(amount_sum):
                return {"success": False, "error": -2, "error_note": "Incorrect amount"}

            existing_payment = await db.fetchrow(
                """SELECT id FROM balance_transactions
                   WHERE description LIKE $1""",
                f"%click_trans:{click_trans_id}"
            )
            if existing_payment:
                return {"success": False, "error": -4, "error_note": "Already paid"}

            user = await db.fetchrow(
                """SELECT u.id, u.telegram_id, u.lang, u.full_name, u.phone,
                          u.company_id, u.total_orders, u.streak_days,
                          u.last_order_date, u.last_streak_bonus,
                          c.name AS company_name
                   FROM users u
                   LEFT JOIN companies c ON c.id = u.company_id
                   WHERE u.id = $1
                   FOR UPDATE OF u""",
                pending["user_id"]
            )
            if not user:
                return {"success": False, "error": -5, "error_note": "User does not exist"}

            raw_items = pending["items_json"]
            items = json.loads(raw_items) if isinstance(raw_items, str) else raw_items
            if not isinstance(items, list) or not items:
                return {"success": False, "error": -9, "error_note": "Saved order is empty"}

            await db.execute(
                """INSERT INTO user_balance (user_id, balance)
                   VALUES ($1, $2)
                   ON CONFLICT (user_id) DO UPDATE
                   SET balance = user_balance.balance + $2,
                       updated_at = CURRENT_TIMESTAMP""",
                user["id"], amount_sum
            )
            await db.execute(
                """INSERT INTO balance_transactions (user_id, amount, type, description)
                   VALUES ($1, $2, 'credit', $3)""",
                user["id"], amount_sum,
                f"Оплата заказа через Click | click_trans:{click_trans_id}"
            )

            positions_created = 0
            for item in items:
                qty = int(item["qty"])
                for _ in range(qty):
                    await db.execute(
                        """INSERT INTO orders
                           (user_id, menu_id, order_date, status, payment_method)
                           VALUES ($1, $2, $3::text, 'pending', 'balance')""",
                        user["id"], int(item["menu_id"]), pending["order_date"]
                    )
                    positions_created += 1

            if positions_created == 0:
                raise RuntimeError("Saved Click order has no positions")

            today_local = tashkent_now().date()
            today_str = today_local.isoformat()
            yesterday_str = (today_local - timedelta(days=1)).isoformat()
            current_streak = user["streak_days"] or 0
            if user["last_order_date"] == yesterday_str:
                new_streak = current_streak + 1
            elif user["last_order_date"] == today_str:
                new_streak = current_streak
            else:
                new_streak = 1

            await db.execute(
                """UPDATE users
                   SET total_orders = total_orders + 1,
                       points = points + 5,
                       last_order_date = $1,
                       streak_days = $2
                   WHERE id = $3""",
                today_str, new_streak, user["id"]
            )
            if user["company_id"]:
                await db.execute(
                    "UPDATE companies SET total_orders = total_orders + 1 WHERE id = $1",
                    user["company_id"]
                )

            streak_bonus = None
            milestone_points = {5: 15, 10: 30, 20: 60, 50: 150}
            last_bonus = user["last_streak_bonus"] or 0
            for milestone in (5, 10, 20, 50):
                if new_streak >= milestone and last_bonus < milestone:
                    bonus = milestone_points[milestone]
                    await db.execute(
                        """UPDATE users
                           SET points = points + $1, last_streak_bonus = $2
                           WHERE id = $3""",
                        bonus, milestone, user["id"]
                    )
                    streak_bonus = {"milestone": milestone, "points": bonus}
                    break

            await db.execute(
                """UPDATE pending_click_orders
                   SET status = 'completed',
                       click_trans_id = $1,
                       completed_at = CURRENT_TIMESTAMP,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = $2""",
                str(click_trans_id), pending["id"]
            )

            return {
                "success": True,
                "duplicate": False,
                "telegram_id": user["telegram_id"],
                "lang": user["lang"] or "ru",
                "full_name": user["full_name"] or "Клиент",
                "phone": user["phone"],
                "company_name": user["company_name"] or "—",
                "order_date": pending["order_date"],
                "delivery_slot": pending["delivery_slot"],
                "items": items,
                "total_amount": int(pending["total_amount"]),
                "topup_amount": int(pending["topup_amount"]),
                "is_first_order": (user["total_orders"] or 0) == 0,
                "streak_bonus": streak_bonus,
            }


async def notify_completed_click_order(result, click_trans_id):
    """Уведомляет клиента и админов и об оплате, и о созданном заказе."""
    if result.get("duplicate"):
        return

    items_text = "\n".join(
        f"• {item['name']} x{item['qty']}" for item in result["items"]
    )
    delivery_day = (
        "завтра"
        if is_tomorrow_order(result["order_date"])
        else "сегодня"
    )

    bot = Bot(token=BOT_TOKEN)
    try:
        client_text = (
            "✅ *Оплата через Click принята!*\n\n"
            f"💰 Поступило: *{result['topup_amount']:,} сум*\n"
            "📦 Заказ оформлен автоматически:\n"
            f"{items_text}\n\n"
            f"🚀 Доставка {delivery_day} к {result['delivery_slot']}"
        )
        try:
            await bot.send_message(
                result["telegram_id"], client_text, parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(
                f"Не удалось уведомить клиента {result['telegram_id']} "
                f"о Click-заказе: {e}"
            )

        title = (
            "🎁 ПЕРВЫЙ ЗАКАЗ НОВОГО КЛИЕНТА"
            if result["is_first_order"]
            else "🆕 НОВЫЙ ЗАКАЗ"
        )
        admin_order_text = (
            f"{title}\n\n"
            f"👤 {result['full_name']}\n"
            f"🏢 {result['company_name']}\n"
            f"📱 {'+' + result['phone'] if result['phone'] else '—'}\n"
            f"📅 Дата доставки: {result['order_date']}\n"
            f"🕐 Время: {result['delivery_slot']}\n\n"
            f"📦 Позиции:\n{items_text}\n\n"
            f"💰 Сумма заказа: {result['total_amount']:,} сум\n"
            f"💳 Оплачено через Click: {result['topup_amount']:,} сум"
        )
        if result["is_first_order"]:
            admin_order_text += (
                "\n\n🥤 Не забудьте положить компот 0,5 л в подарок!"
            )

        for admin_id in get_admin_ids():
            try:
                await bot.send_message(admin_id, admin_order_text)
            except Exception as e:
                logger.warning(
                    f"Не удалось уведомить админа {admin_id} "
                    f"о Click-заказе: {e}"
                )
    finally:
        await bot.session.close()

    await notify_admins_click_payment(
        telegram_id=result["telegram_id"],
        full_name=result["full_name"],
        phone=result["phone"],
        company_name=result["company_name"],
        amount=result["topup_amount"],
        click_trans_id=click_trans_id,
        order_date=result["order_date"],
        order_total=result["total_amount"],
    )


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
            if str(merchant_trans_id).startswith("clickorder_"):
                try:
                    pool = await get_pool()
                    async with pool.acquire() as db:
                        await ensure_pending_click_orders_table(db)
                        await db.execute(
                            """UPDATE pending_click_orders
                               SET status = 'cancelled',
                                   updated_at = CURRENT_TIMESTAMP
                               WHERE merchant_trans_id = $1
                               AND status = 'awaiting_payment'""",
                            merchant_trans_id
                        )
                except Exception as cancel_error:
                    logger.error(
                        f"[COMPLETE] Could not mark Click order cancelled: "
                        f"{cancel_error}"
                    )
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
                            """SELECT u.telegram_id, u.lang, u.full_name, u.phone,
                                      c.name AS company_name
                               FROM users u
                               LEFT JOIN companies c ON c.id = u.company_id
                               WHERE u.id = $1""",
                            user_db_id
                        )
                    if row:
                        await notify_user(row["telegram_id"], amount_sum, row.get("lang", "ru"))
                        await notify_admins_click_payment(
                            telegram_id=row["telegram_id"],
                            full_name=row["full_name"],
                            phone=row["phone"],
                            company_name=row["company_name"],
                            amount=amount_sum,
                            click_trans_id=click_trans_id,
                        )
                except Exception as e:
                    logger.error(f"[COMPLETE] Notify error: {e}")
        elif len(parts) >= 3 and parts[0] == "clickorder":
            amount_sum = int(float(amount_raw))
            completion = await complete_pending_click_order(
                merchant_trans_id, click_trans_id, amount_sum
            )
            if not completion.get("success"):
                return web.json_response({
                    "click_trans_id": int(click_trans_id),
                    "merchant_trans_id": merchant_trans_id,
                    "merchant_confirm_id": 1,
                    "error": completion.get("error", -9),
                    "error_note": completion.get("error_note", "Order completion failed"),
                })
            try:
                await notify_completed_click_order(completion, click_trans_id)
            except Exception as e:
                # Платёж и заказ уже сохранены атомарно. Ошибка Telegram не должна
                # заставлять Click повторять финансовую операцию.
                logger.error(f"[COMPLETE] Click order notify error: {e}")
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
            user = await db.fetchrow(
                "SELECT id, full_name FROM users WHERE telegram_id = $1",
                telegram_id
            )
            if not user:
                return web.json_response(
                    {"error": "User not registered. Напишите /start боту."},
                    status=404, headers=cors_headers()
                )
            user_db_id = user["id"]
            raw_display_name = (
                user["full_name"] or user_data.get("first_name") or ""
            ).strip()
            display_name = (
                raw_display_name.split()[0][:40] if raw_display_name else ""
            )
            await ensure_sales_features_tables(db)

            favorite_rows = await db.fetch(
                """SELECT item_name, category
                   FROM user_favorites
                   WHERE user_id = $1""",
                user_db_id
            )
            favorite_keys = {
                (row["item_name"], row["category"]) for row in favorite_rows
            }

            balance_row = await db.fetchrow(
                "SELECT balance FROM user_balance WHERE user_id = $1", user_db_id
            )
            balance = balance_row["balance"] if balance_row else 0

            user_stats = await db.fetchrow(
                "SELECT total_orders, points FROM users WHERE id = $1", user_db_id
            )
            total_orders = user_stats["total_orders"] or 0
            user_points = user_stats["points"] or 0

            order_date = get_active_order_date()
            day_num = date.fromisoformat(order_date).weekday()

            # Разовые позиции, которые уже реально существуют в menus на эту дату
            # (например, потому что кто-то уже сделал заказ — позиция автоматически
            # копируется из weekly_menu в menus в момент создания заказа).
            menu_rows = await db.fetch(
                """SELECT id, item_number, name, price, photo_id, category
                   FROM menus WHERE menu_date = $1::text AND is_active = 1
                   AND category != 'main'
                   ORDER BY category, item_number""",
                order_date
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
                   AND category != 'main'
                   ORDER BY category, item_number""",
                day_num
            )

            categories = {"breakfast": [], "first": [], "second": [], "salad": [], "dessert": [], "drink": []}

            if weekly_rows:
                for row in weekly_rows:
                    cat = row["category"] or "second"
                    key = (row["item_number"], cat)
                    existing = existing_by_key.get(key)
                    item_name = existing["name"] if existing else row["name"]
                    categories.setdefault(cat, []).append({
                        "id": existing["id"] if existing else f"weekly_{day_num}_{row['item_number']}_{cat}",
                        "item_number": row["item_number"],
                        "name": item_name,
                        "price": existing["price"] if existing else row["price"],
                        "photo_url": build_photo_url(existing["photo_id"] if existing else row["photo_id"]),
                        "category": cat,
                        "is_favorite": (item_name, cat) in favorite_keys,
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
                        "photo_url": build_photo_url(row["photo_id"]),
                        "category": cat,
                        "is_favorite": (row["name"], cat) in favorite_keys,
                    })

            # Индекс текущего каталога нужен для безопасного повтора заказа:
            # в корзину попадают только блюда, которые действительно доступны
            # на активную дату. Старые menu_id напрямую не переиспользуем.
            catalog_by_key = {}
            for cat, items in categories.items():
                for item in items:
                    catalog_by_key[(cat, item["item_number"])] = item

            last_order_date = await db.fetchval(
                """SELECT MAX(order_date)
                   FROM orders
                   WHERE user_id = $1
                     AND status != 'cancelled'
                     AND order_date < $2::text""",
                user_db_id, order_date
            )
            last_order_items = []
            if last_order_date:
                last_rows = await db.fetch(
                    """SELECT m.item_number, m.category, COUNT(o.id)::int AS qty
                       FROM orders o
                       JOIN menus m ON m.id = o.menu_id
                       WHERE o.user_id = $1
                         AND o.order_date = $2::text
                         AND o.status != 'cancelled'
                         AND m.category != 'main'
                       GROUP BY m.item_number, m.category
                       ORDER BY m.category, m.item_number""",
                    user_db_id, last_order_date
                )
                for row in last_rows:
                    current_item = catalog_by_key.get(
                        (row["category"], row["item_number"])
                    )
                    if current_item:
                        last_order_items.append({
                            **current_item,
                            "category": row["category"],
                            "qty": row["qty"],
                        })

            # Хиты считаются по реальным заказам за последние 30 дней, но в
            # ответ включаются только позиции, доступные в текущем меню.
            popular_rows = await db.fetch(
                """SELECT m.item_number, m.category, COUNT(o.id)::int AS order_count
                   FROM orders o
                   JOIN menus m ON m.id = o.menu_id
                   WHERE o.status != 'cancelled'
                     AND o.order_date >= $1::text
                     AND m.category != 'main'
                   GROUP BY m.item_number, m.category
                   ORDER BY order_count DESC
                   LIMIT 30""",
                (date.fromisoformat(order_date) - timedelta(days=30)).isoformat()
            )
            popular_items = []
            popular_count_by_key = {}
            for row in popular_rows:
                key = (row["category"], row["item_number"])
                popular_count_by_key[key] = row["order_count"]
                current_item = catalog_by_key.get(key)
                if current_item and len(popular_items) < 6:
                    popular_items.append({
                        **current_item,
                        "category": row["category"],
                        "order_count": row["order_count"],
                    })

            # Персональная подборка строится только по истории этого клиента.
            # Если знакомое блюдо сегодня недоступно, оно не показывается.
            personal_rows = await db.fetch(
                """SELECT m.item_number, m.category, COUNT(o.id)::int AS order_count
                   FROM orders o
                   JOIN menus m ON m.id = o.menu_id
                   WHERE o.user_id = $1
                     AND o.status != 'cancelled'
                     AND o.order_date >= $2::text
                     AND m.category != 'main'
                   GROUP BY m.item_number, m.category
                   ORDER BY order_count DESC
                   LIMIT 20""",
                user_db_id,
                (date.fromisoformat(order_date) - timedelta(days=90)).isoformat()
            )
            personal_items = []
            for row in personal_rows:
                current_item = catalog_by_key.get(
                    (row["category"], row["item_number"])
                )
                if current_item and len(personal_items) < 4:
                    personal_items.append({
                        **current_item,
                        "category": row["category"],
                        "order_count": row["order_count"],
                    })

            # Дополнения для блока «С этим заказывают»: сначала самые
            # популярные напитки/салаты/десерты, затем доступные позиции меню.
            complementary_categories = ("drink", "salad", "dessert")
            recommendation_candidates = []
            for cat in complementary_categories:
                for item in categories.get(cat, []):
                    key = (cat, item["item_number"])
                    recommendation_candidates.append((
                        popular_count_by_key.get(key, 0), cat, item
                    ))
            recommendation_candidates.sort(
                key=lambda value: (-value[0], complementary_categories.index(value[1]))
            )
            recommendations = [
                {**item, "category": cat}
                for _, cat, item in recommendation_candidates[:3]
            ]

            gift_levels = [
                (50, "drink", "🥤"),
                (100, "dessert", "🍰"),
                (200, "lunch", "🍱"),
                (500, "vip", "👑"),
            ]
            next_gift = next(
                (level for level in gift_levels if user_points < level[0]),
                gift_levels[-1]
            )
            gift_progress = {
                "points": user_points,
                "target": next_gift[0],
                "remaining": max(0, next_gift[0] - user_points),
                "gift_id": next_gift[1],
                "emoji": next_gift[2],
                "completed": user_points >= gift_levels[-1][0],
            }

        return web.json_response({
            "categories": categories,
            "balance": balance,
            "date_label": order_date,
            "order_date": order_date,
            "is_tomorrow": is_tomorrow_order(order_date),
            "earliest_delivery_slot": get_delivery_time(order_date),
            "orders_open": is_orders_open(),
            "order_close_time": ORDER_CLOSE_TIME,
            "is_first_order": total_orders == 0,
            "display_name": display_name,
            "tashkent_hour": tashkent_now().hour,
            "last_order_date": last_order_date,
            "last_order_items": last_order_items,
            "popular_items": popular_items,
            "personal_items": personal_items,
            "recommendations": recommendations,
            "gift_progress": gift_progress,
        }, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_menu error: {e}")
        return web.json_response({"error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_toggle_favorite(request):
    """Добавляет блюдо в избранное или удаляет его."""
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response(
                {"success": False, "error": "Invalid auth"},
                status=401, headers=cors_headers()
            )

        body = await request.json()
        item_name = str(body.get("item_name") or "").strip()
        category = str(body.get("category") or "").strip()
        is_favorite = bool(body.get("is_favorite"))
        if not item_name or len(item_name) > 200 or not category:
            return web.json_response(
                {"success": False, "error": "Неверные данные блюда"},
                status=400, headers=cors_headers()
            )
        if category in HIDDEN_CLIENT_CATEGORIES:
            return web.json_response(
                {"success": False, "error": "Категория недоступна"},
                status=400, headers=cors_headers()
            )

        pool = await get_pool()
        async with pool.acquire() as db:
            user_id = await db.fetchval(
                "SELECT id FROM users WHERE telegram_id = $1",
                user_data["id"]
            )
            if not user_id:
                return web.json_response(
                    {"success": False, "error": "User not found"},
                    status=404, headers=cors_headers()
                )
            await ensure_sales_features_tables(db)

            item_exists = await db.fetchval(
                """SELECT 1
                   WHERE EXISTS (
                       SELECT 1 FROM menus
                       WHERE name = $1 AND category = $2 AND is_active = 1
                   ) OR EXISTS (
                       SELECT 1 FROM weekly_menu
                       WHERE name = $1 AND category = $2 AND is_active = 1
                   )""",
                item_name, category
            )
            if not item_exists:
                return web.json_response(
                    {"success": False, "error": "Блюдо больше недоступно"},
                    status=400, headers=cors_headers()
                )

            if is_favorite:
                await db.execute(
                    """INSERT INTO user_favorites (user_id, item_name, category)
                       VALUES ($1, $2, $3)
                       ON CONFLICT (user_id, item_name, category) DO NOTHING""",
                    user_id, item_name, category
                )
            else:
                await db.execute(
                    """DELETE FROM user_favorites
                       WHERE user_id = $1 AND item_name = $2 AND category = $3""",
                    user_id, item_name, category
                )

        return web.json_response(
            {"success": True, "is_favorite": is_favorite},
            headers=cors_headers()
        )
    except Exception as e:
        logger.error(f"webapp_toggle_favorite error: {e}")
        return web.json_response(
            {"success": False, "error": str(e)},
            status=500, headers=cors_headers()
        )


async def handle_webapp_corporate_request(request):
    """Сохраняет заявку на корпоративное питание и уведомляет администраторов."""
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response(
                {"success": False, "error": "Invalid auth"},
                status=401, headers=cors_headers()
            )

        body = await request.json()
        try:
            employees = int(body.get("employees"))
        except (TypeError, ValueError):
            employees = 0
        preferred_time = str(body.get("preferred_time") or "").strip()
        comment = str(body.get("comment") or "").strip()[:500]
        allowed_times = {
            f"{hour:02d}:{minute:02d}"
            for hour in range(8, 17)
            for minute in (0, 30)
            if not (hour == 16 and minute == 30)
        }
        if employees < 2 or employees > 10000:
            return web.json_response(
                {"success": False, "error": "Укажите количество сотрудников от 2 до 10000"},
                status=400, headers=cors_headers()
            )
        if preferred_time not in allowed_times:
            return web.json_response(
                {"success": False, "error": "Выберите корректное время доставки"},
                status=400, headers=cors_headers()
            )

        pool = await get_pool()
        async with pool.acquire() as db:
            await ensure_sales_features_tables(db)
            client = await db.fetchrow(
                """SELECT u.id, u.full_name, u.phone, c.name AS company_name,
                          COALESCE(c.maps_link, c.address) AS company_address
                   FROM users u
                   LEFT JOIN companies c ON c.id = u.company_id
                   WHERE u.telegram_id = $1""",
                user_data["id"]
            )
            if not client:
                return web.json_response(
                    {"success": False, "error": "User not found"},
                    status=404, headers=cors_headers()
                )

            recent_id = await db.fetchval(
                """SELECT id FROM corporate_requests
                   WHERE user_id = $1
                     AND created_at > CURRENT_TIMESTAMP - INTERVAL '10 minutes'
                   ORDER BY created_at DESC
                   LIMIT 1""",
                client["id"]
            )
            if recent_id:
                return web.json_response(
                    {"success": True, "already_received": True},
                    headers=cors_headers()
                )

            request_id = await db.fetchval(
                """INSERT INTO corporate_requests
                   (user_id, employees, preferred_time, comment)
                   VALUES ($1, $2, $3, $4)
                   RETURNING id""",
                client["id"], employees, preferred_time, comment or None
            )

        admin_text = (
            "🏢 НОВАЯ ЗАЯВКА НА КОРПОРАТИВНОЕ ПИТАНИЕ\n\n"
            f"🔢 Заявка №{request_id}\n"
            f"👤 {client['full_name'] or 'Клиент'}\n"
            f"🏢 {client['company_name'] or '—'}\n"
            f"📱 {'+' + str(client['phone']) if client['phone'] else '—'}\n"
            f"👥 Сотрудников: {employees}\n"
            f"🕐 Желаемое время: {preferred_time}\n"
            f"📍 Адрес: {client['company_address'] or '—'}"
        )
        if comment:
            admin_text += f"\n💬 Комментарий: {comment}"

        bot = Bot(token=BOT_TOKEN)
        try:
            for admin_id in get_admin_ids():
                try:
                    await bot.send_message(admin_id, admin_text)
                except Exception as e:
                    logger.warning(
                        f"Не удалось уведомить админа {admin_id} "
                        f"о корпоративной заявке {request_id}: {e}"
                    )
        finally:
            await bot.session.close()

        return web.json_response(
            {"success": True, "request_id": request_id},
            headers=cors_headers()
        )
    except Exception as e:
        logger.error(f"webapp_corporate_request error: {e}")
        return web.json_response(
            {"success": False, "error": str(e)},
            status=500, headers=cors_headers()
        )


async def handle_webapp_order(request):
    try:
        init_data = await get_init_data_from_request(request)
        body = await request.json()
        items = body.get("items", [])
        payment_method = body.get("payment_method", "auto")
        requested_order_date = body.get("order_date")
        selected_delivery_slot = body.get("delivery_slot")

        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"success": False, "error": "Invalid auth"}, status=401, headers=cors_headers())


        telegram_id = user_data.get("id")
        if not items:
            return web.json_response({"success": False, "error": "Корзина пуста"}, headers=cors_headers())

        order_date, date_error = resolve_order_date(
            requested_order_date, require_active=True
        )
        if date_error:
            return web.json_response(
                {"success": False, "error": date_error, "date_changed": True},
                headers=cors_headers()
            )

        slot_is_valid, slot_error = validate_delivery_slot(
            selected_delivery_slot, order_date
        )
        if not slot_is_valid:
            return web.json_response(
                {"success": False, "error": slot_error},
                headers=cors_headers()
            )

        pool = await get_pool()

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

            # Предварительный подсчёт суммы заказа (без побочных эффектов в БД),
            # чтобы проверить минимальную сумму ДО создания реальных позиций заказа.
            MIN_ORDER_AMOUNT = 40000
            precheck_total = 0
            for entry in items:
                menu_id = entry.get("menu_id")
                qty = entry.get("qty", 1)
                if isinstance(menu_id, str) and menu_id.startswith("weekly_"):
                    _, day_num, item_number, cat = menu_id.split("_")
                    if int(day_num) != date.fromisoformat(order_date).weekday():
                        return web.json_response({
                            "success": False,
                            "error": "Меню уже обновилось. Откройте его заново."
                        }, headers=cors_headers())
                    if cat in HIDDEN_CLIENT_CATEGORIES:
                        return web.json_response({
                            "success": False,
                            "error": "Категория «Вторые блюда» временно недоступна."
                        }, headers=cors_headers())
                    price_row = await db.fetchrow(
                        """SELECT price FROM weekly_menu
                           WHERE day_of_week = $1 AND item_number = $2
                           AND category = $3 AND category != 'main'
                           AND is_active = 1""",
                        int(day_num), int(item_number), cat
                    )
                else:
                    price_row = await db.fetchrow(
                        """SELECT price FROM menus
                           WHERE id = $1 AND menu_date = $2::text
                           AND category != 'main' AND is_active = 1""",
                        int(menu_id), order_date
                    )
                if not price_row:
                    return web.json_response({
                        "success": False,
                        "error": "Одна из позиций больше недоступна. Обновите меню."
                    }, headers=cors_headers())
                precheck_total += price_row["price"] * qty

            if precheck_total < MIN_ORDER_AMOUNT:
                remaining_needed = MIN_ORDER_AMOUNT - precheck_total
                return web.json_response({
                    "success": False,
                    "error": f"Минимальная сумма заказа — {MIN_ORDER_AMOUNT:,} сум. Добавьте ещё {remaining_needed:,} сум."
                }, headers=cors_headers())

            for entry in items:
                menu_id = entry.get("menu_id")
                qty = entry.get("qty", 1)

                if isinstance(menu_id, str) and menu_id.startswith("weekly_"):
                    _, day_num, item_number, cat = menu_id.split("_")
                    if int(day_num) != date.fromisoformat(order_date).weekday():
                        continue
                    menu_item = await db.fetchrow(
                        """SELECT item_number, name, price, photo_id, category
                           FROM weekly_menu
                           WHERE day_of_week = $1 AND item_number = $2
                           AND category = $3 AND category != 'main'
                           AND is_active = 1""",
                        int(day_num), int(item_number), cat
                    )
                    if not menu_item:
                        continue
                    real_row = await db.fetchrow(
                        """INSERT INTO menus (menu_date, item_number, name, description, price, photo_id, category)
                           VALUES ($1, $2, $3, '', $4, $5, $6)
                           ON CONFLICT (menu_date, item_number, category) DO UPDATE SET name = EXCLUDED.name
                           RETURNING id, name, price""",
                        order_date, menu_item["item_number"], menu_item["name"],
                        menu_item["price"], menu_item["photo_id"], menu_item["category"]
                    )
                    real_menu_id = real_row["id"]
                    item_name = real_row["name"]
                    item_price = real_row["price"]
                else:
                    menu_item = await db.fetchrow(
                        """SELECT id, name, price FROM menus
                           WHERE id = $1 AND menu_date = $2::text
                           AND category != 'main' AND is_active = 1""",
                        int(menu_id), order_date
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
                        user_db_id, real_menu_id, order_date, payment_method
                    )
                    orders_created += 1

                total_amount += item_price * qty
                order_summaries.append(f"{item_name} x{qty}")

            streak_bonus_info = None
            is_first_order = False
            if orders_created > 0:
                from datetime import date as date_cls, timedelta as td_cls
                today_local = tashkent_now().date()
                today_str = str(today_local)
                yesterday_str = str(today_local - td_cls(days=1))

                # Проверяем был ли это первый заказ ДО обновления total_orders
                prev_total = await db.fetchval(
                    "SELECT total_orders FROM users WHERE id = $1", user_db_id
                ) or 0
                is_first_order = (prev_total == 0)

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

        bot = Bot(token=BOT_TOKEN)
        try:
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

            slot_row = None
            async with pool.acquire() as slot_db:
                slot_row = await slot_db.fetchrow(
                    """SELECT ds.slot FROM delivery_slots ds
                       JOIN users u ON u.id = ds.user_id
                       WHERE u.telegram_id = $1 AND ds.order_date = $2::text""",
                    telegram_id, order_date
                )

            selected_slot = (
                slot_row["slot"] if slot_row
                else get_delivery_time(order_date)
            )
            delivery_day = "завтра" if is_tomorrow_order(order_date) else "сегодня"
            delivery_text = f"🚀 Доставка {delivery_day} к {selected_slot}"

            # Ошибка отправки сообщения клиенту не должна блокировать
            # уведомление администраторов о новом заказе.
            try:
                await bot.send_message(
                    telegram_id,
                    f"✅ *Заказ оформлен через Mini App!*\n\n{items_text}{balance_text}{streak_text}\n\n"
                    f"{delivery_text}",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.warning(
                    f"Не удалось уведомить клиента {telegram_id} о заказе: {e}"
                )

            # Уведомляем администраторов о КАЖДОМ оформленном заказе.
            # Для первого заказа добавляем напоминание про подарок.
            if orders_created > 0:
                try:
                    async with pool.acquire() as info_db:
                        client = await info_db.fetchrow(
                            """SELECT u.full_name, u.phone, c.name as company_name
                               FROM users u
                               LEFT JOIN companies c ON c.id = u.company_id
                               WHERE u.telegram_id = $1""",
                            telegram_id
                        )
                    client_name = client["full_name"] if client else "Новый клиент"
                    company_name = client["company_name"] if client and client["company_name"] else "—"
                    phone = f"+{client['phone']}" if client and client["phone"] else "—"

                    title = (
                        "🎁 ПЕРВЫЙ ЗАКАЗ НОВОГО КЛИЕНТА"
                        if is_first_order
                        else "🆕 НОВЫЙ ЗАКАЗ"
                    )
                    admin_text = (
                        f"{title}\n\n"
                        f"👤 {client_name}\n"
                        f"🏢 {company_name}\n"
                        f"📱 {phone}\n"
                        f"📅 Дата доставки: {order_date}\n"
                        f"🕐 Время: {selected_slot}\n\n"
                        f"📦 Позиции:\n{items_text.strip()}\n\n"
                        f"💰 Сумма: {total_amount:,} сум\n"
                        f"{payment_labels.get(payment_method, payment_labels['balance'])}"
                    )
                    if is_first_order:
                        admin_text += (
                            "\n\n🥤 Не забудьте положить компот 0,5 л в подарок!"
                        )

                    admin_ids = [
                        int(value.strip())
                        for value in os.getenv("ADMIN_IDS", "").split(",")
                        if value.strip()
                    ]
                    for admin_id in admin_ids:
                        try:
                            await bot.send_message(admin_id, admin_text)
                        except Exception as e:
                            logger.warning(
                                f"Не удалось уведомить админа {admin_id} "
                                f"о новом заказе: {e}"
                            )
                except Exception as e:
                    logger.error(f"New order admin notify error: {e}")
        except Exception as e:
            logger.error(f"Order notify error: {e}")
        finally:
            await bot.session.close()

        return web.json_response({"success": True}, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_order error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_my_order(request):
    """POST /api/my-order — позиции заказа на выбранную дату."""
    try:
        init_data = await get_init_data_from_request(request)
        body = await request.json()
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        order_date, date_error = resolve_order_date(body.get("order_date"))
        if date_error:
            return web.json_response(
                {"error": date_error}, status=400, headers=cors_headers()
            )

        pool = await get_pool()
        async with pool.acquire() as db:
            rows = await db.fetch(
                """SELECT o.id, o.menu_id, o.status, m.name as meal_name, m.category, m.price
                   FROM orders o
                   JOIN users u ON o.user_id = u.id
                   JOIN menus m ON o.menu_id = m.id
                   WHERE u.telegram_id = $1 AND o.order_date = $2::text
                   AND o.status != 'cancelled'
                   ORDER BY m.category, m.item_number""",
                telegram_id, order_date
            )
            slot_row = await db.fetchrow(
                """SELECT ds.slot FROM delivery_slots ds
                   JOIN users u ON u.id = ds.user_id
                   WHERE u.telegram_id = $1 AND ds.order_date = $2::text""",
                telegram_id, order_date
            )

        # Группируем по menu_id — несколько строк orders с одинаковым menu_id
        # означают "несколько штук этого блюда", показываем как qty, а не дублируем.
        grouped = {}
        for r in rows:
            key = r["menu_id"]
            if key not in grouped:
                grouped[key] = {
                    "menu_id": r["menu_id"],
                    "meal_name": r["meal_name"],
                    "category": r["category"],
                    "price": r["price"],
                    "status": r["status"],
                    "qty": 0,
                    "order_ids": []
                }
            grouped[key]["qty"] += 1
            grouped[key]["order_ids"].append(r["id"])

        items = list(grouped.values())
        total = sum(i["price"] * i["qty"] for i in items)

        return web.json_response({
            "items": items,
            "total": total,
            "date_label": order_date,
            "order_date": order_date,
            "delivery_slot": slot_row["slot"] if slot_row else None
        }, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_my_order error: {e}")
        return web.json_response({"error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_update_order_qty(request):
    """
    POST /api/update-order-qty — изменяет количество позиции на выбранную дату.
    direction: "inc" (добавить одну единицу) или "dec" (убрать одну единицу).
    Если после уменьшения остаётся 0 — позиция удаляется полностью (отменяется).
    """
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"success": False, "error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        body = await request.json()
        menu_id = body.get("menu_id")
        direction = body.get("direction")  # "inc" | "dec"
        order_date, date_error = resolve_order_date(body.get("order_date"))
        if date_error:
            return web.json_response(
                {"success": False, "error": date_error},
                headers=cors_headers()
            )

        if direction == "inc" and not is_orders_open():
            return web.json_response({
                "success": False,
                "error": f"Изменение заказа доступно с {ORDER_OPEN_TIME} до {ORDER_CLOSE_TIME}."
            }, headers=cors_headers())

        if direction not in ("inc", "dec") or not menu_id:
            return web.json_response({"success": False, "error": "Неверные параметры"}, headers=cors_headers())

        pool = await get_pool()
        async with pool.acquire() as db:
            user = await db.fetchrow("SELECT id FROM users WHERE telegram_id = $1", telegram_id)
            if not user:
                return web.json_response({"success": False, "error": "User not found"}, status=404, headers=cors_headers())
            user_db_id = user["id"]

            # Заказ можно менять только пока он pending (до закрытия в 20:00)
            existing = await db.fetch(
                """SELECT id, status, payment_method FROM orders
                   WHERE user_id = $1 AND menu_id = $2 AND order_date = $3::text AND status != 'cancelled'
                   ORDER BY id""",
                user_db_id, int(menu_id), order_date
            )
            if existing and existing[0]["status"] != "pending":
                return web.json_response({"success": False, "error": "Заказ уже подтверждён, изменение недоступно"}, headers=cors_headers())

            if direction == "inc":
                allowed_item = await db.fetchval(
                    """SELECT 1 FROM menus
                       WHERE id = $1 AND menu_date = $2::text
                       AND category != 'main' AND is_active = 1""",
                    int(menu_id), order_date
                )
                if not allowed_item:
                    return web.json_response({
                        "success": False,
                        "error": "Эта позиция больше недоступна."
                    }, headers=cors_headers())
                payment_method = existing[0]["payment_method"] if existing else "balance"
                await db.execute(
                    """INSERT INTO orders (user_id, menu_id, order_date, status, payment_method)
                       VALUES ($1, $2, $3::text, 'pending', $4)""",
                    user_db_id, int(menu_id), order_date, payment_method
                )
                await db.execute(
                    "UPDATE users SET total_orders = total_orders + 1, points = points + 5 WHERE id = $1",
                    user_db_id
                )
            else:
                if not existing:
                    return web.json_response({"success": False, "error": "Позиция не найдена"}, headers=cors_headers())
                await db.execute("UPDATE orders SET status = 'cancelled' WHERE id = $1", existing[0]["id"])
                await db.execute(
                    "UPDATE users SET total_orders = total_orders - 1, points = points - 5 WHERE id = $1",
                    user_db_id
                )

        return web.json_response({"success": True}, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_update_order_qty error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_cancel_order(request):
    """POST /api/cancel-order — отменить заказ на выбранную дату."""
    try:
        init_data = await get_init_data_from_request(request)
        body = await request.json()
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"success": False, "error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        order_date, date_error = resolve_order_date(body.get("order_date"))
        if date_error:
            return web.json_response(
                {"success": False, "error": date_error},
                headers=cors_headers()
            )

        pool = await get_pool()
        async with pool.acquire() as db:
            user = await db.fetchrow(
                """SELECT u.id, u.full_name, u.phone,
                          c.name AS company_name
                   FROM users u
                   LEFT JOIN companies c ON c.id = u.company_id
                   WHERE u.telegram_id = $1""",
                telegram_id
            )
            if not user:
                return web.json_response({"success": False, "error": "User not found"}, status=404, headers=cors_headers())

            cancelled_items = await db.fetch(
                """SELECT m.name, m.price, COUNT(o.id) AS qty
                   FROM orders o
                   JOIN menus m ON m.id = o.menu_id
                   WHERE o.user_id = $1
                   AND o.order_date = $2::text
                   AND o.status = 'pending'
                   GROUP BY m.id, m.name, m.price
                   ORDER BY m.name""",
                user["id"], order_date
            )
            cancelled_total = sum(
                item["price"] * item["qty"] for item in cancelled_items
            )
            delivery_slot = await db.fetchval(
                """SELECT slot FROM delivery_slots
                   WHERE user_id = $1 AND order_date = $2::text""",
                user["id"], order_date
            )

            debit_marker = f"|{order_date}"
            refund_marker = f"REFUND|{order_date}"

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
                user["id"], order_date
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
            bot = Bot(token=BOT_TOKEN)
            try:
                refund_text = (
                    f"\n💳 +{refund_amount:,} сум возвращено на баланс" if refund_amount > 0 else ""
                )
                try:
                    await bot.send_message(
                        telegram_id,
                        f"❌ *Заказ отменён*{refund_text}",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.warning(
                        f"Не удалось уведомить клиента {telegram_id} об отмене: {e}"
                    )

                items_text = "\n".join(
                    f"• {item['name']} × {item['qty']} — "
                    f"{item['price'] * item['qty']:,} сум"
                    for item in cancelled_items
                )
                admin_text = (
                    "❌ КЛИЕНТ ОТМЕНИЛ ЗАКАЗ\n\n"
                    f"👤 {user['full_name'] or 'Клиент'}\n"
                    f"🏢 {user['company_name'] or '—'}\n"
                    f"📱 {'+' + user['phone'] if user['phone'] else '—'}\n"
                    f"📅 Дата доставки: {order_date}\n"
                    f"🕐 Время доставки: {delivery_slot or '—'}\n\n"
                    f"📦 Отменённые позиции:\n{items_text}\n\n"
                    f"💰 Сумма: {cancelled_total:,} сум"
                )
                if refund_amount > 0:
                    admin_text += (
                        f"\n💳 Возвращено клиенту: {refund_amount:,} сум"
                    )

                admin_ids = [
                    int(value.strip())
                    for value in os.getenv("ADMIN_IDS", "").split(",")
                    if value.strip()
                ]
                for admin_id in admin_ids:
                    try:
                        await bot.send_message(admin_id, admin_text)
                    except Exception as e:
                        logger.warning(
                            f"Не удалось уведомить админа {admin_id} об отмене: {e}"
                        )
            finally:
                await bot.session.close()

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
            "is_admin": telegram_id in get_admin_ids(),
        }, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_profile error: {e}")
        return web.json_response({"error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_rating(request):
    """POST /api/rating — топ компаний за месяц"""
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        pool = await get_pool()
        async with pool.acquire() as db:
            current_user = await db.fetchrow(
                "SELECT company_id FROM users WHERE telegram_id = $1", telegram_id
            )
            rows = await db.fetch(
                """SELECT c.id, c.name, c.total_orders,
                   (SELECT COUNT(*) FROM orders o
                    JOIN users u ON o.user_id = u.id
                    WHERE u.company_id = c.id
                    AND to_char(o.created_at, 'YYYY-MM') = to_char(NOW(), 'YYYY-MM')
                    AND o.status != 'cancelled') as month_orders
                   FROM companies c
                   ORDER BY month_orders DESC, c.name ASC"""
            )
        companies = [dict(r) for r in rows[:10]]
        current_company = None
        company_id = current_user["company_id"] if current_user else None
        if company_id:
            for index, row in enumerate(rows):
                if row["id"] == company_id:
                    previous_orders = rows[index - 1]["month_orders"] if index > 0 else row["month_orders"]
                    current_company = {
                        "name": row["name"],
                        "rank": index + 1,
                        "month_orders": row["month_orders"],
                        "orders_to_next": max(0, previous_orders - row["month_orders"] + (1 if index > 0 else 0)),
                    }
                    break
        return web.json_response({
            "companies": companies,
            "current_company": current_company,
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


async def prepare_pending_click_order(db, user, order_payload):
    """Проверяет корзину и сохраняет её до перехода клиента в Click."""
    items = order_payload.get("items") or []
    order_date, date_error = resolve_order_date(
        order_payload.get("order_date"), require_active=True
    )
    if date_error:
        return {"error": date_error, "date_changed": True}

    delivery_slot = order_payload.get("delivery_slot")
    slot_ok, slot_error = validate_delivery_slot(delivery_slot, order_date)
    if not slot_ok:
        return {"error": slot_error}
    if not items:
        return {"error": "Корзина пуста"}

    normalized_items = []
    total_amount = 0
    expected_weekday = date.fromisoformat(order_date).weekday()

    for entry in items:
        try:
            menu_id = entry.get("menu_id")
            qty = int(entry.get("qty", 1))
        except (TypeError, ValueError):
            return {"error": "Неверное количество блюда"}
        if qty < 1 or qty > 100:
            return {"error": "Неверное количество блюда"}

        if isinstance(menu_id, str) and menu_id.startswith("weekly_"):
            try:
                _, day_num, item_number, category = menu_id.split("_")
                day_num = int(day_num)
                item_number = int(item_number)
            except (TypeError, ValueError):
                return {"error": "Меню уже обновилось. Откройте его заново."}

            if day_num != expected_weekday or category in HIDDEN_CLIENT_CATEGORIES:
                return {"error": "Меню уже обновилось. Откройте его заново."}

            weekly_item = await db.fetchrow(
                """SELECT item_number, name, price, photo_id, category
                   FROM weekly_menu
                   WHERE day_of_week = $1 AND item_number = $2
                   AND category = $3 AND category != 'main'
                   AND is_active = 1""",
                day_num, item_number, category
            )
            if not weekly_item:
                return {"error": "Одна из позиций больше недоступна. Обновите меню."}

            real_item = await db.fetchrow(
                """INSERT INTO menus
                   (menu_date, item_number, name, description, price, photo_id, category)
                   VALUES ($1, $2, $3, '', $4, $5, $6)
                   ON CONFLICT (menu_date, item_number, category)
                   DO UPDATE SET name = EXCLUDED.name,
                                 price = EXCLUDED.price,
                                 photo_id = EXCLUDED.photo_id
                   RETURNING id, name, price""",
                order_date,
                weekly_item["item_number"],
                weekly_item["name"],
                weekly_item["price"],
                weekly_item["photo_id"],
                weekly_item["category"],
            )
        else:
            try:
                numeric_menu_id = int(menu_id)
            except (TypeError, ValueError):
                return {"error": "Одна из позиций больше недоступна. Обновите меню."}
            real_item = await db.fetchrow(
                """SELECT id, name, price FROM menus
                   WHERE id = $1 AND menu_date = $2::text
                   AND category != 'main' AND is_active = 1""",
                numeric_menu_id, order_date
            )
            if not real_item:
                return {"error": "Одна из позиций больше недоступна. Обновите меню."}

        normalized_items.append({
            "menu_id": int(real_item["id"]),
            "name": real_item["name"],
            "price": int(real_item["price"]),
            "qty": qty,
        })
        total_amount += int(real_item["price"]) * qty

    if total_amount < 40000:
        return {"error": "Минимальная сумма заказа — 40 000 сум"}

    current_balance = await db.fetchval(
        "SELECT balance FROM user_balance WHERE user_id = $1", user["id"]
    ) or 0
    topup_amount = max(total_amount - int(current_balance), 0)
    if topup_amount < 100:
        return {
            "balance_sufficient": True,
            "total_amount": total_amount,
        }

    await ensure_pending_click_orders_table(db)
    merchant_trans_id = (
        f"clickorder_{user['id']}_{secrets.token_hex(8)}"
    )
    await db.execute(
        """INSERT INTO pending_click_orders
           (merchant_trans_id, user_id, order_date, delivery_slot,
            items_json, total_amount, topup_amount)
           VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7)""",
        merchant_trans_id,
        user["id"],
        order_date,
        delivery_slot,
        json.dumps(normalized_items, ensure_ascii=False),
        total_amount,
        topup_amount,
    )
    return {
        "merchant_trans_id": merchant_trans_id,
        "amount": topup_amount,
        "total_amount": total_amount,
        "order_date": order_date,
    }


async def handle_webapp_topup(request):
    """POST /api/topup — ссылка Click для баланса или сохранённого заказа."""
    try:
        init_data = await get_init_data_from_request(request)
        body = await request.json() if request.has_body else {}
        order_payload = body.get("order")

        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        pool = await get_pool()
        async with pool.acquire() as db:
            user = await db.fetchrow("SELECT id FROM users WHERE telegram_id = $1", telegram_id)
            if not user:
                return web.json_response({"error": "User not registered"}, status=404, headers=cors_headers())

            if isinstance(order_payload, dict):
                async with db.transaction():
                    prepared = await prepare_pending_click_order(
                        db, user, order_payload
                    )
                if prepared.get("error"):
                    return web.json_response(prepared, headers=cors_headers())
                if prepared.get("balance_sufficient"):
                    return web.json_response(prepared, headers=cors_headers())
                merchant_trans_id = prepared["merchant_trans_id"]
                amount = prepared["amount"]
            else:
                try:
                    amount = int(body.get("amount", 0))
                except (TypeError, ValueError):
                    amount = 0
                if amount < 100:
                    return web.json_response(
                        {"error": "Минимальная сумма — 100 сум"},
                        headers=cors_headers()
                    )
                merchant_trans_id = f"balance_{user['id']}_{amount}"

        from urllib.parse import urlencode
        click_query = urlencode({
            "service_id": CLICK_SERVICE_ID,
            "merchant_id": CLICK_MERCHANT_ID,
            "amount": amount,
            "transaction_param": merchant_trans_id,
            "return_url": "https://t.me/BazilikCateringBot",
        })
        click_link = (
            f"https://my.click.uz/services/pay?{click_query}"
        )

        return web.json_response({
            "click_link": click_link,
            "amount": amount,
            "merchant_trans_id": merchant_trans_id,
            "order_saved": isinstance(order_payload, dict),
        }, headers=cors_headers())
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


async def handle_webapp_support_request(request):
    """POST /api/support-request — обращение клиента администратору."""
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"error": "Invalid auth"}, status=401, headers=cors_headers())

        payload = await request.json()
        topic = str(payload.get("topic") or "other").strip().lower()
        message = str(payload.get("message") or "").strip()
        if topic not in {"order", "payment", "delivery", "other"}:
            topic = "other"
        if len(message) < 5 or len(message) > 1000:
            return web.json_response({"error": "Сообщение должно содержать от 5 до 1000 символов"}, status=400, headers=cors_headers())

        telegram_id = user_data.get("id")
        pool = await get_pool()
        async with pool.acquire() as db:
            user = await db.fetchrow(
                """SELECT u.id, u.full_name, u.phone, c.name AS company_name
                   FROM users u LEFT JOIN companies c ON c.id = u.company_id
                   WHERE u.telegram_id = $1""",
                telegram_id,
            )
            if not user:
                return web.json_response({"error": "User not registered"}, status=404, headers=cors_headers())
            await db.execute(
                """CREATE TABLE IF NOT EXISTS support_requests (
                       id BIGSERIAL PRIMARY KEY,
                       user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                       topic TEXT NOT NULL,
                       message TEXT NOT NULL,
                       status TEXT NOT NULL DEFAULT 'new',
                       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                   )"""
            )
            duplicate = await db.fetchval(
                """SELECT EXISTS(
                       SELECT 1 FROM support_requests
                       WHERE user_id = $1 AND topic = $2 AND message = $3
                       AND created_at > NOW() - INTERVAL '5 minutes'
                   )""",
                user["id"], topic, message,
            )
            if not duplicate:
                await db.execute(
                    "INSERT INTO support_requests (user_id, topic, message) VALUES ($1, $2, $3)",
                    user["id"], topic, message,
                )

        topic_names = {
            "order": "📦 Заказ", "payment": "💳 Оплата",
            "delivery": "🚚 Доставка", "other": "💬 Другое",
        }
        notice = (
            "🆘 НОВОЕ ОБРАЩЕНИЕ\n\n"
            f"Тема: {topic_names[topic]}\n"
            f"Клиент: {user['full_name'] or '—'}\n"
            f"Компания: {user['company_name'] or '—'}\n"
            f"Телефон: {'+' + user['phone'] if user['phone'] else '—'}\n"
            f"Telegram ID: {telegram_id}\n\n"
            f"{message}"
        )
        if not duplicate and BOT_TOKEN:
            bot = Bot(token=BOT_TOKEN)
            try:
                for admin_id in get_admin_ids():
                    try:
                        await bot.send_message(admin_id, notice)
                    except Exception as exc:
                        logger.warning("Не удалось отправить обращение админу %s: %s", admin_id, exc)
            finally:
                await bot.session.close()

        return web.json_response({"success": True, "duplicate": bool(duplicate)}, headers=cors_headers())
    except Exception as e:
        logger.error("webapp_support_request error: %s", e)
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
                   WHERE user_id = $1 AND is_active = 1
                   AND category != 'main'""",
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
                       WHERE day_of_week = $1 AND item_number = $2
                       AND category = $3 AND category != 'main'
                       AND is_active = 1""",
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


DELIVERY_START_MINUTES = 8 * 60
DELIVERY_END_MINUTES = 16 * 60


def validate_delivery_slot(slot, order_date):
    """
    Проверяет выбранное время доставки.

    Mini App отправляет конкретное время в формате HH:MM:
    самое быстрое — через 60 минут, остальные варианты — с шагом 30 минут.
    Доставка доступна с 08:00 до 16:00 по времени Ташкента.
    """
    if not isinstance(slot, str):
        return False, "Недопустимое время доставки"

    try:
        hours_text, minutes_text = slot.split(":")
        if len(hours_text) != 2 or len(minutes_text) != 2:
            raise ValueError
        hours = int(hours_text)
        minutes = int(minutes_text)
        if not (0 <= hours <= 23 and 0 <= minutes <= 59):
            raise ValueError
    except (TypeError, ValueError):
        return False, "Недопустимое время доставки"

    selected_minutes = hours * 60 + minutes
    if not DELIVERY_START_MINUTES <= selected_minutes <= DELIVERY_END_MINUTES:
        return False, "Доставка доступна с 08:00 до 16:00"

    now = tashkent_now()
    try:
        target_date = date.fromisoformat(order_date)
    except (TypeError, ValueError):
        return False, "Недопустимая дата заказа"

    # Для завтрашнего заказа доступны все интервалы с 08:00.
    # Правило «через 60 минут» применяется только к доставке сегодня.
    earliest_minutes = now.hour * 60 + now.minute + DELIVERY_MINUTES
    if target_date == now.date() and selected_minutes < earliest_minutes:
        return False, "Выберите время не раньше чем через 60 минут"

    return True, None


async def handle_webapp_set_delivery_slot(request):
    """POST /api/set-delivery-slot — сохраняет время на актуальную дату заказа."""
    try:
        init_data = await get_init_data_from_request(request)
        user_data = await verify_telegram_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"success": False, "error": "Invalid auth"}, status=401, headers=cors_headers())

        telegram_id = user_data.get("id")
        body = await request.json()
        slot = body.get("slot")
        order_date, date_error = resolve_order_date(
            body.get("order_date"), require_active=True
        )
        if date_error:
            return web.json_response(
                {"success": False, "error": date_error, "date_changed": True},
                headers=cors_headers()
            )

        is_valid, validation_error = validate_delivery_slot(slot, order_date)
        if not is_valid:
            return web.json_response(
                {"success": False, "error": validation_error},
                headers=cors_headers()
            )

        pool = await get_pool()
        async with pool.acquire() as db:
            user = await db.fetchrow("SELECT id FROM users WHERE telegram_id = $1", telegram_id)
            if not user:
                return web.json_response({"success": False, "error": "User not found"}, status=404, headers=cors_headers())
            await db.execute(
                """INSERT INTO delivery_slots (user_id, order_date, slot)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (user_id, order_date) DO UPDATE SET slot = $3""",
                user["id"], order_date, slot
            )

        return web.json_response({
            "success": True,
            "slot": slot,
            "order_date": order_date
        }, headers=cors_headers())
    except Exception as e:
        logger.error(f"webapp_set_delivery_slot error: {e}")
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
                """SELECT id, item_number, name, price, category, photo_id FROM menus
                   WHERE menu_date = $1::text AND is_active = 1
                   AND category != 'main'
                   ORDER BY category, item_number""",
                target_date
            )
            if not rows:
                day_num = date_cls.fromisoformat(target_date).weekday()
                rows = await db.fetch(
                    """SELECT item_number, name, price, category, photo_id FROM weekly_menu
                       WHERE day_of_week = $1 AND is_active = 1
                       AND category != 'main'
                       ORDER BY category, item_number""",
                    day_num
                )

        items = [dict(r) for r in rows]
        for item in items:
            photo_id = item.pop("photo_id", None)
            item["photo_url"] = build_photo_url(photo_id)

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
        if category in HIDDEN_CLIENT_CATEGORIES:
            return web.json_response({
                "success": False,
                "error": "Категория «Вторые блюда» временно недоступна."
            }, headers=cors_headers())

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
            # COUNT(DISTINCT user_id) — уникальные клиенты заказавшие блюдо,
            # не количество строк в orders
            top_dishes = await db.fetch(
                """SELECT m.name, m.category, COUNT(DISTINCT o.user_id) as cnt
                   FROM orders o
                   JOIN menus m ON o.menu_id = m.id
                   WHERE o.order_date >= $1::text
                   AND o.status != 'cancelled'
                   GROUP BY m.name, m.category
                   ORDER BY cnt DESC
                   LIMIT 5""",
                str(today - td_cls(days=30))
            )

            # Общая статистика — считаем уникальные заказы (user_id + order_date),
            # а не строки positions
            total_users = await db.fetchval("SELECT COUNT(*) FROM users")
            total_companies = await db.fetchval("SELECT COUNT(*) FROM companies")
            total_all_orders = await db.fetchval(
                """SELECT COUNT(DISTINCT (user_id, order_date))
                   FROM orders WHERE status != 'cancelled'"""
            )
            avg_rating = await db.fetchval("SELECT AVG(rating) FROM reviews")

            # ── Статистика "прямо сейчас" (онлайн-режим) ──────────────────
            today_str = str(today)

            # Активных заказов сегодня (уникальных клиентов)
            orders_today_total = await db.fetchval(
                """SELECT COUNT(DISTINCT user_id) FROM orders
                   WHERE order_date = $1::text AND status != 'cancelled'""",
                today_str
            )
            # Позиций сегодня
            positions_today = await db.fetchval(
                """SELECT COUNT(*) FROM orders
                   WHERE order_date = $1::text AND status != 'cancelled'""",
                today_str
            )
            # Выручка сегодня
            revenue_today_total = await db.fetchval(
                """SELECT COALESCE(SUM(m.price), 0) FROM orders o
                   JOIN menus m ON o.menu_id = m.id
                   WHERE o.order_date = $1::text AND o.status != 'cancelled'""",
                today_str
            )
            # Статус доставки
            delivered_today = await db.fetchval(
                """SELECT COUNT(DISTINCT user_id) FROM orders
                   WHERE order_date = $1::text AND status = 'delivered'""",
                today_str
            )
            in_transit_today = await db.fetchval(
                """SELECT COUNT(DISTINCT user_id) FROM orders
                   WHERE order_date = $1::text AND status = 'in_transit'""",
                today_str
            )
            pending_today = await db.fetchval(
                """SELECT COUNT(DISTINCT user_id) FROM orders
                   WHERE order_date = $1::text AND status = 'pending'""",
                today_str
            )

            now_stats = {
                "orders_today": orders_today_total or 0,
                "positions_today": positions_today or 0,
                "revenue_today": revenue_today_total or 0,
                "pending_today": pending_today or 0,
                "in_transit_today": in_transit_today or 0,
                "delivered_today": delivered_today or 0,
                "date_today": today_str,
                "delivery_minutes": DELIVERY_MINUTES,
                "orders_open": is_orders_open(),
                "open_time": ORDER_OPEN_TIME,
                "close_time": ORDER_CLOSE_TIME,
            }

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
            "couriers_stats": couriers_stats,
            "now_stats": now_stats
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
    app.router.add_post("/api/toggle-favorite", handle_webapp_toggle_favorite)
    app.router.add_post("/api/corporate-request", handle_webapp_corporate_request)
    app.router.add_post("/api/order", handle_webapp_order)
    app.router.add_post("/api/my-order", handle_webapp_my_order)
    app.router.add_post("/api/cancel-order", handle_webapp_cancel_order)
    app.router.add_post("/api/profile", handle_webapp_profile)
    app.router.add_post("/api/rating", handle_webapp_rating)
    app.router.add_post("/api/balance-history", handle_webapp_balance_history)
    app.router.add_post("/api/topup", handle_webapp_topup)
    app.router.add_post("/api/gifts", handle_webapp_gifts)
    app.router.add_post("/api/referral", handle_webapp_referral)
    app.router.add_post("/api/support-request", handle_webapp_support_request)
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
    app.router.add_post("/api/set-delivery-slot", handle_webapp_set_delivery_slot)
    app.router.add_post("/api/update-order-qty", handle_webapp_update_order_qty)

    for path in ["/api/menu", "/api/toggle-favorite", "/api/corporate-request",
                 "/api/order", "/api/my-order", "/api/cancel-order",
                 "/api/profile", "/api/rating", "/api/balance-history", "/api/topup",
                 "/api/gifts", "/api/referral", "/api/support-request", "/api/settings",
                 "/api/settings/toggle-auto", "/api/settings/weekly-menu", "/api/settings/set-weekly",
                 "/api/dashboard", "/api/autoorder", "/api/full-settings", "/api/update-profile",
                 "/api/update-company-address", "/api/update-birthday", "/api/update-lang",
                 "/api/toggle-notification", "/api/update-order-location", "/api/set-delivery-slot",
                 "/api/update-order-qty"]:
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
