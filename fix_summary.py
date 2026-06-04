code = open("handlers/admin.py", "r", encoding="utf-8").read()

old = "AND o.status = 'confirmed'"
new = "AND o.status IN ('confirmed', 'pending')"

code = code.replace(old, new)

with open("handlers/admin.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ Готово!")