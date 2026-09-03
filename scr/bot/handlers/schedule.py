from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from scr.parsers.schedule_parser import fetch_schedule, get_current_week_and_day, get_tomorrow_week_and_day
from scr.core.stats import stats_manager
from scr.core.users import user_manager
from scr.core.notes import notes_manager
from scr.core.settings import WEEKDAYS, EXPECTED_DAYS, RU_WEEKDAYS_ORDER
from scr.core.logger import logger
from scr.bot.handlers.utils import safe_edit_message, require_auth, format_day_schedule, format_week_schedule, split_message_markdown


@require_auth
async def week_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    uid = query.from_user.id
    username = query.from_user.username or query.from_user.full_name

    await query.answer()
    week = query.data  # week_1 или week_2

    stats_manager.add_schedule_request()
    stats_manager.save()

    schedule = await fetch_schedule(context.application)

    if not schedule or week not in schedule:
        await safe_edit_message(query, "Расписание недоступно.")
        logger.error(f"Расписание не загружено или неделя {week} отсутствует.")
        return

    keyboard = [
        [InlineKeyboardButton(WEEKDAYS[day], callback_data=f"{week}_{WEEKDAYS[day]}")]
        for day in EXPECTED_DAYS
    ]
    keyboard.append([InlineKeyboardButton("📅 Все дни", callback_data=f"{week}_all")])
    keyboard.append([InlineKeyboardButton("⬅ Назад", callback_data="back_to_week")])

    week_title = week.replace('week_', 'Неделя ')
    await safe_edit_message(
        query,
        f"Вы выбрали {week_title}. Выберите день:",
        InlineKeyboardMarkup(keyboard),
    )
    logger.info(f"✅ {username} ({uid}) выбрал {week}.")


