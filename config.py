import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "123456789").split(",")))
DATABASE_URL = os.getenv("DATABASE_URL", "lunch_bot.db")

# Время работы системы
MENU_SEND_TIME = "10:00"       # Отправка меню
REMINDER_TIME = "16:00"        # Напоминание
ORDER_CLOSE_TIME = "23:59"     # Закрытие заказов
DELIVERY_START = "12:00"       # Начало доставки
DELIVERY_END = "13:00"         # Конец доставки

# Система лояльности (баллы не сгорают!)
LOYALTY_LEVELS = {
    50:  {"reward": "Напиток 🥤"},
    100: {"reward": "Десерт 🍰"},
    200: {"reward": "Бесплатный обед 🍱"},
    500: {"reward": "Статус VIP 👑"},
}

COMPANY_STATUSES = {
    0:   "Новая компания 🆕",
    50:  "Бронзовая компания 🥉",
    100: "Серебряная компания 🥈",
    200: "Золотая компания 🥇",
}

# Реферальная программа
REFERRAL_BONUS_INVITER = 5    # Баллов за приглашение
REFERRAL_BONUS_INVITED = 10   # Баллов новому пользователю (напиток при первом заказе)
# Click настройки
CLICK_SERVICE_ID = os.getenv("CLICK_SERVICE_ID")
CLICK_MERCHANT_ID = os.getenv("CLICK_MERCHANT_ID")
CLICK_SECRET_KEY = os.getenv("CLICK_SECRET_KEY")
CLICK_MERCHANT_USER_ID = os.getenv("CLICK_MERCHANT_USER_ID")
