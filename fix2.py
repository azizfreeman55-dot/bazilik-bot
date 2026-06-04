# Исправляем create_user в db.py
code = open("database/db.py", "r", encoding="utf-8").read()

old = '''    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO users (telegram_id, full_name, username, company_id,
               referral_code, referred_by, points)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",'''

new = '''    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR IGNORE INTO users (telegram_id, full_name, username, company_id,
               referral_code, referred_by, points)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",'''

code = code.replace(old, new)

with open("database/db.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ db.py исправлен!")