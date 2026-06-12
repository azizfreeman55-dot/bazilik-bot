from datetime import date, datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from database.db import (
    get_user, get_menu, get_today_order,
    create_order, cancel_order, get_user_lang, get_pool
)
from langs import t
from keyboards.keyboards import (
    menu_keyboard, order_actions_keyboard,
    confirm_cancel_keyboard, back_keyboard
)
from config import ORDER_CLOSE_TIME

router = Router()


def is_orders_open() -> bool:
    now = datetime.now().strftime("%H:%M")
    return now < ORDER_CLOSE_TIME


def get_tomorrow_date() -> str:
    from datetime import timedelta
    tomorrow = date.today() + timedelta(days=1)
    return str(tomorrow)


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


async def deduct_balance(user_id: int, amount: int, description: str) -> bool:
    """
    Списывает сумму с баланса.
    Возвращает True если списание прошло, False если баланса недостаточно.
    """
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            "SELECT balance FROM user_balance WHERE user_id = $1", user_id
        )
        current = row["balance"] if row else 0
        if current < amount:
            return False
        await db.execute(
            "UPDATE user_balance SET balance = balance - $1 WHERE user_id = $2",
            amount, user_id
        )
        await db.execute(
            """INSERT INTO balance_transactions (user_id, amount, type, description)
               VALUES ($1, $2, 'debit', $3)""",
            user_id, amount, description
        )
    return True


async def refund_balance(user_id: int, amount: int, description: str):
    """Возвращает сумму на баланс (при отмене заказа)"""
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


async def was_balance_deducted_for_order(user_id: int, order_date: str) -> bool:
    """
    Проверяет, было ли реальное списание с баланса за заказ на эту дату.
    Смотрим в balance_transactions — есть ли debit запись в день заказа.
    """
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            """SELECT id FROM balance_transactions
               WHERE user_id = $1
               AND type = 'debit'
               AND description IN ('Заказ обеда', 'Tushlik buyurtmasi')
               AND DATE(created_at) = $2::date""",
            user_id, order_date
        )
    return row is not None


@router.message(F.text.in_({"🍽️ Заказать обед", "🍽️ Tushlik buyurtma qilish"}))
async def order_lunch(message: Message):
    user = await get_user(message.from_user.id)
    lang = await get_user_lang(message.from_user.id)
    if not user:
        await message.answer("❌ /start")
        return

    if not is_orders_open():
        await message.answer(t(lang, "orders_closed"), parse_mode="Markdown")
        return

    tomorrow = get_tomorrow_date()
    day_name = get_day_name(tomorrow)

    existing_order = await get_today_order(message.from_user.id, tomorrow)
    if existing_order:
        await message.answer(
            f"✅ *{existing_order['meal_name']}*\n\n"
            f"{t(lang, 'change_btn')} / {t(lang, 'cancel_btn')}?",
            parse_mode="Markdown",
            reply_markup=order_actions_keyboard(True)
        )
        return

    menu = await get_menu(tomorrow)
    if not menu:
        await message.answer(t(lang, "no_menu"))
        return

    # Показываем баланс клиента
    balance = await get_user_balance(user["id"])
    meal_price = 35000
    if balance >= meal_price:
        balance_info = f"\n💳 {'Ваш баланс' if lang == 'ru' else 'Sizning hisobingiz'}: *{balance:,} сум* ✅"
    else:
        balance_info = f"\n💳 {'Ваш баланс' if lang == 'ru' else 'Sizning hisobingiz'}: *{balance:,} сум* ⚠️"

    text = f"{t(lang, 'menu_title')} {day_name}* ({tomorrow}):\n\n"
    for item in menu:
        text += f"{item['item_number']}. {item['name']} — {item['price']:,} сум\n"
    text += f"\n{t(lang, 'free_delivery')}\n{t(lang, 'choose_dish')}"
    text += balance_info

    first_photo = next((i for i in menu if i.get("photo_id")), None)
    if first_photo:
        for item in menu:
            if item.get("photo_id"):
                await message.answer_photo(
                    photo=item["photo_id"],
                    caption=f"{item['item_number']}. *{item['name']}* — {item['price']:,} сум",
                    parse_mode="Markdown"
                )
            else:
                await message.answer(
                    f"{item['item_number']}. *{item['name']}* — {item['price']:,} сум",
                    parse_mode="Markdown"
                )
        await message.answer(
            f"{t(lang, 'free_delivery')}\n{t(lang, 'choose_dish')}{balance_info}",
            parse_mode="Markdown",
            reply_markup=menu_keyboard(menu)
        )
    else:
        await message.answer(text, parse_mode="Markdown", reply_markup=menu_keyboard(menu))


