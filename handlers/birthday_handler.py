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
