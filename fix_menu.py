# Обновляем admin.py - добавляем загрузку фото к меню
code = open("handlers/admin.py", "r", encoding="utf-8").read()

old = '''class AddMenu(StatesGroup):
    waiting_date = State()
    waiting_items = State()'''

new = '''class AddMenu(StatesGroup):
    waiting_date = State()
    waiting_photo = State()
    waiting_name = State()
    waiting_price = State()
    waiting_more = State()'''

code = code.replace(old, new)

old2 = '''@router.callback_query(F.data == "admin_add_menu")
async def admin_add_menu_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    tomorrow = str(date.today() + timedelta(days=1))
    await state.set_state(AddMenu.waiting_items)
    await state.update_data(menu_date=tomorrow)
    await callback.answer()
    await callback.message.answer(
        f"🍽️ *Добавление меню на {tomorrow}*\\n\\n"
        "Отправьте блюда в формате (каждое с новой строки):\\n\\n"
        "`Плов с говядиной + салат + хлеб\\n"
        "Курица с рисом + салат + хлеб\\n"
        "Котлеты с пюре + салат + хлеб`\\n\\n"
        "Или отправьте в формате с ценой:\\n"
        "`Плов;35000\\nКурица;32000`",
        parse_mode="Markdown"
    )


@router.message(AddMenu.waiting_items)
async def process_menu_items(message: Message, state: FSMContext):
    data = await state.get_data()
    menu_date = data["menu_date"]
    lines = message.text.strip().split("\\n")

    items = []
    for i, line in enumerate(lines, 1):
        if ";" in line:
            parts = line.split(";")
            name = parts[0].strip()
            price = int(parts[1].strip()) if len(parts) > 1 else 35000
        else:
            name = line.strip()
            price = 35000

        if name:
            items.append({"item_number": i, "name": name, "price": price})

    if not items:
        await message.answer("❌ Не удалось распознать меню. Попробуйте снова.")
        return

    await set_menu(menu_date, items)
    await state.clear()

    text = f"✅ *Меню на {menu_date} добавлено:*\\n\\n"
    for item in items:
        text += f"{item['item_number']}. {item['name']} — {item['price']:,} сум\\n"

    await message.answer(text, parse_mode="Markdown", reply_markup=admin_keyboard())'''

new2 = '''@router.callback_query(F.data == "admin_add_menu")
async def admin_add_menu_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    tomorrow = str(date.today() + timedelta(days=1))
    await state.set_state(AddMenu.waiting_photo)
    await state.update_data(menu_date=tomorrow, items=[], item_number=1)
    await callback.answer()
    await callback.message.answer(
        f"🍽️ *Добавление меню на {tomorrow}*\\n\\n"
        f"*Блюдо 1:*\\n"
        "📸 Отправьте фото блюда:\\n"
        "_(или напишите 'нет' если фото нет)_",
        parse_mode="Markdown"
    )


@router.message(AddMenu.waiting_photo)
async def process_menu_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    
    if message.photo:
        photo_id = message.photo[-1].file_id
    else:
        photo_id = None

    await state.update_data(current_photo=photo_id)
    await state.set_state(AddMenu.waiting_name)
    await message.answer(
        f"✅ Фото принято!\\n\\n"
        f"📝 Введите *название блюда {data['item_number']}*:\\n"
        f"Например: _Плов с говядиной + салат + хлеб_",
        parse_mode="Markdown"
    )


@router.message(AddMenu.waiting_name)
async def process_menu_name(message: Message, state: FSMContext):
    await state.update_data(current_name=message.text.strip())
    await state.set_state(AddMenu.waiting_price)
    await message.answer(
        f"💰 Введите *цену* (в сумах):\\n"
        f"Например: _35000_\\n\\n"
        f"_(или напишите 'стандарт' для цены 35000 сум)_",
        parse_mode="Markdown"
    )


@router.message(AddMenu.waiting_price)
async def process_menu_price(message: Message, state: FSMContext):
    text = message.text.strip()
    if text.lower() == "стандарт":
        price = 35000
    else:
        try:
            price = int(text.replace(" ", "").replace(",", ""))
        except:
            await message.answer("❌ Введите число. Например: 35000")
            return

    data = await state.get_data()
    items = data.get("items", [])
    items.append({
        "item_number": data["item_number"],
        "name": data["current_name"],
        "price": price,
        "photo_id": data.get("current_photo")
    })
    await state.update_data(items=items)
    await state.set_state(AddMenu.waiting_more)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить ещё блюдо", callback_data="menu_add_more")
    builder.button(text="✅ Сохранить меню", callback_data="menu_save")
    builder.adjust(1)

    await message.answer(
        f"✅ *Блюдо {data['item_number']} добавлено:*\\n"
        f"🍱 {data['current_name']}\\n"
        f"💰 {price:,} сум\\n\\n"
        f"Добавить ещё блюдо или сохранить меню?",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data == "menu_add_more")
async def menu_add_more(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    next_num = data["item_number"] + 1
    await state.update_data(item_number=next_num)
    await state.set_state(AddMenu.waiting_photo)
    await callback.answer()
    await callback.message.answer(
        f"*Блюдо {next_num}:*\\n"
        f"📸 Отправьте фото блюда:\\n"
        f"_(или напишите 'нет' если фото нет)_",
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "menu_save")
async def menu_save(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    menu_date = data["menu_date"]
    items = data["items"]

    # Сохраняем в БД с photo_id
    import aiosqlite
    from config import DATABASE_URL
    async with aiosqlite.connect(DATABASE_URL) as db:
        await db.execute("DELETE FROM menus WHERE menu_date = ?", (menu_date,))
        for item in items:
            try:
                await db.execute("ALTER TABLE menus ADD COLUMN photo_id TEXT")
                await db.commit()
            except:
                pass
            await db.execute(
                """INSERT INTO menus (menu_date, item_number, name, price, photo_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (menu_date, item["item_number"], item["name"],
                 item["price"], item.get("photo_id"))
            )
        await db.commit()

    await state.clear()
    text = f"✅ *Меню на {menu_date} сохранено!*\\n\\n"
    for item in items:
        photo_text = "📸 с фото" if item.get("photo_id") else "без фото"
        text += f"{item['item_number']}. {item['name']} — {item['price']:,} сум ({photo_text})\\n"

    await callback.answer()
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=admin_keyboard())'''

