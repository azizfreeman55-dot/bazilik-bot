"""
courier_bot.py — Курьерский бот @BazilikuryerBot

Запуск на Render: отдельный Worker сервис
Start command: python courier_bot.py

Добавьте в .env:
COURIER_BOT_TOKEN=ваш_токен
COURIER_ADMIN_IDS=ваш_telegram_id (через запятую)
"""

import asyncio
import logging
import os
from datetime import date, timedelta

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from dotenv import load_dotenv

load_dotenv()

# Импортируем общую БД
from database.db import (
    get_courier, create_courier, get_all_couriers,
    get_orders_by_company, get_company_order_details,
    create_delivery_route, get_courier_route,
    mark_stop_delivered, mark_route_started, mark_route_finished,
    get_company_clients_telegram_ids, init_db
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

COURIER_BOT_TOKEN = os.getenv("COURIER_BOT_TOKEN")
MAIN_BOT_TOKEN = os.getenv("BOT_TOKEN")
COURIER_ADMIN_IDS = [
    int(x.strip()) for x in os.getenv("COURIER_ADMIN_IDS", "").split(",") if x.strip()
]

CATEGORY_ICONS = {
    "main": "🍱",
    "salad": "🥗",
    "dessert": "🍰",
    "drink": "🥤",
}

# Telegram ID которым админ разрешил регистрацию
_allowed_to_register = set()

router = Router()


class CourierReg(StatesGroup):
    waiting_name = State()
    waiting_phone = State()


class AssignRoute(StatesGroup):
    waiting_courier = State()
    waiting_companies = State()


# ─── Утилиты ──────────────────────────────────────────────────────────────────

def get_today() -> str:
    return str(date.today())


def get_tomorrow() -> str:
    return str(date.today() + timedelta(days=1))


def yandex_maps_link(address: str) -> str:
    """Генерируем ссылку Яндекс.Карты по адресу"""
    query = f"Чирчик, {address}" if address else "Чирчик"
    import urllib.parse
    return f"https://yandex.uz/maps/?text={urllib.parse.quote(query)}"


def courier_main_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="📦 Мои заказы")
    builder.button(text="🗺 Мой маршрут")
    builder.button(text="📊 Статистика")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)


def admin_main_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="📦 Мои заказы")
    builder.button(text="🗺 Мой маршрут")
    builder.button(text="🚚 Распределить заказы")
    builder.button(text="👥 Курьеры")
    builder.button(text="📊 Статистика")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)


# ─── Регистрация курьера ───────────────────────────────────────────────────────

@router.message(CommandStart())
async def courier_start(message: Message, state: FSMContext):
    courier = await get_courier(message.from_user.id)

    if courier:
        is_admin = message.from_user.id in COURIER_ADMIN_IDS
        kb = admin_main_keyboard() if is_admin else courier_main_keyboard()
        await message.answer(
            f"👋 С возвращением, *{courier['full_name']}*!\n\n"
            f"📅 Сегодня: {get_today()}",
            parse_mode="Markdown",
            reply_markup=kb
        )
        return

    # Если это admin ID — разрешаем регистрацию










    await state.set_state(CourierReg.waiting_name)
    await message.answer(
        "🚚 *Добро пожаловать в Bazilik Courier!*\n\n"
        "Для начала работы пройдите регистрацию.\n\n"
        "Введите ваше *полное имя*:",
        parse_mode="Markdown"
    )


@router.message(CourierReg.waiting_name)
async def courier_reg_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 3:
        await message.answer("❌ Введите полное имя (минимум 3 символа)")
        return
    await state.update_data(name=name)
    await state.set_state(CourierReg.waiting_phone)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить номер", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await message.answer(
        f"✅ {name}!\n\n📱 Отправьте ваш номер телефона:",
        reply_markup=kb
    )


