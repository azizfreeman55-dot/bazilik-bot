import aiosqlite
import logging
from datetime import date
from config import DATABASE_URL

logger = logging.getLogger(__name__)
DB_PATH = DATABASE_URL


async def init_db():
    """Создаём все таблицы при старте"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            -- Компании
            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                total_orders INTEGER DEFAULT 0,
                city TEXT DEFAULT 'Ташкент',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Пользователи
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Меню
            CREATE TABLE IF NOT EXISTS menus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                menu_date TEXT NOT NULL,
                item_number INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                price INTEGER DEFAULT 35000,
                is_active INTEGER DEFAULT 1,
                UNIQUE(menu_date, item_number)
            );

            -- Заказы
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id),
                menu_id INTEGER REFERENCES menus(id),
                order_date TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                is_auto_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Достижения
            CREATE TABLE IF NOT EXISTS achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id),
                achievement_type TEXT NOT NULL,
                earned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, achievement_type)
            );

            -- Недельное меню (автозаказ)
            CREATE TABLE IF NOT EXISTS weekly_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id),
                day_of_week INTEGER NOT NULL,
                menu_item INTEGER NOT NULL,
                is_active INTEGER DEFAULT 1,
                UNIQUE(user_id, day_of_week)
            );
        """)
        await db.commit()
    logger.info("✅ Таблицы созданы")


# ─────────────────── USERS ───────────────────

async def get_user(telegram_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT u.*, c.name as company_name, c.total_orders as company_orders
               FROM users u
               LEFT JOIN companies c ON u.company_id = c.id
               WHERE u.telegram_id = ?""",
            (telegram_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def create_user(telegram_id: int, full_name: str, username: str,
                      company_id: int, referral_code: str, referred_by_code: str = None) -> dict:
    referred_by_id = None
    bonus_points = 0

    if referred_by_code:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id FROM users WHERE referral_code = ?", (referred_by_code,)
            ) as cursor:
                ref_row = await cursor.fetchone()
                if ref_row:
                    referred_by_id = ref_row["id"]
                    bonus_points = 10  # Бонус приглашённому

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR IGNORE INTO users (telegram_id, full_name, username, company_id,
               referral_code, referred_by, points)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (telegram_id, full_name, username, company_id,
             referral_code, referred_by_id, bonus_points)
        )
        await db.commit()

        # Бонус тому, кто пригласил
        if referred_by_id:
            await db.execute(
                "UPDATE users SET points = points + 5 WHERE id = ?", (referred_by_id,)
            )
            await db.commit()

    return await get_user(telegram_id)


async def update_user_status(user_id: int, total_orders: int) -> str:
    """Обновляем статус пользователя по количеству заказов"""
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

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET status = ? WHERE id = ?", (status, user_id)
        )
        await db.commit()
    return status


# ─────────────────── COMPANIES ───────────────────

async def get_or_create_company(name: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id FROM companies WHERE name = ?", (name,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return row["id"]
        cursor = await db.execute(
            "INSERT INTO companies (name) VALUES (?)", (name,)
        )
        await db.commit()
        return cursor.lastrowid


async def get_company_ranking(city: str = "Ташкент") -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT c.name, c.total_orders,
               (SELECT COUNT(*) FROM orders o
                JOIN users u ON o.user_id = u.id
                WHERE u.company_id = c.id
                AND strftime('%Y-%m', o.order_date) = strftime('%Y-%m', 'now')) as month_orders
               FROM companies c
               ORDER BY month_orders DESC LIMIT 10"""
        ) as cursor:
            return [dict(r) for r in await cursor.fetchall()]


# ─────────────────── MENU ───────────────────

async def get_menu(menu_date: str) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM menus WHERE menu_date = ? AND is_active = 1 ORDER BY item_number",
            (menu_date,)
        ) as cursor:
            return [dict(r) for r in await cursor.fetchall()]


