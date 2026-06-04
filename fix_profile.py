code = open("handlers/profile.py", "r", encoding="utf-8").read()

old = '''    for milestone in milestones:
        reward = LOYALTY_LEVELS[milestone]["reward"]
        if total_orders >= milestone:
            text += f"✅ {milestone} заказов — {reward}\\n"
        else:
            remaining = milestone - total_orders
            text += f"⬜ {milestone} заказов — {reward} (ещё {remaining})\\n"'''

new = '''    for milestone in milestones:
        reward = LOYALTY_LEVELS[milestone]["reward"]
        if total_orders >= milestone:
            text += f"✅ {milestone} заказов — {reward}\\n"
        else:
            remaining = milestone - total_orders
            text += f"🔘 {milestone} заказов — {reward} (ещё {remaining})\\n"'''

code = code.replace(old, new)

with open("handlers/profile.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ Готово!")