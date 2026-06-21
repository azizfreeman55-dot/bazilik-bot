"""
Тест с использованием готовой библиотеки init-data-py вместо самописного кода.
Сначала установите библиотеку в Render Shell:
    pip install init-data-py --break-system-packages

Затем выполните:
    python3 test_with_library.py
"""
import os

try:
    from init_data_py import InitData
except ImportError:
    print("Библиотека не установлена. Выполните:")
    print("pip install init-data-py --break-system-packages")
    exit(1)

BOT_TOKEN = os.getenv("BOT_TOKEN")

# Вставьте сюда самые свежие данные initData из debug_widget.html
raw_init_data = "user=%7B%22id%22%3A7796034681%2C%22first_name%22%3A%22AbdulAziz%22%2C%22last_name%22%3A%22%22%2C%22language_code%22%3A%22ru%22%2C%22allows_write_to_pm%22%3Atrue%2C%22photo_url%22%3A%22https%3A%5C%2F%5C%2Ft.me%5C%2Fi%5C%2Fuserpic%5C%2F320%5C%2FFy4qGQYgnl9vZ0WHVYBFdVDF2vzkHmzp1WBPxZCfn5m3BHMiJI9VszPYQx11ntKn.svg%22%7D&chat_instance=-4333018823323661791&chat_type=sender&auth_date=1782050565&signature=kWmKLDwEs-VyunYQJd3OUguYkuq52si9KRofMzUP6kmgQ7AKjE6dgmp9eyKhU9yjM3vyLDQ5MoWHRFIcSTsKCw&hash=741ba797e452391ffbb8a988ccda7ac7eb76a8a3cc8aba33173e74f8e8dca127"

print("Используем BOT_TOKEN:", BOT_TOKEN[:15] + "...")
print()

try:
    init_data = InitData.parse(raw_init_data)
    print("Parsed успешно:", init_data)
    print()
    is_valid = init_data.validate(BOT_TOKEN)
    print("Validate result:", is_valid)
except Exception as e:
    print("Ошибка:", type(e).__name__, str(e))
