from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.db import get_user, get_company_ranking, get_user_lang, get_pool
from langs import t
from config import LOYALTY_LEVELS, ADMIN_IDS

router = Router()


def get_loyalty_progress(points: int, lang: str) -> str:
    milestones = sorted(LOYALTY_LEVELS.keys())
    text = ""
    for milestone in milestones:
        reward = LOYALTY_LEVELS[milestone]["reward"]
        if points >= milestone:
            text += f"✅ {milestone} — {reward}\n"
        else:
            remaining = milestone - points
            text += f"🔘 {milestone} — {reward} (ещё {remaining})\n"
    return text


@router.message(F.text.in_({"🪪 Мой профиль", "🪪 Mening profilim"}))
async def my_profile(message: Message):
    user = await get_user(message.from_user.id)
    lang = await get_user_lang(message.from_user.id)
    if not user:
        await message.answer("❌ /start")
        return

    loyalty_text = get_loyalty_progress(user['points'], lang)
    next_milestone = next(
        (m for m in sorted(LOYALTY_LEVELS.keys()) if m > user['points']), None
    )
    next_text = f"{t(lang, 'next_reward')} *{next_milestone - user['points']}*" if next_milestone else t(lang, 'all_rewards')

    await message.answer(
        f"👤 *{user['full_name']}*\n"
        f"{t(lang, 'status')}: {user['status']}\n"
        f"🏢 {user.get('company_name', '—')}\n\n"
        f"{t(lang, 'orders')}: {user['total_orders']}\n"
        f"{t(lang, 'points')}: *{user['points']}*\n\n"
        f"{t(lang, 'loyalty_title')}\n{loyalty_text}\n"
        f"📍 {next_text}\n\n"
        f"{t(lang, 'code_label')}: `{user['referral_code']}`",
        parse_mode="Markdown"
    )


@router.message(F.text.in_({"👥 Пригласить коллегу", "👥 Hamkasbni taklif qilish"}))
async def invite_colleague(message: Message):
    user = await get_user(message.from_user.id)
    lang = await get_user_lang(message.from_user.id)
    if not user:
        await message.answer("❌ /start")
        return

    bot_username = (await message.bot.get_me()).username
    invite_link = f"https://t.me/{bot_username}?start={user['referral_code']}"
    share_link = f"https://t.me/share/url?url={invite_link}&text=Bazilik+Catering+botiga+qo'shiling!"

    builder = InlineKeyboardBuilder()
    builder.button(text="📤 Ulashish / Поделиться", url=share_link)
    builder.adjust(1)

    await message.answer(
        f"{t(lang, 'invite_text')}\n\n"
        f"{t(lang, 'code_label')}: `{user['referral_code']}`\n"
        f"{t(lang, 'your_link')}\n`{invite_link}`\n\n"
        f"{t(lang, 'you_get')}\n"
        f"{t(lang, 'friend_gets')}",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.message(F.text.in_({"🏆 Рейтинг", "🏆 Reyting"}))
async def company_ranking(message: Message):
    lang = await get_user_lang(message.from_user.id)
    companies = await get_company_ranking()
    user = await get_user(message.from_user.id)

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    title = "🏆 *Reyting*" if lang == "uz_latin" else "🏆 *Рейтинг компаний*"
    text = f"{title}\n\n"

    for i, company in enumerate(companies):
        medal = medals[i] if i < len(medals) else f"{i+1}."
        highlight = " ◀️" if user and company["name"] == user.get("company_name") else ""
        text += f"{medal} {company['name']} — {company['month_orders']} заказов{highlight}\n"

    if not companies:
        text += "—"

    await message.answer(text, parse_mode="Markdown")


@router.message(F.text.in_({"⚙️ Настройки", "⚙️ Sozlamalar"}))
async def settings(message: Message):
    user = await get_user(message.from_user.id)
    lang = await get_user_lang(message.from_user.id)
    if not user:
        await message.answer("❌ /start")
        return

    builder = InlineKeyboardBuilder()
    builder.button(
        text=t(lang, "btn_auto_on") if user.get("auto_order") else t(lang, "btn_auto_off"),
        callback_data="toggle_auto_order"
    )
    builder.button(text=t(lang, "btn_weekly"), callback_data="weekly_menu")
    builder.adjust(1)

    await message.answer(
        f"⚙️ *{'Sozlamalar' if lang == 'uz_latin' else 'Настройки'}*",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data == "toggle_auto_order")
async def toggle_auto_order(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = await get_user_lang(callback.from_user.id)
    new_status = 0 if user["auto_order"] else 1

    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE users SET auto_order = $1 WHERE telegram_id = $2",
            new_status, callback.from_user.id
        )

    await callback.answer(t(lang, "btn_auto_on") if new_status else t(lang, "btn_auto_off"))

    builder = InlineKeyboardBuilder()
    builder.button(
        text=t(lang, "btn_auto_on") if new_status else t(lang, "btn_auto_off"),
        callback_data="toggle_auto_order"
    )
    builder.button(text=t(lang, "btn_weekly"), callback_data="weekly_menu")
    builder.adjust(1)
    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())