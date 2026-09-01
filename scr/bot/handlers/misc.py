from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from scr.core.settings import PLAN_URL, lookup_campus, CAMPUS_DIRECTORY
from scr.core.users import user_manager
from scr.core.stats import stats_manager
from scr.core.notes import notes_manager
from scr.core.logger import logger
from scr.parsers.schedule_parser import fetch_schedule
from scr.parsers.teacher_parser import fetch_teachers, teachers_cache
from scr.bot.handlers.utils import require_auth, split_message_markdown


# /help
@require_auth
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name
    role = user_manager.get_role(uid)

    public_commands = [
        "🤖 *Основные команды:*",
        "/start - Главное меню и статус текущей пары",
        "/help - Справка по всем командам",
        "/web - Вход в веб-панель (1-клик ссылка и одноразовый код)",
    ]

    user_commands = [
        "\n📚 *Функции для студентов:*",
        "/search <запрос> - Поиск по предметам, кабинетам и преподавателям",
        "/subgroup [1|2|all] - Выбрать свою подгруппу (1 / 2)",
        "/export - Скачать расписание в календарь (.ics)",
        "/notifications - Вкл/выкл утренние напоминания (07:30)",
        "/note <предмет> : <текст> - Добавить заметку/дедлайн к предмету",
        "/notes - Список ваших заметок и дедлайнов",
        "/delnote <id> - Удалить заметку по номеру",
        "/room <номер/корпус> - Справочник аудиторий и корпусов",
        "/plan - Показать учебный план",
        "/map - Показать интерактивную карту корпусов"
    ]

    mod_admin_commands = [
        "\n👮 *Для модераторов:*",
        "/adduser <user_id> - Добавить пользователя (Студента)",
        "/removeuser <user_id> - Удалить пользователя",
        "/listusers - Показать список пользователей",
        "/reload - Перезагрузить кэш расписания"
    ]

    admin_commands = [
        "\n🛡️ *Для администраторов:*",
        "/fullreload - Полная перезагрузка (расписание + преподаватели)",
        "/showlog [число] - Показать последние записи логов",
        "/stats - Показать подробную статистику бота",
        "/mod <user_id> - Назначить модератора",
        "/unmod <user_id> - Снять с роли модератора",
        "/broadcast <текст> - Отправить рассылку всем пользователям"
    ]

    owner_commands = [
        "\n👑 *Для владельца:*",
        "/adm <user_id> - Назначить администратора",
        "/unadm <user_id> - Снять с роли администратора",
        "/setpanel [url|auto] - Настроить домен/IP веб-панели",
        "/restart - Перезапустить бота"
    ]

    message_lines = []
    message_lines.extend(public_commands)
    message_lines.extend(user_commands)

    if role in ["mod", "admin", "owner"]:
        message_lines.extend(mod_admin_commands)

    if role in ["admin", "owner"]:
        message_lines.extend(admin_commands)

    if role == "owner":
        message_lines.extend(owner_commands)

    await update.message.reply_text("\n".join(message_lines), parse_mode="Markdown")
    logger.info(f"✅ {username} ({uid}) вызвал /help.")


# /note
@require_auth
async def note_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text(
            "📝 *Как добавить заметку к предмету:*\n\n"
            "Использование:\n"
            "`/note <предмет> : <текст заметки>`\n\n"
            "Пример:\n"
            "`/note Электроника : Сдать отчет по лабе №2 к среде`\n"
            "`/note Физика : Подготовиться к контрольной`",
            parse_mode="Markdown"
        )
        return

    full_arg = " ".join(context.args)
    if ":" in full_arg:
        parts = full_arg.split(":", 1)
        subject = parts[0].strip()
        text = parts[1].strip()
    else:
        subject = context.args[0].strip()
        text = " ".join(context.args[1:]).strip() if len(context.args) > 1 else "Заметка"

    note_id = notes_manager.add_note(uid, subject, text)
    await update.message.reply_text(
        f"✅ *Заметка сохранена!* (ID: `{note_id}`)\n\n"
        f"📚 *Предмет:* {subject}\n"
        f"📝 *Текст:* {text}\n\n"
        f"Она будет отображаться в вашем расписании в дни этого предмета. Просмотр всех: /notes",
        parse_mode="Markdown"
    )


