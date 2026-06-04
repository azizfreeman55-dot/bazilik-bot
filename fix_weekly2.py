code = open("handlers/weekly.py", "r", encoding="utf-8").read()

old = '''def day_items_keyboard(day: int, current_item: int = None) -> object:
    builder = InlineKeyboardBuilder()
    for i in range(1, 4):
        check = "✅ " if current_item == i else ""
        builder.button(text=f"{check}Блюдо {i}", callback_data=f"weekly_set_{day}_{i}")
    if current_item:
        builder.button(text="🗑 Убрать этот день", callback_data=f"weekly_del_{day}")
    builder.button(text="◀️ Назад", callback_data="weekly_back_list")
    builder.adjust(1)
    return builder.as_markup()'''

new = '''def day_items_keyboard(day: int, menu_items: list, current_item: int = None) -> object:
    builder = InlineKeyboardBuilder()
    for item in menu_items:
        check = "✅ " if current_item == item["item_number"] else ""
        builder.button(
            text=f"{check}{item['item_number']}. {item['name']}",
            callback_data=f"weekly_set_{day}_{item['item_number']}"
        )
    if not menu_items:
        builder.button(text="❌ Меню не добавлено", callback_data="weekly_no_menu")
    if current_item:
        builder.button(text="🗑 Убрать этот день", callback_data=f"weekly_del_{day}")
    builder.button(text="◀️ Назад", callback_data="weekly_back_list")
    builder.adjust(1)
    return builder.as_markup()'''

code = code.replace(old, new)

old2 = '''@router.callback_query(F.data.startswith("weekly_day_"))
async def weekly_day_select(callback: CallbackQuery):
    day = int(callback.data.split("_")[2])
    day_name = DAYS_RU[day]
    user = await get_user(callback.from_user.id)
    weekly = await get_weekly_orders(user["id"])
    current = weekly.get(day)
    await callback.message.edit_text(
        f"📅 *{day_name}*\\n\\nВыберите блюдо:",
        parse_mode="Markdown",
        reply_markup=day_items_keyboard(day, current)
    )
    await callback.answer()'''

new2 = '''@router.callback_query(F.data.startswith("weekly_day_"))
async def weekly_day_select(callback: CallbackQuery):
    day = int(callback.data.split("_")[2])
    day_name = DAYS_RU[day]
    user = await get_user(callback.from_user.id)
    weekly = await get_weekly_orders(user["id"])
    current = weekly.get(day)

    # Находим ближайшую дату этого дня недели
    from datetime import date, timedelta
    today = date.today()
    days_ahead = (day - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    target_date = str(today + timedelta(days=days_ahead))

    menu_items = await get_menu(target_date)

    await callback.message.edit_text(
        f"📅 *{day_name}* ({target_date})\\n\\nВыберите блюдо:",
        parse_mode="Markdown",
        reply_markup=day_items_keyboard(day, menu_items, current)
    )
    await callback.answer()


@router.callback_query(F.data == "weekly_no_menu")
async def weekly_no_menu(callback: CallbackQuery):
    await callback.answer("❌ Меню на этот день ещё не добавлено!", show_alert=True)'''

code = code.replace(old2, new2)

with open("handlers/weekly.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ Готово!")