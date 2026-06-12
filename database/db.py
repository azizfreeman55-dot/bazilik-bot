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
        """
handlers/birthday.py — обработчик ввода дня рождения

Добавьте роутер в handlers/__init__.py:
    from handlers.birthday import router as birthday_router
    dp.include_router(birthday_router)
"""

from datetime import datetime
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database.db import get_user_lang, get_pool

router = Router()


class BirthdayState(StatesGroup):
    waiting_for_date = State()


@router.callback_query(F.data == "set_birthday")
async def ask_birthday(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_lang(callback.from_user.id)

    if lang == "uz":
        text = (
            "🎂 *Tug'ilgan kuningizni kiriting*\n\n"
            "Format: `DD.MM.YYYY`\n"
            "Masalan: `15.03.1990`\n\n"
            "_Tug'ilgan kuningizda sizga maxsus sovg'a beriladi!_ 🎁"
        )
    else:
        text = (
            "🎂 *Введите вашу дату рождения*\n\n"
            "Формат: `ДД.ММ.ГГГГ`\n"
            "Например: `15.03.1990`\n\n"
            "_В день рождения вас ждёт особый подарок!_ 🎁"
        )

    await callback.message.edit_text(text, parse_mode="Markdown")
    await state.set_state(BirthdayState.waiting_for_date)
    await callback.answer()


@router.message(BirthdayState.waiting_for_date)
async def save_birthday(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    text = message.text.strip()

    try:
        birthday = datetime.strptime(text, "%d.%m.%Y").date()

        # Проверяем что дата реалистичная
        today = datetime.today().date()
        age = (today - birthday).days // 365
        if age < 10 or age > 100:
            raise ValueError("Unrealistic age")

        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute(
                "UPDATE users SET birthday = $1 WHERE telegram_id = $2",
                birthday, message.from_user.id
            )

        await state.clear()

        builder = InlineKeyboardBuilder()
        builder.button(
            text="◀️ Назад в профиль" if lang == "ru" else "◀️ Profilga qaytish",
            callback_data="my_profile"
        )

        if lang == "uz":
            await message.answer(
                f"✅ *Tug'ilgan kun saqlandi!*\n\n"
                f"📅 {birthday.strftime('%d.%m.%Y')}\n\n"
                f"Tug'ilgan kuningizda sizga *+50 ball* sovg'a beriladi! 🎁",
                parse_mode="Markdown",
                reply_markup=builder.as_markup()
            )
        else:
            await message.answer(
                f"✅ *День рождения сохранён!*\n\n"
                f"📅 {birthday.strftime('%d.%m.%Y')}\n\n"
                f"В день рождения вам будет начислено *+50 баллов*! 🎁",
                parse_mode="Markdown",
                reply_markup=builder.as_markup()
            )

    except ValueError:
        if lang == "uz":
            await message.answer(
                "❌ Noto'g'ri format. Iltimos qayta kiriting:\n`DD.MM.YYYY`\n\nMasalan: `15.03.1990`",
                parse_mode="Markdown"
            )
        else:
            await message.answer(
                "❌ Неверный формат. Попробуйте снова:\n`ДД.ММ.ГГГГ`\n\nНапример: `15.03.1990`",
                parse_mode="Markdown"
            )
            
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
                UNIQUE(menu_date, item_number)
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
    logger.info("✅ Таблицы созданы")


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


async def get_menu(menu_date: str) -> list:
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            "SELECT * FROM menus WHERE menu_date = $1 AND is_active = 1 ORDER BY item_number",
            menu_date
        )
        return [dict(r) for r in rows]


async def set_menu(menu_date: str, items: list):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute("DELETE FROM menus WHERE menu_date = $1", menu_date)
        for item in items:
            await db.execute(
                """INSERT INTO menus (menu_date, item_number, name, description, price, photo_id)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                menu_date, item["item_number"], item["name"],
                item.get("description", ""), item.get("price", 35000),
                item.get("photo_id")
            )


async def get_today_order(telegram_id: int, order_date: str) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            """SELECT o.*, m.name as meal_name, m.item_number
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
            """SELECT m.name, m.item_number, COUNT(*) as count
               FROM orders o
               JOIN menus m ON o.menu_id = m.id
               WHERE o.order_date = $1 AND o.status IN ('confirmed', 'pending')
               GROUP BY m.id, m.name, m.item_number ORDER BY count DESC""",
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


async def save_user_phone(telegram_id: int, phone: str):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE users SET phone = $1 WHERE telegram_id = $2",
            phone, telegram_id
        )
