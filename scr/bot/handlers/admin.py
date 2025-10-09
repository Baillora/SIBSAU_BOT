import os
from telegram import Update
from telegram.ext import ContextTypes
from scr.core.users import get_user_role, is_user_allowed, load_allowed_users, save_allowed_users
from scr.core.stats import stats, save_stats
from scr.core.settings import OWNER_ID, LOG_FILE
from scr.core.logger import logger
from scr.parsers.schedule_parser import fetch_schedule, schedule_cache
from scr.parsers.teacher_parser import fetch_teachers, teachers_cache


# ---------------- Команды управления доступом ----------------

async def adduser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    if get_user_role(uid) not in ["mod", "admin", "owner"]:
        await update.message.reply_text("Нет прав.")
        logger.warning(f"❌ {username} ({uid}) попытался выполнить /adduser без прав.")
        return

    if not context.args:
        await update.message.reply_text("Использование: /adduser <id>")
        logger.warning(f"❌ {username} ({uid}) вызвал /adduser без аргументов.")
        return

    try:
        new_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")
        logger.warning(f"❌ {username} ({uid}) указал некорректный ID в /adduser: {context.args[0]}")
        return

    if is_user_allowed(new_id):
        await update.message.reply_text("Уже есть в списке.")
        logger.warning(f"❌ {username} ({uid}) пытался добавить {new_id}, но он уже есть.")
        return

    data = load_allowed_users()
    data["users"][str(new_id)] = {"role": "user", "username": "Неизвестно"}
    save_allowed_users(data)
    await update.message.reply_text(f"✅ Пользователь {new_id} добавлен.")
    logger.info(f"✅ {username} ({uid}) добавил пользователя {new_id}.")


async def removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name
    if get_user_role(uid) not in ["mod", "admin", "owner"]:
        await update.message.reply_text("Нет прав.")
        logger.warning(f"❌ {username} ({uid}) попытался выполнить /removeuser без прав.")
        return

    if not context.args:
        await update.message.reply_text("Использование: /removeuser <id>")
        logger.warning(f"❌ {username} ({uid}) вызвал /removeuser без аргументов.")
        return

    try:
        rem_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")
        logger.warning(f"❌ {username} ({uid}) указал некорректный ID в /removeuser: {context.args[0]}")
        return

    data = load_allowed_users()
    if str(rem_id) not in data["users"]:
        await update.message.reply_text("Пользователь не найден.")
        logger.warning(f"❌ {username} ({uid}) пытался удалить пользователя, но его нет в базе.")
        return

    del data["users"][str(rem_id)]
    save_allowed_users(data)
    await update.message.reply_text(f"Пользователь {rem_id} удалён.")
    logger.info(f"✅ {username} ({uid}) удалил пользователя {rem_id}.")


async def listusers_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    if get_user_role(uid) not in ["mod", "admin", "owner"]:
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        logger.warning(f"❌ {username} ({uid}) попытался выполнить /listusers без прав.")
        return

    message_lines = []

    # Владелец
    try:
        owner_user = await context.bot.get_chat(OWNER_ID)
        owner_username = f"@{owner_user.username}" if owner_user.username else owner_user.full_name
    except Exception as e:
        logger.error(f"Ошибка при получении владельца: {e}")
        owner_username = "Владелец"

    message_lines.append(f"ID: {OWNER_ID}, Роль: owner, Username: {owner_username}")

    # Остальные пользователи
    users_data = load_allowed_users()["users"]
    for uid_str, udata in users_data.items():
        try:
            user = await context.bot.get_chat(int(uid_str))
            user_username = f"@{user.username}" if user.username else user.full_name
        except Exception as e:
            logger.error(f"Ошибка при получении {uid_str}: {e}")
            user_username = udata.get("username", "Неизвестно")

        role = udata.get("role", "user")
        message_lines.append(f"ID: {uid_str}, Роль: {role}, Username: {user_username}")
        udata["username"] = user_username

    save_allowed_users({"users": users_data})

    if not users_data:
        message_lines.append("Список разрешённых пользователей пуст.")

    message = "\n".join(message_lines)
    if len(message) > 4096:
        for i in range(0, len(message), 4096):
            await update.message.reply_text(message[i:i+4096])
    else:
        message += "\n\nРазработчик @lssued"
        await update.message.reply_text(message)

    logger.info(f"✅ {username} ({uid}) выполнил /listusers.")
    stats['commands_executed'] += 1
    save_stats()


# ---------------- Управление кэшем ----------------

async def reload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name
    if get_user_role(uid) not in ["mod", "admin", "owner"]:
        await update.message.reply_text("Нет прав.")
        logger.warning(f"❌ {username} ({uid}) попытался выполнить /reload без прав.")
        return

    schedule_cache.clear()
    await fetch_schedule(context.application)
    await update.message.reply_text("Кэш расписания обновлён.")
    logger.info(f"✅ {username} ({uid}) выполнил /reload.")