@router.message(CourierReg.waiting_phone)
async def courier_reg_phone(message: Message, state: FSMContext):
    if message.contact:
        phone = message.contact.phone_number.replace("+", "")
    else:
        phone = message.text.strip().replace("+", "").replace(" ", "")
        if not phone.isdigit() or len(phone) < 9:
            await message.answer("❌ Неверный формат. Введите номер или нажмите кнопку.")
            return

    data = await state.get_data()
    courier = await create_courier(message.from_user.id, data["name"], phone)
    await state.clear()

    is_admin = message.from_user.id in COURIER_ADMIN_IDS
    kb = admin_main_keyboard() if is_admin else courier_main_keyboard()

    await message.answer(
        f"✅ *Регистрация завершена!*\n\n"
        f"👤 {courier['full_name']}\n"
        f"📱 +{phone}\n\n"
        f"Вы готовы к работе! 🚀",
        parse_mode="Markdown",
        reply_markup=kb
    )


# ─── Просмотр заказов ─────────────────────────────────────────────────────────

@router.message(F.text == "📦 Мои заказы")
async def show_my_orders(message: Message):
    courier = await get_courier(message.from_user.id)
    if not courier:
        await message.answer("❌ Вы не зарегистрированы. Напишите /start")
        return

    delivery_date = get_tomorrow()
    route_data = await get_courier_route(courier["id"], delivery_date)

    if not route_data:
        await message.answer(
            f"📦 *Заказы на {delivery_date}*\n\n"
            f"Маршрут ещё не назначен.\n"
            f"Ожидайте уведомления от диспетчера.",
            parse_mode="Markdown"
        )
        return

    stops = route_data["stops"]
    text = f"📦 *Ваши заказы на {delivery_date}*\n\n"

    for stop in stops:
        status_icon = "✅" if stop["status"] == "delivered" else "⏳"
        text += f"{status_icon} *{stop['stop_order']}. {stop['company_name']}*\n"
        if stop.get("address"):
            text += f"📍 {stop['address']}\n"
        text += f"👥 {stop['order_count']} заказов\n\n"

    total = sum(s["order_count"] for s in stops)
    text += f"📊 Всего точек: {len(stops)} | Заказов: {total}"

    builder = InlineKeyboardBuilder()
    for stop in stops:
        if stop["status"] != "delivered":
            builder.button(
                text=f"📋 {stop['company_name']} ({stop['order_count']} зак.)",
                callback_data=f"stop_detail_{stop['id']}_{stop['company_id']}_{delivery_date}"
            )
    builder.adjust(1)

    await message.answer(text, parse_mode="Markdown", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("stop_detail_"))
async def show_stop_detail(callback: CallbackQuery):
    _, _, stop_id, company_id, delivery_date = callback.data.split("_", 4)
    stop_id = int(stop_id)
    company_id = int(company_id)

    orders = await get_company_order_details(company_id, delivery_date)

    if not orders:
        await callback.answer("Заказов не найдено", show_alert=True)
        return

    # Группируем по клиенту
    clients = {}
    for o in orders:
        name = o["full_name"] or "—"
        if name not in clients:
            clients[name] = []
        icon = CATEGORY_ICONS.get(o["category"], "🍽")
        clients[name].append(f"{icon} {o['meal_name']}")

    text = f"📋 *Список заказов*\n\n"
    for i, (client, items) in enumerate(clients.items(), 1):
        text += f"{i}. *{client}*\n"
        for item in items:
            text += f"   {item}\n"
        text += "\n"

    text += f"\n👥 Итого клиентов: {len(clients)}"

    # Получаем адрес для Яндекс.Карт
    from database.db import get_pool
    pool = await get_pool()
    async with pool.acquire() as db:
        company = await db.fetchrow(
            "SELECT name, address, maps_link FROM companies WHERE id = $1", company_id
        )

    builder = InlineKeyboardBuilder()

    # Ссылка на Яндекс.Карты
    if company and company.get("maps_link"):
        builder.button(
            text="🗺 Открыть в Яндекс.Картах",
            url=company["maps_link"]
        )
    elif company and company.get("address"):
        builder.button(
            text="🗺 Открыть в Яндекс.Картах",
            url=yandex_maps_link(company["address"])
        )

    builder.button(
        text="✅ Доставлено",
        callback_data=f"delivered_{stop_id}_{company_id}_{delivery_date}"
    )
    builder.button(
        text="⚠️ Проблема",
        callback_data=f"problem_{stop_id}"
    )
    builder.button(text="◀️ Назад", callback_data="back_to_orders")
    builder.adjust(1)

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("delivered_"))
async def mark_delivered(callback: CallbackQuery):
    _, _, stop_id, company_id, delivery_date = callback.data.split("_", 4)
    stop_id = int(stop_id)
    company_id = int(company_id)

    await mark_stop_delivered(stop_id)

    # Уведомляем клиентов
    client_ids = await get_company_clients_telegram_ids(company_id, delivery_date)
    main_bot = Bot(token=MAIN_BOT_TOKEN)
    notified = 0
    for tg_id in client_ids:
        try:
            await main_bot.send_message(
                tg_id,
                "✅ *Ваш обед доставлен!*\n\n"
                "Приятного аппетита! 🍱\n\n"
                "_Bazilik Catering_",
                parse_mode="Markdown"
            )
            notified += 1
        except Exception as e:
            logger.warning(f"Не удалось уведомить {tg_id}: {e}")
    await main_bot.session.close()

    await callback.message.edit_text(
        f"✅ *Доставлено!*\n\n"
        f"📱 Уведомлено клиентов: {notified}",
        parse_mode="Markdown"
    )
    await callback.answer("✅ Отмечено как доставлено!")