@require_auth
async def day_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    uid = query.from_user.id
    username = query.from_user.username or query.from_user.full_name

    await query.answer()
    parts = query.data.split("_", 2)
    if len(parts) < 3:
        await safe_edit_message(query, "Некорректный запрос.")
        logger.warning(f"❌ {username} ({uid}) отправил некорректный callback: {query.data}")
        return

    week = parts[0] + "_" + parts[1]
    day_ru = parts[2]

    stats_manager.add_schedule_request()
    stats_manager.save()

    schedule = await fetch_schedule(context.application)
    if not schedule or week not in schedule:
        await safe_edit_message(query, "Расписание недоступно.")
        logger.error(f"Расписание не загружено для {week}.")
        return

    subgroup = user_manager.get_subgroup(uid)
    week_title = week.replace('week_', 'Неделя ')
    is_backup = bool(schedule.get("_is_backup"))
    backup_time = schedule.get("_backup_time")

    if day_ru == "all":
        week_data = schedule.get(week, {})
        text = format_week_schedule(
            week_title,
            week_data,
            user_subgroup=subgroup,
            is_backup=is_backup,
            backup_time=backup_time
        )
        keyboard = [[InlineKeyboardButton("⬅ Назад", callback_data="back_to_week")]]

        # Защита от лимита 4096 символов Telegram при выводе всей недели
        if len(text) > 4000:
            chunks = split_message_markdown(text, 4000)
            await safe_edit_message(query, chunks[0])
            for chunk in chunks[1:-1]:
                await query.message.reply_text(chunk, parse_mode="Markdown")
            await query.message.reply_text(chunks[-1], reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            logger.info(f"✅ {username} ({uid}) запросил расписание всей недели {week}.")
            return
    else:
        lessons = schedule.get(week, {}).get(day_ru, [])
        text = format_day_schedule(
            day_ru,
            lessons,
            user_subgroup=subgroup,
            is_backup=is_backup,
            backup_time=backup_time
        )

        # Проверяем заметки студента к предметам этого дня
        user_notes = notes_manager.get_user_notes(uid)
        day_notes = []
        for l in lessons:
            info_str = (l.get("info") or "").lower()
            for n in user_notes:
                if n.get("subject", "").lower() in info_str:
                    if n not in day_notes:
                        day_notes.append(n)

        if day_notes:
            text += "\n📝 *Ваши заметки на этот день:*\n"
            for n in day_notes:
                text += f"• *{n.get('subject')}*: {n.get('text')}\n"

        # Пагинация по дням недели (◀️ Вчера / Завтра ▶️)
        curr_idx = RU_WEEKDAYS_ORDER.index(day_ru) if day_ru in RU_WEEKDAYS_ORDER else 0
        prev_idx = (curr_idx - 1) % len(RU_WEEKDAYS_ORDER)
        next_idx = (curr_idx + 1) % len(RU_WEEKDAYS_ORDER)

        prev_day = RU_WEEKDAYS_ORDER[prev_idx]
        next_day = RU_WEEKDAYS_ORDER[next_idx]

        keyboard = [
            [
                InlineKeyboardButton(f"◀️ {prev_day[:2]}", callback_data=f"{week}_{prev_day}"),
                InlineKeyboardButton(f"📅 {day_ru}", callback_data=f"{week}"),
                InlineKeyboardButton(f"{next_day[:2]} ▶️", callback_data=f"{week}_{next_day}")
            ],
            [InlineKeyboardButton("⬅ Назад в меню", callback_data="back_to_week")]
        ]

    await safe_edit_message(
        query,
        text,
        InlineKeyboardMarkup(keyboard)
    )
    logger.info(f"✅ {username} ({uid}) запросил расписание: {week} → {day_ru} (подгруппа: {subgroup}).")



@require_auth
async def today_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    uid = query.from_user.id
    username = query.from_user.username or query.from_user.full_name

    await query.answer()
    schedule = await fetch_schedule(context.application)
    date_str, day_name, current_week = get_current_week_and_day(schedule)

    stats_manager.add_schedule_request()
    stats_manager.save()

    if not schedule or not current_week or current_week not in schedule:
        await safe_edit_message(query, "Расписание недоступно.")
        logger.error("Расписание не загружено для текущей недели.")
        return

    subgroup = user_manager.get_subgroup(uid)
    lessons = schedule.get(current_week, {}).get(day_name, [])
    is_backup = bool(schedule.get("_is_backup"))
    backup_time = schedule.get("_backup_time")

    header = f"📅 Сегодня ({date_str}, {day_name}):\n\n"
    if is_backup and backup_time:
        header = f"⚠️ _Сайт расписания недоступен. Копия от {backup_time}_\n\n" + header
    text = header + format_day_schedule(day_name, lessons, user_subgroup=subgroup)

    # Заметки
    user_notes = notes_manager.get_user_notes(uid)
    day_notes = []
    for l in lessons:
        info_str = (l.get("info") or "").lower()
        for n in user_notes:
            if n.get("subject", "").lower() in info_str:
                if n not in day_notes:
                    day_notes.append(n)

    if day_notes:
        text += "\n📝 *Ваши заметки на сегодня:*\n"
        for n in day_notes:
            text += f"• *{n.get('subject')}*: {n.get('text')}\n"

    # Кнопка перехода к завтрашнему дню
    keyboard = [
        [InlineKeyboardButton("🔜 Перейти на завтра", callback_data="tomorrow")],
        [InlineKeyboardButton("⬅ Назад в меню", callback_data="back_to_week")]
    ]

    await safe_edit_message(
        query,
        text,
        InlineKeyboardMarkup(keyboard)
    )
    logger.info(f"✅ {username} ({uid}) запросил расписание на сегодня (подгруппа: {subgroup}).")


@require_auth
async def tomorrow_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    uid = query.from_user.id
    username = query.from_user.username or query.from_user.full_name

    await query.answer()
    schedule = await fetch_schedule(context.application)
    date_str, day_name, week = get_tomorrow_week_and_day(schedule)

    stats_manager.add_schedule_request()
    stats_manager.save()

    if not schedule or not week or week not in schedule:
        await safe_edit_message(query, "Расписание недоступно.")
        logger.error("Расписание не загружено для завтрашнего дня.")
        return

    subgroup = user_manager.get_subgroup(uid)
    lessons = schedule.get(week, {}).get(day_name, [])
    is_backup = bool(schedule.get("_is_backup"))
    backup_time = schedule.get("_backup_time")

    header = f"📅 Завтра ({date_str}, {day_name}):\n\n"
    if is_backup and backup_time:
        header = f"⚠️ _Сайт расписания недоступен. Копия от {backup_time}_\n\n" + header
    text = header + format_day_schedule(day_name, lessons, user_subgroup=subgroup)

    # Заметки
    user_notes = notes_manager.get_user_notes(uid)
    day_notes = []
    for l in lessons:
        info_str = (l.get("info") or "").lower()
        for n in user_notes:
            if n.get("subject", "").lower() in info_str:
                if n not in day_notes:
                    day_notes.append(n)

    if day_notes:
        text += "\n📝 *Ваши заметки на завтра:*\n"
        for n in day_notes:
            text += f"• *{n.get('subject')}*: {n.get('text')}\n"

    keyboard = [
        [InlineKeyboardButton("📅 Вернуться на сегодня", callback_data="today")],
        [InlineKeyboardButton("⬅ Назад в меню", callback_data="back_to_week")]
    ]

    await safe_edit_message(
        query,
        text,
        InlineKeyboardMarkup(keyboard)
    )
    logger.info(f"✅ {username} ({uid}) запросил расписание на завтра (подгруппа: {subgroup}).")


@require_auth
async def session_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    uid = query.from_user.id
    username = query.from_user.username or query.from_user.full_name

    await query.answer()
    stats_manager.add_schedule_request()
    stats_manager.save()

    schedule = await fetch_schedule(context.application)

    if not schedule or "session" not in schedule or not schedule["session"]:
        await safe_edit_message(
            query,
            "Сессионное расписание недоступно.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Назад", callback_data="back_to_week")]])
        )
        logger.error("Сессионное расписание не загружено.")
        return

    subgroup = user_manager.get_subgroup(uid)
    is_backup = bool(schedule.get("_is_backup"))
    backup_time = schedule.get("_backup_time")

    text = "📅 Сессионное расписание:\n\n"
    if is_backup and backup_time:
        text = f"⚠️ _Сайт расписания недоступен. Копия от {backup_time}_\n\n" + text
    for day_name_ru, lessons in schedule["session"].items():
        text += format_day_schedule(day_name_ru, lessons, user_subgroup=subgroup, empty_text="Нет экзаменов.")

    await safe_edit_message(
        query,
        text,
        InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Назад", callback_data="back_to_week")]])
    )
    logger.info(f"✅ {username} ({uid}) запросил сессионное расписание.")