# /notes
@require_auth
async def notes_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    user_notes = notes_manager.get_user_notes(uid)

    if not user_notes:
        await update.message.reply_text(
            "📝 У вас пока нет сохраненных заметок.\n\n"
            "Добавить заметку: `/note <предмет> : <текст>`",
            parse_mode="Markdown"
        )
        return

    msg = "📝 *Ваши заметки и дедлайны:*\n\n"
    for n in user_notes:
        msg += (
            f"📌 *{n.get('subject')}* (ID: `{n.get('id')}`)\n"
            f"   {n.get('text')}\n"
            f"   _Добавлено: {n.get('created_at', '')}_\n"
            f"   Удалить: `/delnote {n.get('id')}`\n\n"
        )

    await update.message.reply_text(msg, parse_mode="Markdown")


# /delnote
@require_auth
async def delnote_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Использование: `/delnote <ID заметки>`\nСписок всех заметок: /notes", parse_mode="Markdown")
        return

    note_id = context.args[0].strip()
    if notes_manager.delete_note(uid, note_id):
        await update.message.reply_text(f"✅ Заметка `{note_id}` успешно удалена.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ Заметка с ID `{note_id}` не найдена.", parse_mode="Markdown")


# /room
@require_auth
async def room_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    if not context.args:
        # Список всех корпусов
        msg = "🏢 *Справочник корпусов СибГУ:*\n\n"
        for code, info in CAMPUS_DIRECTORY.items():
            msg += (
                f"🏛 *{info['name']}*\n"
                f"📍 {info['address']}\n"
                f"ℹ️ {info['description']}\n"
                f"🗺 [Открыть на карте]({info['map_url']})\n\n"
            )
        msg += "Для поиска аудитории введите: `/room <аудитория>` (например: `/room С3-504` или `/room Н-304`)"
        await update.message.reply_text(msg, parse_mode="Markdown", disable_web_page_preview=True)
        return

    query = " ".join(context.args)
    info = lookup_campus(query)

    if info:
        text = (
            f"📍 *Информация об аудитории / корпусе:* `{query}`\n\n"
            f"🏛 *{info['name']}*\n"
            f"🏢 *Адрес:* {info['address']}\n"
            f"ℹ️ *Назначение:* {info['description']}\n\n"
            f"🗺 [Посмотреть на Яндекс.Картах]({info['map_url']})"
        )
    else:
        text = (
            f"❓ Корпус для `{query}` не найден в базе.\n\n"
            "Популярные коды: `С3` (Семафорная 123), `С1` (ВУЦ), `Н` (Красраб 31/5), `А` (Красраб 31), `ДВС` (Спортзал), `П` (Физика), `ГЛ` (Мира 82).\n"
            "Все корпуса: `/room`"
        )

    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=False)