@router.callback_query(F.data.startswith("problem_"))
async def report_problem(callback: CallbackQuery):
    stop_id = int(callback.data.split("_")[1])

    builder = InlineKeyboardBuilder()
    builder.button(text="🚪 Никого нет в офисе", callback_data=f"prob_note_{stop_id}_никого нет")
    builder.button(text="📍 Не могу найти адрес", callback_data=f"prob_note_{stop_id}_не найден адрес")
    builder.button(text="📦 Не хватает заказов", callback_data=f"prob_note_{stop_id}_не хватает заказов")
    builder.button(text="◀️ Назад", callback_data="back_to_orders")
    builder.adjust(1)

    await callback.message.edit_text(
        "⚠️ *Укажите проблему:*",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("prob_note_"))
async def save_problem_note(callback: CallbackQuery):
    parts = callback.data.split("_", 3)
    stop_id = int(parts[2])
    note = parts[3]

    await mark_stop_delivered(stop_id, note=f"⚠️ {note}")

    # Уведомляем админа
    for admin_id in COURIER_ADMIN_IDS:
        try:
            await callback.bot.send_message(
                admin_id,
                f"⚠️ *Проблема с доставкой!*\n\n"
                f"Курьер сообщил: _{note}_\n"
                f"Stop ID: {stop_id}",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    await callback.message.edit_text(
        f"⚠️ Проблема зафиксирована: _{note}_\n\n"
        f"Администратор уведомлён.",
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_orders")
async def back_to_orders(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()


# ─── Маршрут ──────────────────────────────────────────────────────────────────

@router.message(F.text == "🗺 Мой маршрут")
async def show_route(message: Message):
    courier = await get_courier(message.from_user.id)
    if not courier:
        await message.answer("❌ Вы не зарегистрированы. Напишите /start")
        return

    delivery_date = get_tomorrow()
    route_data = await get_courier_route(courier["id"], delivery_date)

    if not route_data:
        await message.answer(
            "🗺 *Маршрут на завтра ещё не назначен*\n\n"
            "Ожидайте уведомления.",
            parse_mode="Markdown"
        )
        return

    route = route_data["route"]
    stops = route_data["stops"]

    status_map = {
        "pending": "⏳ Ожидает старта",
        "active": "🚚 В пути",
        "finished": "✅ Завершён"
    }

    text = (
        f"🗺 *Маршрут на {delivery_date}*\n"
        f"Статус: {status_map.get(route['status'], route['status'])}\n\n"
    )

    for stop in stops:
        done = stop["status"] == "delivered"
        icon = "✅" if done else "📍"
        text += f"{icon} *{stop['stop_order']}. {stop['company_name']}*\n"
        if stop.get("address"):
            text += f"    {stop['address']}\n"
        text += f"    👥 {stop['order_count']} заказов\n\n"

    builder = InlineKeyboardBuilder()

    if route["status"] == "pending":
        builder.button(
            text="▶️ Начать маршрут",
            callback_data=f"start_route_{route['id']}"
        )

    # Кнопки Яндекс.Карт для каждой точки
    for stop in stops:
        if stop["status"] != "delivered":
            if stop.get("maps_link"):
                url = stop["maps_link"]
            else:
                url = yandex_maps_link(stop.get("address", ""))
            builder.button(
                text=f"🗺 {stop['company_name']}",
                url=url
            )

    if route["status"] == "active":
        delivered = sum(1 for s in stops if s["status"] == "delivered")
        if delivered == len(stops):
            builder.button(
                text="🏁 Завершить маршрут",
                callback_data=f"finish_route_{route['id']}"
            )

    builder.adjust(1)
    await message.answer(text, parse_mode="Markdown", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("start_route_"))
async def start_route(callback: CallbackQuery):
    route_id = int(callback.data.split("_")[2])
    await mark_route_started(route_id)
    await callback.answer("🚚 Маршрут начат! Удачи!")
    await callback.message.edit_text(
        "🚚 *Маршрут начат!*\n\nНажмите '📦 Мои заказы' чтобы отмечать доставки.",
        parse_mode="Markdown"
    )

    # Уведомляем клиентов ВСЕХ компаний этого маршрута, что обед готовится к отправке
    try:
        from database.db import get_pool
        pool = await get_pool()
        async with pool.acquire() as db:
            route = await db.fetchrow(
                "SELECT delivery_date FROM delivery_routes WHERE id = $1", route_id
            )
            stops = await db.fetch(
                "SELECT company_id FROM delivery_stops WHERE route_id = $1", route_id
            )

        if route:
            delivery_date = route["delivery_date"]
            main_bot = Bot(token=MAIN_BOT_TOKEN)
            notified = 0
            for stop in stops:
                client_ids = await get_company_clients_telegram_ids(
                    stop["company_id"], delivery_date
                )
                for tg_id in client_ids:
                    try:
                        await main_bot.send_message(
                            tg_id,
                            "🚚 *Ваш обед готовится к отправке!*\n\n"
                            "Курьер начал маршрут — скоро доставим. 🍱",
                            parse_mode="Markdown"
                        )
                        notified += 1
                    except Exception as e:
                        logger.warning(f"Не удалось уведомить {tg_id}: {e}")
            await main_bot.session.close()
            logger.info(f"Уведомлено о начале маршрута: {notified} клиентов")
    except Exception as e:
        logger.error(f"Ошибка уведомления о старте маршрута: {e}")


@router.callback_query(F.data.startswith("finish_route_"))
async def finish_route(callback: CallbackQuery):
    route_id = int(callback.data.split("_")[2])
    await mark_route_finished(route_id)

    # Уведомляем админа
    for admin_id in COURIER_ADMIN_IDS:
        try:
            await callback.bot.send_message(
                admin_id,
                f"✅ *Маршрут завершён!*\n\n"
                f"Курьер завершил все доставки на сегодня.",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    await callback.answer("🏁 Маршрут завершён!")
    await callback.message.edit_text(
        "🏁 *Маршрут завершён!*\n\nОтличная работа! Все заказы доставлены. 💪",
        parse_mode="Markdown"
    )


# ─── Распределение заказов (только для админа) ────────────────────────────────

@router.message(F.text == "🚚 Распределить заказы")
async def distribute_orders(message: Message):
    if message.from_user.id not in COURIER_ADMIN_IDS:
        return

    delivery_date = get_tomorrow()
    companies = await get_orders_by_company(delivery_date)

    if not companies:
        await message.answer(
            f"📦 На {delivery_date} заказов нет.",
            parse_mode="Markdown"
        )
        return

    couriers = await get_all_couriers()
    if not couriers:
        await message.answer("❌ Нет зарегистрированных курьеров.")
        return

    text = f"🚚 *Распределение заказов на {delivery_date}*\n\n"
    text += "📦 *Компании:*\n"
    for c in companies:
        text += f"• {c['company_name']}: {c['order_count']} заказов\n"

    text += f"\n👥 *Курьеры:*\n"
    for c in couriers:
        text += f"• {c['full_name']}\n"

    # Строим кнопки — для каждого курьера кнопка "Назначить все"
    builder = InlineKeyboardBuilder()
    for courier in couriers:
        builder.button(
            text=f"📋 Все → {courier['full_name']}",
            callback_data=f"assign_all_{courier['id']}_{delivery_date}"
        )
    builder.button(
        text="⚙️ Распределить вручную",
        callback_data=f"assign_manual_{delivery_date}"
    )
    builder.adjust(1)

    await message.answer(text, parse_mode="Markdown", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("assign_all_"))
async def assign_all_to_courier(callback: CallbackQuery):
    parts = callback.data.split("_")
    courier_id = int(parts[2])
    delivery_date = parts[3]

    companies = await get_orders_by_company(delivery_date)
    company_ids = [c["company_id"] for c in companies]

    route_id = await create_delivery_route(courier_id, delivery_date, company_ids)

    # Получаем курьера и уведомляем его
    from database.db import get_pool
    pool = await get_pool()
    async with pool.acquire() as db:
        courier = await db.fetchrow("SELECT * FROM couriers WHERE id = $1", courier_id)

    total_orders = sum(c["order_count"] for c in companies)

    # Уведомление курьеру
    try:
        text = (
            f"🚚 *Вам назначен маршрут на {delivery_date}!*\n\n"
            f"📦 Компаний: {len(companies)}\n"
            f"👥 Заказов: {total_orders}\n\n"
        )
        for i, c in enumerate(companies, 1):
            text += f"{i}. {c['company_name']} — {c['order_count']} зак.\n"
            if c.get("address"):
                text += f"   📍 {c['address']}\n"
        text += "\nОткройте '🗺 Мой маршрут' для начала работы."

        await callback.bot.send_message(
            courier["telegram_id"], text, parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning(f"Не удалось уведомить курьера: {e}")

    await callback.message.edit_text(
        f"✅ *Маршрут назначен!*\n\n"
        f"Курьер: *{courier['full_name']}*\n"
        f"Компаний: {len(companies)}\n"
        f"Заказов: {total_orders}",
        parse_mode="Markdown"
    )
    await callback.answer("✅ Маршрут создан!")


# ─── Список курьеров ──────────────────────────────────────────────────────────

@router.message(F.text == "👥 Курьеры")
async def show_couriers(message: Message):
    if message.from_user.id not in COURIER_ADMIN_IDS:
        return

    couriers = await get_all_couriers()
    if not couriers:
        await message.answer("👥 Курьеров пока нет.")
        return

    text = f"👥 *Курьеры ({len(couriers)} чел.)*\n\n"
    for i, c in enumerate(couriers, 1):
        text += (
            f"{i}. *{c['full_name']}*\n"
            f"   📱 +{c['phone'] or '—'}\n"
            f"   {'🟢 Активен' if c['is_active'] else '🔴 Неактивен'}\n\n"
        )

    builder = InlineKeyboardBuilder()
    for c in couriers:
        builder.button(
            text=f"🗑 Удалить {c['full_name']}",
            callback_data=f"deactivate_courier_{c['id']}"
        )
    builder.adjust(1)

    await message.answer(text, parse_mode="Markdown", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("deactivate_courier_"))
async def deactivate_courier(callback: CallbackQuery):
    if callback.from_user.id not in COURIER_ADMIN_IDS:
        return
    courier_id = int(callback.data.split("_")[2])
    from database.db import get_pool
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE couriers SET is_active = FALSE WHERE id = $1", courier_id
        )
    await callback.answer("✅ Курьер деактивирован")
    await callback.message.delete()


# ─── Статистика ───────────────────────────────────────────────────────────────

@router.message(F.text == "📊 Статистика")
async def show_stats(message: Message):
    courier = await get_courier(message.from_user.id)
    if not courier:
        return

    from database.db import get_pool
    pool = await get_pool()
    async with pool.acquire() as db:
        total_routes = await db.fetchval(
            "SELECT COUNT(*) FROM delivery_routes WHERE courier_id=$1 AND status='finished'",
            courier["id"]
        )
        total_stops = await db.fetchval(
            """SELECT COUNT(*) FROM delivery_stops ds
               JOIN delivery_routes dr ON ds.route_id = dr.id
               WHERE dr.courier_id=$1 AND ds.status='delivered'""",
            courier["id"]
        )

    await message.answer(
        f"📊 *Ваша статистика*\n\n"
        f"✅ Завершённых маршрутов: *{total_routes}*\n"
        f"📦 Доставлено точек: *{total_stops}*\n\n"
        f"Отличная работа! 💪",
        parse_mode="Markdown"
    )


# ─── Запуск ───────────────────────────────────────────────────────────────────

async def main():
    await init_db()

    bot = Bot(token=COURIER_BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    logger.info("🚚 Курьерский бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())


# ─── Добавление курьера (только для админа) ───────────────────────────────────

# Список telegram_id которым разрешена регистрация
_allowed_to_register = set()


@router.message(F.text.startswith("/addcourier"))
async def admin_add_courier(message: Message):
    if message.from_user.id not in COURIER_ADMIN_IDS:
        return

    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer(
            "❌ Укажите Telegram ID курьера.\n\n"
            "Пример: `/addcourier 123456789`\n\n"
            "Попросите курьера написать боту @userinfobot чтобы узнать свой ID.",
            parse_mode="Markdown"
        )
        return

    try:
        courier_telegram_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Неверный формат ID. Введите числовой Telegram ID.")
        return

    # Добавляем в список разрешённых
    _allowed_to_register.add(courier_telegram_id)

    # Отправляем приглашение курьеру
    try:
        await message.bot.send_message(
            courier_telegram_id,
            "🚚 *Добро пожаловать в Bazilik Courier!*\n\n"
            "Администратор открыл вам доступ.\n"
            "Нажмите /start для регистрации.",
            parse_mode="Markdown"
        )
        await message.answer(
            f"✅ Доступ открыт!\n\n"
            f"Telegram ID: `{courier_telegram_id}`\n"
            f"Курьер получил уведомление и может зарегистрироваться.",
            parse_mode="Markdown"
        )
    except Exception:
        await message.answer(
            f"✅ Доступ открыт для ID `{courier_telegram_id}`.\n\n"
            f"⚠️ Не удалось отправить уведомление — курьер должен сам написать боту /start",
            parse_mode="Markdown"
        )


@router.message(F.text.startswith("/removecourier"))
async def admin_remove_courier(message: Message):
    """Деактивировать курьера по telegram_id"""
    if message.from_user.id not in COURIER_ADMIN_IDS:
        return

    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer(
            "❌ Укажите Telegram ID курьера.\n\n"
            "Пример: `/removecourier 123456789`",
            parse_mode="Markdown"
        )
        return

    try:
        courier_telegram_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Неверный формат ID.")
        return

    from database.db import get_pool
    pool = await get_pool()
    async with pool.acquire() as db:
        result = await db.fetchrow(
            "SELECT full_name FROM couriers WHERE telegram_id = $1", courier_telegram_id
        )
        if not result:
            await message.answer("❌ Курьер с таким ID не найден.")
            return
        await db.execute(
            "UPDATE couriers SET is_active = FALSE WHERE telegram_id = $1",
            courier_telegram_id
        )

    await message.answer(
        f"✅ Курьер *{result['full_name']}* деактивирован.",
        parse_mode="Markdown"
    )
