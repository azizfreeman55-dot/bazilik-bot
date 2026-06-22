"""
handlers/reviews.py — обработка отзывов на блюда после доставки.

Добавьте роутер в handlers/__init__.py:
    from handlers.reviews import router as reviews_router
    dp.include_router(reviews_router)
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery

from database.db import get_user, get_user_lang, save_review, save_courier_review

router = Router()


@router.callback_query(F.data.startswith("review_"))
async def process_review(callback: CallbackQuery):
    parts = callback.data.split("_")
    order_id = int(parts[1])
    menu_id = int(parts[2])
    rating = int(parts[3])

    lang = await get_user_lang(callback.from_user.id)
    user = await get_user(callback.from_user.id)

    saved = await save_review(order_id, user["id"], menu_id, rating)

    stars_display = "⭐" * rating

    if not saved:
        text = (
            "Siz allaqachon baholagansiz, rahmat!" if lang == "uz"
            else "Вы уже оставили отзыв на этот заказ, спасибо!"
        )
        await callback.answer(text, show_alert=True)
        return

    if lang == "uz":
        text = (
            f"✅ *Rahmat!*\n\n"
            f"Sizning bahoyingiz: {stars_display}\n"
            f"🎁 +2 ball hisobingizga qo'shildi!"
        )
    else:
        text = (
            f"✅ *Спасибо за отзыв!*\n\n"
            f"Ваша оценка: {stars_display}\n"
            f"🎁 +2 балла начислено!"
        )

    try:
        await callback.message.edit_text(text, parse_mode="Markdown")
    except Exception:
        await callback.message.answer(text, parse_mode="Markdown")

    await callback.answer("✅ Спасибо!" if lang == "ru" else "✅ Rahmat!")


@router.callback_query(F.data.startswith("crreview_"))
async def process_courier_review(callback: CallbackQuery):
    """Обработка оценки курьера/доставки (отдельно от оценки блюд)"""
    parts = callback.data.split("_")
    courier_id = int(parts[1])
    route_id = int(parts[2])
    rating = int(parts[3])

    lang = await get_user_lang(callback.from_user.id)
    user = await get_user(callback.from_user.id)

    saved = await save_courier_review(courier_id, user["id"], route_id, rating)

    stars_display = "⭐" * rating

    if not saved:
        text = (
            "Siz allaqachon baholagansiz, rahmat!" if lang == "uz"
            else "Вы уже оценили эту доставку, спасибо!"
        )
        await callback.answer(text, show_alert=True)
        return

    if lang == "uz":
        text = f"✅ *Rahmat!*\n\nYetkazib berish bahosi: {stars_display}"
    else:
        text = f"✅ *Спасибо за оценку доставки!*\n\nВаша оценка: {stars_display}"

    try:
        await callback.message.edit_text(text, parse_mode="Markdown")
    except Exception:
        await callback.message.answer(text, parse_mode="Markdown")

    await callback.answer("✅ Спасибо!" if lang == "ru" else "✅ Rahmat!")
