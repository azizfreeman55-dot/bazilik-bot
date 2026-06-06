from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database.db import get_user, get_user_lang, get_pool
from langs import t

router = Router()

GIFTS = [
    {
        "id": "drink",
        "points": 50,
        "emoji": "🥤",
        "name_ru": "Напиток",
        "name_uz": "Ichimlik",
        "desc_ru": "Освежающий напиток на выбор к вашему обеду!",
        "desc_uz": "Tushligingizga xohlaganingizcha ichimlik!",
        "photo_id": None
    },
    {
        "id": "dessert",
        "points": 100,
        "emoji": "🍰",
        "name_ru": "Десерт",
        "name_uz": "Desert",
        "desc_ru": "Вкусный десерт — сладкое завершение обеда!",
        "desc_uz": "Mazali desert — tushlikning shirin yakuni!",
        "photo_id": None
    },
    {
        "id": "lunch",
        "points": 200,
        "emoji": "🍱",
        "name_ru": "Бесплатный обед",
        "name_uz": "Bepul tushlik",
        "desc_ru": "Полноценный обед абсолютно бесплатно!",
        "desc_uz": "To'liq tushlik mutlaqo bepul!",
        "photo_id": None
    },
    {
        "id": "vip",
        "points": 500,
        "emoji": "👑",
        "name_ru": "Статус VIP",
        "name_uz": "VIP status",
        "desc_ru": "Особый статус с приоритетной доставкой и эксклюзивными бонусами!",
        "desc_uz": "Ustuvor yetkazib berish va eksklyuziv bonuslar bilan maxsus status!",
        "photo_id": None
    },
]


