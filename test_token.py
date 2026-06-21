"""
Тест проверки initData с реальным токеном из переменной окружения.
Выполнить в Render Shell: python3 test_token.py
"""
import hashlib
import hmac
import os
from urllib.parse import parse_qsl

BOT_TOKEN = os.getenv("BOT_TOKEN")
print("BOT_TOKEN из окружения (длина):", len(BOT_TOKEN) if BOT_TOKEN else "ПУСТО")
print("BOT_TOKEN первые 10 символов:", BOT_TOKEN[:10] if BOT_TOKEN else "—")
print("BOT_TOKEN содержит пробелы:", " " in BOT_TOKEN if BOT_TOKEN else "—")
print("BOT_TOKEN содержит переносы строк:", "\n" in BOT_TOKEN if BOT_TOKEN else "—")

init_data = "query_id=AAF5DK5QAwAAAHkMrlBHjooS&user=%7B%22id%22%3A7796034681%2C%22first_name%22%3A%22AbdulAziz%22%2C%22last_name%22%3A%22%22%2C%22language_code%22%3A%22ru%22%2C%22allows_write_to_pm%22%3Atrue%2C%22photo_url%22%3A%22https%3A%5C%2F%5C%2Ft.me%5C%2Fi%5C%2Fuserpic%5C%2F320%5C%2FFy4qGQYgnl9vZ0WHVYBFdVDF2vzkHmzp1WBPxZCfn5m3BHMiJI9VszPYQx11ntKn.svg%22%7D&auth_date=1782043138&signature=sK7xo8-_3T0o3CdPIx0QFo_-jAwjrv_w7RNK3UAsBdhetrHiYXnY5AENn7SLyrMTLn6y_DmLzdiAJG_JXhubCA&hash=0888f892c14a15f55564decea71011e687d435fd51cb1c4807b5f09a50c8bd67"

parsed = dict(parse_qsl(init_data))
received_hash = parsed.pop("hash", None)
parsed.pop("signature", None)

data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))

secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

print("\nComputed hash:", computed_hash)
print("Received hash:", received_hash)
print("Match:", computed_hash == received_hash)
