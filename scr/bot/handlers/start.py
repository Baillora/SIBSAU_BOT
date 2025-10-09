from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from scr.core.stats import stats, save_stats, increment_user_commands, record_peak_usage, record_daily_active
from scr.core.users import UserManager, get_user_role, is_user_allowed
from scr.parsers.schedule_parser import get_current_week_and_day, fetch_schedule, get_current_and_next_lesson
from scr.core.settings import OWNER_ID
from scr.core.logger import logger

users = UserManager(owner_id=OWNER_ID)


# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    # Сбор статистики
    stats['unique_users'].add(uid)
    stats['total_messages'] += 1
    increment_user_commands(uid)
    record_peak_usage()
    record_daily_active(uid)
    stats['commands_executed'] += 1
    save_stats()

    if not is_user_allowed(uid):
        logger.warning(f"❌ Неавторизованный пользователь {username} ({uid}) вызвал /start.")
        try:
            owner_user = await context.bot.get_chat(OWNER_ID)
            owner_username = f"@{owner_user.username}" if owner_user.username else owner_user.full_name
        except Exception as e:
            logger.error(f"Ошибка при получении информации о владельце: {e}")
            owner_username = "администратору"

        await update.message.reply_text(
            f"Ваш ID: {uid}\n\n"
            f"Для использования бота сообщите ваш ID {owner_username}.\n\n"
            "Разработчик @lssued"
        )
        return

    # Авторизованный пользователь
    role = get_user_role(uid)
    logger.info(f"✅ {username} ({uid}) [{role}] вызвал /start.")

    # Получаем данные о дне и расписании
    date_str, day_name, current_week = get_current_week_and_day()
    schedule = await fetch_schedule(context.application)
    current_lesson, time_until_current_end, next_lesson, time_until_next = get_current_and_next_lesson(
        schedule, current_week, day_name
    )
    # Конец получения данных

    week_text = "1-ая неделя" if current_week == 'week_1' else "2-ая неделя"
    welcome_message = f"⏱️ Сегодня: {date_str}, {day_name}, {week_text}.\n\n"

    if current_lesson:
        info_lines = [ln for ln in (current_lesson.get("info") or "").split("\n") if ln.strip()]
        subject = info_lines[0].replace('*', '').strip() if info_lines else "Без названия"
        subgroup = current_lesson.get("subgroup", "")
        classroom = current_lesson.get("classroom", "")
        welcome_message += f"🎓 Сейчас идёт: *{subject}*\n"
        if time_until_current_end is not None:
            mins = time_until_current_end
            hours, minutes = divmod(mins, 60)
            if hours > 0:
                end_str = f"{hours} ч {minutes} мин"
            else:
                end_str = f"{minutes} мин"
            welcome_message += f"⏳ До конца: *{end_str}*\n"
        if subgroup:
            welcome_message += f"🔸 {subgroup}\n"
        if classroom:
            welcome_message += f"📍 {classroom}\n"
        welcome_message += "\n"

    else:
        welcome_message += "🎓 Сейчас пар нет.\n\n"

    # Всегда показываем следующую пару (если есть)
    if next_lesson is not None and time_until_next is not None:
        total_minutes = time_until_next
        if total_minutes < 0:
            pass
        elif total_minutes == 0:
            welcome_message += "🔜 Следующая пара *начинается сейчас*!\n\n"
        else:
            hours, minutes = divmod(total_minutes, 60)
            if hours > 0:
                time_str = f"{hours} ч {minutes} мин"
            else:
                time_str = f"{minutes} мин"
            info_lines = [ln for ln in (next_lesson.get("info") or "").split("\n") if ln.strip()]
            subject = info_lines[0].replace('*', '').strip() if info_lines else "Без названия"
            subgroup = next_lesson.get("subgroup", "")
            classroom = next_lesson.get("classroom", "")
            welcome_message += f"🔜 Следующая пара через *{time_str}*:\n📚 *{subject}*\n"
            if subgroup:
                welcome_message += f"🔸 {subgroup}\n"
            if classroom:
                welcome_message += f"📍 {classroom}\n"
            welcome_message += "\n"
    elif not current_lesson:
        welcome_message += "🔚 Сегодня больше пар нет.\n\n"

    welcome_message += "💻 Разработчик @lssued\n\n🤖 https://github.com/Baillora"

    keyboard = [
        [
            InlineKeyboardButton("1 неделя", callback_data='week_1'),
            InlineKeyboardButton("2 неделя", callback_data='week_2'),
            InlineKeyboardButton("Сессия", callback_data='session')
        ],
        [
            InlineKeyboardButton("Сегодня", callback_data='today'),
            InlineKeyboardButton("Завтра", callback_data='tomorrow')
        ],
        [
            InlineKeyboardButton("Преподаватели", callback_data='teachers_list')
        ]
    ]

    await update.message.reply_text(welcome_message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


# Хэндлер для кнопки "Назад"
async def back_to_week_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    uid = query.from_user.id
    username = query.from_user.username or query.from_user.full_name

    if not is_user_allowed(uid):
        await query.answer("У вас нет доступа к боту.", show_alert=True)
        logger.warning(f"❌ {username} ({uid}) попытался вернуться в главное меню без доступа.")
        return

    await query.answer()

    # Получаем данные о дне и расписании
    date_str, day_name, current_week = get_current_week_and_day()
    schedule = await fetch_schedule(context.application)
    current_lesson, time_until_current_end, next_lesson, time_until_next = get_current_and_next_lesson(
        schedule, current_week, day_name
    )
    # Конец получения данных

    week_text = "1-ая неделя" if current_week == 'week_1' else "2-ая неделя"
    welcome_message = f"⏱️ Сегодня: {date_str}, {day_name}, {week_text}.\n\n"

    if current_lesson:
        info_lines = [ln for ln in (current_lesson.get("info") or "").split("\n") if ln.strip()]
        subject = info_lines[0].replace('*', '').strip() if info_lines else "Без названия"
        subgroup = current_lesson.get("subgroup", "")
        classroom = current_lesson.get("classroom", "")
        welcome_message += f"🎓 Сейчас идёт: *{subject}*\n"
        if time_until_current_end is not None:
            mins = time_until_current_end
            hours, minutes = divmod(mins, 60)
            if hours > 0:
                end_str = f"{hours} ч {minutes} мин"
            else:
                end_str = f"{minutes} мин"
            welcome_message += f"⏳ До конца: *{end_str}*\n"
        if subgroup:
            welcome_message += f"🔸 {subgroup}\n"
        if classroom:
            welcome_message += f"📍 {classroom}\n"
        welcome_message += "\n"

    else:
        welcome_message += "🎓 Сейчас пар нет.\n\n"

    # Всегда показываем следующую пару (если есть)
    if next_lesson is not None and time_until_next is not None:
        total_minutes = time_until_next
        if total_minutes < 0:
            pass
        elif total_minutes == 0:
            welcome_message += "🔜 Следующая пара *начинается сейчас*!\n\n"
        else:
            hours, minutes = divmod(total_minutes, 60)
            if hours > 0:
                time_str = f"{hours} ч {minutes} мин"
            else:
                time_str = f"{minutes} мин"
            info_lines = [ln for ln in (next_lesson.get("info") or "").split("\n") if ln.strip()]
            subject = info_lines[0].replace('*', '').strip() if info_lines else "Без названия"
            subgroup = next_lesson.get("subgroup", "")
            classroom = next_lesson.get("classroom", "")
            welcome_message += f"🔜 Следующая пара через *{time_str}*:\n📚 *{subject}*\n"
            if subgroup:
                welcome_message += f"🔸 {subgroup}\n"
            if classroom:
                welcome_message += f"📍 {classroom}\n"
            welcome_message += "\n"
    elif not current_lesson:
        welcome_message += "🔚 Сегодня больше пар нет.\n\n"

    welcome_message += "💻 Разработчик @lssued\n\n🤖 https://github.com/Baillora"

    keyboard = [
        [
            InlineKeyboardButton("1 неделя", callback_data='week_1'),
            InlineKeyboardButton("2 неделя", callback_data='week_2'),
            InlineKeyboardButton("Сессия", callback_data='session')
        ],
        [
            InlineKeyboardButton("Сегодня", callback_data='today'),
            InlineKeyboardButton("Завтра", callback_data='tomorrow')
        ],
        [
            InlineKeyboardButton("Преподаватели", callback_data='teachers_list')
        ]
    ]

    try:
        await query.edit_message_text(
            text=welcome_message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        logger.info(f"✅ {username} ({uid}) вернулся в главное меню.")
    except Exception as e:
        logger.error(f"Ошибка при редактировании сообщения в back_to_week: {e}")
        await query.message.reply_text("Ошибка при обновлении меню.")