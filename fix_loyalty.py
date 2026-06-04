# Обновляем config.py - новая система баллов
config = open("config.py", "r", encoding="utf-8").read()

old = '''# Система лояльности
LOYALTY_LEVELS = {
    5:  {"reward": "Напиток 🥤",     "points": 10},
    10: {"reward": "Десерт 🍰",      "points": 25},
    20: {"reward": "Бесплатный обед 🍱", "points": 50},
    30: {"reward": "Статус VIP 👑",  "points": 100},
}

COMPANY_STATUSES = {
    0:   "Новая компания 🆕",
    50:  "Бронзовая компания 🥉",
    100: "Серебряная компания 🥈",
    200: "Золотая компания 🥇",
}'''

new = '''# Система лояльности (баллы не сгорают!)
LOYALTY_LEVELS = {
    50:  {"reward": "Напиток 🥤"},
    100: {"reward": "Десерт 🍰"},
    200: {"reward": "Бесплатный обед 🍱"},
    500: {"reward": "Статус VIP 👑"},
}

COMPANY_STATUSES = {
    0:   "Новая компания 🆕",
    50:  "Бронзовая компания 🥉",
    100: "Серебряная компания 🥈",
    200: "Золотая компания 🥇",
}'''

config = config.replace(old, new)

with open("config.py", "w", encoding="utf-8") as f:
    f.write(config)

print("✅ config.py обновлён!")

# Обновляем profile.py - убираем серию, обновляем лояльность
code = open("handlers/profile.py", "r", encoding="utf-8").read()

old2 = '''def get_loyalty_progress(total_orders: int) -> str:
    milestones = sorted(LOYALTY_LEVELS.keys())
    text = ""
    for milestone in milestones:
        reward = LOYALTY_LEVELS[milestone]["reward"]
        if total_orders >= milestone:
            text += f"✅ {milestone} заказов — {reward}\\n"
        else:
            remaining = milestone - total_orders
            text += f"🔘 {milestone} заказов — {reward} (ещё {remaining})\\n"
    return text'''

new2 = '''def get_loyalty_progress(points: int) -> str:
    milestones = sorted(LOYALTY_LEVELS.keys())
    text = ""
    for milestone in milestones:
        reward = LOYALTY_LEVELS[milestone]["reward"]
        if points >= milestone:
            text += f"✅ {milestone} баллов — {reward} *(получено!)*\\n"
        else:
            remaining = milestone - points
            text += f"🔘 {milestone} баллов — {reward} (ещё {remaining})\\n"
    return text'''

code = code.replace(old2, new2)

old3 = '''    loyalty_text = get_loyalty_progress(user['total_orders'])
    next_milestone = next(
        (m for m in sorted(LOYALTY_LEVELS.keys()) if m > user['total_orders']), None
    )
    next_text = f"До следующей награды: {next_milestone - user['total_orders']} заказов" if next_milestone else "🎉 Все награды получены!"

    await message.answer(
        f"👤 *{user['full_name']}*\\n"
        f"🏅 Статус: {user['status']}\\n"
        f"🏢 Компания: {user.get('company_name', 'Не указана')}\\n\\n"
        f"📦 Заказов в этом месяце: {user['total_orders']}\\n"
        f"💰 Баллы: {user['points']}\\n"
        f"🔥 Серия: {user['streak_days']} дней подряд\\n\\n"
        f"🎯 *Система лояльности:*\\n{loyalty_text}\\n"
        f"📍 {next_text}\\n\\n"
        f"🔑 Ваш код: `{user['referral_code']}`",
        parse_mode="Markdown"
    )'''

new3 = '''    loyalty_text = get_loyalty_progress(user['points'])
    next_milestone = next(
        (m for m in sorted(LOYALTY_LEVELS.keys()) if m > user['points']), None
    )
    next_text = f"До следующей награды: *{next_milestone - user['points']} баллов*" if next_milestone else "🎉 Все награды получены!"

    await message.answer(
        f"👤 *{user['full_name']}*\\n"
        f"🏅 Статус: {user['status']}\\n"
        f"🏢 Компания: {user.get('company_name', 'Не указана')}\\n\\n"
        f"📦 Заказов: {user['total_orders']}\\n"
        f"💰 Баллы: *{user['points']}*\\n\\n"
        f"🎯 *Система лояльности:*\\n{loyalty_text}\\n"
        f"📍 {next_text}\\n\\n"
        f"🔑 Ваш код: `{user['referral_code']}`",
        parse_mode="Markdown"
    )'''

code = code.replace(old3, new3)

with open("handlers/profile.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ profile.py обновлён!")

# Обновляем orders.py - убираем серию из сообщения о заказе
code2 = open("handlers/orders.py", "r", encoding="utf-8").read()

old4 = '''        f"💰 Баллы: {user['points']} (+5)\\n"
        f"📦 Всего заказов: {user['total_orders']}\\n"
        f"🔥 Серия: {user['streak_days']} дней подряд"'''

new4 = '''        f"💰 Баллы: *{user['points']}* (+5)\\n"
        f"📦 Всего заказов: {user['total_orders']}"'''

code2 = code2.replace(old4, new4)

with open("handlers/orders.py", "w", encoding="utf-8") as f:
    f.write(code2)

print("✅ orders.py обновлён!")

# Обновляем уведомление о наградах в orders.py
code3 = open("handlers/orders.py", "r", encoding="utf-8").read()

old5 = '''    # Проверяем награду за количество заказов
    reward_text = ""
    total = user["total_orders"]
    if total == 5:
        reward_text = "\\n🎁 *Поздравляем! Вы заработали Напиток!*"
    elif total == 10:
        reward_text = "\\n🎁 *Поздравляем! Вы заработали Десерт!*"
    elif total == 20:
        reward_text = "\\n🎁 *Поздравляем! Вы заработали Бесплатный обед!*"
    elif total == 30:
        reward_text = "\\n👑 *Поздравляем! Вы получили статус VIP!*"'''

new5 = '''    # Проверяем награду по баллам
    reward_text = ""
    points = user["points"]
    if points >= 500:
        reward_text = "\\n👑 *Поздравляем! Вы достигли статуса VIP!*"
    elif points >= 200:
        reward_text = "\\n🍱 *Поздравляем! Вы заработали Бесплатный обед!*"
    elif points >= 100:
        reward_text = "\\n🍰 *Поздравляем! Вы заработали Десерт!*"
    elif points >= 50:
        reward_text = "\\n🥤 *Поздравляем! Вы заработали Напиток!*"'''

code3 = code3.replace(old5, new5)

with open("handlers/orders.py", "w", encoding="utf-8") as f:
    f.write(code3)

print("✅ Система лояльности обновлена!")