import logging
import asyncpg
from datetime import date, timedelta
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
                payment_method TEXT DEFAULT 'balance',
                paid INTEGER DEFAULT 0,
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
                category TEXT NOT NULL DEFAULT 'main',
                is_active INTEGER DEFAULT 1,
                UNIQUE(user_id, day_of_week, category)
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

        # ─── Новые таблицы для лояльности ──────────────────────────────────
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id SERIAL PRIMARY KEY,
                order_id INTEGER REFERENCES orders(id),
                user_id INTEGER REFERENCES users(id),
                menu_id INTEGER REFERENCES menus(id),
                rating INTEGER NOT NULL,
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(order_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS company_of_month (
                id SERIAL PRIMARY KEY,
                company_id INTEGER REFERENCES companies(id),
                month_year TEXT NOT NULL UNIQUE,
                order_count INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS courier_reviews (
                id SERIAL PRIMARY KEY,
                courier_id INTEGER REFERENCES couriers(id),
                user_id INTEGER REFERENCES users(id),
                delivery_route_id INTEGER REFERENCES delivery_routes(id),
                rating INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, delivery_route_id)
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
        await db.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='users' AND column_name='last_streak_bonus'
                ) THEN
                    ALTER TABLE users ADD COLUMN last_streak_bonus INTEGER DEFAULT 0;
                END IF;
            END
            $$;
        """)
        await db.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='orders' AND column_name='payment_method'
                ) THEN
                    ALTER TABLE orders ADD COLUMN payment_method TEXT DEFAULT 'balance';
                END IF;
            END
            $$;
        """)
        await db.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='orders' AND column_name='paid'
                ) THEN
                    ALTER TABLE orders ADD COLUMN paid INTEGER DEFAULT 0;
                END IF;
            END
            $$;
        """)
        await db.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='weekly_orders' AND column_name='category'
                ) THEN
                    ALTER TABLE weekly_orders ADD COLUMN category TEXT NOT NULL DEFAULT 'main';

                    -- Старый constraint UNIQUE(user_id, day_of_week) больше не подходит,
                    -- так как теперь можно выбрать блюдо в каждой категории на один день.
                    -- Удаляем его и создаём новый с учётом category.
                    IF EXISTS (
                        SELECT 1 FROM pg_constraint WHERE conname = 'weekly_orders_user_id_day_of_week_key'
                    ) THEN
                        ALTER TABLE weekly_orders DROP CONSTRAINT weekly_orders_user_id_day_of_week_key;
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint WHERE conname = 'weekly_orders_user_day_category_key'
                    ) THEN
                        ALTER TABLE weekly_orders ADD CONSTRAINT weekly_orders_user_day_category_key
                        UNIQUE (user_id, day_of_week, category);
                    END IF;
                END IF;
            END
            $$;
        """)
        await db.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='users' AND column_name='notify_reminder'
                ) THEN
                    ALTER TABLE users ADD COLUMN notify_reminder INTEGER DEFAULT 1;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='users' AND column_name='notify_delivery'
                ) THEN
                    ALTER TABLE users ADD COLUMN notify_delivery INTEGER DEFAULT 1;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='users' AND column_name='notify_marketing'
                ) THEN
                    ALTER TABLE users ADD COLUMN notify_marketing INTEGER DEFAULT 1;
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
        old_items = await db.fetch(
            "SELECT id FROM menus WHERE menu_date = $1 AND category = $2",
            menu_date, category
        )
        for old in old_items:
            try:
                await db.execute("DELETE FROM menus WHERE id = $1", old["id"])
            except Exception:
                await db.execute(
                    "UPDATE menus SET is_active = 0 WHERE id = $1", old["id"]
                )

        for item in items:
            await db.execute(
                """INSERT INTO menus (menu_date, item_number, name, description, price, photo_id, category)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)
                   ON CONFLICT (menu_date, item_number, category)
                   DO UPDATE SET name = EXCLUDED.name,
                                 description = EXCLUDED.description,
                                 price = EXCLUDED.price,
                                 photo_id = EXCLUDED.photo_id,
                                 is_active = 1""",
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
               WHERE u.telegram_id = $1 AND o.order_date = $2::text AND o.status != 'cancelled'
               ORDER BY o.id LIMIT 1""",
            telegram_id, str(order_date)
        )
        return dict(row) if row else None


async def get_today_orders_list(telegram_id: int, order_date: str) -> list:
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            """SELECT o.id, o.status, m.name as meal_name, m.item_number,
               m.category, m.price
               FROM orders o
               JOIN users u ON o.user_id = u.id
               JOIN menus m ON o.menu_id = m.id
               WHERE u.telegram_id = $1 AND o.order_date = $2::text
               AND o.status != 'cancelled'
               ORDER BY m.category, m.item_number""",
            telegram_id, str(order_date)
        )
        return [dict(r) for r in rows]


STREAK_MILESTONES = [5, 10, 20, 50]
STREAK_BONUS_POINTS = {5: 15, 10: 30, 20: 60, 50: 150}


async def update_streak_and_get_bonus(telegram_id: int) -> dict | None:
    """
    Обновляет streak_days при заказе на следующий день подряд.
    Если streak достиг порога (5/10/20/50) и бонус за этот порог
    ещё не выдавался — начисляет баллы и возвращает информацию о бонусе.
    Возвращает None если бонуса нет.
    """
    pool = await get_pool()
    today = date.today()
    yesterday = str(today - timedelta(days=1))

    async with pool.acquire() as db:
        user = await db.fetchrow(
            "SELECT id, streak_days, last_order_date, last_streak_bonus FROM users WHERE telegram_id = $1",
            telegram_id
        )
        if not user:
            return None

        last_order = user["last_order_date"]
        current_streak = user["streak_days"] or 0

        # Если последний заказ был "вчера" (по дате создания заказа) — продолжаем серию
        # last_order_date обновляется в create_order на дату ФАКТИЧЕСКОГО создания заказа (today)
        if last_order == yesterday:
            new_streak = current_streak + 1
        elif last_order == str(today):
            # Уже заказывали сегодня — серия не меняется (защита от двойного начисления)
            new_streak = current_streak
        else:
            new_streak = 1

        await db.execute(
            "UPDATE users SET streak_days = $1 WHERE id = $2",
            new_streak, user["id"]
        )

        last_bonus_milestone = user["last_streak_bonus"] or 0
        bonus_info = None

        for milestone in STREAK_MILESTONES:
            if new_streak >= milestone and last_bonus_milestone < milestone:
                bonus_points = STREAK_BONUS_POINTS[milestone]
                await db.execute(
                    "UPDATE users SET points = points + $1, last_streak_bonus = $2 WHERE id = $3",
                    bonus_points, milestone, user["id"]
                )
                await db.execute(
                    """INSERT INTO balance_transactions (user_id, amount, type, description)
                       VALUES ($1, $2, 'credit', $3)""",
                    user["id"], bonus_points, f"🔥 Бонус за серию {milestone} дней"
                )
                bonus_info = {"milestone": milestone, "points": bonus_points, "streak": new_streak}
                break  # начисляем только один (самый актуальный) порог за раз

    return bonus_info


async def create_order(telegram_id: int, menu_id: int, order_date: str,
                       is_auto: bool = False) -> dict:
    pool = await get_pool()
    async with pool.acquire() as db:
        user = await db.fetchrow(
            "SELECT id, company_id FROM users WHERE telegram_id = $1", telegram_id
        )
        await db.execute(
            """INSERT INTO orders (user_id, menu_id, order_date, status, is_auto_order)
               VALUES ($1, $2, $3::text, 'pending', $4)
               ON CONFLICT DO NOTHING""",
            user["id"], menu_id, str(order_date), 1 if is_auto else 0
        )
        today = str(date.today())
        await db.execute(
            """UPDATE users SET
               total_orders = total_orders + 1,
               points = points + 5,
               last_order_date = $1
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
               WHERE id = (
                   SELECT o.id FROM orders o
                   JOIN users u ON o.user_id = u.id
                   WHERE u.telegram_id = $1
                   AND o.order_date = $2::text AND o.status = 'pending'
                   LIMIT 1
               )""",
            telegram_id, str(order_date)
        )
        await db.execute(
            "UPDATE users SET total_orders = total_orders - 1, points = points - 5 WHERE telegram_id = $1",
            telegram_id
        )
    return True


async def cancel_all_orders_for_date(telegram_id: int, order_date: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as db:
        result = await db.fetch(
            """UPDATE orders SET status = 'cancelled'
               WHERE user_id = (SELECT id FROM users WHERE telegram_id = $1)
               AND order_date = $2::text AND status = 'pending'
               RETURNING id""",
            telegram_id, str(order_date)
        )
        cancelled_count = len(result)
        if cancelled_count > 0:
            await db.execute(
                """UPDATE users SET total_orders = total_orders - 1, points = points - 5
                   WHERE telegram_id = $1""",
                telegram_id
            )
    return cancelled_count


async def close_orders_for_date(order_date: str):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE orders SET status = 'confirmed' WHERE order_date = $1::text AND status = 'pending'",
            str(order_date)
        )


async def get_daily_summary(order_date: str) -> dict:
    pool = await get_pool()
    async with pool.acquire() as db:
        items = await db.fetch(
            """SELECT m.name, m.item_number, m.category, COUNT(*) as count
               FROM orders o
               JOIN menus m ON o.menu_id = m.id
               WHERE o.order_date = $1::text AND o.status IN ('confirmed', 'pending')
               GROUP BY m.id, m.name, m.item_number, m.category
               ORDER BY m.category, count DESC""",
            str(order_date)
        )
        total = await db.fetchval(
            "SELECT COUNT(*) FROM orders WHERE order_date = $1::text AND status != 'cancelled'",
            str(order_date)
        )
    return {"items": [dict(r) for r in items], "total": total, "date": order_date}


async def get_all_users_for_notification() -> list:
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch("SELECT telegram_id FROM users")
        return [row["telegram_id"] for row in rows]


# ─── Отзывы на блюда ────────────────────────────────────────────────────────

async def get_deliverable_orders_without_review(order_date: str) -> list:
    """Заказы со статусом delivered за дату, на которые ещё нет отзыва"""
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            """SELECT o.id as order_id, o.menu_id, u.telegram_id, u.lang, m.name as meal_name
               FROM orders o
               JOIN users u ON o.user_id = u.id
               JOIN menus m ON o.menu_id = m.id
               LEFT JOIN reviews r ON r.order_id = o.id
               WHERE o.order_date = $1::text AND o.status = 'delivered'
               AND r.id IS NULL""",
            str(order_date)
        )
        return [dict(r) for r in rows]


async def save_review(order_id: int, user_id: int, menu_id: int, rating: int, comment: str = None) -> bool:
    """Сохраняет отзыв и начисляет +2 балла. Возвращает False если отзыв уже был."""
    pool = await get_pool()
    async with pool.acquire() as db:
        existing = await db.fetchrow("SELECT id FROM reviews WHERE order_id = $1", order_id)
        if existing:
            return False

        await db.execute(
            """INSERT INTO reviews (order_id, user_id, menu_id, rating, comment)
               VALUES ($1, $2, $3, $4, $5)""",
            order_id, user_id, menu_id, rating, comment
        )
        await db.execute(
            "UPDATE users SET points = points + 2 WHERE id = $1", user_id
        )
        await db.execute(
            """INSERT INTO balance_transactions (user_id, amount, type, description)
               VALUES ($1, 2, 'credit', '⭐ Бонус за отзыв')""",
            user_id
        )
    return True


async def get_menu_rating(menu_id: int) -> dict:
    """Средний рейтинг и количество отзывов для блюда"""
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            "SELECT AVG(rating) as avg_rating, COUNT(*) as count FROM reviews WHERE menu_id = $1",
            menu_id
        )
        return {
            "avg_rating": round(float(row["avg_rating"]), 1) if row["avg_rating"] else None,
            "count": row["count"] or 0
        }


# ─── Компания месяца ─────────────────────────────────────────────────────────

async def calculate_and_award_company_of_month(prev_month_year: str) -> dict | None:
    """
    Находит компанию-лидера по заказам за прошлый месяц,
    начисляет +50 баллов всем её сотрудникам.
    prev_month_year в формате 'YYYY-MM'.
    Возвращает {"company_id", "company_name", "order_count", "employees_rewarded"} или None.
    """
    pool = await get_pool()
    async with pool.acquire() as db:
        already_awarded = await db.fetchrow(
            "SELECT id FROM company_of_month WHERE month_year = $1", prev_month_year
        )
        if already_awarded:
            return None

        leader = await db.fetchrow(
            """SELECT c.id as company_id, c.name as company_name, COUNT(o.id) as order_count
               FROM orders o
               JOIN users u ON o.user_id = u.id
               JOIN companies c ON u.company_id = c.id
               WHERE to_char(o.created_at, 'YYYY-MM') = $1
               AND o.status != 'cancelled'
               GROUP BY c.id, c.name
               ORDER BY order_count DESC
               LIMIT 1""",
            prev_month_year
        )
        if not leader or leader["order_count"] == 0:
            return None

        await db.execute(
            """INSERT INTO company_of_month (company_id, month_year, order_count)
               VALUES ($1, $2, $3)""",
            leader["company_id"], prev_month_year, leader["order_count"]
        )

        employees = await db.fetch(
            "SELECT id, telegram_id, lang FROM users WHERE company_id = $1",
            leader["company_id"]
        )
        for emp in employees:
            await db.execute(
                "UPDATE users SET points = points + 50 WHERE id = $1", emp["id"]
            )
            await db.execute(
                """INSERT INTO balance_transactions (user_id, amount, type, description)
                   VALUES ($1, 50, 'credit', '🏆 Бонус Компания месяца')""",
                emp["id"]
            )

    return {
        "company_id": leader["company_id"],
        "company_name": leader["company_name"],
        "order_count": leader["order_count"],
        "employees": [dict(e) for e in employees]
    }


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
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            """SELECT
                c.id as company_id,
                c.name as company_name,
                c.address,
                c.maps_link,
                COUNT(o.id) as order_count,
                COUNT(DISTINCT o.user_id) as client_count
               FROM orders o
               JOIN users u ON o.user_id = u.id
               JOIN companies c ON u.company_id = c.id
               WHERE o.order_date = $1::text AND o.status != 'cancelled'
               GROUP BY c.id, c.name, c.address, c.maps_link
               ORDER BY order_count DESC""",
            str(order_date)
        )
        return [dict(r) for r in rows]


async def get_company_order_details(company_id: int, order_date: str) -> list:
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            """SELECT
                u.telegram_id,
                u.full_name,
                u.phone,
                m.name as meal_name,
                m.category,
                m.price
               FROM orders o
               JOIN users u ON o.user_id = u.id
               JOIN menus m ON o.menu_id = m.id
               WHERE u.company_id = $1
               AND o.order_date = $2::text
               AND o.status != 'cancelled'
               ORDER BY u.full_name, m.category""",
            company_id, str(order_date)
        )
        return [dict(r) for r in rows]


async def create_delivery_route(courier_id: int, delivery_date: str,
                                 company_ids: list) -> int:
    pool = await get_pool()
    delivery_date = str(delivery_date)
    async with pool.acquire() as db:
        old = await db.fetchrow(
            "SELECT id FROM delivery_routes WHERE courier_id=$1 AND delivery_date=$2::text",
            courier_id, delivery_date
        )
        if old:
            await db.execute(
                "DELETE FROM delivery_stops WHERE route_id=$1", old["id"]
            )
            await db.execute(
                "DELETE FROM delivery_routes WHERE id=$1", old["id"]
            )

        route = await db.fetchrow(
            """INSERT INTO delivery_routes (courier_id, delivery_date, status)
               VALUES ($1, $2::text, 'pending') RETURNING id""",
            courier_id, delivery_date
        )
        route_id = route["id"]

        for i, company_id in enumerate(company_ids, 1):
            await db.execute(
                """INSERT INTO delivery_stops (route_id, company_id, stop_order, status)
                   VALUES ($1, $2, $3, 'pending')""",
                route_id, company_id, i
            )

    return route_id


async def get_courier_route(courier_id: int, delivery_date: str) -> dict | None:
    pool = await get_pool()
    delivery_date = str(delivery_date)
    async with pool.acquire() as db:
        route = await db.fetchrow(
            """SELECT * FROM delivery_routes
               WHERE courier_id = $1 AND delivery_date = $2::text""",
            courier_id, delivery_date
        )
        if not route:
            return None

        stops = await db.fetch(
            """SELECT ds.*, c.name as company_name, c.address, c.maps_link,
               COUNT(o.id) as order_count,
               COUNT(DISTINCT o.user_id) as client_count
               FROM delivery_stops ds
               JOIN companies c ON ds.company_id = c.id
               LEFT JOIN orders o ON o.order_date = $2::text
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
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            """UPDATE delivery_stops
               SET status = 'delivered', delivered_at = NOW(), note = $2
               WHERE id = $1""",
            stop_id, note
        )
        stop = await db.fetchrow(
            "SELECT route_id, company_id FROM delivery_stops WHERE id = $1", stop_id
        )
        route = await db.fetchrow(
            "SELECT delivery_date FROM delivery_routes WHERE id = $1", stop["route_id"]
        )
        await db.execute(
            """UPDATE orders SET status = 'delivered', updated_at = NOW()
               WHERE order_date = $1::text
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

        route = await db.fetchrow(
            "SELECT delivery_date FROM delivery_routes WHERE id = $1", route_id
        )
        stop_company_ids = await db.fetch(
            "SELECT company_id FROM delivery_stops WHERE route_id = $1", route_id
        )
        for stop in stop_company_ids:
            await db.execute(
                """UPDATE orders SET status = 'in_transit', updated_at = NOW()
                   WHERE order_date = $1::text AND status = 'confirmed'
                   AND user_id IN (SELECT id FROM users WHERE company_id = $2)""",
                route["delivery_date"], stop["company_id"]
            )


async def mark_route_finished(route_id: int):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE delivery_routes SET status='finished', finished_at=NOW() WHERE id=$1",
            route_id
        )


async def get_company_clients_telegram_ids(company_id: int, order_date: str) -> list:
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            """SELECT u.telegram_id FROM users u
               JOIN orders o ON o.user_id = u.id
               WHERE u.company_id = $1
               AND o.order_date = $2::text
               AND o.status != 'cancelled'""",
            company_id, str(order_date)
        )
        return [r["telegram_id"] for r in rows]


# ─── Оплата при доставке ──────────────────────────────────────────────────────

async def charge_balance_on_delivery(company_id: int, order_date: str) -> list:
    """
    Вызывается когда курьер отмечает компанию как 'Доставлено'.
    Для каждого НЕ оплаченного заказа этой компании на эту дату:
      - списывает сумму с баланса клиента (баланс может уйти в минус)
      - помечает заказ как paid=1
    Возвращает список {telegram_id, full_name, amount, new_balance} для отчёта курьеру.
    """
    pool = await get_pool()
    results = []
    async with pool.acquire() as db:
        orders = await db.fetch(
            """SELECT o.id as order_id, o.user_id, o.payment_method, m.price,
               u.telegram_id, u.full_name
               FROM orders o
               JOIN users u ON o.user_id = u.id
               JOIN menus m ON o.menu_id = m.id
               WHERE u.company_id = $1 AND o.order_date = $2::text
               AND o.status != 'cancelled' AND o.paid = 0""",
            company_id, str(order_date)
        )

        # Группируем по user_id чтобы списать одной операцией на клиента
        by_user = {}
        for o in orders:
            by_user.setdefault(o["user_id"], {
                "telegram_id": o["telegram_id"],
                "full_name": o["full_name"],
                "order_ids": [],
                "total": 0
            })
            by_user[o["user_id"]]["order_ids"].append(o["order_id"])
            by_user[o["user_id"]]["total"] += o["price"]

        for user_id, info in by_user.items():
            if info["total"] <= 0:
                continue

            await db.execute(
                """INSERT INTO user_balance (user_id, balance) VALUES ($1, $2)
                   ON CONFLICT (user_id) DO UPDATE SET balance = user_balance.balance - $3""",
                user_id, -info["total"], info["total"]
            )
            await db.execute(
                """INSERT INTO balance_transactions (user_id, amount, type, description)
                   VALUES ($1, $2, 'debit', $3)""",
                user_id, info["total"], f"Списание за доставленный заказ ({order_date})"
            )
            for oid in info["order_ids"]:
                await db.execute("UPDATE orders SET paid = 1 WHERE id = $1", oid)

            new_balance = await db.fetchval(
                "SELECT balance FROM user_balance WHERE user_id = $1", user_id
            )

            results.append({
                "telegram_id": info["telegram_id"],
                "full_name": info["full_name"],
                "amount": info["total"],
                "new_balance": new_balance
            })

    return results


async def accept_cash_payment(telegram_id: int, amount: int) -> dict:
    """
    Курьер принял наличные у клиента — зачисляет указанную сумму на баланс.
    Используется когда баланс клиента в минусе (из-за неоплаченных заказов)
    и курьер физически получил деньги.
    """
    pool = await get_pool()
    async with pool.acquire() as db:
        user = await db.fetchrow("SELECT id, full_name FROM users WHERE telegram_id = $1", telegram_id)
        if not user:
            return {"success": False, "error": "Клиент не найден"}

        await db.execute(
            """INSERT INTO user_balance (user_id, balance) VALUES ($1, $2)
               ON CONFLICT (user_id) DO UPDATE SET balance = user_balance.balance + $2""",
            user["id"], amount
        )
        await db.execute(
            """INSERT INTO balance_transactions (user_id, amount, type, description)
               VALUES ($1, $2, 'credit', '💵 Наличные принял курьер')""",
            user["id"], amount
        )
        new_balance = await db.fetchval(
            "SELECT balance FROM user_balance WHERE user_id = $1", user["id"]
        )

    return {
        "success": True,
        "full_name": user["full_name"],
        "amount": amount,
        "new_balance": new_balance
    }


async def get_unpaid_clients_for_company(company_id: int, order_date: str) -> list:
    """Список клиентов компании с неоплаченными заказами на дату (для курьера)"""
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            """SELECT u.telegram_id, u.full_name, SUM(m.price) as total,
               bal.balance as current_balance
               FROM orders o
               JOIN users u ON o.user_id = u.id
               JOIN menus m ON o.menu_id = m.id
               LEFT JOIN user_balance bal ON bal.user_id = u.id
               WHERE u.company_id = $1 AND o.order_date = $2::text
               AND o.status != 'cancelled'
               GROUP BY u.telegram_id, u.full_name, bal.balance""",
            company_id, str(order_date)
        )
        return [dict(r) for r in rows]


# ─── Рейтинг курьера ───────────────────────────────────────────────────────────

async def save_courier_review(courier_id: int, user_id: int, delivery_route_id: int, rating: int) -> bool:
    """Сохраняет оценку курьера от клиента. Возвращает False если уже оценено."""
    pool = await get_pool()
    async with pool.acquire() as db:
        existing = await db.fetchrow(
            "SELECT id FROM courier_reviews WHERE user_id = $1 AND delivery_route_id = $2",
            user_id, delivery_route_id
        )
        if existing:
            return False
        await db.execute(
            """INSERT INTO courier_reviews (courier_id, user_id, delivery_route_id, rating)
               VALUES ($1, $2, $3, $4)""",
            courier_id, user_id, delivery_route_id, rating
        )
    return True


async def get_courier_rating(courier_id: int) -> dict:
    """Средний рейтинг и количество отзывов конкретного курьера"""
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            "SELECT AVG(rating) as avg_rating, COUNT(*) as count FROM courier_reviews WHERE courier_id = $1",
            courier_id
        )
        return {
            "avg_rating": round(float(row["avg_rating"]), 1) if row["avg_rating"] else None,
            "count": row["count"] or 0
        }


async def get_all_couriers_stats() -> list:
    """Статистика всех курьеров для админ-дашборда: доставки, рейтинг, среднее время маршрута"""
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
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
        result = []
        for r in rows:
            result.append({
                "id": r["id"],
                "full_name": r["full_name"],
                "routes_finished": r["routes_finished"] or 0,
                "stops_delivered": r["stops_delivered"] or 0,
                "avg_minutes": round(float(r["avg_minutes"]), 1) if r["avg_minutes"] else None,
                "avg_rating": round(float(r["avg_rating"]), 1) if r["avg_rating"] else None,
                "review_count": r["review_count"] or 0
            })
        return result


async def get_order_delivery_status(telegram_id: int, order_date: str) -> dict:
    """
    Возвращает агрегированный статус доставки заказа для отображения клиенту:
    'pending' (ожидает подтверждения), 'confirmed' (готовится),
    'in_transit' (курьер в пути), 'delivered' (доставлено), 'cancelled'.
    Если позиций несколько — берём самый "продвинутый" статус.
    """
    pool = await get_pool()
    status_priority = {"cancelled": 0, "pending": 1, "confirmed": 2, "in_transit": 3, "delivered": 4}
    async with pool.acquire() as db:
        rows = await db.fetch(
            """SELECT o.status FROM orders o
               JOIN users u ON o.user_id = u.id
               WHERE u.telegram_id = $1 AND o.order_date = $2::text
               AND o.status != 'cancelled'""",
            telegram_id, str(order_date)
        )
    if not rows:
        return {"status": None}

    statuses = [r["status"] for r in rows]
    best_status = max(statuses, key=lambda s: status_priority.get(s, 0))
    return {"status": best_status}


async def get_courier_for_route_by_company(company_id: int, order_date: str) -> dict | None:
    """Находит курьера и route_id, который обслуживает доставку этой компании на дату —
    используется чтобы привязать отзыв клиента к конкретному курьеру."""
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            """SELECT dr.id as route_id, dr.courier_id, c.full_name as courier_name
               FROM delivery_routes dr
               JOIN delivery_stops ds ON ds.route_id = dr.id
               JOIN couriers c ON c.id = dr.courier_id
               WHERE ds.company_id = $1 AND dr.delivery_date = $2::text
               ORDER BY dr.id DESC LIMIT 1""",
            company_id, str(order_date)
        )
        return dict(row) if row else None


# ─── Расширенные настройки профиля ─────────────────────────────────────────────

async def get_full_settings(telegram_id: int) -> dict | None:
    """Полные настройки пользователя для раздела Настройки в Mini App"""
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            """SELECT full_name, phone, lang, birthday,
               notify_reminder, notify_delivery, notify_marketing,
               company_id
               FROM users WHERE telegram_id = $1""",
            telegram_id
        )
        if not row:
            return None

        company_name = None
        company_address = None
        if row["company_id"]:
            company = await db.fetchrow(
                "SELECT name, address FROM companies WHERE id = $1", row["company_id"]
            )
            if company:
                company_name = company["name"]
                company_address = company["address"]

        return {
            "full_name": row["full_name"],
            "phone": row["phone"],
            "lang": row["lang"],
            "birthday": row["birthday"].isoformat() if row["birthday"] else None,
            "notify_reminder": bool(row["notify_reminder"]),
            "notify_delivery": bool(row["notify_delivery"]),
            "notify_marketing": bool(row["notify_marketing"]),
            "company_name": company_name,
            "company_address": company_address
        }


async def update_profile_field(telegram_id: int, field: str, value: str) -> bool:
    """Обновляет одно из разрешённых полей профиля: full_name, phone"""
    allowed_fields = {"full_name", "phone"}
    if field not in allowed_fields:
        return False
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            f"UPDATE users SET {field} = $1 WHERE telegram_id = $2",
            value, telegram_id
        )
    return True


async def update_company_address(telegram_id: int, address: str) -> bool:
    """Обновляет адрес компании клиента"""
    pool = await get_pool()
    async with pool.acquire() as db:
        user = await db.fetchrow(
            "SELECT company_id FROM users WHERE telegram_id = $1", telegram_id
        )
        if not user or not user["company_id"]:
            return False
        await db.execute(
            "UPDATE companies SET address = $1 WHERE id = $2",
            address, user["company_id"]
        )
    return True


async def toggle_notification(telegram_id: int, notify_type: str) -> bool | None:
    """Переключает один из notify_reminder/notify_delivery/notify_marketing. Возвращает новое значение."""
    allowed = {"notify_reminder", "notify_delivery", "notify_marketing"}
    if notify_type not in allowed:
        return None
    pool = await get_pool()
    async with pool.acquire() as db:
        current = await db.fetchrow(
            f"SELECT {notify_type} as val FROM users WHERE telegram_id = $1", telegram_id
        )
        if current is None:
            return None
        new_value = 0 if current["val"] else 1
        await db.execute(
            f"UPDATE users SET {notify_type} = $1 WHERE telegram_id = $2",
            new_value, telegram_id
        )
        return bool(new_value)
