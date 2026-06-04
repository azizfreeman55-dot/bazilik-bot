code = open("handlers/registration.py", "r", encoding="utf-8").read()

old = '''    builder.button(text="🇷🇺 Русский", callback_data="lang_ru")
    builder.button(text="🇺🇿 O\'zbekcha (lotin)", callback_data="lang_uz_latin")
    builder.button(text="🇺🇿 Ўзбекча (кирилл)", callback_data="lang_uz_cyrillic")'''

new = '''    builder.button(text="🇷🇺 Русский", callback_data="lang_ru")
    builder.button(text="🇺🇿 O\'zbekcha (lotin)", callback_data="lang_uz_latin")'''

code = code.replace(old, new)

with open("handlers/registration.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ Готово!")