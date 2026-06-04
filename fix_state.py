code = open("handlers/registration.py", "r", encoding="utf-8").read()

old = "@router.message(Registration.waiting_address)"
new = "@router.message(Registration.waiting_location)"

code = code.replace(old, new)

with open("handlers/registration.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ Готово!")