import os
import threading
import time
from telegram import Update
from telegram.ext import ContextTypes

from scr.core.users import user_manager
from scr.core.stats import stats_manager
from scr.core.settings import OWNER_ID, LOG_FILE, get_panel_base_url
import scr.core.settings as settings
from scr.core.logger import logger
from scr.parsers.schedule_parser import fetch_schedule, schedule_cache
from scr.parsers.teacher_parser import fetch_teachers, teachers_cache
from scr.bot.handlers.utils import require_auth, require_role, split_message_markdown


# ---------------- Команды управления доступом ----------------

@require_auth
@require_role("mod", "admin", "owner")
async def adduser(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

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

    if user_manager.is_allowed(new_id):
        await update.message.reply_text("Уже есть в списке.")
        logger.warning(f"❌ {username} ({uid}) пытался добавить {new_id}, но он уже есть.")
        return

    user_manager.add_user(new_id, role="user", username="Неизвестно")
    await update.message.reply_text(f"✅ Пользователь {new_id} добавлен.")
    logger.info(f"✅ {username} ({uid}) добавил пользователя {new_id}.")


@require_auth
@require_role("mod", "admin", "owner")
async def removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

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

    if not user_manager.remove_user(rem_id):
        await update.message.reply_text("Пользователь не найден.")
        logger.warning(f"❌ {username} ({uid}) пытался удалить пользователя, но его нет в базе.")
        return

    await update.message.reply_text(f"Пользователь {rem_id} удалён.")
    logger.info(f"✅ {username} ({uid}) удалил пользователя {rem_id}.")


@require_auth
@require_role("mod", "admin", "owner")
async def listusers_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    message_lines = []

    # Владелец
    try:
        owner_user = await context.bot.get_chat(OWNER_ID) if OWNER_ID else None
        owner_username = f"@{owner_user.username}" if (owner_user and owner_user.username) else (owner_user.full_name if owner_user else "Владелец")
    except Exception as e:
        logger.error(f"Ошибка при получении владельца: {e}")
        owner_username = "Владелец"

    message_lines.append(f"👑 ID: `{OWNER_ID}`, Роль: owner, Username: {owner_username}")

    # Остальные пользователи
    users_data = user_manager.get_all_users()
    for uid_str, udata in users_data.items():
        try:
            user = await context.bot.get_chat(int(uid_str))
            user_username = f"@{user.username}" if user.username else user.full_name
            user_manager.update_username(int(uid_str), user_username)
        except Exception:
            user_username = udata.get("username", "Неизвестно")

        role = udata.get("role", "user")
        message_lines.append(f"👤 ID: `{uid_str}`, Роль: {role}, Username: {user_username}")

    if not users_data:
        message_lines.append("Список разрешённых пользователей пуст.")

    full_text = "\n".join(message_lines) + "\n\nРазработчик @m3di4"
    chunks = split_message_markdown(full_text)
    for chunk in chunks:
        await update.message.reply_text(chunk, parse_mode="Markdown")

    logger.info(f"✅ {username} ({uid}) выполнил /listusers.")


# ---------------- Управление кэшем ----------------

@require_auth
@require_role("mod", "admin", "owner")
async def reload_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    schedule_cache.clear()
    await fetch_schedule(context.application)
    await update.message.reply_text("✅ Кэш расписания обновлён.")
    logger.info(f"✅ {username} ({uid}) выполнил /reload.")


@require_auth
@require_role("admin", "owner")
async def fullreload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    schedule_cache.clear()
    teachers_cache.clear()
    await fetch_schedule(context.application)
    await fetch_teachers(context.application)
    await update.message.reply_text("✅ Полная перезагрузка завершена.")
    logger.info(f"✅ {username} ({uid}) выполнил /fullreload.")


# ---------------- Логи и статистика ----------------

@require_auth
@require_role("admin", "owner")
async def showlog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    num_lines = int(context.args[0]) if (context.args and context.args[0].isdigit()) else 50

    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[-num_lines:]
            log_text = "".join(lines) or "Лог пуст."
        else:
            log_text = "Лог-файл отсутствует."

        chunks = split_message_markdown(log_text)
        for chunk in chunks:
            await update.message.reply_text(chunk)

        logger.info(f"✅ {username} ({uid}) запросил последние {num_lines} строк лога.")
    except Exception as e:
        logger.error(f"Ошибка логов: {e}")
        await update.message.reply_text("Ошибка при чтении логов.")


@require_auth
@require_role("admin", "owner")
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    snap = stats_manager.get_snapshot()

    sorted_commands = sorted(snap["commands_per_user"].items(), key=lambda item: item[1], reverse=True)
    top_commands = "\n".join([f"• User ID `{uid_k}`: {count} команд" for uid_k, count in sorted_commands[:5]]) or "Нет данных"

    sorted_peak = sorted(snap["peak_usage"].items(), key=lambda item: item[1], reverse=True)
    peak_times = "\n".join([f"• Час {hour}: {count} запросов" for hour, count in sorted_peak[:5]]) or "Нет данных"

    sorted_daily = sorted(snap["daily_active_users"].items(), key=lambda item: len(item[1]), reverse=True)
    daily_active = "\n".join([f"• {day}: {len(u_list)} пользователей" for day, u_list in sorted_daily[:5]]) or "Нет данных"

    message = (
        f"📊 *Статистика использования* 📊\n\n"
        f"👥 *Уникальных пользователей:* {snap['unique_users_count']}\n"
        f"💬 *Общее количество сообщений:* {snap['total_messages']}\n"
        f"🔄 *Запросов расписания:* {snap['schedule_requests']}\n"
        f"🔍 *Поисковых запросов:* {snap['search_queries']}\n"
        f"📌 *Выполнено команд:* {snap['commands_executed']}\n"
        f"⚠️ *Ошибок:* {snap['errors']}\n\n"
        f"🔝 *Топ 5 пользователей по выполненным командам:*\n{top_commands}\n\n"
        f"⏰ *Пиковые часы активности:*\n{peak_times}\n\n"
        f"📅 *Ежедневная активность (топ 5 дней):*\n{daily_active}\n"
    )

    await update.message.reply_text(message, parse_mode="Markdown")
    logger.info(f"✅ {username} ({uid}) выполнил /stats.")


# ---------------- Управление ролями ----------------

@require_auth
@require_role("admin", "owner")
async def mod_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    if not context.args:
        await update.message.reply_text("Использование: /mod <id>")
        logger.warning(f"❌ {username} ({uid}) вызвал /mod без аргументов.")
        return

    try:
        tid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")
        return

    if not user_manager.set_role(tid, "mod"):
        await update.message.reply_text("Пользователь не найден.")
        return

    await update.message.reply_text(f"✅ Пользователь {tid} назначен модератором.")
    logger.info(f"✅ {username} ({uid}) назначил {tid} модератором.")


@require_auth
@require_role("admin", "owner")
async def unmod_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    if not context.args:
        await update.message.reply_text("Использование: /unmod <id>")
        return

    try:
        tid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")
        return

    if not user_manager.set_role(tid, "user"):
        await update.message.reply_text("Пользователь не найден.")
        return

    await update.message.reply_text(f"✅ Пользователь {tid} снят с роли модератора.")
    logger.info(f"✅ {username} ({uid}) снял {tid} с роли модератора.")


@require_auth
@require_role("owner")
async def adm_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    if not context.args:
        await update.message.reply_text("Использование: /adm <id>")
        return

    try:
        tid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")
        return

    if not user_manager.set_role(tid, "admin"):
        await update.message.reply_text("Пользователь не найден.")
        return

    await update.message.reply_text(f"✅ Пользователь {tid} назначен администратором.")
    logger.info(f"✅ OWNER {username} ({uid}) назначил {tid} администратором.")


@require_auth
@require_role("owner")
async def unadm_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    if not context.args:
        await update.message.reply_text("Использование: /unadm <id>")
        return

    try:
        tid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")
        return

    if not user_manager.set_role(tid, "user"):
        await update.message.reply_text("Пользователь не найден.")
        return

    await update.message.reply_text(f"✅ Пользователь {tid} снят с роли администратора.")
    logger.info(f"✅ OWNER {username} ({uid}) снял {tid} с роли администратора.")


# ---------------- Другое ----------------

@require_auth
@require_role("admin", "owner")
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    msg = " ".join(context.args) if context.args else ""
    if not msg:
        await update.message.reply_text("Использование: /broadcast <текст>")
        return

    users_data = user_manager.get_all_users()
    ok, fail = 0, 0
    for user_id_str in users_data:
        try:
            await context.bot.send_message(chat_id=int(user_id_str), text=f"🔔 {msg}")
            ok += 1
        except Exception as e:
            logger.warning(f"Не удалось отправить broadcast пользователю {user_id_str}: {e}")
            fail += 1

    await update.message.reply_text(f"Рассылка завершена. Успех: {ok}, Ошибки: {fail}")
    logger.info(f"✅ {username} ({uid}) отправил broadcast: '{msg}' (успех: {ok}, ошибок: {fail})")


@require_auth
@require_role("owner")
async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    await update.message.reply_text("♻️ Перезапуск бота...")
    logger.info(f"✅ OWNER ({uid}) инициировал перезапуск бота.")

    def trigger_exit():
        time.sleep(1.5)
        logger.info("♻️ Завершение процесса для перезапуска...")
        os._exit(42)

    threading.Thread(target=trigger_exit, daemon=True).start()


@require_auth
@require_role("owner")
async def setpanel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /setpanel для настройки домена/IP/DDNS веб-панели (только для Владельца)"""
    uid = update.effective_user.id

    if not context.args:
        current_url = get_panel_base_url()
        is_custom = bool(settings.PANEL_URL)
        status_str = "настроен вручную" if is_custom else "определяется автоматически"
        await update.message.reply_text(
            f"🌐 *Текущий адрес веб-панели:* `{current_url}`\n"
            f"📌 Режим: _{status_str}_\n\n"
            "💡 Чтобы установить домен/DDNS/статический IP, используйте:\n"
            "`/setpanel http://ваш-домен:19999`\n\n"
            "Или сбросить на автоопределение IP:\n"
            "`/setpanel auto`",
            parse_mode="Markdown"
        )
        return

    new_val = context.args[0].strip()
    if new_val.lower() == "auto":
        settings.PANEL_URL = ""
        current_url = get_panel_base_url()
        await update.message.reply_text(
            f"✅ Сброшено на автоматическое определение внешнего IP.\n🌐 Текущий адрес: `{current_url}`",
            parse_mode="Markdown"
        )
    else:
        if not new_val.startswith("http://") and not new_val.startswith("https://"):
            new_val = f"http://{new_val}"
        settings.PANEL_URL = new_val.rstrip("/")
        await update.message.reply_text(
            f"✅ *Адрес веб-панели успешно обновлен!*\n"
            f"🌐 Теперь ссылки `/web` будут вести на: `{settings.PANEL_URL}`",
            parse_mode="Markdown"
        )
    logger.info(f"Владелец ({uid}) обновил адрес веб-панели: {settings.PANEL_URL or 'AUTO'}")