async def get_gift_photos() -> dict:
    """Получаем фото подарков из БД"""
    pool = await get_pool()
    async with pool.acquire() as db:
        try:
            rows = await db.fetch("SELECT gift_id, photo_id FROM gift_photos")
            return {row["gift_id"]: row["photo_id"] for row in rows}
        except Exception:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS gift_photos (
                    gift_id TEXT PRIMARY KEY,
                    photo_id TEXT
                )
            """)
            return {}


def gifts_keyboard(lang: str) -> object:
    builder = InlineKeyboardBuilder()
    for gift in GIFTS:
        name = gift["name_ru"] if lang == "ru" else gift["name_uz"]
        builder.button(
            text=f"{gift['emoji']} {gift['points']} баллов — {name}" if lang == "ru"
            else f"{gift['emoji']} {gift['points']} ball — {name}",
            callback_data=f"gift_{gift['id']}"
        )
    builder.adjust(1)
    return builder.as_markup()


@router.message(F.text.in_({"🎁 Подарки", "🎁 Sovg'alar", "🎁 Sovg`alar"}))
async def show_gifts(message: Message):
    user = await get_user(message.from_user.id)
    lang = await get_user_lang(message.from_user.id)

    points = user["points"] if user else 0
    next_gift = next((g for g in GIFTS if g["points"] > points), None)
    next_text = (
        f"До следующего подарка: *{next_gift['points'] - points} баллов* {next_gift['emoji']}"
        if next_gift else "🎉 Вы получили все подарки!"
    ) if lang == "ru" else (
        f"Keyingi sovg'agacha: *{next_gift['points'] - points} ball* {next_gift['emoji']}"
        if next_gift else "🎉 Siz barcha sovg'alarni oldingiz!"
    )

    title = "🎁 *Подарки и награды*" if lang == "ru" else "🎁 *Sovg'alar va mukofotlar*"
    desc = (
        "Копите баллы и получайте призы!\n"
        "Нажмите на подарок чтобы узнать подробнее 👇"
    ) if lang == "ru" else (
        "Ball to'plang va sovg'alar oling!\n"
        "Batafsil ma'lumot uchun sovg'ani bosing 👇"
    )

    await message.answer(
        f"{title}\n\n"
        f"💰 Ваши баллы: *{points}*\n"
        f"📍 {next_text}\n\n"
        f"{desc}",
        parse_mode="Markdown",
        reply_markup=gifts_keyboard(lang)
    )


@router.callback_query(F.data.startswith("gift_"))
async def show_gift_detail(callback: CallbackQuery):
    gift_id = callback.data.replace("gift_", "")
    lang = await get_user_lang(callback.from_user.id)
    user = await get_user(callback.from_user.id)

    gift = next((g for g in GIFTS if g["id"] == gift_id), None)
    if not gift:
        await callback.answer()
        return

    photos = await get_gift_photos()
    photo_id = photos.get(gift_id)

    name = gift["name_ru"] if lang == "ru" else gift["name_uz"]
    desc = gift["desc_ru"] if lang == "ru" else gift["desc_uz"]
    points = user["points"] if user else 0
    remaining = gift["points"] - points

    if remaining <= 0:
        status = "✅ *Получено!*" if lang == "ru" else "✅ *Olindi!*"
    else:
        status = (
            f"🔘 Ещё *{remaining} баллов*" if lang == "ru"
            else f"🔘 Yana *{remaining} ball*"
        )

    caption = (
        f"{gift['emoji']} *{name}*\n\n"
        f"{desc}\n\n"
        f"💰 Нужно баллов: *{gift['points']}*\n"
        f"📊 Статус: {status}"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад" if lang == "ru" else "◀️ Orqaga", callback_data="back_gifts")
    builder.adjust(1)

    if photo_id:
        try:
            await callback.message.delete()
            await callback.message.answer_photo(
                photo=photo_id,
                caption=caption,
                parse_mode="Markdown",
                reply_markup=builder.as_markup()
            )
        except Exception:
            await callback.message.edit_text(caption, parse_mode="Markdown", reply_markup=builder.as_markup())
    else:
        await callback.message.edit_text(caption, parse_mode="Markdown", reply_markup=builder.as_markup())

    await callback.answer()


@router.callback_query(F.data == "back_gifts")
async def back_to_gifts(callback: CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)
    user = await get_user(callback.from_user.id)
    points = user["points"] if user else 0
    next_gift = next((g for g in GIFTS if g["points"] > points), None)
    next_text = (
        f"До следующего подарка: *{next_gift['points'] - points} баллов* {next_gift['emoji']}"
        if next_gift else "🎉 Вы получили все подарки!"
    ) if lang == "ru" else (
        f"Keyingi sovg'agacha: *{next_gift['points'] - points} ball* {next_gift['emoji']}"
        if next_gift else "🎉 Siz barcha sovg'alarni oldingiz!"
    )

    title = "🎁 Подарки и награды" if lang == "ru" else "Sovgalar va mukofotlar"
    desc = "Нажмите на подарок чтобы узнать подробнее 👇" if lang == "ru" else "Batafsil malumot uchun sovgani bosing 👇"
    
    try:
        await callback.message.edit_text(
            f"🎁 *{title}*\n\n"
            f"💰 {'Ваши баллы' if lang == 'ru' else 'Sizning ballaringiz'}: *{points}*\n"
            f"📍 {next_text}\n\n"
            f"{desc}",
            parse_mode="Markdown",
            reply_markup=gifts_keyboard(lang)
        )
    except Exception:
        pass
    await callback.answer()


# Для админа — загрузка фото подарков
@router.callback_query(F.data.startswith("admin_gift_photo_"))
async def admin_set_gift_photo(callback: CallbackQuery):
    from config import ADMIN_IDS
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    gift_id = callback.data.replace("admin_gift_photo_", "")
    gift = next((g for g in GIFTS if g["id"] == gift_id), None)

    await callback.message.answer(
        f"📸 Отправьте фото для подарка *{gift['name_ru']}*\n"
        f"Просто отправьте фото следующим сообщением!",
        parse_mode="Markdown"
    )

    from aiogram.fsm.context import FSMContext
    await callback.answer()
