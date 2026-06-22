import logging
from datetime import date, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot

from database.db import (
    get_menu, get_all_users_for_notification,
    get_today_order, close_orders_for_date,
    get_daily_summary, create_order, get_pool,
    get_orders_by_company, get_all_couriers, create_delivery_route
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
    """
    Закрывает заказы на завтра, отправляет сводку админам,
    и автоматически распределяет заказы по курьерам (round-robin).
    """
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

    # Автоматическое распределение по курьерам
    await auto_assign_couriers(bot, tomorrow)


async def auto_assign_couriers(bot: Bot, delivery_date: str):
    """
    Автоматически распределяет заказы (сгруппированные по компаниям)
    между активными курьерами равномерно (round-robin).
    Если курьер один — все компании достаются ему, как раньше.
    """
    companies = await get_orders_by_company(delivery_date)
    if not companies:
        logger.info("Автораспределение: заказов нет, пропускаем")
        return

    couriers = await get_all_couriers()
    if not couriers:
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"⚠️ Заказы на {delivery_date} закрыты, но нет ни одного "
                    f"зарегистрированного курьера! Распределите вручную через "
                    f"курьерский бот или зарегистрируйте курьера."
                )
            except Exception:
                pass
        return

    # Round-robin: компании раздаём по очереди каждому курьеру
    courier_assignments = {c["id"]: [] for c in couriers}
    for i, company in enumerate(companies):
        courier = couriers[i % len(couriers)]
        courier_assignments[courier["id"]].append(company)

    from aiogram import Bot as CourierBotImport
    import os
    courier_bot_token = os.getenv("COURIER_BOT_TOKEN")

    for courier in couriers:
        assigned_companies = courier_assignments[courier["id"]]
        if not assigned_companies:
            continue

        company_ids = [c["company_id"] for c in assigned_companies]
        await create_delivery_route(courier["id"], delivery_date, company_ids)

        total_orders = sum(c["order_count"] for c in assigned_companies)

        # Уведомляем курьера через КУРЬЕРСКИЙ бот (другой токен)
        if courier_bot_token:
            try:
                courier_bot = CourierBotImport(token=courier_bot_token)
                text = (
                    f"🚚 *Автоматически назначен маршрут на {delivery_date}!*\n\n"
                    f"📦 Компаний: {len(assigned_companies)}\n"
                    f"👥 Заказов: {total_orders}\n\n"
                )
                for i, c in enumerate(assigned_companies, 1):
                    text += f"{i}. {c['company_name']} — {c['order_count']} зак.\n"
                    if c.get("address"):
                        text += f"   📍 {c['address']}\n"
                text += "\nОткройте '🗺 Мой маршрут' для начала работы."

                await courier_bot.send_message(
                    courier["telegram_id"], text, parse_mode="Markdown"
                )
                await courier_bot.session.close()
            except Exception as e:
                logger.error(f"Не удалось уведомить курьера {courier['telegram_id']}: {e}")

    logger.info(
        f"✅ Автораспределение завершено: {len(companies)} компаний "
        f"между {len(couriers)} курьерами"
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🚚 *Заказы автоматически распределены по курьерам*\n\n"
                f"Курьеров: {len(couriers)}\n"
                f"Компаний: {len(companies)}",
                parse_mode="Markdown"
            )
        except Exception:
            pass


async def send_birthday_greetings(bot: Bot):
    """
    Каждый день в 9:00 поздравляет именинников и начисляет +50 баллов.
    Требует поля birthday (DATE) в таблице users.
    """
    pool = await get_pool()
    async with pool.acquire() as db:
        users = await db.fetch(
            """SELECT id, telegram_id, full_name, lang
               FROM users
               WHERE birthday IS NOT NULL
               AND EXTRACT(MONTH FROM birthday) = EXTRACT(MONTH FROM CURRENT_DATE)
               AND EXTRACT(DAY FROM birthday) = EXTRACT(DAY FROM CURRENT_DATE)"""
        )

    if not users:
        return

    logger.info(f"🎂 Именинников сегодня: {len(users)}")

    for user in users:
        try:
            lang = user["lang"] or "ru"
            name = user["full_name"] or ("Дорогой клиент" if lang == "ru" else "Hurmatli mijoz")

            async with pool.acquire() as db:
                await db.execute(
                    "UPDATE users SET points = points + 50 WHERE id = $1",
                    user["id"]
                )
                await db.execute(
                    """INSERT INTO balance_transactions (user_id, amount, type, description)
                       VALUES ($1, 50, 'credit', $2)""",
                    user["id"],
                    "🎂 Подарок в день рождения" if lang == "ru" else "🎂 Tug'ilgan kun sovg'asi"
                )

            if lang == "uz":
                text = (
                    f"🎂 *Tug'ilgan kuningiz bilan, {name}!*\n\n"
                    f"Bazilik Catering jamoasi sizni tabriklayman! 🎉\n\n"
                    f"🎁 Sovg'a sifatida *+50 ball* hisobingizga qo'shildi!\n\n"
                    f"Sizga sog'lik, baxt va mazali tushliklar tilaymiz! 🍱"
                )
            else:
                text = (
                    f"🎂 *С Днём Рождения, {name}!*\n\n"
                    f"Команда Bazilik Catering поздравляет вас! 🎉\n\n"
                    f"🎁 В подарок вам начислено *+50 баллов*!\n\n"
                    f"Желаем здоровья, счастья и вкусных обедов! 🍱"
                )

            await bot.send_message(user["telegram_id"], text, parse_mode="Markdown")
            logger.info(f"🎂 Поздравление отправлено: {user['telegram_id']}")

        except Exception as e:
            logger.error(f"Birthday error for {user['telegram_id']}: {e}")


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")

    scheduler.add_job(
        send_birthday_greetings,
        trigger=CronTrigger(hour=9, minute=0),
        args=[bot], id="birthday_greetings", replace_existing=True
    )
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

    logger.info(
        "✅ Планировщик настроен (09:00 ДР, 10:00 меню, 16:00 напоминание, "
        "20:00 закрытие + автораспределение курьерам)"
    )
    return scheduler
