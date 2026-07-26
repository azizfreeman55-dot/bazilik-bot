from datetime import date, datetime
from zoneinfo import ZoneInfo
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.db import (
    get_user, get_today_orders_list, get_user_lang, get_pool,
    cancel_all_orders_for_date, get_delivery_slot
)
from config import ADMIN_IDS
from langs import t
from keyboards.keyboards import CATEGORY_NAMES, WEBAPP_URL

router = Router()
TASHKENT_TZ = ZoneInfo("Asia/Tashkent")


def is_orders_open() -> bool:
    """Заказы принимаются ежедневно, кроме воскресенья (время Ташкента)."""
    return datetime.now(TASHKENT_TZ).weekday() != 6


def orders_closed_text(lang: str) -> str:
    if lang == "uz":
        return (
            "😌 *Bugun dam olish kuni.*\n\n"
            "Buyurtmalar dushanbadan shanbagacha qabul qilinadi."
        )
    return (
        "😌 *Сегодня выходной.*\n\n"
        "Заказы принимаются с понедельника по субботу."
    )


def get_today_date() -> str:
    return str(datetime.now(TASHKENT_TZ).date())


def get_day_name(date_str: str) -> str:
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    d = date.fromisoformat(date_str)
    return days[d.weekday()]


async def get_user_balance(user_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            "SELECT balance FROM user_balance WHERE user_id = $1", user_id
        )
    return row["balance"] if row else 0


async def refund_balance(user_id: int, amount: int, description: str):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            """INSERT INTO user_balance (user_id, balance)
               VALUES ($1, $2)
               ON CONFLICT (user_id) DO UPDATE SET balance = user_balance.balance + $2,
               updated_at = CURRENT_TIMESTAMP""",
            user_id, amount
        )
        await db.execute(
            """INSERT INTO balance_transactions (user_id, amount, type, description)
               VALUES ($1, $2, 'credit', $3)""",
            user_id, amount, description
        )


async def find_total_deduction_for_date(user_id: int, order_date: str) -> int:
    """
    Считает суммарное списание за заказ на конкретную order_date,
    которое ещё не было возвращено. Используется при полной отмене заказа.
    """
    pool = await get_pool()
    debit_marker = f"|{order_date}"
    refund_marker = f"REFUND|{order_date}"
    async with pool.acquire() as db:
        already_refunded = await db.fetchrow(
            """SELECT id FROM balance_transactions
               WHERE user_id = $1 AND type = 'credit'
               AND description LIKE '%' || $2 || '%'""",
            user_id, refund_marker
        )
        if already_refunded:
            return 0

        total = await db.fetchval(
            """SELECT COALESCE(SUM(amount), 0) FROM balance_transactions
               WHERE user_id = $1 AND type = 'debit'
               AND description LIKE '%' || $2""",
            user_id, debit_marker
        )
        return total or 0


def order_management_keyboard(lang: str = "ru") -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✏️ Изменить заказ" if lang == "ru" else "✏️ Buyurtmani o'zgartirish",
        web_app=WebAppInfo(url=WEBAPP_URL)
    )
    builder.button(
        text="❌ Отменить весь заказ" if lang == "ru" else "❌ Hammasini bekor qilish",
        callback_data="cancel_full_order"
    )
    builder.adjust(1)
    return builder.as_markup()


def webapp_button_keyboard(lang: str = "ru"):
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🍽️ Открыть меню" if lang == "ru" else "🍽️ Menyuni ochish",
        web_app=WebAppInfo(url=WEBAPP_URL)
    )
    return builder.as_markup()


# ─── Заказать обед — сразу открываем Mini App ────────────────────────────────

@router.message(F.text.in_({"🍽️ Заказать обед", "🍽️ Tushlik buyurtma qilish"}))
async def order_lunch(message: Message):
    user = await get_user(message.from_user.id)
    lang = await get_user_lang(message.from_user.id)
    if not user:
        await message.answer("❌ /start")
        return

    if not is_orders_open():
        await message.answer(orders_closed_text(lang), parse_mode="Markdown")
        return

    tomorrow = get_today_date()
    day_name = get_day_name(tomorrow)

    existing_orders = await get_today_orders_list(message.from_user.id, tomorrow)
    if existing_orders:
        text = format_order_summary(existing_orders, day_name, lang)
        await message.answer(
            text, parse_mode="Markdown",
            reply_markup=order_management_keyboard(lang)
        )
        return

    balance = await get_user_balance(user["id"])
    balance_text = (
        f"\n💳 {'Ваш баланс' if lang == 'ru' else 'Hisobingiz'}: *{balance:,} сум*"
    )

    if lang == "ru":
        text = f"🍽️ *Меню на сегодня ({tomorrow})*\n\nОткройте каталог чтобы выбрать блюда:{balance_text}"
    else:
        text = f"🍽️ *Bugun ({tomorrow}) menyu*\n\nTaomlarni tanlash uchun katalogni oching:{balance_text}"

    await message.answer(
        text, parse_mode="Markdown",
        reply_markup=webapp_button_keyboard(lang)
    )