# /search
@require_auth
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    query = " ".join(context.args).strip().lower() if context.args else ""
    if not query:
        await update.message.reply_text("Использование: /search <запрос>\nНапример: `/search физика` или `/search кустов`", parse_mode="Markdown")
        logger.warning(f"❌ {username} ({uid}) вызвал /search без аргументов.")
        return

    stats_manager.add_search_query()
    stats_manager.save()

    results = []

    # Поиск в расписании
    schedule = await fetch_schedule(context.application)
    if schedule:
        for week_key in ["week_1", "week_2", "session"]:
            if week_key not in schedule:
                continue
            for day, lessons in schedule[week_key].items():
                if str(day).startswith("_"):
                    continue
                for lesson in lessons:
                    if isinstance(lesson, dict):
                        info_text = (lesson.get("info", "") + " " + lesson.get("classroom", "") + " " + (lesson.get("subgroup") or "")).lower()
                        if query in info_text:
                            results.append({
                                "source": "schedule",
                                "week": week_key,
                                "day": day,
                                "time": lesson.get("time", ""),
                                "info": lesson.get("info", ""),
                                "subgroup": lesson.get("subgroup"),
                                "classroom": lesson.get("classroom"),
                            })

    # Поиск по преподавателям
    await fetch_teachers(context.application)
    for tid, t in teachers_cache.items():
        if t.get("name") and query in t["name"].lower():
            results.append({
                "source": "teacher",
                "id": tid,
                "name": t["name"],
                "href": t.get("href", "")
            })

    if not results:
        await update.message.reply_text("🔍 Совпадений не найдено.")
        return

    message = f"🔍 Результаты поиска для *'{query}'*:\n\n"

    for res in results:
        if res["source"] == "schedule":
            week_text = "1-ая неделя" if res["week"] == "week_1" else ("2-ая неделя" if res["week"] == "week_2" else "Сессия")
            info_lines = [ln.strip() for ln in (res["info"] or "").split("\n") if ln.strip()]
            subject = info_lines[0].replace("*", "").strip() if info_lines else ""
            rest = "\n".join(info_lines[1:]) if len(info_lines) > 1 else ""

            message += f"📅 {week_text} — {res['day']}\n"
            message += f"⏰ {res['time']}\n"
            if res.get("subgroup"):
                message += f"🔸 {res['subgroup']}\n"
            if subject:
                message += f"📚 *{subject}*\n"
            if rest:
                message += rest + "\n"
            if res.get("classroom"):
                message += f"📍 {res['classroom']}\n"
            message += "\n"

        elif res["source"] == "teacher":
            message += f"👨‍🏫 Преподаватель: *{res['name']}*\n"
            if res.get("href"):
                message += f"🔗 {res['href']}\n"
            message += "\n"

    chunks = split_message_markdown(message)
    for chunk in chunks:
        await update.message.reply_text(chunk, parse_mode="Markdown")

    logger.info(f"✅ {username} ({uid}) выполнил поиск '{query}' -> найдено {len(results)} результатов.")


# /subgroup
@require_auth
async def subgroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    if context.args:
        arg = context.args[0].lower()
        if arg in ("1", "1️⃣", "1-я"):
            user_manager.set_subgroup(uid, "1")
            await update.message.reply_text("✅ Выбрана *1-я подгруппа*. Теперь в расписании показываются только ваши лабораторные.", parse_mode="Markdown")
            return
        elif arg in ("2", "2️⃣", "2-я"):
            user_manager.set_subgroup(uid, "2")
            await update.message.reply_text("✅ Выбрана *2-я подгруппа*. Теперь в расписании показываются только ваши лабораторные.", parse_mode="Markdown")
            return
        elif arg in ("all", "все", "0"):
            user_manager.set_subgroup(uid, "all")
            await update.message.reply_text("✅ Выбран режим *Все подгруппы*.", parse_mode="Markdown")
            return

    cur_subgroup = user_manager.get_subgroup(uid)
    sub_label = f"{cur_subgroup}-я подгруппа" if cur_subgroup in ("1", "2") else "Все подгруппы"

    text = (
        f"👥 Текущая подгруппа: *{sub_label}*\n\n"
        "Выберите вашу подгруппу с помощью кнопок ниже или командой `/subgroup 1` / `/subgroup 2`:"
    )

    keyboard = [
        [
            InlineKeyboardButton("1️⃣ 1-я подгруппа", callback_data='set_subgroup_1'),
            InlineKeyboardButton("2️⃣ 2-я подгруппа", callback_data='set_subgroup_2'),
        ],
        [InlineKeyboardButton("👥 Показать все", callback_data='set_subgroup_all')]
    ]

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


# /notifications
@require_auth
async def notifications_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    cur = user_manager.get_notifications(uid)
    new_val = not cur
    user_manager.set_notifications(uid, new_val)

    if new_val:
        await update.message.reply_text("🔔 Утренние уведомления *включены*! Каждое утро бот будет присылать расписание на день.", parse_mode="Markdown")
    else:
        await update.message.reply_text("🔕 Утренние уведомления *выключены*.", parse_mode="Markdown")


# /plan
@require_auth
async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    if not PLAN_URL:
        await update.message.reply_text("Учебный план недоступен (не задан PLAN_URL).")
        logger.error("PLAN_URL не задан в настройках.")
        return

    await update.message.reply_text(f"📑 Учебный план:\n{PLAN_URL}")
    logger.info(f"✅ {username} ({uid}) запросил учебный план.")


# /map
@require_auth
async def map_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    await update.message.reply_text("🗺 Карта корпусов:\nhttps://cloud.sibsau.ru/s/KsYWFjEig2emNwH")
    logger.info(f"✅ {username} ({uid}) запросил карту корпусов.")
