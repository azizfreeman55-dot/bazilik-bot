# Обновляем клавиатуру
code = open("keyboards/keyboards.py", "r", encoding="utf-8").read()

old = '''def main_menu_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="🍱 Заказать обед"), KeyboardButton(text="📋 Мой заказ")],
        [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="🏆 Рейтинг")],
        [KeyboardButton(text="👥 Пригласить коллегу"), KeyboardButton(text="⚙️ Настройки")],
    ]
    if is_admin:
        buttons.append([KeyboardButton(text="🔧 Админ панель")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)'''

new = '''def main_menu_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="🍽️ Заказать обед"), KeyboardButton(text="📝 Мой заказ")],
        [KeyboardButton(text="🪪 Мой профиль"), KeyboardButton(text="🏆 Рейтинг")],
        [KeyboardButton(text="👥 Пригласить коллегу"), KeyboardButton(text="⚙️ Настройки")],
    ]
    if is_admin:
        buttons.append([KeyboardButton(text="🖥️ Админ панель")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)'''

code = code.replace(old, new)

with open("keyboards/keyboards.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ keyboards.py обновлён!")

# Обновляем все хендлеры где используются старые эмодзи
files = [
    "handlers/orders.py",
    "handlers/profile.py", 
    "handlers/admin.py",
    "handlers/analytics.py",
]

replacements = [
    ("🍱 Заказать обед", "🍽️ Заказать обед"),
    ("📋 Мой заказ", "📝 Мой заказ"),
    ("👤 Мой профиль", "🪪 Мой профиль"),
    ("🔧 Админ панель", "🖥️ Админ панель"),
    ('F.text == "🔧 Админ панель"', 'F.text == "🖥️ Админ панель"'),
]

for filename in files:
    try:
        code = open(filename, "r", encoding="utf-8").read()
        for old, new in replacements:
            code = code.replace(old, new)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(code)
        print(f"✅ {filename} обновлён!")
    except Exception as e:
        print(f"❌ {filename}: {e}")