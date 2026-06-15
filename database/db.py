import logging
import asyncpg
from datetime import date
from config import DATABASE_URL

logger = logging.getLogger(__name__)

_pool = None


async def get_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL)
    return _pool


async def init_db():
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS companies (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                total_orders INTEGER DEFAULT 0,
                city TEXT DEFAULT 'Ташкент',
                address TEXT,
                maps_link TEXT,
                contact TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,
                full_name TEXT,
                username TEXT,
                company_id INTEGER REFERENCES companies(id),
                points INTEGER DEFAULT 0,
                total_orders INTEGER DEFAULT 0,
                streak_days INTEGER DEFAULT 0,
                last_order_date TEXT,
                referral_code TEXT UNIQUE,
                referred_by INTEGER REFERENCES users(id),
                auto_order INTEGER DEFAULT 0,
                auto_order_item INTEGER DEFAULT 1,
                status TEXT DEFAULT 'Новый',
                lang TEXT DEFAULT 'ru',
                phone TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS menus (
                id SERIAL PRIMARY KEY,
                menu_date TEXT NOT NULL,
                item_number INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                price INTEGER DEFAULT 35000,
                photo_id TEXT,
                is_active INTEGER DEFAULT 1,
                category TEXT DEFAULT 'main',
                UNIQUE(menu_date, item_number, category)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS weekly_menu (
                id SERIAL PRIMARY KEY,
                day_of_week INTEGER NOT NULL,
                item_number INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                price INTEGER DEFAULT 35000,
                photo_id TEXT,
                category TEXT DEFAULT 'main',
                is_active INTEGER DEFAULT 1,
                UNIQUE(day_of_week, item_number, category)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                menu_id INTEGER REFERENCES menus(id),
                order_date TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                is_auto_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS weekly_orders (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                day_of_week INTEGER NOT NULL,
                menu_item INTEGER NOT NULL,
                is_active INTEGER DEFAULT 1,
                UNIQUE(user_id, day_of_week)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS balance_transactions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                amount INTEGER NOT NULL,
                type TEXT NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_balance (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) UNIQUE,
                balance INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ─── Таблицы для курьерской системы ───────────────────────────────
        await db.execute("""
            CREATE TABLE IF NOT EXISTS couriers (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                phone TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS delivery_routes (
                id SERIAL PRIMARY KEY,
                courier_id INTEGER REFERENCES couriers(id),
                delivery_date TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                started_at TIMESTAMP,
                finished_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(courier_id, delivery_date)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS delivery_stops (
                id SERIAL PRIMARY KEY,
                route_id INTEGER REFERENCES delivery_routes(id),
                company_id INTEGER REFERENCES companies(id),
                stop_order INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                delivered_at TIMESTAMP,
                note TEXT
            )
        """)

        # Миграции
        await db.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='users' AND column_name='birthday'
                ) THEN
                    ALTER TABLE users ADD COLUMN birthday DATE;
                END IF;
            END
            $$;
        """)
        await db.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='menus' AND column_name='category'
                ) THEN
                    ALTER TABLE menus ADD COLUMN category TEXT DEFAULT 'main';
                END IF;
            END
            $$;
        """)

    logger.info("✅ Таблицы созданы / обновлены")


# ─── Пользователи ─────────────────────────────────────────────────────────────

async def get_user(telegram_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            """SELECT u.*, c.name as company_name, c.total_orders as company_orders
               FROM users u
               LEFT JOIN companies c ON u.company_id = c.id
               WHERE u.telegram_id = $1""",
            telegram_id
        )
        return dict(row) if row else None


async def get_user_lang(telegram_id: int) -> str:
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            "SELECT lang FROM users WHERE telegram_id = $1", telegram_id
        )
        return row["lang"] if row else "ru"


async def set_user_lang(telegram_id: int, lang: str):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE users SET lang = $1 WHERE telegram_id = $2",
            lang, telegram_id
        )


async def create_user(telegram_id: int, full_name: str, username: str,
                      company_id: int, referral_code: str, referred_by_code: str = None) -> dict:
    referred_by_id = None
    bonus_points = 0

    if referred_by_code:
        pool = await get_pool()
        async with pool.acquire() as db:
            ref_row = await db.fetchrow(
                "SELECT id FROM users WHERE referral_code = $1", referred_by_code
            )
            if ref_row:
                referred_by_id = ref_row["id"]
                bonus_points = 10

    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            """INSERT INTO users (telegram_id, full_name, username, company_id,
               referral_code, referred_by, points)
               VALUES ($1, $2, $3, $4, $5, $6, $7)
               ON CONFLICT (telegram_id) DO NOTHING""",
            telegram_id, full_name, username, company_id,
            referral_code, referred_by_id, bonus_points
        )
        if referred_by_id:
            await db.execute(
                "UPDATE users SET points = points + 5 WHERE id = $1", referred_by_id
            )

    return await get_user(telegram_id)


