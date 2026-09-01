import sys
import datetime
from telegram import BotCommand, Update
from telegram.request import HTTPXRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    InlineQueryHandler,
    ContextTypes,
)
from scr.core.settings import TOKEN, OWNER_ID, PROXY_URL
from scr.bot.handlers import start, schedule, teachers, admin, misc, inline, calendar_export, web_auth
from scr.parsers.schedule_parser import fetch_schedule, get_current_week_and_day
from scr.parsers.teacher_parser import fetch_teachers
from scr.core.users import user_manager
from scr.core.logger import logger
from scr.bot.handlers.utils import format_day_schedule

# Глобальная ссылка на приложение бота
bot_app = None


async def send_daily_digest(context) -> None:
    """Утренняя рассылка расписания подписанным пользователям"""
    try:
        schedule_data = await fetch_schedule(context.application)
        date_str, day_name, current_week = get_current_week_and_day(schedule_data)
        if not schedule_data or not current_week or current_week not in schedule_data:
            return

        all_users = user_manager.get_all_users()
        for uid_str, udata in all_users.items():
            if not udata.get("notifications"):
                continue

            try:
                uid = int(uid_str)
                subgroup = udata.get("subgroup", "all")
                lessons = schedule_data.get(current_week, {}).get(day_name, [])

                if lessons:
                    text = f"☀️ *Доброе утро! Расписание на сегодня* ({date_str}, {day_name}):\n\n"
                    text += format_day_schedule(day_name, lessons, user_subgroup=subgroup)
                else:
                    text = f"☀️ *Доброе утро!*\nСегодня ({date_str}, {day_name}) пар нет. Отличного дня! 🎉"

                await context.bot.send_message(chat_id=uid, text=text, parse_mode="Markdown")
            except Exception as e:
                logger.warning(f"Не удалось отправить утренний дайджест пользователю {uid_str}: {e}")
    except Exception as e:
        logger.error(f"Ошибка в задаче send_daily_digest: {e}")


async def setup_bot_commands(application) -> None:
    """Регистрация команд в меню Telegram бота"""
    try:
        commands = [
            BotCommand("start", "Главное меню и статус пары"),
            BotCommand("help", "Справка по всем командам"),
            BotCommand("search", "Поиск по предмету или преподавателю"),
            BotCommand("subgroup", "Выбрать свою подгруппу (1 / 2)"),
            BotCommand("export", "Экспорт расписания в календарь (.ics)"),
            BotCommand("notifications", "Вкл/выкл утренние уведомления"),
            BotCommand("note", "Добавить заметку к предмету"),
            BotCommand("notes", "Список ваших заметок и дедлайнов"),
            BotCommand("room", "Справочник корпусов и аудиторий"),
            BotCommand("web", "Получить код для входа в веб-панель"),
            BotCommand("plan", "Учебный план"),
            BotCommand("map", "Карта корпусов"),
        ]
        await application.bot.set_my_commands(commands)
        logger.info("✅ Команды бота зарегистрированы в меню Telegram")
    except Exception as e:
        logger.warning(f"Не удалось установить команды меню Telegram: {e}")


async def preload_data(application):
    """Предзагрузка данных и настройка фоновых задач при старте бота"""
    try:
        await fetch_schedule(application)
        logger.info("✅ Расписание загружено в кэш при старте")
    except Exception as e:
        logger.error(f"❌ Ошибка при предзагрузке расписания: {e}")

    try:
        await fetch_teachers(application)
        logger.info("✅ Преподаватели загружены в кэш при старте")
    except Exception as e:
        logger.error(f"❌ Ошибка при предзагрузке преподавателей: {e}")

    await setup_bot_commands(application)

    # Настройка ежедневной утренней рассылки (07:30 по локальному времени)
    if application.job_queue:
        digest_time = datetime.time(hour=7, minute=30)
        application.job_queue.run_daily(send_daily_digest, time=digest_time, name="daily_digest")
        logger.info("✅ Утренняя рассылка расписания запланирована на 07:30")


