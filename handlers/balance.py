from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database.db import get_user, get_user_lang, get_pool
from langs import t

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
            """UPDATE user_balance SET balance = balance - $1 WHERE user_id = $2""",
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
        f"{title}\n\n"
        f"{balance_text}\n\n"
        f"{history_title}\n{history_text}",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data == "topup_balance")
async def topup_balance(callback: CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)

    builder = InlineKeyboardBuilder()
    amounts = [50000, 100000, 200000, 500000]
    for amount in amounts:
        builder.button(
            text=f"{amount:,} сум",
            callback_data=f"topup_{amount}"
        )
    builder.button(
        text="◀️ Назад" if lang == "ru" else "◀️ Orqaga",
        callback_data="back_balance"
    )
    builder.adjust(2)

    await callback.message.edit_text(
        "➕ *Пополнение баланса*\n\nВыберите сумму:" if lang == "ru"
        else "➕ *Hisob to'ldirish*\n\nSummani tanlang:",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("topup_"))
async def process_topup(callback: CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)
    amount = int(callback.data.replace("topup_", ""))

    # Здесь будет интеграция с Payme/Click
    # Пока показываем реквизиты для ручного пополнения
    await callback.message.edit_text(
        f"💳 *Пополнение на {amount:,} сум*\n\n"
        f"Для пополнения баланса переведите *{amount:,} сум* на:\n\n"
        f"🏦 Банк: *Uzum Bank*\n"
        f"💳 Карта: *8600 XXXX XXXX XXXX*\n"
        f"👤 Получатель: *Bazilik Catering*\n\n"
        f"После оплаты отправьте скриншот администратору!\n"
        f"📞 +998 77 181 50 00"
        if lang == "ru" else
        f"💳 *{amount:,} sum to'ldirish*\n\n"
        f"Hisobni to'ldirish uchun *{amount:,} sum* o'tkazing:\n\n"
        f"🏦 Bank: *Uzum Bank*\n"
        f"💳 Karta: *8600 XXXX XXXX XXXX*\n"
        f"👤 Oluvchi: *Bazilik Catering*\n\n"
        f"To'lovdan so'ng skrinshot adminga yuboring!\n"
        f"📞 +998 77 181 50 00",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardBuilder().button(
            text="◀️ Назад" if lang == "ru" else "◀️ Orqaga",
            callback_data="topup_balance"
        ).as_markup()
    )
    await callback.answer()


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