async def fullreload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name
    if get_user_role(uid) not in ["admin", "owner"]:
        await update.message.reply_text("Нет прав.")
        logger.warning(f"❌ {username} ({uid}) попытался выполнить /fullreload без прав.")
        return

    schedule_cache.clear()
    teachers_cache.clear()
    await fetch_schedule(context.application)
    await fetch_teachers(context.application)
    await update.message.reply_text("Полная перезагрузка завершена.")
    logger.info(f"✅ {username} ({uid}) выполнил /fullreload.")


# ---------------- Логи и статистика ----------------

async def showlog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name
    if get_user_role(uid) not in ["admin", "owner"]:
        await update.message.reply_text("Нет прав.")
        logger.warning(f"❌ {username} ({uid}) попытался выполнить /showlog без прав.")
        return

    num_lines = int(context.args[0]) if context.args else 50
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()[-num_lines:]
        log_text = "".join(lines) or "Лог пуст."

        # Безопасная отправка по частям
        MAX_LEN = 4000
        if len(log_text) <= MAX_LEN:
            await update.message.reply_text(log_text)
        else:
            for i in range(0, len(log_text), MAX_LEN):
                await update.message.reply_text(log_text[i:i + MAX_LEN])

        logger.info(f"✅ {username} ({uid}) запросил последние {num_lines} строк лога.")
    except Exception as e:
        logger.error(f"Ошибка логов: {e}")
        await update.message.reply_text("Ошибка при чтении логов.")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    if get_user_role(uid) not in ["admin", "owner"]:
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        logger.warning(f"❌ {username} ({uid}) попытался выполнить /stats без прав.")
        return

    unique_users_count = len(stats['unique_users'])
    schedule_requests = stats['schedule_requests']
    search_queries = stats['search_queries']
    commands_executed = stats['commands_executed']
    errors = stats['errors']
    total_messages = stats['total_messages']

    sorted_commands = sorted(stats['commands_per_user'].items(), key=lambda item: item[1], reverse=True)
    top_commands = "\n".join([f"• User ID {uid}: {count} команд" for uid, count in sorted_commands[:5]]) or "Нет данных"

    sorted_peak = sorted(stats['peak_usage'].items(), key=lambda item: item[1], reverse=True)
    peak_times = "\n".join([f"• Час {hour}: {count} команд" for hour, count in sorted_peak[:5]]) or "Нет данных"

    sorted_daily = sorted(stats['daily_active_users'].items(), key=lambda item: len(item[1]), reverse=True)
    daily_active = "\n".join([f"• {day}: {len(users)} пользователей" for day, users in sorted_daily[:5]]) or "Нет данных"

    message = (
        f"📊 **Статистика использования** 📊\n\n"
        f"👥 **Уникальных пользователей:** {unique_users_count}\n"
        f"💬 **Общее количество сообщений:** {total_messages}\n"
        f"🔄 **Запросов расписания:** {schedule_requests}\n"
        f"🔍 **Поисковых запросов:** {search_queries}\n"
        f"📌 **Выполнено команд:** {commands_executed}\n"
        f"⚠️ **Ошибок:** {errors}\n\n"
        f"🔝 **Топ 5 пользователей по выполненным командам:**\n{top_commands}\n\n"
        f"⏰ **Пиковые времена использования (топ 5):**\n{peak_times}\n\n"
        f"📅 **Ежедневная активность (топ 5 дней):**\n{daily_active}\n"
    )

    await update.message.reply_text(message, parse_mode='Markdown')
    logger.info(f"✅ {username} ({uid}) выполнил /stats.")
    stats['commands_executed'] += 1
    save_stats()


# ---------------- Управление ролями ----------------

async def mod_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    if get_user_role(uid) not in ["admin", "owner"]:
        await update.message.reply_text("Нет прав.")
        logger.warning(f"❌ {username} ({uid}) попытался выполнить /mod без прав.")
        return

    if not context.args:
        await update.message.reply_text("Использование: /mod <id>")
        logger.warning(f"❌ {username} ({uid}) вызвал /mod без аргументов.")
        return

    try:
        tid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")
        logger.warning(f"❌ {username} ({uid}) указал некорректный ID в /mod: {context.args[0]}")
        return

    data = load_allowed_users()
    if str(tid) not in data["users"]:
        await update.message.reply_text("Пользователь не найден.")
        logger.warning(f"❌ {username} ({uid}) пытался назначить {tid} модератором, но его нет в allowed_users.json.")
        return

    data["users"][str(tid)]["role"] = "mod"
    save_allowed_users(data)
    await update.message.reply_text(f"{tid} назначен модератором.")
    logger.info(f"✅ {username} ({uid}) назначил {tid} модератором.")


