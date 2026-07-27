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
    today = str(date.today())
    day_num = date.today().weekday()

    menu = await get_menu(today)
    if not menu:
        # Меню на сегодня нет — попробуем из weekly_menu
        from database.db import get_weekly_menu
        menu = await get_weekly_menu(day_num)

    if not menu:
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"⚠️ Меню на {today} не добавлено!\n"
                    "Добавьте через 🖥️ Админ панель → Добавить меню"
                )
            except Exception:
                pass
        return

    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    day_name = days[day_num]

    users = await get_all_users_for_notification()

    for user_id in users:
        try:
            from database.db import get_user_lang
            lang = await get_user_lang(user_id)
            from langs import t

            if lang and lang.startswith("uz"):
                text = (
                    f"🌅 *Bugun ({today}) — {day_name}*\n\n"
                    f"Buyurtmalar qabul qilinmoqda!\n"
                    f"⏰ 07:00 dan 15:00 gacha\n"
                    f"🚚 Yetkazib berish ~45 daqiqa\n\n"
                )
            else:
                text = (
                    f"🌅 *Сегодня ({today}) — {day_name}*\n\n"
                    f"Принимаем заказы прямо сейчас!\n"
                    f"⏰ с 07:00 до 15:00\n"
                    f"🚚 Доставка ~45 минут\n\n"
                )

            for item in menu[:5]:  # показываем первые 5 позиций
                text += f"• {item['name']} — {item['price']:,} сум\n"
            if len(menu) > 5:
                text += f"...и ещё {len(menu) - 5} позиций в Mini App\n"

            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            builder = InlineKeyboardBuilder()
            builder.button(
                text="🍽️ Открыть меню" if not (lang and lang.startswith("uz")) else "🍽️ Menyuni ochish",
                web_app={"url": "https://bazilik-webhook.onrender.com/webapp/index.html"}
            )
            await bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=builder.as_markup())
        except Exception as e:
            logger.warning(f"Не удалось уведомить {user_id}: {e}")

    logger.info(f"✅ Утреннее уведомление отправлено")

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
                ordered_names = auto_ordered[user_id]
                names_text = ", ".join(ordered_names)
                text += f"\n\n🤖 *Автозаказ оформлен:* {names_text}"

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
    """
    Создаёт автозаказы по расписанию weekly_orders.
    Клиент может выбрать блюдо в НЕСКОЛЬКИХ категориях на один день
    (например блюдо + салат + напиток) — для каждой выбранной категории
    создаётся отдельная позиция заказа.
    """
    auto_ordered = {}
    pool = await get_pool()
    async with pool.acquire() as db:
        weekly_users = await db.fetch(
            """SELECT u.telegram_id, w.menu_item, w.category
               FROM weekly_orders w
               JOIN users u ON w.user_id = u.id
               WHERE w.day_of_week = $1 AND w.is_active = 1
               AND w.category != 'main'
               AND u.auto_order = 1""",
            day_num
        )

    # Группируем по клиенту — у одного клиента может быть несколько строк
    # (одна на каждую категорию: main, salad, dessert, drink)
    by_client = {}
    for row in weekly_users:
        by_client.setdefault(row["telegram_id"], []).append(
            {"item_number": row["menu_item"], "category": row["category"]}
        )

    for telegram_id, selections in by_client.items():
        existing = await get_today_order(telegram_id, order_date)
        if existing:
            continue

        ordered_names = []
        for sel in selections:
            category = sel["category"]
            item_num = sel["item_number"]

            # Получаем актуальное меню именно этой категории на эту дату
            category_menu = await get_menu(order_date, category)
            menu_item = next((m for m in category_menu if m["item_number"] == item_num), None)
            if not menu_item:
                continue

            try:
                await create_order(telegram_id, menu_item["id"], order_date, is_auto=True)
                ordered_names.append(menu_item["name"])
            except Exception as e:
                logger.error(f"Ошибка автозаказа для {telegram_id} ({category}): {e}")

        if ordered_names:
            auto_ordered[telegram_id] = ordered_names

    return auto_ordered


async def send_reminder_notification(bot: Bot):
    tomorrow = str(date.today() + timedelta(days=1))
    pool = await get_pool()
    async with pool.acquire() as db:
        users_with_pref = await db.fetch(
            "SELECT telegram_id, lang FROM users WHERE notify_reminder = 1"
        )
    sent = 0

    for row in users_with_pref:
        user_id = row["telegram_id"]
        order = await get_today_order(user_id, tomorrow)
        if not order:
            try:
                lang = row["lang"] or "ru"
                from langs import t
                await bot.send_message(user_id, t(lang, "reminder"), parse_mode="Markdown")
                sent += 1
            except Exception:
                pass

    logger.info(f"✅ Напоминание отправлено {sent} пользователям")