async def update_user_status(user_id: int, total_orders: int) -> str:
    if total_orders >= 30:
        status = "VIP 👑"
    elif total_orders >= 20:
        status = "Золотой 🥇"
    elif total_orders >= 10:
        status = "Серебряный 🥈"
    elif total_orders >= 5:
        status = "Бронзовый 🥉"
    else:
        status = "Новый 🆕"

    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE users SET status = $1 WHERE id = $2", status, user_id
        )
    return status


async def save_user_phone(telegram_id: int, phone: str):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE users SET phone = $1 WHERE telegram_id = $2",
            phone, telegram_id
        )


# ─── Компании ─────────────────────────────────────────────────────────────────

async def get_or_create_company(name: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow("SELECT id FROM companies WHERE name = $1", name)
        if row:
            return row["id"]
        row = await db.fetchrow(
            "INSERT INTO companies (name) VALUES ($1) RETURNING id", name
        )
        return row["id"]


async def get_company_ranking(city: str = "Ташкент") -> list:
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
        return [dict(r) for r in rows]


# ─── Меню ─────────────────────────────────────────────────────────────────────

async def get_menu(menu_date: str, category: str = "main") -> list:
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            """SELECT * FROM menus
               WHERE menu_date = $1 AND is_active = 1 AND category = $2
               ORDER BY item_number""",
            menu_date, category
        )
        if rows:
            return [dict(r) for r in rows]

        d = date.fromisoformat(menu_date)
        day_num = d.weekday()
        weekly_rows = await db.fetch(
            """SELECT * FROM weekly_menu
               WHERE day_of_week = $1 AND is_active = 1 AND category = $2
               ORDER BY item_number""",
            day_num, category
        )
        if not weekly_rows:
            return []

        for item in weekly_rows:
            await db.execute(
                """INSERT INTO menus (menu_date, item_number, name, description, price, photo_id, category)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)
                   ON CONFLICT (menu_date, item_number, category) DO NOTHING""",
                menu_date, item["item_number"], item["name"],
                item["description"] or "", item["price"],
                item["photo_id"], category
            )

        rows = await db.fetch(
            """SELECT * FROM menus
               WHERE menu_date = $1 AND is_active = 1 AND category = $2
               ORDER BY item_number""",
            menu_date, category
        )
        return [dict(r) for r in rows]


async def get_menu_categories(menu_date: str) -> list:
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            """SELECT DISTINCT category FROM menus
               WHERE menu_date = $1 AND is_active = 1
               ORDER BY category""",
            menu_date
        )
        if rows:
            return [row["category"] for row in rows]

        d = date.fromisoformat(menu_date)
        day_num = d.weekday()
        rows = await db.fetch(
            """SELECT DISTINCT category FROM weekly_menu
               WHERE day_of_week = $1 AND is_active = 1
               ORDER BY category""",
            day_num
        )
        return [row["category"] for row in rows]


async def set_menu(menu_date: str, items: list, category: str = "main"):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "DELETE FROM menus WHERE menu_date = $1 AND category = $2",
            menu_date, category
        )
        for item in items:
            await db.execute(
                """INSERT INTO menus (menu_date, item_number, name, description, price, photo_id, category)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                menu_date, item["item_number"], item["name"],
                item.get("description", ""), item.get("price", 35000),
                item.get("photo_id"), category
            )


async def set_weekly_menu(day_of_week: int, items: list, category: str = "main"):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "DELETE FROM weekly_menu WHERE day_of_week = $1 AND category = $2",
            day_of_week, category
        )
        for item in items:
            await db.execute(
                """INSERT INTO weekly_menu
                   (day_of_week, item_number, name, description, price, photo_id, category)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                day_of_week, item["item_number"], item["name"],
                item.get("description", ""), item.get("price", 35000),
                item.get("photo_id"), category
            )


async def get_weekly_menu(day_of_week: int, category: str = "main") -> list:
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            """SELECT * FROM weekly_menu
               WHERE day_of_week = $1 AND is_active = 1 AND category = $2
               ORDER BY item_number""",
            day_of_week, category
        )
        return [dict(r) for r in rows]


async def get_weekly_menu_categories(day_of_week: int) -> list:
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            """SELECT DISTINCT category FROM weekly_menu
               WHERE day_of_week = $1 AND is_active = 1""",
            day_of_week
        )
        return [row["category"] for row in rows]


async def get_all_weekly_menu_summary() -> dict:
    pool = await get_pool()
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    result = {}
    async with pool.acquire() as db:
        for i, day in enumerate(days):
            rows = await db.fetch(
                """SELECT category, COUNT(*) as cnt FROM weekly_menu
                   WHERE day_of_week = $1 AND is_active = 1
                   GROUP BY category""",
                i
            )
            result[i] = {"day": day, "categories": {r["category"]: r["cnt"] for r in rows}}
    return result