def create_bot_app():
    """Создает и настраивает экземпляр Telegram Application"""
    if not TOKEN:
        logger.critical("❌ TOKEN не найден в .env (ключ должен называться TOKEN)")
        sys.exit(1)

    req_kwargs = {
        "connect_timeout": 30.0,
        "read_timeout": 30.0,
        "write_timeout": 30.0,
        "pool_timeout": 30.0,
    }
    if PROXY_URL:
        req_kwargs["proxy"] = PROXY_URL
        logger.info(f"🌐 Используется прокси для Telegram API: {PROXY_URL}")

    request_obj = HTTPXRequest(**req_kwargs)
    get_updates_request_obj = HTTPXRequest(**req_kwargs)

    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .request(request_obj)
        .get_updates_request(get_updates_request_obj)
        .post_init(preload_data)
        .build()
    )

    # --- Команды студента ---
    app.add_handler(CommandHandler("start", start.start))
    app.add_handler(CommandHandler("help", misc.help_command))
    app.add_handler(CommandHandler("search", misc.search_command))
    app.add_handler(CommandHandler("subgroup", misc.subgroup_command))
    app.add_handler(CommandHandler("export", calendar_export.export_calendar_command))
    app.add_handler(CommandHandler("notifications", misc.notifications_command))
    app.add_handler(CommandHandler("note", misc.note_command))
    app.add_handler(CommandHandler("notes", misc.notes_list_command))
    app.add_handler(CommandHandler("delnote", misc.delnote_command))
    app.add_handler(CommandHandler("room", misc.room_command))
    app.add_handler(CommandHandler("plan", misc.plan_command))
    app.add_handler(CommandHandler("map", misc.map_command))
    app.add_handler(CommandHandler("web", web_auth.web_auth_command))
    app.add_handler(CommandHandler("login", web_auth.web_auth_command))
    app.add_handler(CommandHandler("panel", web_auth.web_auth_command))

    # --- Админка ---
    app.add_handler(CommandHandler("adduser", admin.adduser))
    app.add_handler(CommandHandler("removeuser", admin.removeuser))
    app.add_handler(CommandHandler("listusers", admin.listusers_handler))
    app.add_handler(CommandHandler("reload", admin.reload_command))
    app.add_handler(CommandHandler("fullreload", admin.fullreload))
    app.add_handler(CommandHandler("showlog", admin.showlog))
    app.add_handler(CommandHandler("stats", admin.stats_command))
    app.add_handler(CommandHandler("mod", admin.mod_command))
    app.add_handler(CommandHandler("unmod", admin.unmod_command))
    app.add_handler(CommandHandler("adm", admin.adm_command))
    app.add_handler(CommandHandler("unadm", admin.unadm_command))
    app.add_handler(CommandHandler("broadcast", admin.broadcast))
    app.add_handler(CommandHandler("restart", admin.restart))

    # --- Callback-хэндлеры ---
    app.add_handler(CallbackQueryHandler(schedule.day_handler, pattern=r"^week_[12]_.+"))
    app.add_handler(CallbackQueryHandler(schedule.week_handler, pattern=r"^week_[12]$"))
    app.add_handler(CallbackQueryHandler(schedule.today_handler, pattern="^today$"))
    app.add_handler(CallbackQueryHandler(schedule.tomorrow_handler, pattern="^tomorrow$"))
    app.add_handler(CallbackQueryHandler(schedule.session_handler, pattern="^session$"))

    # Настройки и экспорт
    app.add_handler(CallbackQueryHandler(start.menu_subgroup_handler, pattern="^menu_subgroup$"))
    app.add_handler(CallbackQueryHandler(start.set_subgroup_handler, pattern=r"^set_subgroup_.+"))
    app.add_handler(CallbackQueryHandler(start.toggle_notifications_handler, pattern="^toggle_notif$"))
    app.add_handler(CallbackQueryHandler(calendar_export.export_calendar_command, pattern="^export_ics$"))

    # Преподаватели
    app.add_handler(CallbackQueryHandler(teachers.teacher_day_all_handler, pattern=r"^teacher_day_all_[0-9]+$"))
    app.add_handler(CallbackQueryHandler(teachers.teacher_pairs_handler, pattern=r"^teacher_pairs_[0-9]+$"))
    app.add_handler(CallbackQueryHandler(teachers.teacher_consult_handler, pattern=r"^teacher_consult_[0-9]+$"))
    app.add_handler(CallbackQueryHandler(teachers.teacher_handler, pattern=r"^teacher_[0-9]+$"))
    app.add_handler(CallbackQueryHandler(teachers.teacher_day_handler, pattern=r"^teacher_day_[0-9]+_.+"))
    app.add_handler(CallbackQueryHandler(teachers.teachers_list_handler, pattern="^teachers_list$"))

    # Возврат назад
    app.add_handler(CallbackQueryHandler(start.back_to_week_handler, pattern="^back_to_week$"))

    # --- Inline-поиск (@bot_name) ---
    app.add_handler(InlineQueryHandler(inline.inline_query_handler))

    # --- Глобальный обработчик ошибок (защита от падений) ---
    app.add_error_handler(global_error_handler)

    return app


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Глобальный перехватчик исключений для непрерывной работы бота"""
    logger.error(f"❌ Перехвачено исключение в обработчике: {context.error}", exc_info=context.error)
    try:
        if isinstance(update, Update):
            if update.callback_query:
                await update.callback_query.answer("⚠️ Произошла ошибка при выполнении операции.", show_alert=True)
            elif update.message:
                await update.message.reply_text("⚠️ Произошла непредвиденная ошибка. Попробуйте еще раз.")
    except Exception:
        pass


def run_bot():
    """Запуск бота в режиме Polling с автоматическими повторными попытками подключения"""
    global bot_app

    try:
        bot_app = create_bot_app()
        logger.info(f"✅ Бот инициализирован (токен: {TOKEN[:8]}...)")
    except Exception as e:
        logger.critical(f"❌ Ошибка инициализации бота: {e}")
        sys.exit(1)

    print(f"✅ Бот инициализирован с токеном: {TOKEN[:10]}...")
    logger.info("🤖 Бот запущен. Ожидаю команды...")

    try:
        bot_app.run_polling(
            bootstrap_retries=5,
            timeout=20,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )
    except (KeyboardInterrupt, SystemExit) as e:
        logger.info(f"⚠️ Получен сигнал остановки: {e}")
    except Exception as e:
        logger.error(f"❌ Ошибка при работе бота: {e}")