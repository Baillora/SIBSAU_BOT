import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from scr.parsers.schedule_parser import fetch_schedule, get_current_week_and_day, get_tomorrow_week_and_day
from scr.core.stats import stats, save_stats, increment_user_commands
from scr.core.settings import WEEKDAYS, EXPECTED_DAYS, RU_WEEKDAYS_ORDER
from scr.core.users import is_user_allowed
from scr.core.logger import logger
from .utils import safe_edit_message

def escape_markdown(text: str) -> str:
    return text.replace('_', r'\_').replace('*', r'\*')

async def week_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    username = query.from_user.username or query.from_user.full_name

    if not is_user_allowed(uid):
        await query.answer("У вас нет доступа к расписанию.", show_alert=True)
        logger.warning(f"❌ {username} ({uid}) попытался открыть недели без доступа.")
        return

    await query.answer()
    week = query.data  # week_1 или week_2
    schedule = await fetch_schedule(context.application)

    stats["schedule_requests"] += 1
    increment_user_commands(update.effective_user.id)
    save_stats()

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

    await safe_edit_message(
        query,
        f"Вы выбрали {week.replace('week_', 'Неделя ')}. Выберите день:",
        InlineKeyboardMarkup(keyboard),
    )
    logger.info(f"✅ {username} ({uid}) выбрал {week}.")

async def day_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    username = query.from_user.username or query.from_user.full_name

    if not is_user_allowed(uid):
        await query.answer("У вас нет доступа к расписанию.", show_alert=True)
        logger.warning(f"❌ {username} ({uid}) попытался открыть день без доступа.")
        return

    # ожидаем callback вида: week_1_Понедельник или week_1_all
    await query.answer()
    parts = query.data.split("_", 2)
    if len(parts) < 3:
        await safe_edit_message(query, "Некорректный запрос.")
        logger.warning(f"❌ {username} ({uid}) отправил некорректный callback: {query.data}")
        return

    week = parts[0] + "_" + parts[1]
    day_ru = parts[2]

    schedule = await fetch_schedule(context.application)
    if not schedule or week not in schedule:
        await safe_edit_message(query, "Расписание недоступно.")
        logger.error(f"Расписание не загружено для {week}.")
        return

    if day_ru == "all":
        text = f"📅 Расписание ({week.replace('week_', 'Неделя ')}):\n\n"
        for day in RU_WEEKDAYS_ORDER:
            lessons = schedule.get(week, {}).get(day, [])
            text += f"🔹 {day}:\n\n"
            if lessons:
                # сгруппировать по времени
                grouped = {}
                order = []
                for l in lessons:
                    t = l.get("time", "")
                    if t not in grouped:
                        grouped[t] = []
                        order.append(t)
                    grouped[t].append(l)
                for t in order:
                    text += f"⏰{t}\n"
                    for entry in grouped[t]:
                        subgroup = entry.get("subgroup")
                        info_lines = [ln for ln in (entry.get("info") or "").split("\n") if ln.strip()]
                        subject = info_lines[0] if info_lines else ""
                        rest = "\n".join(info_lines[1:]) if len(info_lines) > 1 else ""
                        if subgroup:
                            text += f"🔸 {subgroup}\n"
                        if subject:
                            text += f"📚 *{subject}*\n"
                        if rest:
                            text += rest + "\n"
                        classroom = entry.get("classroom")
                        if classroom:
                            text += f"📍 {classroom}\n"
                            text += "\n"
                        else:
                            text += "Нет пар.\n\n"
    else:
        lessons = schedule.get(week, {}).get(day_ru, [])
        text = f"🔹 {day_ru}:\n\n"
        if lessons:
            grouped = {}
            order = []
            for l in lessons:
                t = l.get("time", "")
                if t not in grouped:
                    grouped[t] = []
                    order.append(t)
                grouped[t].append(l)
            for t in order:
                text += f"⏰{t}\n"
                for entry in grouped[t]:
                    subgroup = entry.get("subgroup")
                    info_lines = [ln for ln in (entry.get("info") or "").split("\n") if ln.strip()]
                    subject = info_lines[0] if info_lines else ""
                    rest = "\n".join(info_lines[1:]) if len(info_lines) > 1 else ""
                    if subgroup:
                        text += f"🔸 {subgroup}\n"
                    if subject:
                        text += f"📚 *{subject}*\n"
                    if rest:
                        text += rest + "\n"
                        classroom = entry.get("classroom")
                    if classroom:
                        text += f"📍 {classroom}\n"
                    text += "\n"
        else:
            text += "Нет пар."

    await safe_edit_message(
        query,
        text,
        InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Назад", callback_data="back_to_week")]])
    )
    logger.info(f"✅ {username} ({uid}) запросил расписание: {week} → {day_ru}.")

