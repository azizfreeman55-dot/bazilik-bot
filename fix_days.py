code = open("handlers/weekly.py", "r", encoding="utf-8").read()

old = '''DAYS_RU = {
    0: "Понедельник", 1: "Вторник", 2: "Среда",
    3: "Четверг", 4: "Пятница"
}'''

new = '''DAYS_RU = {
    0: "Понедельник", 1: "Вторник", 2: "Среда",
    3: "Четверг", 4: "Пятница", 5: "Суббота", 6: "Воскресенье"
}'''

code = code.replace(old, new)

with open("handlers/weekly.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ Готово!")