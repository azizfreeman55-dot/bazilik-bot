import hashlib
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database.db import get_user, get_user_lang, get_pool
from config import CLICK_SERVICE_ID, CLICK_MERCHANT_ID, CLICK_MERCHANT_USER_ID

router = Router()


def generate_click_link(amount: int, order_id: str, user_id: int) -> str:
    """Генерируем ссылку для оплаты через Click"""
    return (
        f"https://my.click.uz/services/pay?"
        f"service_id={CLICK_SERVICE_ID}"
        f"&merchant_id={CLICK_MERCHANT_ID}"
        f"&amount={amount}"
        f"&transaction_param={order_id}"
        f"&return_url=https://t.me/BazilikCateringBot"
    )


@router.callback_query(F.data.startswith("topup_"))
async def process_topup_click(callback: CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)
    amount = int(callback.data.replace("topup_", ""))
    user = await get_user(callback.from_user.id)
    order_id = f"balance_{user['id']}_{amount}"

    click_link = generate_click_link(amount, order_id, user["id"])

    builder = InlineKeyboardBuilder()
    builder.button(
        text="💳 Оплатить через Click" if lang == "ru" else "💳 Click orqali to'lash",
        url=click_link
    )
    builder.button(
        text="✅ Я оплатил" if lang == "ru" else "✅ To'ladim",
        callback_data=f"check_payment_{order_id}_{amount}"
    )
    builder.button(
        text="◀️ Назад" if lang == "ru" else "◀️ Orqaga",
        callback_data="topup_balance"
    )
    builder.adjust(1)

    await callback.message.edit_text(
        f"💳 *{'Пополнение баланса' if lang == 'ru' else 'Hisob toʻldirish'}*\n\n"
        f"{'Сумма' if lang == 'ru' else 'Summa'}: *{amount:,} сум*\n\n"
        f"{'Нажмите кнопку ниже для оплаты через Click' if lang == 'ru' else 'Click orqali toʻlash uchun quyidagi tugmani bosing'}:\n\n"
        f"{'После оплаты нажмите' if lang == 'ru' else 'Toʻlovdan soʻng bosing'} *{'✅ Я оплатил' if lang == 'ru' else '✅ Toʻladim'}*",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("check_payment_"))
async def check_payment(callback: CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)
    
    await callback.message.edit_text(
        f"⏳ *{'Ожидаем подтверждение от Click...' if lang == 'ru' else 'Click dan tasdiqlash kutilmoqda...'}*\n\n"
        f"{'Баланс пополнится автоматически после подтверждения оплаты.' if lang == 'ru' else 'Tolov tasdiqlangandan so ng hisob avtomatik to ldiriladi.'}\n\n"
        f"{'Обычно это занимает 1-2 минуты.' if lang == 'ru' else 'Bu odatda 1-2 daqiqa oladi.'}",
        parse_mode="Markdown"
    )
    await callback.answer()

    # Пополняем баланс
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            """INSERT INTO user_balance (user_id, balance)
               VALUES ($1, $2)
               ON CONFLICT (user_id) DO UPDATE SET balance = user_balance.balance + $2""",
            user["id"], amount
        )
        await db.execute(
            """INSERT INTO balance_transactions (user_id, amount, type, description)
               VALUES ($1, $2, 'credit', $3)""",
            user["id"], amount,
            "Пополнение через Click" if lang == "ru" else "Click orqali toʻldirish"
        )

    await callback.message.edit_text(
        f"✅ *{'Баланс пополнен!' if lang == 'ru' else 'Hisob toʻldirildi!'}*\n\n"
        f"{'Сумма' if lang == 'ru' else 'Summa'}: *+{amount:,} сум*\n\n"
        f"{'Спасибо за оплату!' if lang == 'ru' else 'Toʻlov uchun rahmat!'}",
        parse_mode="Markdown"
    )
    await callback.answer()
