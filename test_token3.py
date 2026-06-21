"""Проверка токена байт-за-байтом на скрытые Unicode символы"""
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
print("Длина строки:", len(BOT_TOKEN))
print("Длина в байтах (UTF-8):", len(BOT_TOKEN.encode('utf-8')))
print()
print("Байтовое представление:")
print(BOT_TOKEN.encode('utf-8'))
print()
print("Все символы с unicode-кодами:")
for i, c in enumerate(BOT_TOKEN):
    code = ord(c)
    if code > 127:
        print(f"  НЕ-ASCII символ на позиции {i}: {repr(c)} U+{code:04X}")
print("Если выше ничего не выведено - все символы ASCII, это нормально")
