# Добавляем выбор дня в admin.py
code = open("handlers/admin.py", "r", encoding="utf-8").read()

old = '''@router.callback_query(F.data == "admin_add_menu")
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
    )'''

new = '''@router.callback_query(F.data == "admin_add_menu")
async def admin_add_menu_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from datetime import timedelta
    builder = InlineKeyboardBuilder()
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    today = date.today()
    for i in range(7):
        d = today + timedelta(days=i)
        label = "Сегодня" if i == 0 else "Завтра" if i == 1 else days[d.weekday()]
        builder.button(text=f"📅 {label} ({d.strftime('%d.%m')})", callback_data=f"menu_date_{d}")
    builder.adjust(2)
    await callback.answer()
    await callback.message.edit_text(
        "🍽️ *Добавление меню*\\n\\nВыберите день:",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("menu_date_"))
async def admin_menu_date_selected(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    menu_date = callback.data.replace("menu_date_", "")
    await state.set_state(AddMenu.waiting_photo)
    await state.update_data(menu_date=menu_date, items=[], item_number=1)
    await callback.answer()
    await callback.message.answer(
        f"🍽️ *Добавление меню на {menu_date}*\\n\\n"
        f"*Блюдо 1:*\\n"
        "📸 Отправьте фото блюда:\\n"
        "_(или напишите 'нет' если фото нет)_",
        parse_mode="Markdown"
    )'''

code = code.replace(old, new)

with open("handlers/admin.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ Готово!")