code = code.replace(old2, new2)

with open("handlers/admin.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ admin.py обновлён!")

# Обновляем orders.py чтобы показывал фото
code2 = open("handlers/orders.py", "r", encoding="utf-8").read()

old3 = '''    text = f"🍽️ *Меню на {day_name}* ({tomorrow}):\\n\\n"
    for item in menu:
        text += f"{item['item_number']}. {item['name']}\\n"
        if item.get("description"):
            text += f"   _{item['description']}_\\n"
        text += f"   💰 {item['price']:,} сум\\n\\n"
    text += "🚚 Доставка бесплатно\\nВыберите блюдо:"

    await message.answer(text, parse_mode="Markdown", reply_markup=menu_keyboard(menu))'''

new3 = '''    # Если есть фото у первого блюда — отправляем меню с фото
    has_photos = any(item.get("photo_id") for item in menu)
    
    if has_photos:
        text = f"🍽️ *Меню на {day_name}* ({tomorrow}):\\n\\n"
        for item in menu:
            text += f"{item['item_number']}. {item['name']} — {item['price']:,} сум\\n"
        text += "\\n🚚 Доставка бесплатно\\nВыберите блюдо 👇"
        
        # Отправляем фото первого блюда с меню
        first_photo = next((i for i in menu if i.get("photo_id")), None)
        if first_photo:
            await message.answer_photo(
                photo=first_photo["photo_id"],
                caption=text,
                parse_mode="Markdown",
                reply_markup=menu_keyboard(menu)
            )
        else:
            await message.answer(text, parse_mode="Markdown", reply_markup=menu_keyboard(menu))
    else:
        text = f"🍽️ *Меню на {day_name}* ({tomorrow}):\\n\\n"
        for item in menu:
            text += f"{item['item_number']}. {item['name']}\\n"
            if item.get("description"):
                text += f"   _{item['description']}_\\n"
            text += f"   💰 {item['price']:,} сум\\n\\n"
        text += "🚚 Доставка бесплатно\\nВыберите блюдо:"
        await message.answer(text, parse_mode="Markdown", reply_markup=menu_keyboard(menu))'''

code2 = code2.replace(old3, new3)

with open("handlers/orders.py", "w", encoding="utf-8") as f:
    f.write(code2)

print("✅ orders.py обновлён — меню с фото!")