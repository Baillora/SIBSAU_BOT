from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from scr.parsers.schedule_parser import (
    get_current_week_and_day,
    fetch_schedule,
    get_current_and_next_lesson,
)
from scr.core.settings import LESSON_SCHEDULE, BOT_TIMEZONE
from scr.core.users import user_manager
from scr.core.logger import logger
from scr.bot.handlers.utils import safe_edit_message, require_auth, render_progress_bar


async def build_start_payload(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Генерация приветственного сообщения и клавиатуры главного меню с виджетами"""
    date_str, day_name, current_week = get_current_week_and_day()
    schedule = await fetch_schedule(context.application)
    current_lesson, time_until_current_end, next_lesson, time_until_next = get_current_and_next_lesson(
        schedule, current_week, day_name
    )

    subgroup = user_manager.get_subgroup(user_id)
    subgroup_label = f"{subgroup}-я подгруппа" if subgroup in ("1", "2") else "Все подгруппы"

    notifications = user_manager.get_notifications(user_id)
    notif_label = "🔔 Вкл" if notifications else "🔕 Выкл"

    week_text = "1-ая неделя" if current_week == 'week_1' else "2-ая неделя"
    header = (
        f"⏱️ Сегодня: *{date_str or 'Не определено'}*, {day_name or ''} ({week_text})\n"
        f"👥 Фильтр: *{subgroup_label}* | 🔔 Уведомления: *{notif_label}*\n\n"
    )
    welcome_message = header

    if current_lesson:
        info_lines = [ln.strip() for ln in (current_lesson.get("info") or "").split("\n") if ln.strip()]
        subject = info_lines[0].replace('*', '').strip() if info_lines else "Без названия"
        l_subgroup = current_lesson.get("subgroup", "")
        classroom = current_lesson.get("classroom", "")

        # Расчет времени для прогресс-бара
        import datetime
        now = datetime.datetime.now(BOT_TIMEZONE)
        cur_min = now.hour * 60 + now.minute
        progress_str = ""
        for s_min, e_min in LESSON_SCHEDULE:
            if s_min <= cur_min < e_min:
                progress_str = render_progress_bar(cur_min, s_min, e_min)
                break

        welcome_message += f"🟢 *Сейчас идёт пара:*\n📚 *{subject}*\n"
        if progress_str:
            welcome_message += f"⏳ {progress_str}\n"
        if time_until_current_end is not None:
            hours, minutes = divmod(time_until_current_end, 60)
            end_str = f"{hours} ч {minutes} мин" if hours > 0 else f"{minutes} мин"
            welcome_message += f"⏱️ До конца: *{end_str}*\n"
        if l_subgroup:
            welcome_message += f"🔸 {l_subgroup}\n"
        if classroom:
            welcome_message += f"📍 {classroom}\n"
        welcome_message += "\n"
    else:
        welcome_message += "⚪ *Сейчас пар нет.*\n\n"

    # Следующая пара
    if next_lesson is not None and time_until_next is not None:
        total_minutes = time_until_next
        if total_minutes <= 0:
            welcome_message += "🔜 Следующая пара *начинается прямо сейчас*!\n\n"
        else:
            hours, minutes = divmod(total_minutes, 60)
            time_str = f"{hours} ч {minutes} мин" if hours > 0 else f"{minutes} мин"
            info_lines = [ln.strip() for ln in (next_lesson.get("info") or "").split("\n") if ln.strip()]
            subject = info_lines[0].replace('*', '').strip() if info_lines else "Без названия"
            l_subgroup = next_lesson.get("subgroup", "")
            classroom = next_lesson.get("classroom", "")

            welcome_message += f"🔜 Следующая пара через *{time_str}*:\n📚 *{subject}*\n"
            if l_subgroup:
                welcome_message += f"🔸 {l_subgroup}\n"
            if classroom:
                welcome_message += f"📍 {classroom}\n"
            welcome_message += "\n"
    elif not current_lesson:
        welcome_message += "🔚 *Сегодня больше пар нет.*\n\n"

    welcome_message += "💻 Разработчик @m3di4 | 🤖 [GitHub](https://github.com/Baillora/SIBSAU_BOT)"

    keyboard = [
        [
            InlineKeyboardButton("1️⃣ 1 неделя", callback_data='week_1'),
            InlineKeyboardButton("2️⃣ 2 неделя", callback_data='week_2'),
            InlineKeyboardButton("🎓 Сессия", callback_data='session')
        ],
        [
            InlineKeyboardButton("📅 Сегодня", callback_data='today'),
            InlineKeyboardButton("🔜 Завтра", callback_data='tomorrow')
        ],
        [
            InlineKeyboardButton("👨‍🏫 Преподаватели", callback_data='teachers_list'),
            InlineKeyboardButton("📥 Календарь (.ics)", callback_data='export_ics')
        ],
        [
            InlineKeyboardButton("👥 Моя подгруппа", callback_data='menu_subgroup'),
            InlineKeyboardButton(f"🔔 Уведомления ({'Вкл' if notifications else 'Выкл'})", callback_data='toggle_notif')
        ]
    ]

    return welcome_message, InlineKeyboardMarkup(keyboard)


@require_auth
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name
    role = user_manager.get_role(uid)

    logger.info(f"✅ {username} ({uid}) [{role}] вызвал /start.")
    welcome_message, markup = await build_start_payload(uid, context)

    if update.message:
        await update.message.reply_text(welcome_message, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)


@require_auth
async def back_to_week_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик кнопки возврата в главное меню"""
    query = update.callback_query
    uid = query.from_user.id
    username = query.from_user.username or query.from_user.full_name

    await query.answer()
    welcome_message, markup = await build_start_payload(uid, context)
    await safe_edit_message(query, welcome_message, reply_markup=markup)
    logger.info(f"✅ {username} ({uid}) вернулся в главное меню.")


@require_auth
async def menu_subgroup_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Меню выбора подгруппы"""
    query = update.callback_query
    uid = query.from_user.id
    await query.answer()

    cur_subgroup = user_manager.get_subgroup(uid)
    text = (
        "👥 *Настройка подгруппы:*\n\n"
        "Выберите вашу подгруппу, чтобы в расписании отображались только ваши лабораторные занятия:\n\n"
        f"Текущий выбор: *{'1-я подгруппа' if cur_subgroup == '1' else ('2-я подгруппа' if cur_subgroup == '2' else 'Все подгруппы')}*"
    )

    keyboard = [
        [
            InlineKeyboardButton("1️⃣ 1-я подгруппа", callback_data='set_subgroup_1'),
            InlineKeyboardButton("2️⃣ 2-я подгруппа", callback_data='set_subgroup_2'),
        ],
        [
            InlineKeyboardButton("👥 Показать все", callback_data='set_subgroup_all'),
        ],
        [
            InlineKeyboardButton("⬅ Назад", callback_data='back_to_week')
        ]
    ]

    await safe_edit_message(query, text, InlineKeyboardMarkup(keyboard))


@require_auth
async def set_subgroup_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Установка выбранной подгруппы"""
    query = update.callback_query
    uid = query.from_user.id
    data = query.data  # set_subgroup_1 / set_subgroup_2 / set_subgroup_all
    sub = data.replace("set_subgroup_", "")

    user_manager.set_subgroup(uid, sub)
    await query.answer(f"Подгруппа сохранена: {sub if sub != 'all' else 'все'}", show_alert=False)

    welcome_message, markup = await build_start_payload(uid, context)
    await safe_edit_message(query, welcome_message, reply_markup=markup)


@require_auth
async def toggle_notifications_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Переключение статуса утренних уведомлений"""
    query = update.callback_query
    uid = query.from_user.id

    cur = user_manager.get_notifications(uid)
    new_val = not cur
    user_manager.set_notifications(uid, new_val)

    status_str = "включены" if new_val else "выключены"
    await query.answer(f"Утренние уведомления {status_str}!", show_alert=False)

    welcome_message, markup = await build_start_payload(uid, context)
    await safe_edit_message(query, welcome_message, reply_markup=markup)