async def close_orders_notification(bot: Bot):
    """
    15:00 — закрывает приём заказов на сегодня,
    отправляет сводку для кухни и курьеров.
    """
    today = str(date.today())
    await close_orders_for_date(today)

    summary = await get_daily_summary(today)
    text = f"🔒 *Приём заказов закрыт ({today})*\n\n"

    if summary["items"]:
        text += "📊 *Сводка для кухни:*\n"
        for item in summary["items"]:
            text += f"• {item['name']}: *{item['count']} порций*\n"
        text += f"\n📦 Итого: *{summary['total']} заказов*"
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
        total_clients = sum(c.get("client_count", c["order_count"]) for c in assigned_companies)

        # Уведомляем курьера через КУРЬЕРСКИЙ бот (другой токен)
        if courier_bot_token:
            try:
                courier_bot = CourierBotImport(token=courier_bot_token)
                text = (
                    f"🚚 *Автоматически назначен маршрут на {delivery_date}!*\n\n"
                    f"📦 Компаний: {len(assigned_companies)}\n"
                    f"👥 Клиентов: {total_clients} | Позиций: {total_orders}\n\n"
                )
                for i, c in enumerate(assigned_companies, 1):
                    client_count = c.get("client_count", c["order_count"])
                    text += f"{i}. {c['company_name']} — {client_count} кл., {c['order_count']} поз.\n"
                    if c.get("address"):
                        text += f"   📍 {c['address']}\n"
                text += "\n📍 Порядок точек оптимизирован по расстоянию.\nОткройте '🗺 Мой маршрут' для начала работы."

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


async def award_company_of_month(bot: Bot):
    """
    1-го числа каждого месяца в 9:30 — находит компанию-лидера прошлого
    месяца по количеству заказов, начисляет +50 баллов всем её сотрудникам.
    """
    from database.db import calculate_and_award_company_of_month

    today = date.today()
    if today.day != 1:
        return  # запускается строго 1-го числа

    prev_month = today.replace(day=1) - timedelta(days=1)
    prev_month_year = prev_month.strftime("%Y-%m")

    result = await calculate_and_award_company_of_month(prev_month_year)
    if not result:
        logger.info(f"Компания месяца за {prev_month_year}: нет данных или уже начислено")
        return

    logger.info(
        f"🏆 Компания месяца за {prev_month_year}: {result['company_name']} "
        f"({result['order_count']} заказов, {len(result['employees'])} сотрудников)"
    )

    for emp in result["employees"]:
        try:
            lang = emp.get("lang", "ru")
            if lang == "uz":
                text = (
                    f"🏆 *Tabriklaymiz!*\n\n"
                    f"Sizning kompaniyangiz — *{result['company_name']}* — "
                    f"o'tgan oyning eng faol kompaniyasi bo'ldi! 🎉\n\n"
                    f"🎁 Sovg'a sifatida *+50 ball* hisobingizga qo'shildi!"
                )
            else:
                text = (
                    f"🏆 *Поздравляем!*\n\n"
                    f"Ваша компания — *{result['company_name']}* — стала "
                    f"самой активной компанией прошлого месяца! 🎉\n\n"
                    f"🎁 В подарок вам начислено *+50 баллов*!"
                )
            await bot.send_message(emp["telegram_id"], text, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Не удалось уведомить {emp['telegram_id']}: {e}")

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🏆 *Компания месяца ({prev_month_year}): {result['company_name']}*\n\n"
                f"📦 Заказов: {result['order_count']}\n"
                f"👥 Сотрудников получили бонус: {len(result['employees'])}",
                parse_mode="Markdown"
            )
        except Exception:
            pass


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")

    # 🎂 День рождения — в 9:00
    scheduler.add_job(
        send_birthday_greetings,
        trigger=CronTrigger(hour=9, minute=0),
        args=[bot], id="birthday_greetings", replace_existing=True
    )

    # 📋 Утреннее уведомление — "Принимаем заказы с 07:00!" в 07:00
    scheduler.add_job(
        send_menu_notification,
        trigger=CronTrigger(hour=7, minute=0),
        args=[bot], id="send_menu", replace_existing=True
    )

    # 🔒 Закрытие приёма в 15:00 — уведомление + автораспределение курьерам
    scheduler.add_job(
        close_orders_notification,
        trigger=CronTrigger(hour=15, minute=0),
        args=[bot], id="close_orders", replace_existing=True
    )

    # 🏆 Компания месяца — 1-го числа в 9:30
    scheduler.add_job(
        award_company_of_month,
        trigger=CronTrigger(day=1, hour=9, minute=30),
        args=[bot], id="company_of_month", replace_existing=True
    )

    logger.info(
        "✅ Планировщик (онлайн-режим): 07:00 меню+заказы, "
        "09:00 ДР, 15:00 закрытие+курьеры, 1-го компания месяца"
    )
    return scheduler