async def today_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    username = query.from_user.username or query.from_user.full_name

    if not is_user_allowed(uid):
        await query.answer("У вас нет доступа к расписанию.", show_alert=True)
        logger.warning(f"❌ {username} ({uid}) попытался посмотреть 'сегодня' без доступа.")
        return

    await query.answer()
    date_str, day_name, current_week = get_current_week_and_day()
    schedule = await fetch_schedule(context.application)

    if not schedule or current_week not in schedule:
        await safe_edit_message(query, "Расписание недоступно.")
        logger.error("Расписание не загружено для текущей недели.")
        return

    lessons = schedule.get(current_week, {}).get(day_name, [])
    text = f"📅 Сегодня ({date_str}, {day_name}):\n\n"
    if lessons:
        # сгруппировать по времени
        grouped = {}
        order = []
        for l in lessons:
            t = l.get("time", "")
            if t not in grouped:
                grouped[t] = []
                order.append(t)
            grouped[t].append(l)
        for t in order:
            text += f"⏰{t}\n"
            for entry in grouped[t]:
                subgroup = entry.get("subgroup")
                info_lines = [ln for ln in (entry.get("info") or "").split("\n") if ln.strip()]
                subject = info_lines[0] if info_lines else ""
                rest = "\n".join(info_lines[1:]) if len(info_lines) > 1 else ""
                if subgroup:
                    text += f"🔸 {subgroup}\n"
                if subject:
                    text += f"📚 *{subject}*\n"
                if rest:
                    text += rest + "\n"
                classroom = entry.get("classroom")
                if classroom:
                    text += f"📍 {classroom}\n"
                text += "\n"
    else:
        text += "Нет пар."

    await safe_edit_message(
        query,
        text,
        InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Назад", callback_data="back_to_week")]])
    )
    logger.info(f"✅ {username} ({uid}) запросил расписание на сегодня.")

async def tomorrow_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    username = query.from_user.username or query.from_user.full_name

    if not is_user_allowed(uid):
        await query.answer("У вас нет доступа к расписанию.", show_alert=True)
        logger.warning(f"❌ {username} ({uid}) попытался посмотреть 'завтра' без доступа.")
        return

    await query.answer()
    date_str, day_name, week = get_tomorrow_week_and_day()
    schedule = await fetch_schedule(context.application)

    if not schedule or week not in schedule:
        await safe_edit_message(query, "Расписание недоступно.")
        logger.error("Расписание не загружено для завтрашнего дня.")
        return

    lessons = schedule.get(week, {}).get(day_name, [])
    text = f"📅 Завтра ({date_str}, {day_name}):\n\n"
    if lessons:
        grouped = {}
        order = []
        for l in lessons:
            t = l.get("time", "")
            if t not in grouped:
                grouped[t] = []
                order.append(t)
            grouped[t].append(l)
        for t in order:
            text += f"⏰{t}\n"
            for entry in grouped[t]:
                subgroup = entry.get("subgroup")
                info_lines = [ln for ln in (entry.get("info") or "").split("\n") if ln.strip()]
                subject = info_lines[0] if info_lines else ""
                rest = "\n".join(info_lines[1:]) if len(info_lines) > 1 else ""
                if subgroup:
                    text += f"🔸 {subgroup}\n"
                if subject:
                    text += f"📚 *{subject}*\n"
                if rest:
                    text += rest + "\n"
                classroom = entry.get("classroom")
                if classroom:
                    text += f"📍 {classroom}\n"
                text += "\n"
    else:
        text += "Нет пар."

    await safe_edit_message(
        query,
        text,
        InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Назад", callback_data="back_to_week")]])
    )
    logger.info(f"✅ {username} ({uid}) запросил расписание на завтра.")

async def session_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    username = query.from_user.username or query.from_user.full_name

    if not is_user_allowed(uid):
        await query.answer("У вас нет доступа к расписанию.", show_alert=True)
        logger.warning(f"❌ {username} ({uid}) попытался открыть сессию без доступа.")
        return

    await query.answer()
    schedule = await fetch_schedule(context.application)

    if not schedule or "session" not in schedule or not schedule["session"]:
        await safe_edit_message(
            query,
            "Сессионное расписание недоступно.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Назад", callback_data="back_to_week")]])
        )
        logger.error("Сессионное расписание не загружено.")
        return

    text = "📅 Сессионное расписание:\n\n"
    # Сортируем дни в порядке недели (если нужно)
    for day_name_ru, lessons in schedule["session"].items():
        text += f"🔹 {day_name_ru}:\n\n"
        if lessons:
            grouped = {}
            order = []
            for l in lessons:
                t = l.get("time", "")
                if t not in grouped:
                    grouped[t] = []
                    order.append(t)
                grouped[t].append(l)
            for t in order:
                text += f"⏰{t}\n"
                for entry in grouped[t]:
                    subgroup = entry.get("subgroup")
                    classroom = entry.get("classroom")
                    info_lines = [ln for ln in (entry.get("info") or "").split("\n") if ln.strip()]
                    subject = info_lines[0] if info_lines else ""
                    rest = "\n".join(info_lines[1:]) if len(info_lines) > 1 else ""
                    if subgroup:
                        text += f"🔸 {subgroup}\n"
                    if subject:
                        text += f"📚 {subject}\n"
                    if rest:
                        text += rest + "\n"
                    if classroom:
                        text += f"📍 {classroom}\n"
                    text += "\n"
        else:
            text += "Нет экзаменов.\n\n"

    await safe_edit_message(
        query,
        text,
        InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Назад", callback_data="back_to_week")]])
    )
    logger.info(f"✅ {username} ({uid}) запросил сессионное расписание.")