async def set_menu(menu_date: str, items: list[dict]):
    """items = [{"item_number": 1, "name": "Плов", "description": "...", "price": 35000}]"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM menus WHERE menu_date = ?", (menu_date,))
        for item in items:
            await db.execute(
                """INSERT INTO menus (menu_date, item_number, name, description, price)
                   VALUES (?, ?, ?, ?, ?)""",
                (menu_date, item["item_number"], item["name"],
                 item.get("description", ""), item.get("price", 35000))
            )
        await db.commit()


# ─────────────────── ORDERS ───────────────────

async def get_today_order(telegram_id: int, order_date: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT o.*, m.name as meal_name, m.item_number
               FROM orders o
               JOIN users u ON o.user_id = u.id
               JOIN menus m ON o.menu_id = m.id
               WHERE u.telegram_id = ? AND o.order_date = ? AND o.status != 'cancelled'""",
            (telegram_id, order_date)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def create_order(telegram_id: int, menu_id: int, order_date: str,
                       is_auto: bool = False) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            user = await cursor.fetchone()

        await db.execute(
            """INSERT OR REPLACE INTO orders (user_id, menu_id, order_date, status, is_auto_order)
               VALUES (?, ?, ?, 'pending', ?)""",
            (user["id"], menu_id, order_date, 1 if is_auto else 0)
        )

        # Обновляем счётчик и баллы
        today = str(date.today())
        await db.execute(
            """UPDATE users SET
               total_orders = total_orders + 1,
               points = points + 5,
               last_order_date = ?,
               streak_days = 0
               WHERE telegram_id = ?""",
            (today, telegram_id)
        )

        # Обновляем счётчик компании
        async with db.execute(
            "SELECT company_id FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            u = await cursor.fetchone()
            if u and u["company_id"]:
                await db.execute(
                    "UPDATE companies SET total_orders = total_orders + 1 WHERE id = ?",
                    (u["company_id"],)
                )

        await db.commit()

    user_data = await get_user(telegram_id)
    await update_user_status(user_data["id"], user_data["total_orders"])
    return await get_today_order(telegram_id, order_date)


async def cancel_order(telegram_id: int, order_date: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE orders SET status = 'cancelled'
               WHERE user_id = (SELECT id FROM users WHERE telegram_id = ?)
               AND order_date = ? AND status = 'pending'""",
            (telegram_id, order_date)
        )
        # Вычитаем баллы обратно
        await db.execute(
            "UPDATE users SET total_orders = total_orders - 1, points = points - 5 WHERE telegram_id = ?",
            (telegram_id,)
        )
        await db.commit()
    return True


async def close_orders_for_date(order_date: str):
    """Фиксируем заказы в 20:00"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE orders SET status = 'confirmed' WHERE order_date = ? AND status = 'pending'",
            (order_date,)
        )
        await db.commit()


async def get_daily_summary(order_date: str) -> dict:
    """Сводка заказов для кухни"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT m.name, m.item_number, COUNT(*) as count
               FROM orders o
               JOIN menus m ON o.menu_id = m.id
               WHERE o.order_date = ? AND o.status = 'confirmed'
               GROUP BY m.id ORDER BY count DESC""",
            (order_date,)
        ) as cursor:
            items = [dict(r) for r in await cursor.fetchall()]

        async with db.execute(
            "SELECT COUNT(*) as total FROM orders WHERE order_date = ? AND status = 'confirmed'",
            (order_date,)
        ) as cursor:
            total = (await cursor.fetchone())["total"]

    return {"items": items, "total": total, "date": order_date}


async def get_user_lang(telegram_id: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT lang FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row["lang"] if row else "ru"


async def set_user_lang(telegram_id: int, lang: str):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("ALTER TABLE users ADD COLUMN lang TEXT DEFAULT 'ru'")
            await db.commit()
        except Exception:
            pass
        await db.execute(
            "UPDATE users SET lang = ? WHERE telegram_id = ?",
            (lang, telegram_id)
        )
        await db.commit()


async def get_all_users_for_notification() -> list:
    """Все активные пользователи для рассылки"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT telegram_id FROM users"
        ) as cursor:
            return [row["telegram_id"] for row in await cursor.fetchall()]
