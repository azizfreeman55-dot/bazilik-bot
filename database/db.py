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

        # Миграции для существующей БД
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


# ─── Разовое меню по датам ────────────────────────────────────────────────────

async def get_menu(menu_date: str, category: str = "main") -> list:
    """Получить меню по дате. Если нет — подставляем из weekly_menu по дню недели."""
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

        # Фолбэк: постоянное меню по дню недели
        d = date.fromisoformat(menu_date)
        day_num = d.weekday()  # 0=Пн, 6=Вс
        weekly_rows = await db.fetch(
            """SELECT * FROM weekly_menu
               WHERE day_of_week = $1 AND is_active = 1 AND category = $2
               ORDER BY item_number""",
            day_num, category
        )
        if not weekly_rows:
            return []

        # Копируем в menus на эту дату чтобы можно было оформить заказ
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
    """Категории на дату. Если нет — берём из weekly_menu по дню недели."""
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
    """Сохранить разовое меню на конкретную дату"""
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


# ─── Постоянное меню по дням недели ──────────────────────────────────────────

async def set_weekly_menu(day_of_week: int, items: list, category: str = "main"):
    """Сохранить постоянное меню для дня недели (0=Пн, 6=Вс)"""
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
    """Сводка постоянного меню по всем дням для админки"""
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
    """Удалить всё постоянное меню для дня недели"""
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
               WHERE u.telegram_id = $1 AND o.order_date = $2::text AND o.status != 'cancelled'""",
            telegram_id, str(order_date)
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
               VALUES ($1, $2, $3::text, 'pending', $4)
               ON CONFLICT DO NOTHING""",
            user["id"], menu_id, str(order_date), 1 if is_auto else 0
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
               AND order_date = $2::text AND status = 'pending'""",
            telegram_id, str(order_date)
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
