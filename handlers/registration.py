import random
import string
from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import CommandStart

from database.db import get_user, create_user, get_or_create_company, get_user_lang, set_user_lang, save_user_phone, get_pool
from keyboards.keyboards import main_menu_keyboard
from config import ADMIN_IDS
from langs import t

router = Router()

class Registration(StatesGroup):
    waiting_lang = State()
    waiting_name = State()
    waiting_phone = State()
    waiting_company = State()
    waiting_location = State()


def generate_referral_code(name: str) -> str:
    letters = name.upper().replace(" ", "")[:3]
    numbers = "".join(random.choices(string.digits, k=3))
    return f"{letters}{numbers}"


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user = await get_user(message.from_user.id)

    if user:
        is_admin = message.from_user.id in ADMIN_IDS
        lang = await get_user_lang(message.from_user.id)
        await message.answer(
            f"{t(lang, 'welcome_back')}, {user['full_name']}!\n\n"
            f"{t(lang, 'points')}: {user['points']} | {t(lang, 'orders')}: {user['total_orders']}\n"
            f"{t(lang, 'status')}: {user['status']}",
            reply_markup=main_menu_keyboard(is_admin, lang)
        )
        return

    args = message.text.split()
    ref_code = args[1] if len(args) > 1 else None
    await state.update_data(ref_code=ref_code)
    await state.set_state(Registration.waiting_lang)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="🇷🇺 Русский", callback_data="lang_ru")
    builder.button(text="🇺🇿 O'zbekcha (lotin)", callback_data="lang_uz_latin")
    builder.adjust(1)

    await message.answer_photo(
        photo="AgACAgIAAxkDAAIBO2ofQk41gxtkh-eUj9vSRqnLWHnlAAIgImsb7_X4SFTotJtbHrfgAQADAgADeAADOwQ",
        caption=(
            "🌿 *Bazilik — Since 2025*\n\n"
            "🍱 *Что умеет этот бот?*\n"
            "• Заказ обедов в офис каждый день\n"
            "• Меню из 3 блюд на выбор ежедневно\n"
            "• Система баллов и бонусов\n\n"
            "📞 +998 77 181 50 00\n"
            "⏰ Пн-Вс: 10:00 — 14:00\n\n"
            "🌐 Выберите язык / Tilni tanlang:"
        ),
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("lang_"), Registration.waiting_lang)
async def process_lang(callback: CallbackQuery, state: FSMContext):
    lang = callback.data.replace("lang_", "")
    await state.update_data(lang=lang)
    await state.set_state(Registration.waiting_name)
    await callback.answer()
    await callback.message.answer(t(lang, "enter_name"), parse_mode="Markdown")


@router.message(Registration.waiting_name)
async def process_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 3:
        await message.answer("❌ Введите полное имя (минимум 3 символа)")
        return

    await state.update_data(name=name)
    data = await state.get_data()
    lang = data.get("lang", "ru")
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(lang, "share_phone"), request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await state.set_state(Registration.waiting_phone)
    await message.answer(
        f"✅ {name}!\n\n" + t(lang, "enter_phone"),
        parse_mode="Markdown",
        reply_markup=kb
    )


@router.message(Registration.waiting_phone, F.contact)
async def process_phone_contact(message: Message, state: FSMContext):
    phone = message.contact.phone_number.replace("+", "").strip()
    await state.update_data(phone=phone)
    data = await state.get_data()
    lang = data.get("lang", "ru")
    await state.set_state(Registration.waiting_company)
    await message.answer(
        f"✅ {t(lang, 'phone_saved')} +{phone}\n\n{t(lang, 'enter_company')}",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )


@router.message(Registration.waiting_phone)
async def process_phone_text(message: Message, state: FSMContext):
    phone = message.text.strip().replace("+", "").replace(" ", "").replace("-", "")
    data = await state.get_data()
    lang = data.get("lang", "ru")

    if not phone.isdigit() or len(phone) < 9:
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=t(lang, "share_phone"), request_contact=True)]],
            resize_keyboard=True, one_time_keyboard=True
        )
        await message.answer("❌ " + t(lang, "enter_phone"), parse_mode="Markdown", reply_markup=kb)
        return

    await state.update_data(phone=phone)
    await state.set_state(Registration.waiting_company)
    await message.answer(
        f"✅ {t(lang, 'phone_saved')} +{phone}\n\n{t(lang, 'enter_company')}",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )


@router.message(Registration.waiting_company)
async def process_company(message: Message, state: FSMContext):
    company_name = message.text.strip()
    if len(company_name) < 2:
        await message.answer("❌ Введите корректное название компании")
        return

    data = await state.get_data()
    lang = data.get("lang", "ru")
    company_id = await get_or_create_company(company_name)
    await state.update_data(company_name=company_name, company_id=company_id)
    await state.set_state(Registration.waiting_location)

    loc_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(
            text="📍 Отправить локацию" if lang == "ru" else "📍 Joylashuvni yuborish",
            request_location=True
        )]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    text = (
        "📍 Отправьте *локацию вашей компании*\nНажмите кнопку ниже 👇"
        if lang == "ru" else
        "📍 *Kompaniya joylashuvingizni* yuboring\nQuyidagi tugmani bosing 👇"
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=loc_kb)


@router.message(Registration.waiting_location, F.location)
async def process_location(message: Message, state: FSMContext):
    lat = message.location.latitude
    lon = message.location.longitude
    maps_link = f"https://maps.google.com/?q={lat},{lon}"

    await state.update_data(maps_link=maps_link)
    data = await state.get_data()
    lang = data.get("lang", "ru")
    company_name = data["company_name"]
    company_id = data["company_id"]
    referral_code = generate_referral_code(data["name"])

    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE companies SET maps_link = $1 WHERE id = $2",
            maps_link, company_id
        )

    user = await create_user(
    telegram_id=message.from_user.id,
    full_name=data["name"],
    username=message.from_user.username or "",
    company_id=company_id,
    referral_code=referral_code,
    referred_by_code=data.get("ref_code")
)

    await save_user_phone(message.from_user.id, data.get("phone", ""))
    await set_user_lang(message.from_user.id, lang)

    bonus_text = ""
    if data.get("ref_code"):
        bonus_text = "\n🎁 *+10 баллов* за приглашение друга!"

    is_admin = message.from_user.id in ADMIN_IDS
    await state.clear()
    await message.answer(
        f"{t(lang, 'reg_done')}\n\n"
        f"{t(lang, 'name_label')}: {user['full_name']}\n"
        f"{t(lang, 'phone_label')}: +{data.get('phone', '—')}\n"
        f"{t(lang, 'company_label')}: {company_name}\n"
        f"📍 [Lokatsiya]({maps_link})\n"
        f"{t(lang, 'code_label')}: `{referral_code}`\n"
        f"{t(lang, 'points_label')}: {user['points']}"
        f"{bonus_text}\n\n"
        f"{t(lang, 'daily_info')}",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(is_admin, lang)
    )