async def delete_weekly_menu_day(day_of_week: int):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "DELETE FROM weekly_menu WHERE day_of_week = $1", day_of_week
        )


# ─── Заказы ───────────────────────────────────────────────────────────────────

async def get_today_order(telegram_id: int, order_date: str) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            """SELECT o.*, m.name as meal_name, m.item_number, m.category
               FROM orders o
               JOIN users u ON o.user_id = u.id
               JOIN menus m ON o.menu_id = m.id
               WHERE u.telegram_id = $1 AND o.order_date = $2 AND o.status != 'cancelled'""",
            telegram_id, order_date
        )
        return dict(row) if row else None


async def create_order(telegram_id: int, menu_id: int, order_date: str,
                       is_auto: bool = False) -> dict:
    pool = await get_pool()
    async with pool.acquire() as db:
        user = await db.fetchrow(
            "SELECT id, company_id FROM users WHERE telegram_id = $1", telegram_id
        )
        await db.execute(
            """INSERT INTO orders (user_id, menu_id, order_date, status, is_auto_order)
               VALUES ($1, $2, $3, 'pending', $4)
               ON CONFLICT DO NOTHING""",
            user["id"], menu_id, order_date, 1 if is_auto else 0
        )
        today = str(date.today())
        await db.execute(
            """UPDATE users SET
               total_orders = total_orders + 1,
               points = points + 5,
               last_order_date = $1,
               streak_days = 0
               WHERE telegram_id = $2""",
            today, telegram_id
        )
        if user["company_id"]:
            await db.execute(
                "UPDATE companies SET total_orders = total_orders + 1 WHERE id = $1",
                user["company_id"]
            )

    user_data = await get_user(telegram_id)
    await update_user_status(user_data["id"], user_data["total_orders"])
    return await get_today_order(telegram_id, order_date)


async def cancel_order(telegram_id: int, order_date: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            """UPDATE orders SET status = 'cancelled'
               WHERE user_id = (SELECT id FROM users WHERE telegram_id = $1)
               AND order_date = $2 AND status = 'pending'""",
            telegram_id, order_date
        )
        await db.execute(
            "UPDATE users SET total_orders = total_orders - 1, points = points - 5 WHERE telegram_id = $1",
            telegram_id
        )
    return True


async def close_orders_for_date(order_date: str):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE orders SET status = 'confirmed' WHERE order_date = $1 AND status = 'pending'",
            order_date
        )


async def get_daily_summary(order_date: str) -> dict:
    pool = await get_pool()
    async with pool.acquire() as db:
        items = await db.fetch(
            """SELECT m.name, m.item_number, m.category, COUNT(*) as count
               FROM orders o
               JOIN menus m ON o.menu_id = m.id
               WHERE o.order_date = $1 AND o.status IN ('confirmed', 'pending')
               GROUP BY m.id, m.name, m.item_number, m.category
               ORDER BY m.category, count DESC""",
            order_date
        )
        total = await db.fetchval(
            "SELECT COUNT(*) FROM orders WHERE order_date = $1 AND status != 'cancelled'",
            order_date
        )
    return {"items": [dict(r) for r in items], "total": total, "date": order_date}


async def get_all_users_for_notification() -> list:
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch("SELECT telegram_id FROM users")
        return [row["telegram_id"] for row in rows]


# ─── Курьерская система ───────────────────────────────────────────────────────

async def get_courier(telegram_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            "SELECT * FROM couriers WHERE telegram_id = $1 AND is_active = TRUE",
            telegram_id
        )
        return dict(row) if row else None


async def create_courier(telegram_id: int, full_name: str, phone: str) -> dict:
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            """INSERT INTO couriers (telegram_id, full_name, phone)
               VALUES ($1, $2, $3)
               ON CONFLICT (telegram_id) DO UPDATE SET full_name=$2, phone=$3, is_active=TRUE""",
            telegram_id, full_name, phone
        )
        row = await db.fetchrow(
            "SELECT * FROM couriers WHERE telegram_id = $1", telegram_id
        )
        return dict(row)


async def get_all_couriers() -> list:
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            "SELECT * FROM couriers WHERE is_active = TRUE ORDER BY full_name"
        )
        return [dict(r) for r in rows]


async def get_orders_by_company(order_date: str) -> list:
    """Заказы сгруппированные по компаниям для распределения курьерам"""
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            """SELECT
                c.id as company_id,
                c.name as company_name,
                c.address,
                c.maps_link,
                COUNT(o.id) as order_count
               FROM orders o
               JOIN users u ON o.user_id = u.id
               JOIN companies c ON u.company_id = c.id
               WHERE o.order_date = $1 AND o.status != 'cancelled'
               GROUP BY c.id, c.name, c.address, c.maps_link
               ORDER BY order_count DESC""",
            order_date
        )
        return [dict(r) for r in rows]


