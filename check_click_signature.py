"""Проверяет вручную вычисление подписи Click с реальными данными из лога"""
import hashlib
import os

CLICK_SECRET_KEY = os.getenv("CLICK_SECRET_KEY")

# Данные из последнего лога
click_trans_id = "3749840404"
service_id = "105165"
merchant_trans_id = "balance_1_1000"
amount = "1000"
action = 0
sign_time = "2026-06-25 13:17:59"
received_sign = "ef6c0d4e8a7ee9c71c21ed5152553d38"

my_sign = hashlib.md5(
    f"{click_trans_id}{service_id}{CLICK_SECRET_KEY}{merchant_trans_id}{amount}{action}{sign_time}".encode()
).hexdigest()

print("CLICK_SECRET_KEY установлен:", bool(CLICK_SECRET_KEY))
print("CLICK_SECRET_KEY длина:", len(CLICK_SECRET_KEY) if CLICK_SECRET_KEY else 0)
print()
print("Computed sign:", my_sign)
print("Received sign:", received_sign)
print("Match:", my_sign == received_sign)
