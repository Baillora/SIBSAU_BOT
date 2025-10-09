import sys
import os
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
)
from scr.core.settings import TOKEN
from scr.bot.handlers import start, schedule, teachers, admin, misc
from scr.parsers.schedule_parser import fetch_schedule
from scr.parsers.teacher_parser import fetch_teachers
from scr.core.logger import logger


# Глобальная переменная, чтобы Flask мог к ней обращаться
bot_app = None

async def preload_data(application):
    """Предзагрузка данных при старте бота."""
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


def run_bot():
    global bot_app

    if not TOKEN:
        logger.critical("❌ TOKEN не найден в .env (ключ должен называться TOKEN)")
        sys.exit(1)

    # создаём приложение и указываем preload_data в post_init
    try:
        bot_app = (
            ApplicationBuilder()
            .token(TOKEN)
            .post_init(preload_data)
            .build()
        )
        logger.info(f"✅ Бот инициализирован (токен: {TOKEN[:8]}...)")
    except Exception as e:
        logger.critical(f"❌ Ошибка инициализации бота: {e}")
        sys.exit(1)

    print(f"✅ Бот инициализирован с токеном: {TOKEN[:10]}...")

    # --- Команды ---
    bot_app.add_handler(CommandHandler("start", start.start))
    bot_app.add_handler(CommandHandler("help", misc.help_command))
    bot_app.add_handler(CommandHandler("search", misc.search_command))
    bot_app.add_handler(CommandHandler("plan", misc.plan_command))
    bot_app.add_handler(CommandHandler("map", misc.map_command))

    # Админка
    bot_app.add_handler(CommandHandler("adduser", admin.adduser))
    bot_app.add_handler(CommandHandler("removeuser", admin.removeuser))
    bot_app.add_handler(CommandHandler("listusers", admin.listusers_handler))
    bot_app.add_handler(CommandHandler("reload", admin.reload_command))
    bot_app.add_handler(CommandHandler("fullreload", admin.fullreload))
    bot_app.add_handler(CommandHandler("showlog", admin.showlog))
    bot_app.add_handler(CommandHandler("stats", admin.stats_command))
    bot_app.add_handler(CommandHandler("mod", admin.mod_command))
    bot_app.add_handler(CommandHandler("unmod", admin.unmod_command))
    bot_app.add_handler(CommandHandler("adm", admin.adm_command))
    bot_app.add_handler(CommandHandler("unadm", admin.unadm_command))
    bot_app.add_handler(CommandHandler("broadcast", admin.broadcast))
    bot_app.add_handler(CommandHandler("restart", admin.restart))

    # --- Callback-хэндлеры ---
    bot_app.add_handler(CallbackQueryHandler(schedule.day_handler, pattern=r"^week_[12]_.+"))
    bot_app.add_handler(CallbackQueryHandler(schedule.week_handler, pattern=r"^week_[12]$"))
    bot_app.add_handler(CallbackQueryHandler(schedule.today_handler, pattern="^today$"))
    bot_app.add_handler(CallbackQueryHandler(schedule.tomorrow_handler, pattern="^tomorrow$"))
    bot_app.add_handler(CallbackQueryHandler(schedule.session_handler, pattern="^session$"))

    # Преподаватели
    bot_app.add_handler(CallbackQueryHandler(teachers.teacher_day_all_handler, pattern=r"^teacher_day_all_[0-9]+$"))
    bot_app.add_handler(CallbackQueryHandler(teachers.teacher_pairs_handler, pattern=r"^teacher_pairs_[0-9]+$"))
    bot_app.add_handler(CallbackQueryHandler(teachers.teacher_consult_handler, pattern=r"^teacher_consult_[0-9]+$"))
    bot_app.add_handler(CallbackQueryHandler(teachers.teacher_handler, pattern=r"^teacher_[0-9]+$"))
    bot_app.add_handler(CallbackQueryHandler(teachers.teacher_day_handler, pattern=r"^teacher_day_[0-9]+_.+"))
    bot_app.add_handler(CallbackQueryHandler(teachers.teachers_list_handler, pattern="^teachers_list$"))

    # Возвраты назад
    bot_app.add_handler(CallbackQueryHandler(start.back_to_week_handler, pattern="^back_to_week$"))

    logger.info("🤖 Бот запущен. Ожидаю команды...")
    
    try:
        bot_app.run_polling()
        logger.info("✅ Зарегистрированы callback-хэндлеры для: week, day, today, tomorrow, session")
    except (KeyboardInterrupt, SystemExit) as e:
        logger.info(f"⚠️ Получен сигнал остановки: {e}")
    except Exception as e:
        logger.error(f"❌ Ошибка при работе бота: {e}")
    
    # Проверяем флаг перезапуска ВСЕГДА
    if os.path.exists('.restart_flag'):
        try:
            with open('.restart_flag', 'r') as f:
                code = int(f.read().strip())
            os.remove('.restart_flag')
            logger.info(f"♻️ Обнаружен флаг перезапуска с кодом {code}")
            sys.exit(code)
        except Exception as e:
            logger.error(f"⚠️ Ошибка чтения флага: {e}")
            if os.path.exists('.restart_flag'):
                os.remove('.restart_flag')