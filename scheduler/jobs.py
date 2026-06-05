import logging
from datetime import date, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot

from database.db import (
    get_menu, get_all_users_for_notification,
    get_today_order, close_orders_for_date, get_daily_summary
)
from config import ADMIN_IDS

logger = logging.getLogger(__name__)


async def send_menu_notification(bot: Bot):
    """10:00 — рассылка меню на завтра"""
    tomorrow = str(date.today() + timedelta(days=1))
    menu = await get_menu(tomorrow)

    if not menu:
        logger.warning(f"Меню на {tomorrow} не добавлено!")
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"⚠️ Меню на {tomorrow} не добавлено!\n"
                    "Добавьте через 🔧 Админ панель → Добавить меню"
                )
            except Exception:
                pass
        return

    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    d = date.fromisoformat(tomorrow)
    day_name = days[d.weekday()]

    text = f"🍽️ *Меню на {day_name}* ({tomorrow}):\n\n"
    for item in menu:
        text += f"{item['item_number']}. {item['name']}\n"
    text += f"\n💰 Цена: {menu[0]['price']:,} сум | 🚚 Доставка бесплатно\n"
    text += "\nНажмите *🍱 Заказать обед* чтобы выбрать блюдо!\n"
    text += "⏰ Заказы принимаются до *20:00*"

    users = await get_all_users_for_notification()
    sent = 0
    for user_id in users:
        try:
            await bot.send_message(user_id, text, parse_mode="Markdown")
            sent += 1
        except Exception as e:
            logger.warning(f"Не удалось отправить меню пользователю {user_id}: {e}")

    logger.info(f"✅ Меню отправлено {sent}/{len(users)} пользователям")


async def send_reminder_notification(bot: Bot):
    """16:00 — напоминание тем, кто не заказал"""
    tomorrow = str(date.today() + timedelta(days=1))
    users = await get_all_users_for_notification()
    sent = 0

    for user_id in users:
        order = await get_today_order(user_id, tomorrow)
        if not order:
            try:
                await bot.send_message(
                    user_id,
                    "⏰ *Напоминание!*\n\n"
                    "Вы ещё не заказали обед на завтра.\n"
                    "Осталось всего 4 часа — заказы закрываются в *20:00*!\n\n"
                    "👇 Нажмите *🍱 Заказать обед*",
                    parse_mode="Markdown"
                )
                sent += 1
            except Exception:
                pass

    logger.info(f"✅ Напоминание отправлено {sent} пользователям")


async def close_orders_notification(bot: Bot):
    """20:00 — закрытие заказов"""
    tomorrow = str(date.today() + timedelta(days=1))

    # Закрываем заказы
    await close_orders_for_date(tomorrow)

    # Итоговая сводка для администраторов
    summary = await get_daily_summary(tomorrow)

    text = f"🔒 *Заказы на {tomorrow} закрыты!*\n\n"
    if summary["items"]:
        text += "📊 *Сводка для кухни:*\n"
        for item in summary["items"]:
            text += f"• {item['name']}: {item['count']} порций\n"
        text += f"\n📦 Итого: *{summary['total']} обедов*"
    else:
        text += "❌ Заказов нет"

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="Markdown")
        except Exception:
            pass

    logger.info(f"✅ Заказы закрыты. Всего: {summary['total']}")


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")

    # 10:00 — рассылка меню
    scheduler.add_job(
        send_menu_notification,
        trigger=CronTrigger(hour=10, minute=0),
        args=[bot],
        id="send_menu",
        replace_existing=True
    )

    # 16:00 — напоминание
    scheduler.add_job(
        send_reminder_notification,
        trigger=CronTrigger(hour=16, minute=0),
        args=[bot],
        id="send_reminder",
        replace_existing=True
    )

    # 20:00 — закрытие заказов
    scheduler.add_job(
        close_orders_notification,
        trigger=CronTrigger(hour=20, minute=0),
        args=[bot],
        id="close_orders",
        replace_existing=True
    )

    logger.info("✅ Планировщик настроен (10:00, 16:00, 20:00 по Ташкенту)")
    return scheduler
