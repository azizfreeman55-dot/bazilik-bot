from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database.db import get_user, get_user_lang, get_pool

router = Router()


async def get_user_balance(user_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            "SELECT balance FROM user_balance WHERE user_id = $1", user_id
        )
        return row["balance"] if row else 0


async def get_balance_history(user_id: int) -> list:
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            """SELECT amount, type, description, created_at
               FROM balance_transactions
               WHERE user_id = $1
               ORDER BY created_at DESC LIMIT 10""",
            user_id
        )
        return [dict(r) for r in rows]


async def add_balance(user_id: int, amount: int, description: str):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            """INSERT INTO user_balance (user_id, balance)
               VALUES ($1, $2)
               ON CONFLICT (user_id) DO UPDATE SET balance = user_balance.balance + $2""",
            user_id, amount
        )
        await db.execute(
            """INSERT INTO balance_transactions (user_id, amount, type, description)
               VALUES ($1, $2, $3, $4)""",
            user_id, amount, "credit" if amount > 0 else "debit", description
        )


async def deduct_balance(user_id: int, amount: int, description: str) -> bool:
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


@router.message(F.text.contains("баланс") | F.text.contains("hisobim"))
async def my_balance(message: Message):
    user = await get_user(message.from_user.id)
    lang = await get_user_lang(message.from_user.id)
    if not user:
        await message.answer("❌ /start")
        return

    balance = await get_user_balance(user["id"])
    history = await get_balance_history(user["id"])

    title = "💳 *Мой баланс*" if lang == "ru" else "💳 *Mening hisobim*"
    balance_text = f"{'Баланс' if lang == 'ru' else 'Hisob'}: *{balance:,} сум*"
    history_title = "📊 *История операций:*" if lang == "ru" else "📊 *Operatsiyalar tarixi:*"
    history_text = ""

    if history:
        for h in history:
            sign = "+" if h["type"] == "credit" else "-"
            date = h["created_at"].strftime("%d.%m")
            history_text += f"{sign} {abs(h['amount']):,} сум — {h['description']} ({date})\n"
    else:
        history_text = "Операций пока нет" if lang == "ru" else "Operatsiyalar yo'q"

    builder = InlineKeyboardBuilder()
    builder.button(
        text="➕ Пополнить баланс" if lang == "ru" else "➕ Hisob to'ldirish",
        callback_data="topup_balance"
    )
    builder.adjust(1)

    await message.answer(
        f"{title}\n\n{balance_text}\n\n{history_title}\n{history_text}",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data == "topup_balance")
async def topup_balance(callback: CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)

    builder = InlineKeyboardBuilder()
    amounts = [50000, 100000, 200000, 500000]
    for amount in amounts:
        builder.button(text=f"{amount:,} сум", callback_data=f"topup_{amount}")
    builder.button(
        text="✏️ Своя сумма" if lang == "ru" else "✏️ O'z summasi",
        callback_data="topup_custom"
    )
    builder.button(
        text="◀️ Назад" if lang == "ru" else "◀️ Orqaga",
        callback_data="back_balance"
    )
    builder.adjust(2)

    await callback.message.edit_text(
        "➕ *Пополнение баланса*\n\nВыберите сумму или введите свою:" if lang == "ru"
        else "➕ *Hisob to'ldirish*\n\nSummani tanlang yoki o'zingiz kiriting:",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data == "topup_custom")
async def topup_custom(callback: CallbackQuery, state):
    lang = await get_user_lang(callback.from_user.id)
    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.state import State, StatesGroup

    await state.set_state("waiting_custom_amount")
    await callback.message.answer(
        "✏️ *Введите сумму пополнения:*\nНапример: 150000" if lang == "ru"
        else "✏️ *To'ldirish summasini kiriting:*\nMasalan: 150000",
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(F.text.regexp(r'^\d+$'))
async def process_custom_amount(message: Message, state):
    current_state = await state.get_state()
    if current_state != "waiting_custom_amount":
        return

    lang = await get_user_lang(message.from_user.id)
    amount = int(message.text.strip())

    if amount < 1000:
        await message.answer(
            "❌ Минимальная сумма 1,000 сум" if lang == "ru"
            else "❌ Minimal summa 1,000 sum"
        )
        return
        
    if amount > 10000000:
        await message.answer(
            "❌ Максимальная сумма 10,000,000 сум" if lang == "ru"
            else "❌ Maksimal summa 10,000,000 sum"
        )
        return

    await state.clear()

    from config import CLICK_SERVICE_ID, CLICK_MERCHANT_ID
    user = await get_user(message.from_user.id)
    order_id = f"balance_{user['id']}_{amount}"
    click_link = (
        f"https://my.click.uz/services/pay?"
        f"service_id={CLICK_SERVICE_ID}"
        f"&merchant_id={CLICK_MERCHANT_ID}"
        f"&amount={amount}"
        f"&transaction_param={order_id}"
        f"&return_url=https://t.me/BazilikCateringBot"
    )

    builder = InlineKeyboardBuilder()
    builder.button(
        text="💳 Оплатить через Click" if lang == "ru" else "💳 Click orqali to'lash",
        url=click_link
    )
    builder.button(
        text="✅ Я оплатил" if lang == "ru" else "✅ To'ladim",
        callback_data=f"check_payment_balance_{user['id']}_{amount}_{amount}"
    )
    builder.adjust(1)

    await message.answer(
        f"💳 *{'Пополнение баланса' if lang == 'ru' else 'Hisob toʻldirish'}*\n\n"
        f"{'Сумма' if lang == 'ru' else 'Summa'}: *{amount:,} сум*\n\n"
        f"{'Нажмите кнопку для оплаты через Click' if lang == 'ru' else 'Click orqali toʻlash uchun tugmani bosing'}:",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data == "back_balance")
async def back_balance(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = await get_user_lang(callback.from_user.id)
    balance = await get_user_balance(user["id"])
    history = await get_balance_history(user["id"])

    history_text = ""
    if history:
        for h in history:
            sign = "+" if h["type"] == "credit" else "-"
            date = h["created_at"].strftime("%d.%m")
            history_text += f"{sign} {abs(h['amount']):,} сум — {h['description']} ({date})\n"
    else:
        history_text = "Операций пока нет" if lang == "ru" else "Operatsiyalar yo'q"

    builder = InlineKeyboardBuilder()
    builder.button(
        text="➕ Пополнить баланс" if lang == "ru" else "➕ Hisob to'ldirish",
        callback_data="topup_balance"
    )

    await callback.message.edit_text(
        f"💳 *{'Мой баланс' if lang == 'ru' else 'Mening hisobim'}*\n\n"
        f"{'Баланс' if lang == 'ru' else 'Hisob'}: *{balance:,} сум*\n\n"
        f"📊 *{'История операций' if lang == 'ru' else 'Operatsiyalar tarixi'}:*\n{history_text}",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )
    await callback.answer()
