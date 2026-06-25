"""Проверяет подпись с РЕАЛЬНЫМИ данными последней неудачной транзакции"""
import hashlib
import os

CLICK_SECRET_KEY = os.getenv("CLICK_SECRET_KEY")

# Точные данные из последнего лога [PREPARE] Received
click_trans_id = "3749862958"
service_id = "105165"
merchant_trans_id = "balance_1_1000"
amount = "1000"
action = "0"
sign_time = "2026-06-25 13:31:38"
received_sign = "fe8a84e7bcc5c52c10cc116ca961b11f"

# Вариант A: текущий код (все как строки в f-string)
my_sign_a = hashlib.md5(
    f"{click_trans_id}{service_id}{CLICK_SECRET_KEY}{merchant_trans_id}{amount}{action}{sign_time}".encode()
).hexdigest()

# Вариант B: amount как float (на случай если документация ожидает float формат типа 1000.0)
amount_float = float(amount)
my_sign_b = hashlib.md5(
    f"{click_trans_id}{service_id}{CLICK_SECRET_KEY}{merchant_trans_id}{amount_float}{action}{sign_time}".encode()
).hexdigest()

print("CLICK_SECRET_KEY:", repr(CLICK_SECRET_KEY))
print()
print("Вариант A (amount как строка '1000'):", my_sign_a)
print("Вариант B (amount как float 1000.0):  ", my_sign_b)
print("Received:                              ", received_sign)
print()
print("A match:", my_sign_a == received_sign)
print("B match:", my_sign_b == received_sign)
