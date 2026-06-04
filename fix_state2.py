code = open("handlers/registration.py", "r", encoding="utf-8").read()

old = "await state.set_state(Registration.waiting_address)"
new = "await state.set_state(Registration.waiting_location)"

code = code.replace(old, new)

with open("handlers/registration.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ Готово!")