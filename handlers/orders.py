from datetime import date, datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

from database.db import (
    get_user, get_menu, get_menu_categories, get_today_order,
    create_order, cancel_order, get_user_lang, get_pool
)
from langs import t
from keyboards.keyboards import (
    category_keyboard, menu_keyboard, order_actions_keyboard,
    confirm_cancel_keyboard, CATEGORY_NAMES
)
from config import ORDER_CLOSE_TIME

router = Router()


def is_orders_open() -> bool:
    now = datetime.now().strftime("%H:%M")
    return now < ORDER_CLOSE_TIME


def get_tomorrow_date() -> str:
    from datetime import timedelta
    return str(date.today() + timedelta(days=1))


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


async def deduct_balance(user_id: int, amount: int, description: str, order_date: str) -> bool:
    """Списывает сумму с баланса. description содержит order_date для точного поиска при отмене."""
    pool = await get_pool()
    full_description = f"{description}|{order_date}"
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
            user_id, amount, full_description
        )
    return True


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


async def find_deduction_for_order(user_id: int, order_date: str) -> dict | None:
    """
    Ищем запись о списании за заказ на конкретную order_date.
    Маркер |order_date зашит в description при списании (deduct_balance).
    Возвращает {"id":..., "amount":...} если списание было И ещё не возвращено.
    """
    pool = await get_pool()
    debit_marker = f"|{order_date}"
    refund_marker = f"REFUND|{order_date}"
    async with pool.acquire() as db:
        debit = await db.fetchrow(
            """SELECT id, amount FROM balance_transactions
               WHERE user_id = $1
               AND type = 'debit'
               AND description LIKE '%' || $2
               ORDER BY created_at DESC LIMIT 1""",
            user_id, debit_marker
        )
        if not debit:
            return None

        already_refunded = await db.fetchrow(
            """SELECT id FROM balance_transactions
               WHERE user_id = $1
               AND type = 'credit'
               AND description LIKE '%' || $2 || '%'""",
            user_id, refund_marker
        )
        if already_refunded:
            return None

        return {"id": debit["id"], "amount": debit["amount"]}


# ─── Шаг 1: Показываем категории ──────────────────────────────────────────────

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
        cat = existing_order.get("category", "main")
        cat_name = CATEGORY_NAMES.get(cat, {}).get(lang, cat)
        await message.answer(
            f"✅ *{existing_order['meal_name']}* ({cat_name})\n\n"
            f"{t(lang, 'change_btn')} / {t(lang, 'cancel_btn')}?",
            parse_mode="Markdown",
            reply_markup=order_actions_keyboard(True)
        )
        return

    categories = await get_menu_categories(tomorrow)
    if not categories:
        await message.answer(t(lang, "no_menu"))
        return

    balance = await get_user_balance(user["id"])
    balance_text = (
        f"\n💳 {'Ваш баланс' if lang == 'ru' else 'Hisobingiz'}: *{balance:,} сум*"
    )

    if lang == "ru":
        text = f"🍽️ *Меню на {day_name} ({tomorrow})*\n\nВыберите категорию:{balance_text}"
    else:
        text = f"🍽️ *{day_name} ({tomorrow}) menyu*\n\nKategoriyani tanlang:{balance_text}"

    await message.answer(
        text,
        parse_mode="Markdown",
        reply_markup=category_keyboard(categories, lang)
    )


# ─── Шаг 2: Показываем блюда выбранной категории ──────────────────────────────

@router.callback_query(F.data.startswith("menu_category_"))
async def show_category_menu(callback: CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)
    category = callback.data.replace("menu_category_", "")
    tomorrow = get_tomorrow_date()

    menu = await get_menu(tomorrow, category)
    if not menu:
        await callback.answer(
            "❌ В этой категории пока нет позиций" if lang == "ru" else "❌ Bu kategoriyada hozircha pozitsiya yo'q",
            show_alert=True
        )
        return

    cat_name = CATEGORY_NAMES.get(category, {}).get(lang, category)
    day_name = get_day_name(tomorrow)

    text = f"*{cat_name}* — {day_name}\n\n"
    for item in menu:
        text += f"{item['item_number']}. {item['name']} — {item['price']:,} сум\n"

    first_photo = next((i for i in menu if i.get("photo_id")), None)
    if first_photo:
        try:
            await callback.message.delete()
        except Exception:
            pass
        for item in menu:
            if item.get("photo_id"):
                await callback.message.answer_photo(
                    photo=item["photo_id"],
                    caption=f"{item['item_number']}. *{item['name']}* — {item['price']:,} сум",
                    parse_mode="Markdown"
                )
            else:
                await callback.message.answer(
                    f"{item['item_number']}. *{item['name']}* — {item['price']:,} сум",
                    parse_mode="Markdown"
                )
        await callback.message.answer(
            f"{'Выберите позицию:' if lang == 'ru' else 'Pozitsiyani tanlang:'}",
            reply_markup=menu_keyboard(menu, category, lang)
        )
    else:
        await callback.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=menu_keyboard(menu, category, lang)
        )
    await callback.answer()


