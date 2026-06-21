"""Более глубокая проверка - выводим repr токена чтобы увидеть скрытые символы"""
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
print("repr(BOT_TOKEN):", repr(BOT_TOKEN))
print("Все символы с кодами:")
for i, c in enumerate(BOT_TOKEN):
    if not (c.isalnum() or c == ':' or c == '-' or c == '_'):
        print(f"  Позиция {i}: {repr(c)} (код {ord(c)})")
print("Проверка завершена - если выше ничего не выведено, скрытых символов нет")
