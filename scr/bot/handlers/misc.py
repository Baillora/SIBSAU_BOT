from telegram import Update
from telegram.ext import ContextTypes
from scr.core.settings import PLAN_URL, OWNER_ID
from scr.core.users import UserManager, get_user_role, is_user_allowed
from scr.core.stats import StatsManager
from scr.core.logger import logger
from scr.parsers.schedule_parser import fetch_schedule
from scr.parsers.teacher_parser import fetch_teachers, teachers_cache

# Инициализация
users = UserManager(owner_id=OWNER_ID)
stats = StatsManager()


# /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    # Базовый набор
    public_commands = [
        "/start - Запустить бота",
        "/help - Показать доступные команды",
    ]

    # Для обычных юзеров
    user_commands = [
        "/search <запрос> - Поиск по предметам и преподавателям",
        "/plan - Показать учебный план",
        "/map - Показать карту корпусов"
    ]

    # Модер/админ
    mod_admin_commands = [
        "/adduser <user_id> - Добавить пользователя",
        "/removeuser <user_id> - Удалить пользователя",
        "/listusers - Показать список пользователей",
        "/reload - Перезагрузить кэш расписания",
        "/fullreload - Полная перезагрузка (расписание + преподаватели)"
    ]

    # Админ
    admin_commands = [
        "/showlog [число] - Показать последние записи из логов",
        "/stats - Показать статистику",
        "/mod <user_id> - Назначить пользователя модератором",
        "/unmod <user_id> - Снять пользователя с роли модератора",
        "/broadcast <сообщение> - Рассылка объявления"
    ]

    # Владелец
    owner_commands = [
        "/adm <user_id> - Назначить пользователя администратором",
        "/unadm <user_id> - Снять пользователя с роли администратора",
        "/restart - Перезапустить бота"
    ]

    message_lines = []
    message_lines.extend(public_commands)

    if is_user_allowed(uid):
        role = get_user_role(uid)

        message_lines.append("\n-- Для пользователей --")
        message_lines.extend(user_commands)

        if role in ["mod", "admin", "owner"]:
            message_lines.append("\n-- Для модераторов/админов --")
            message_lines.extend(mod_admin_commands)

        if role in ["admin", "owner"]:
            message_lines.append("\n-- Для администраторов --")
            message_lines.extend(admin_commands)

        if role == "owner":
            message_lines.append("\n-- Для владельца --")
            message_lines.extend(owner_commands)

    await update.message.reply_text("\n".join(message_lines))
    logger.info(f"✅ {username} ({uid}) вызвал /help.")

# ---------------- /search ----------------
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    if not is_user_allowed(uid):
        await update.message.reply_text("У вас нет доступа к использованию этого бота.")
        logger.warning(f"❌ {username} ({uid}) попытался выполнить /search без доступа.")
        return

    query = " ".join(context.args).strip().lower()
    username = update.effective_user.username or update.effective_user.full_name

    stats.add_search_query()
    stats.increment_command(uid)
    stats.save()

    if not query:
        await update.message.reply_text("Использование: /search <запрос>")
        logger.warning(f"❌ {username} ({uid}) вызвал /search без аргументов.")
        return

    application = context.application
    results = []

    # --- Поиск в расписании ---
    schedule = await fetch_schedule(application)
    if schedule:
        for week_key in ["week_1", "week_2", "session"]:
            if week_key not in schedule:
                continue
            for day, lessons in schedule[week_key].items():
                if day.startswith("_"):
                    continue
                for lesson in lessons:
                    if isinstance(lesson, dict):
                        if query in lesson["info"].lower():
                            results.append({
                                "source": "schedule",
                                "week": week_key,
                                "day": day,
                                "time": lesson["time"],
                                "info": lesson["info"],
                                "subgroup": lesson.get("subgroup"),
                            })

    # --- Поиск по преподавателям ---
    await fetch_teachers(application)
    for tid, t in teachers_cache.items():
        if t["name"] and query in t["name"].lower():
            results.append({
                "source": "teacher",
                "id": tid,
                "name": t["name"],
            })

    if not results:
        await update.message.reply_text("Совпадений не найдено.")
        return

    # --- Формируем сообщение ---
    message = f"🔍 Результаты поиска для '{query}':\n\n"

    for res in results:
        if res["source"] == "schedule":
            # неделя
            if res["week"] == "week_1":
                week_text = "1-ая неделя"
            elif res["week"] == "week_2":
                week_text = "2-ая неделя"
            else:
                week_text = "Сессия"

            # форматируем инфо как в расписании
            info_lines = [ln for ln in (res["info"] or "").split("\n") if ln.strip()]
            subject = info_lines[0] if info_lines else ""
            rest = "\n".join(info_lines[1:]) if len(info_lines) > 1 else ""

            message += f"{week_text} - {res['day']}\n"
            message += f"⏰ {res['time']}\n"
            if res.get("subgroup"):
                message += f"🔸 {res['subgroup']}\n"
            if subject:
                message += f"📚 *{subject}*\n"
            if rest:
                message += rest + "\n"
            message += "\n"

        elif res["source"] == "teacher":
            message += f"👨‍🏫 Преподаватель: *{res['name']}*\n\n"

    # Ограничение телеги
    if len(message) > 4096:
        for i in range(0, len(message), 4096):
            await update.message.reply_text(message[i:i+4096], parse_mode="Markdown")
    else:
        await update.message.reply_text(message, parse_mode="Markdown")

    logger.info(f"✅ {username} ({uid}) выполнил поиск: '{query}' -> найдено {len(results)} результатов.")

# ---------------- /plan ----------------
async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    if not is_user_allowed(uid):
        await update.message.reply_text("У вас нет доступа к использованию этого бота.")
        logger.warning(f"❌ {username} ({uid}) попытался выполнить /plan без доступа.")
        return

    stats.increment_command(uid)
    stats.save()

    if not PLAN_URL:
        await update.message.reply_text("Учебный план недоступен.")
        logger.error("PLAN_URL не задан в настройках.")
        return

    await update.message.reply_text(f"📑 Учебный план: {PLAN_URL}")
    logger.info(f"✅ {username} ({uid}) запросил учебный план.")


# ---------------- /map ----------------
async def map_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    if not is_user_allowed(uid):
        await update.message.reply_text("У вас нет доступа к использованию этого бота.")
        logger.warning(f"❌ {username} ({uid}) попытался выполнить /map без доступа.")
        return

    stats.increment_command(uid)
    stats.save()

    await update.message.reply_text("🗺 Карта корпусов: https://cloud.sibsau.ru/s/KsYWFjEig2emNwH")
    logger.info(f"✅ {username} ({uid}) запросил карту корпусов.")