@router.callback_query(F.data == "back_to_categories")
async def back_to_categories(callback: CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)
    tomorrow = get_tomorrow_date()
    day_name = get_day_name(tomorrow)
    categories = await get_menu_categories(tomorrow)

    if lang == "ru":
        text = f"🍽️ *Меню на {day_name} ({tomorrow})*\n\nВыберите категорию:"
    else:
        text = f"🍽️ *{day_name} ({tomorrow}) menyu*\n\nKategoriyani tanlang:"

    await callback.message.edit_text(
        text,
        parse_mode="Markdown",
        reply_markup=category_keyboard(categories, lang)
    )
    await callback.answer()


# ─── Шаг 3: Оформляем заказ ───────────────────────────────────────────────────

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

    pool = await get_pool()
    async with pool.acquire() as db:
        menu_item = await db.fetchrow("SELECT price, category FROM menus WHERE id = $1", menu_id)
    item_price = menu_item["price"] if menu_item else 35000
    category = menu_item["category"] if menu_item else "main"
    cat_name = CATEGORY_NAMES.get(category, {}).get(lang, category)

    deducted = await deduct_balance(
        user["id"], item_price,
        "Заказ обеда" if lang == "ru" else "Tushlik buyurtmasi",
        tomorrow
    )

    if deducted:
        balance_text = (
            f"\n💳 {'Списано' if lang == 'ru' else 'Ayirildi'}: *-{item_price:,} сум*"
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
        f"{cat_name}: *{order['meal_name']}*\n"
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
        text = f"{t(lang, 'no_order')}\n\n*{t(lang, 'btn_order')}*" if is_orders_open() else t(lang, "orders_closed")
        await message.answer(text, parse_mode="Markdown")
        return

    status_emoji = {"pending": "⏳", "confirmed": "✅", "delivered": "🚚", "cancelled": "❌"}
    status_ru = {"pending": "Ожидает", "confirmed": "Подтверждён", "delivered": "Доставлен", "cancelled": "Отменён"}
    status_uz = {"pending": "Kutilmoqda", "confirmed": "Tasdiqlandi", "delivered": "Yetkazildi", "cancelled": "Bekor qilindi"}
    status = order.get("status", "pending")
    st = status_ru if lang == "ru" else status_uz
    cat_name = CATEGORY_NAMES.get(order.get("category", "main"), {}).get(lang, "")

    await message.answer(
        f"{t(lang, 'my_order')} {day_name}\n\n"
        f"{cat_name}: *{order['meal_name']}*\n"
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
    categories = await get_menu_categories(tomorrow)
    day_name = get_day_name(tomorrow)

    await callback.message.edit_text(
        f"✏️ *{day_name}* — {'выберите категорию:' if lang == 'ru' else 'kategoriyani tanlang:'}",
        parse_mode="Markdown",
        reply_markup=category_keyboard(categories, lang)
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

    # Ищем была ли запись о списании именно за заказ на эту дату
    deduction = await find_deduction_for_order(user["id"], tomorrow)

    await cancel_order(callback.from_user.id, tomorrow)

    if deduction:
        refund_amount = deduction["amount"]
        # Помечаем явным маркером REFUND чтобы не вернуть дважды
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


@router.callback_query(F.data == "back_to_order")
async def back_to_order(callback: CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)
    tomorrow = get_tomorrow_date()
    day_name = get_day_name(tomorrow)
    order = await get_today_order(callback.from_user.id, tomorrow)
    if order:
        cat_name = CATEGORY_NAMES.get(order.get("category", "main"), {}).get(lang, "")
        await callback.message.edit_text(
            f"{t(lang, 'my_order')} {day_name}\n\n{cat_name}: *{order['meal_name']}*",
            parse_mode="Markdown",
            reply_markup=order_actions_keyboard(True)
        )
    await callback.answer()
