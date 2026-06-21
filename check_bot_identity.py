"""
Проверяет какой именно бот стоит за токеном BOT_TOKEN через Telegram API.
Выполнить в Render Shell: python3 check_bot_identity.py
"""
import os
import urllib.request
import json

BOT_TOKEN = os.getenv("BOT_TOKEN")
url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"

try:
    with urllib.request.urlopen(url, timeout=10) as response:
        data = json.loads(response.read())
        print("Ответ Telegram API:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
except Exception as e:
    print("Ошибка запроса:", e)