@router.callback_query(F.data.startswith("order_"))
async def process_order_selection(callback: CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)
    if not is_orders_open():
        await callback.answer(t(lang, "orders_closed")[:200], show_alert=True)
        return

    menu_id = int(callback.data.split("_")[1])
    tomorrow = get_tomorrow_date()

    order = await create_order(callback.from_user.id, menu_id, tomorrow)
    user = await get_user(callback.from_user.id)
    if not order:
        await callback.answer("❌", show_alert=True)
        return

    # Пробуем списать с баланса
    meal_price = 35000
    deducted = await deduct_balance(
        user["id"], meal_price,
        "Заказ обеда" if lang == "ru" else "Tushlik buyurtmasi"
    )

    if deducted:
        balance_text = (
            f"\n💳 {'Списано с баланса' if lang == 'ru' else 'Hisobdan ayirildi'}: "
            f"*-{meal_price:,} сум*"
        )
    else:
        balance = await get_user_balance(user["id"])
        balance_text = (
            f"\n💳 {'Баланс' if lang == 'ru' else 'Hisob'}: *{balance:,} сум* "
            f"({'оплата при получении' if lang == 'ru' else 'olishda toʻlov'})"
        )

    reward_text = ""
    points = user["points"]
    if points >= 500:
        reward_text = f"\n{t(lang, 'reward_vip')}"
    elif points >= 200:
        reward_text = f"\n{t(lang, 'reward_lunch')}"
    elif points >= 100:
        reward_text = f"\n{t(lang, 'reward_dessert')}"
    elif points >= 50:
        reward_text = f"\n{t(lang, 'reward_drink')}"

    text = (
        f"{t(lang, 'order_accepted')}\n\n"
        f"🍱 {order['meal_name']}\n"
        f"{t(lang, 'delivery_time')}\n\n"
        f"{t(lang, 'points')}: *{user['points']}* (+5)\n"
        f"{t(lang, 'orders')}: {user['total_orders']}"
        f"{balance_text}"
        f"{reward_text}"
    )
    try:
        await callback.message.edit_text(
            text, parse_mode="Markdown",
            reply_markup=order_actions_keyboard(True)
        )
    except Exception:
        await callback.message.answer(
            text, parse_mode="Markdown",
            reply_markup=order_actions_keyboard(True)
        )
    await callback.answer()


@router.message(F.text.in_({"📝 Мой заказ", "📝 Mening buyurtmam"}))
async def my_order(message: Message):
    lang = await get_user_lang(message.from_user.id)
    tomorrow = get_tomorrow_date()
    day_name = get_day_name(tomorrow)
    order = await get_today_order(message.from_user.id, tomorrow)

    if not order:
        if is_orders_open():
            text = f"{t(lang, 'no_order')}\n\n*{t(lang, 'btn_order')}*"
        else:
            text = t(lang, "orders_closed")
        await message.answer(text, parse_mode="Markdown")
        return

    status_emoji = {"pending": "⏳", "confirmed": "✅", "delivered": "🚚", "cancelled": "❌"}
    status_ru = {"pending": "Ожидает", "confirmed": "Подтверждён", "delivered": "Доставлен", "cancelled": "Отменён"}
    status_uz = {"pending": "Kutilmoqda", "confirmed": "Tasdiqlandi", "delivered": "Yetkazildi", "cancelled": "Bekor qilindi"}
    status = order.get("status", "pending")
    st = status_ru if lang == "ru" else status_uz

    await message.answer(
        f"{t(lang, 'my_order')} {day_name}\n\n"
        f"🍱 {order['meal_name']}\n"
        f"📊 {status_emoji.get(status, '⏳')} {st.get(status, status)}\n"
        f"{t(lang, 'delivery_time')}",
        parse_mode="Markdown",
        reply_markup=order_actions_keyboard(status == "pending")
    )


@router.callback_query(F.data == "change_order")
async def change_order(callback: CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)
    if not is_orders_open():
        await callback.answer(t(lang, "orders_closed")[:200], show_alert=True)
        return

    tomorrow = get_tomorrow_date()
    menu = await get_menu(tomorrow)
    day_name = get_day_name(tomorrow)
    text = f"✏️ *{day_name}*\n\n{t(lang, 'choose_dish')}"
    await callback.message.edit_text(
        text, parse_mode="Markdown", reply_markup=menu_keyboard(menu)
    )
    await callback.answer()


@router.callback_query(F.data == "cancel_order")
async def ask_cancel_order(callback: CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)
    if not is_orders_open():
        await callback.answer(t(lang, "orders_closed")[:200], show_alert=True)
        return
    await callback.message.edit_text(
        t(lang, "confirm_cancel"),
        reply_markup=confirm_cancel_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "confirm_cancel")
async def confirm_cancel_order(callback: CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)
    tomorrow = get_tomorrow_date()
    user = await get_user(callback.from_user.id)
    meal_price = 35000

    # Возвращаем баланс ТОЛЬКО если при заказе реально списывалось
    was_deducted = await was_balance_deducted_for_order(user["id"], tomorrow)

    await cancel_order(callback.from_user.id, tomorrow)

    if was_deducted:
        await refund_balance(
            user["id"], meal_price,
            "Возврат за отмену заказа" if lang == "ru" else "Buyurtma bekor qilingani uchun qaytarish"
        )
        refund_text = (
            f"\n💳 +{meal_price:,} сум "
            f"{'возвращено на баланс' if lang == 'ru' else 'hisobga qaytarildi'}"
        )
    else:
        refund_text = ""

    await callback.message.edit_text(
        f"{t(lang, 'order_cancelled')}{refund_text}"
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_order")
async def back_to_order(callback: CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)
    tomorrow = get_tomorrow_date()
    day_name = get_day_name(tomorrow)
    order = await get_today_order(callback.from_user.id, tomorrow)
    if order:
        await callback.message.edit_text(
            f"{t(lang, 'my_order')} {day_name}\n\n🍱 {order['meal_name']}",
            parse_mode="Markdown",
            reply_markup=order_actions_keyboard(True)
        )
    await callback.answer()