async def unmod_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    if get_user_role(uid) not in ["admin", "owner"]:
        await update.message.reply_text("Нет прав.")
        logger.warning(f"❌ {username} ({uid}) попытался выполнить /unmod без прав.")
        return

    if not context.args:
        await update.message.reply_text("Использование: /unmod <id>")
        logger.warning(f"❌ {username} ({uid}) вызвал /unmod без аргументов.")
        return

    try:
        tid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")
        logger.warning(f"❌ {username} ({uid}) указал некорректный ID в /unmod: {context.args[0]}")
        return

    data = load_allowed_users()
    if str(tid) not in data["users"]:
        await update.message.reply_text("Пользователь не найден.")
        logger.warning(f"❌ {username} ({uid}) пытался снять {tid} с роли модератора, но его нет в allowed_users.json.")
        return

    data["users"][str(tid)]["role"] = "user"
    save_allowed_users(data)
    await update.message.reply_text(f"{tid} снят с роли модератора.")
    logger.info(f"✅ {username} ({uid}) снял {tid} с роли модератора.")


async def adm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    if uid != OWNER_ID:
        await update.message.reply_text("Только OWNER.")
        logger.warning(f"❌ {username} ({uid}) попытался выполнить /adm без прав (не OWNER).")
        return

    if not context.args:
        await update.message.reply_text("Использование: /adm <id>")
        logger.warning(f"❌ OWNER {username} ({uid}) вызвал /adm без аргументов.")
        return

    try:
        tid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")
        logger.warning(f"❌ OWNER {username} ({uid}) указал некорректный ID в /adm: {context.args[0]}")
        return

    data = load_allowed_users()
    if str(tid) not in data["users"]:
        await update.message.reply_text("Пользователь не найден.")
        logger.warning(f"❌ OWNER {username} ({uid}) пытался назначить {tid} админом, но его нет в allowed_users.json.")
        return

    data["users"][str(tid)]["role"] = "admin"
    save_allowed_users(data)
    await update.message.reply_text(f"{tid} назначен админом.")
    logger.info(f"✅ OWNER {username} ({uid}) назначил {tid} администратором.")


async def unadm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    if uid != OWNER_ID:
        await update.message.reply_text("Только OWNER.")
        logger.warning(f"❌ {username} ({uid}) попытался выполнить /unadm без прав.")
        return

    if not context.args:
        await update.message.reply_text("Использование: /unadm <id>")
        logger.warning(f"❌ {username} ({uid}) вызвал /unadm без аргументов.")
        return

    try:
        tid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")
        logger.warning(f"❌ {username} ({uid}) указал некорректный ID в /unadm: {context.args[0]}")
        return

    data = load_allowed_users()
    if str(tid) not in data["users"]:
        await update.message.reply_text("Пользователь не найден.")
        logger.warning(f"❌ {username} ({uid}) пытался снять роль admin у {tid}, но пользователя нет в allowed_users.json.")
        return

    data["users"][str(tid)]["role"] = "user"
    save_allowed_users(data)
    await update.message.reply_text(f"{tid} снят с роли админа.")
    logger.info(f"✅ OWNER {username} ({uid}) снял {tid} с роли администратора.")


# ---------------- Другое ----------------

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    if get_user_role(uid) not in ["admin", "owner"]:
        await update.message.reply_text("Нет прав.")
        logger.warning(f"❌ {username} ({uid}) попытался выполнить /broadcast без прав.")
        return

    msg = " ".join(context.args) if context.args else ""
    if not msg:
        await update.message.reply_text("Использование: /broadcast <текст>")
        logger.warning(f"❌ {username} ({uid}) вызвал /broadcast без текста.")
        return

    data = load_allowed_users()
    ok, fail = 0, 0
    for user_id_str in data["users"]:
        try:
            await context.bot.send_message(chat_id=int(user_id_str), text=f"🔔 {msg}")
            ok += 1
        except Exception as e:
            logger.warning(f"Не удалось отправить сообщение пользователю {user_id_str}: {e}")
            fail += 1

    await update.message.reply_text(f"Рассылка завершена. Успех: {ok}, Ошибки: {fail}")
    logger.info(f"✅ {username} ({uid}) отправил broadcast: '{msg}' (успех: {ok}, ошибок: {fail})")


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != OWNER_ID:
        await update.message.reply_text("❌ Только OWNER может перезапускать бота.")
        return
    
    await update.message.reply_text("♻️ Перезапуск бота...")
    logger.info(f"✅ OWNER ({uid}) инициировал перезапуск бота.")
    
    # Просто выходим с кодом 42 через главный поток
    import threading
    
    def exit_main_thread():
        import time
        time.sleep(2)
        logger.info("♻️ Выполнение перезапуска...")
        # Используем os._exit для немедленного завершения
        os._exit(42)
    
    # Запускаем в отдельном потоке
    threading.Thread(target=exit_main_thread, daemon=True).start()