def format_order_summary(orders: list, day_name: str, lang: str) -> str:
    """Форматирует список позиций заказа в текст"""
    total = sum(o["price"] for o in orders)

    by_category = {}
    for o in orders:
        cat = o.get("category", "main")
        by_category.setdefault(cat, []).append(o)

    text = f"📝 *{'Ваш заказ на сегодня' if lang == 'ru' else 'Bugungi buyurtmangiz'}*\n\n"
    for cat, items in by_category.items():
        cat_name = CATEGORY_NAMES.get(cat, {}).get(lang, cat)
        text += f"{cat_name}:\n"
        for item in items:
            text += f"  • {item['meal_name']} — {item['price']:,} сум\n"

    text += f"\n💰 {'Итого' if lang == 'ru' else 'Jami'}: *{total:,} сум*"

    status = orders[0].get("status", "pending")
    status_map_ru = {"pending": "⏳ Ожидает", "confirmed": "✅ Подтверждён", "delivered": "🚚 Доставлен"}
    status_map_uz = {"pending": "⏳ Kutilmoqda", "confirmed": "✅ Tasdiqlandi", "delivered": "🚚 Yetkazildi"}
    status_map = status_map_ru if lang == "ru" else status_map_uz
    text += f"\n📊 {status_map.get(status, status)}"

    return text


@router.message(F.text.in_({"📝 Мой заказ", "📝 Mening buyurtmam"}))
async def my_order(message: Message):
    lang = await get_user_lang(message.from_user.id)
    tomorrow = get_today_date()
    day_name = get_day_name(tomorrow)
    orders = await get_today_orders_list(message.from_user.id, tomorrow)

    if not orders:
        text = (
            f"{t(lang, 'no_order')}\n\n*{t(lang, 'btn_order')}*"
            if is_orders_open()
            else orders_closed_text(lang)
        )
        await message.answer(text, parse_mode="Markdown")
        return

    text = format_order_summary(orders, day_name, lang)
    status = orders[0].get("status", "pending")

    if status == "pending":
        await message.answer(text, parse_mode="Markdown", reply_markup=order_management_keyboard(lang))
    else:
        await message.answer(text, parse_mode="Markdown")


@router.callback_query(F.data == "cancel_full_order")
async def ask_cancel_full_order(callback: CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)

    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Да, отменить всё" if lang == "ru" else "✅ Ha, hammasini bekor qilish",
        callback_data="confirm_cancel_full"
    )
    builder.button(
        text="◀️ Назад" if lang == "ru" else "◀️ Orqaga",
        callback_data="back_to_order_summary"
    )
    builder.adjust(1)

    await callback.message.edit_text(
        t(lang, "confirm_cancel"),
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data == "confirm_cancel_full")
async def confirm_cancel_full_order(callback: CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)
    tomorrow = get_today_date()
    user = await get_user(callback.from_user.id)
    cancelled_orders = await get_today_orders_list(
        callback.from_user.id, tomorrow
    )
    delivery_slot = await get_delivery_slot(
        callback.from_user.id, tomorrow
    )

    refund_amount = await find_total_deduction_for_date(user["id"], tomorrow)

    cancelled_count = await cancel_all_orders_for_date(
        callback.from_user.id, tomorrow
    )

    if refund_amount > 0:
        refund_marker = f"REFUND|{tomorrow}"
        await refund_balance(
            user["id"], refund_amount,
            f"{'Возврат за отмену заказа' if lang == 'ru' else 'Buyurtma bekor qilingani uchun qaytarish'} | {refund_marker}"
        )
        refund_text = (
            f"\n💳 +{refund_amount:,} сум "
            f"{'возвращено на баланс' if lang == 'ru' else 'hisobga qaytarildi'}"
        )
    else:
        refund_text = ""

    await callback.message.edit_text(
        f"{t(lang, 'order_cancelled')}{refund_text}"
    )
    await callback.answer()

    if cancelled_count > 0:
        grouped = {}
        for order in cancelled_orders:
            key = (order["meal_name"], order["price"])
            grouped[key] = grouped.get(key, 0) + 1

        items_text = "\n".join(
            f"• {name} × {qty} — {price * qty:,} сум"
            for (name, price), qty in grouped.items()
        )
        cancelled_total = sum(
            order["price"] for order in cancelled_orders
        )
        admin_text = (
            "❌ КЛИЕНТ ОТМЕНИЛ ЗАКАЗ\n\n"
            f"👤 {user.get('full_name') or 'Клиент'}\n"
            f"🏢 {user.get('company_name') or '—'}\n"
            f"📱 {'+' + user['phone'] if user.get('phone') else '—'}\n"
            f"📅 Дата доставки: {tomorrow}\n"
            f"🕐 Время доставки: {delivery_slot or '—'}\n\n"
            f"📦 Отменённые позиции:\n{items_text}\n\n"
            f"💰 Сумма: {cancelled_total:,} сум"
        )
        if refund_amount > 0:
            admin_text += (
                f"\n💳 Возвращено клиенту: {refund_amount:,} сум"
            )

        for admin_id in ADMIN_IDS:
            try:
                await callback.bot.send_message(admin_id, admin_text)
            except Exception:
                # Ошибка отправки одному администратору не должна мешать
                # отмене заказа и уведомлению остальных.
                pass


@router.callback_query(F.data == "back_to_order_summary")
async def back_to_order_summary(callback: CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)
    tomorrow = get_today_date()
    day_name = get_day_name(tomorrow)
    orders = await get_today_orders_list(callback.from_user.id, tomorrow)

    if orders:
        text = format_order_summary(orders, day_name, lang)
        await callback.message.edit_text(
            text, parse_mode="Markdown",
            reply_markup=order_management_keyboard(lang)
        )
    await callback.answer()
