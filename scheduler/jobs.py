import logging
from datetime import date, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot

from database.db import (
    get_menu, get_all_users_for_notification,
    get_today_order, close_orders_for_date,
    get_daily_summary, create_order, get_pool
)
from config import ADMIN_IDS

logger = logging.getLogger(__name__)


async def send_menu_notification(bot: Bot):
    tomorrow = str(date.today() + timedelta(days=1))
    menu = await get_menu(tomorrow)

    if not menu:
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"⚠️ Меню на {tomorrow} не добавлено!\n"
                    "Добавьте через 🖥️ Админ панель → Добавить меню"
                )
            except Exception:
                pass
        return

    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    d = date.fromisoformat(tomorrow)
    day_name = days[d.weekday()]
    day_num = d.weekday()

    users = await get_all_users_for_notification()
    auto_ordered = await process_weekly_auto_orders(day_num, tomorrow, menu)

    for user_id in users:
        try:
            from database.db import get_user_lang
            lang = await get_user_lang(user_id)
            from langs import t

            text = f"{t(lang, 'menu_title')} {day_name}* ({tomorrow}):\n\n"
            for item in menu:
                text += f"{item['item_number']}. {item['name']} — {item['price']:,} сум\n"
            text += f"\n{t(lang, 'free_delivery')}\n{t(lang, 'choose_dish')}"

            if user_id in auto_ordered:
                item_num = auto_ordered[user_id]
                meal = next((m for m in menu if m["item_number"] == item_num), None)
                if meal:
                    text += f"\n\n🤖 *Автозаказ оформлен:* {meal['name']}"

            first_photo = next((i for i in menu if i.get("photo_id")), None)
            if first_photo:
                await bot.send_photo(
                    user_id,
                    photo=first_photo["photo_id"],
                    caption=text,
                    parse_mode="Markdown"
                )
            else:
                await bot.send_message(user_id, text, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Не удалось отправить меню {user_id}: {e}")

    logger.info(f"✅ Меню отправлено. Автозаказов: {len(auto_ordered)}")


async def process_weekly_auto_orders(day_num: int, order_date: str, menu: list) -> dict:
    auto_ordered = {}
    pool = await get_pool()
    async with pool.acquire() as db:
        weekly_users = await db.fetch(
            """SELECT u.telegram_id, w.menu_item
               FROM weekly_orders w
               JOIN users u ON w.user_id = u.id
               WHERE w.day_of_week = $1 AND w.is_active = 1""",
            day_num
        )

    for row in weekly_users:
        telegram_id = row["telegram_id"]
        item_num = row["menu_item"]
        existing = await get_today_order(telegram_id, order_date)
        if existing:
            continue
        menu_item = next((m for m in menu if m["item_number"] == item_num), None)
        if not menu_item:
            menu_item = menu[0]
        try:
            await create_order(telegram_id, menu_item["id"], order_date, is_auto=True)
            auto_ordered[telegram_id] = item_num
        except Exception as e:
            logger.error(f"Ошибка автозаказа для {telegram_id}: {e}")

    return auto_ordered


async def send_reminder_notification(bot: Bot):
    tomorrow = str(date.today() + timedelta(days=1))
    users = await get_all_users_for_notification()
    sent = 0

    for user_id in users:
        order = await get_today_order(user_id, tomorrow)
        if not order:
            try:
                from database.db import get_user_lang
                lang = await get_user_lang(user_id)
                from langs import t
                await bot.send_message(user_id, t(lang, "reminder"), parse_mode="Markdown")
                sent += 1
            except Exception:
                pass

    logger.info(f"✅ Напоминание отправлено {sent} пользователям")


async def close_orders_notification(bot: Bot):
    tomorrow = str(date.today() + timedelta(days=1))
    await close_orders_for_date(tomorrow)

    summary = await get_daily_summary(tomorrow)
    text = f"🔒 *Заказы на {tomorrow} закрыты!*\n\n"

    if summary["items"]:
        text += "📊 *Сводка для кухни:*\n"
        for item in summary["items"]:
            text += f"• {item['name']}: *{item['count']} порций*\n"
        text += f"\n📦 Итого: *{summary['total']} обедов*\n"
        text += f"💰 Выручка: *{summary['total'] * 35000:,} сум*"
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

    scheduler.add_job(
        send_menu_notification,
        trigger=CronTrigger(hour=10, minute=0),
        args=[bot], id="send_menu", replace_existing=True
    )
    scheduler.add_job(
        send_reminder_notification,
        trigger=CronTrigger(hour=16, minute=0),
        args=[bot], id="send_reminder", replace_existing=True
    )
    scheduler.add_job(
        close_orders_notification,
        trigger=CronTrigger(hour=20, minute=0),
        args=[bot], id="close_orders", replace_existing=True
    )

    logger.info("✅ Планировщик настроен (10:00, 16:00, 20:00 по Ташкенту)")
    return scheduler