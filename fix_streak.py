# Убираем серию из регистрации и профиля
code = open("handlers/registration.py", "r", encoding="utf-8").read()
code = code.replace(
    "        f\"🔥 Серия: {user['streak_days']} дней подряд\\n\"",
    ""
)
with open("handlers/registration.py", "w", encoding="utf-8") as f:
    f.write(code)

# Убираем серию из БД запроса
code2 = open("database/db.py", "r", encoding="utf-8").read()
code2 = code2.replace(
    """               streak_days = CASE
                   WHEN last_order_date = date('now', '-1 day') THEN streak_days + 1
                   ELSE 1
               END""",
    "               streak_days = 0"
)
with open("database/db.py", "w", encoding="utf-8") as f:
    f.write(code2)

print("✅ Серия убрана!")