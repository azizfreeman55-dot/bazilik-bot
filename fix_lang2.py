# Добавляем язык в БД и регистрацию
code = open("database/db.py", "r", encoding="utf-8").read()

old = '''            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                full_name TEXT,
                username TEXT,
                company_id INTEGER REFERENCES companies(id),
                points INTEGER DEFAULT 0,
                total_orders INTEGER DEFAULT 0,
                streak_days INTEGER DEFAULT 0,
                last_order_date TEXT,
                referral_code TEXT UNIQUE,
                referred_by INTEGER REFERENCES users(id),
                auto_order INTEGER DEFAULT 0,
                auto_order_item INTEGER DEFAULT 1,
                status TEXT DEFAULT 'Новый',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );'''

new = '''            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                full_name TEXT,
                username TEXT,
                company_id INTEGER REFERENCES companies(id),
                points INTEGER DEFAULT 0,
                total_orders INTEGER DEFAULT 0,
                streak_days INTEGER DEFAULT 0,
                last_order_date TEXT,
                referral_code TEXT UNIQUE,
                referred_by INTEGER REFERENCES users(id),
                auto_order INTEGER DEFAULT 0,
                auto_order_item INTEGER DEFAULT 1,
                status TEXT DEFAULT 'Новый',
                lang TEXT DEFAULT 'ru',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );'''

code = code.replace(old, new)

with open("database/db.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ db.py обновлён!")

# Добавляем функцию получения языка
code2 = open("database/db.py", "r", encoding="utf-8").read()

old2 = '''async def get_all_users_for_notification() -> list:'''

new2 = '''async def get_user_lang(telegram_id: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT lang FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row["lang"] if row else "ru"


async def set_user_lang(telegram_id: int, lang: str):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("ALTER TABLE users ADD COLUMN lang TEXT DEFAULT 'ru'")
            await db.commit()
        except Exception:
            pass
        await db.execute(
            "UPDATE users SET lang = ? WHERE telegram_id = ?",
            (lang, telegram_id)
        )
        await db.commit()


async def get_all_users_for_notification() -> list:'''

code2 = code2.replace(old2, new2)

with open("database/db.py", "w", encoding="utf-8") as f:
    f.write(code2)

print("✅ get_user_lang добавлен!")

# Обновляем регистрацию - добавляем выбор языка
code3 = open("handlers/registration.py", "r", encoding="utf-8").read()

old3 = '''class Registration(StatesGroup):
    waiting_name = State()
    waiting_phone = State()
    waiting_company = State()
    waiting_address = State()'''

new3 = '''class Registration(StatesGroup):
    waiting_lang = State()
    waiting_name = State()
    waiting_phone = State()
    waiting_company = State()
    waiting_address = State()'''

code3 = code3.replace(old3, new3)

old4 = '''    await state.update_data(ref_code=ref_code)
    await state.set_state(Registration.waiting_name)
    await message.answer_photo(
        photo="AgACAgIAAxkDAAIBO2ofQk41gxtkh-eUj9vSRqnLWHnlAAIgImsb7_X4SFTotJtbHrfgAQADAgADeAADOwQ",
        caption=(
            "🌿 *Добро пожаловать в Bazilik!*\\n\\n"
            "🍱 Мы доставляем свежие домашние обеды\\n"
            "прямо в ваш офис каждый день\\n\\n"
            "✅ Выбирайте из 3 блюд ежедневно\\n"
            "✅ Заказывайте до 20:00\\n"
            "✅ Получайте обед с 12:00 до 13:00\\n"
            "✅ Копите баллы и получайте бонусы\\n\\n"
            "📝 Для начала введите ваше *полное имя*:"
        ),
        parse_mode="Markdown"
    )'''

