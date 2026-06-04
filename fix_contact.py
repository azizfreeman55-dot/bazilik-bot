code = open("handlers/analytics.py", "r", encoding="utf-8").read()

old = '''            COALESCE(c.address, 'Адрес не указан') as address,
            COALESCE(c.contact, 'Контакт не указан') as contact'''

new = '''            COALESCE(c.address, 'Адрес не указан') as address'''

code = code.replace(old, new)

old2 = '''            text += f"   📞 {r['contact']}\\\\n"
            text += f"   🗺 [Открыть карту]({maps_link})\\\\n\\\\n"'''

new2 = '''            text += f"   🗺 [Открыть карту]({maps_link})\\\\n\\\\n"'''

code = code.replace(old2, new2)

with open("handlers/analytics.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ Готово!")