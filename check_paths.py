"""Диагностика путей — выполнить в Render Shell: python3 check_paths.py"""
import os

print("Текущая директория (cwd):", os.getcwd())
print("Путь к этому файлу:", os.path.abspath(__file__))
print("Директория этого файла:", os.path.dirname(os.path.abspath(__file__)))
print()
print("Содержимое текущей директории:")
for f in sorted(os.listdir(".")):
    print(" -", f)
print()
webapp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp")
print("Ожидаемый путь к webapp:", webapp_path)
print("Существует ли:", os.path.isdir(webapp_path))
if os.path.isdir(webapp_path):
    print("Содержимое webapp/:", os.listdir(webapp_path))