new4 = '''    await state.update_data(ref_code=ref_code)
    await state.set_state(Registration.waiting_lang)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="🇷🇺 Русский", callback_data="lang_ru")
    builder.button(text="🇺🇿 O\'zbekcha (lotin)", callback_data="lang_uz_latin")
    builder.button(text="🇺🇿 Ўзбекча (кирилл)", callback_data="lang_uz_cyrillic")
    builder.adjust(1)

    await message.answer_photo(
        photo="AgACAgIAAxkDAAIBO2ofQk41gxtkh-eUj9vSRqnLWHnlAAIgImsb7_X4SFTotJtbHrfgAQADAgADeAADOwQ",
        caption="🌿 *Bazilik*\\n\\n🌐 Выберите язык / Tilni tanlang / Тилни танланг:",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("lang_"), Registration.waiting_lang)
async def process_lang(callback: CallbackQuery, state: FSMContext):
    lang = callback.data.replace("lang_", "")
    await state.update_data(lang=lang)
    await state.set_state(Registration.waiting_name)

    from langs import t
    await callback.answer()
    await callback.message.answer(
        t(lang, "enter_name"),
        parse_mode="Markdown"
    )'''

code3 = code3.replace(old4, new4)

# Обновляем process_name чтобы использовал язык
old5 = '''@router.message(Registration.waiting_name)
async def process_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 3:
        await message.answer("❌ Введите полное имя (минимум 3 символа)")
        return

    await state.update_data(name=name)
    await state.set_state(Registration.waiting_phone)
    await message.answer(
        f"✅ Отлично, {name}!\\n\\n"
        "📱 Теперь поделитесь вашим номером телефона.\\n"
        "Нажмите кнопку ниже 👇",
        parse_mode="Markdown",
        reply_markup=phone_keyboard()
    )'''

new5 = '''@router.message(Registration.waiting_name)
async def process_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 3:
        await message.answer("❌ Введите полное имя (минимум 3 символа)")
        return

    await state.update_data(name=name)
    await state.set_state(Registration.waiting_phone)
    data = await state.get_data()
    lang = data.get("lang", "ru")

    from langs import t
    from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(lang, "share_phone"), request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await message.answer(
        f"✅ {name}!\\n\\n" + t(lang, "enter_phone"),
        parse_mode="Markdown",
        reply_markup=kb
    )'''

code3 = code3.replace(old5, new5)

# Финальное сообщение регистрации с языком
old6 = '''    await save_user_phone(message.from_user.id, data.get("phone", ""))
    user = await create_user('''

new6 = '''    lang = data.get("lang", "ru")
    await save_user_phone(message.from_user.id, data.get("phone", ""))

    # Сохраняем язык
    import aiosqlite
    from config import DATABASE_URL as DB_URL
    async with aiosqlite.connect(DB_URL) as db:
        try:
            await db.execute("ALTER TABLE users ADD COLUMN lang TEXT DEFAULT 'ru'")
            await db.commit()
        except Exception:
            pass

    user = await create_user('''

code3 = code3.replace(old6, new6)

with open("handlers/registration.py", "w", encoding="utf-8") as f:
    f.write(code3)

print("✅ registration.py обновлён!")

# Обновляем keyboards.py - кнопки меняются по языку
code4 = open("keyboards/keyboards.py", "r", encoding="utf-8").read()

old7 = '''def main_menu_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="🍽️ Заказать обед"), KeyboardButton(text="📝 Мой заказ")],
        [KeyboardButton(text="🪪 Мой профиль"), KeyboardButton(text="🏆 Рейтинг")],
        [KeyboardButton(text="👥 Пригласить коллегу"), KeyboardButton(text="⚙️ Настройки")],
    ]
    if is_admin:
        buttons.append([KeyboardButton(text="🖥️ Админ панель")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)'''

new7 = '''def main_menu_keyboard(is_admin: bool = False, lang: str = "ru") -> ReplyKeyboardMarkup:
    from langs import t
    buttons = [
        [KeyboardButton(text=t(lang, "btn_order")), KeyboardButton(text=t(lang, "btn_my_order"))],
        [KeyboardButton(text=t(lang, "btn_profile")), KeyboardButton(text=t(lang, "btn_rating"))],
        [KeyboardButton(text=t(lang, "btn_invite")), KeyboardButton(text=t(lang, "btn_settings"))],
    ]
    if is_admin:
        buttons.append([KeyboardButton(text=t(lang, "btn_admin"))])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)'''

code4 = code4.replace(old7, new7)

with open("keyboards/keyboards.py", "w", encoding="utf-8") as f:
    f.write(code4)

print("✅ keyboards.py обновлён!")
print("\\n✅ Все файлы обновлены! Запускай: python main.py")