async def get_company_order_details(company_id: int, order_date: str) -> list:
    """Детальный список заказов по компании — каждый клиент и его блюда"""
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            """SELECT
                u.full_name,
                u.phone,
                m.name as meal_name,
                m.category,
                m.price
               FROM orders o
               JOIN users u ON o.user_id = u.id
               JOIN menus m ON o.menu_id = m.id
               WHERE u.company_id = $1
               AND o.order_date = $2
               AND o.status != 'cancelled'
               ORDER BY u.full_name, m.category""",
            company_id, order_date
        )
        return [dict(r) for r in rows]


async def create_delivery_route(courier_id: int, delivery_date: str,
                                 company_ids: list) -> int:
    """Создать маршрут для курьера с список компаний"""
    pool = await get_pool()
    async with pool.acquire() as db:
        # Удаляем старый маршрут если был
        old = await db.fetchrow(
            "SELECT id FROM delivery_routes WHERE courier_id=$1 AND delivery_date=$2",
            courier_id, delivery_date
        )
        if old:
            await db.execute(
                "DELETE FROM delivery_stops WHERE route_id=$1", old["id"]
            )
            await db.execute(
                "DELETE FROM delivery_routes WHERE id=$1", old["id"]
            )

        # Создаём новый маршрут
        route = await db.fetchrow(
            """INSERT INTO delivery_routes (courier_id, delivery_date, status)
               VALUES ($1, $2, 'pending') RETURNING id""",
            courier_id, delivery_date
        )
        route_id = route["id"]

        # Добавляем остановки
        for i, company_id in enumerate(company_ids, 1):
            await db.execute(
                """INSERT INTO delivery_stops (route_id, company_id, stop_order, status)
                   VALUES ($1, $2, $3, 'pending')""",
                route_id, company_id, i
            )

    return route_id


async def get_courier_route(courier_id: int, delivery_date: str) -> dict | None:
    """Получить маршрут курьера на дату"""
    pool = await get_pool()
    async with pool.acquire() as db:
        route = await db.fetchrow(
            """SELECT * FROM delivery_routes
               WHERE courier_id = $1 AND delivery_date = $2""",
            courier_id, delivery_date
        )
        if not route:
            return None

        stops = await db.fetch(
            """SELECT ds.*, c.name as company_name, c.address, c.maps_link,
               COUNT(o.id) as order_count
               FROM delivery_stops ds
               JOIN companies c ON ds.company_id = c.id
               LEFT JOIN orders o ON o.order_date = $2
                   AND o.status != 'cancelled'
                   AND o.user_id IN (
                       SELECT id FROM users WHERE company_id = c.id
                   )
               WHERE ds.route_id = $1
               GROUP BY ds.id, c.name, c.address, c.maps_link
               ORDER BY ds.stop_order""",
            route["id"], delivery_date
        )

        return {
            "route": dict(route),
            "stops": [dict(s) for s in stops]
        }


async def mark_stop_delivered(stop_id: int, note: str = None):
    """Отметить остановку как доставленную"""
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            """UPDATE delivery_stops
               SET status = 'delivered', delivered_at = NOW(), note = $2
               WHERE id = $1""",
            stop_id, note
        )
        # Обновляем статус заказов этой компании
        stop = await db.fetchrow(
            "SELECT route_id, company_id FROM delivery_stops WHERE id = $1", stop_id
        )
        route = await db.fetchrow(
            "SELECT delivery_date FROM delivery_routes WHERE id = $1", stop["route_id"]
        )
        await db.execute(
            """UPDATE orders SET status = 'delivered', updated_at = NOW()
               WHERE order_date = $1
               AND status = 'confirmed'
               AND user_id IN (
                   SELECT id FROM users WHERE company_id = $2
               )""",
            route["delivery_date"], stop["company_id"]
        )


async def mark_route_started(route_id: int):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE delivery_routes SET status='active', started_at=NOW() WHERE id=$1",
            route_id
        )


async def mark_route_finished(route_id: int):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE delivery_routes SET status='finished', finished_at=NOW() WHERE id=$1",
            route_id
        )


async def get_company_clients_telegram_ids(company_id: int, order_date: str) -> list:
    """Telegram ID клиентов компании у которых есть заказ на эту дату"""
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            """SELECT u.telegram_id FROM users u
               JOIN orders o ON o.user_id = u.id
               WHERE u.company_id = $1
               AND o.order_date = $2
               AND o.status != 'cancelled'""",
            company_id, order_date
        )
        return [r["telegram_id"] for r in rows]
