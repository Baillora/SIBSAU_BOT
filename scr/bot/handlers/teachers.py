from typing import Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from scr.parsers.teacher_parser import (
    fetch_teachers,
    fetch_consultations_for_teacher,
    fetch_pairs_for_teacher,
    teachers_cache,
)
from scr.core.settings import RU_WEEKDAYS_ORDER
from scr.core.logger import logger
from scr.bot.handlers.utils import safe_edit_message, require_auth, format_lessons


def ensure_teacher_cache(teacher_id: str) -> Dict[str, Any]:
    """Гарантирует, что структура в кэше есть даже после рестарта"""
    if teacher_id not in teachers_cache:
        teachers_cache[teacher_id] = {
            "name": None,
            "pairs": {},
            "consultations": [],
        }
    return teachers_cache[teacher_id]


def format_teacher_day_schedule(day_name: str, pairs_by_week: Dict[str, Any]) -> str:
    """Форматирование пар преподавателя по неделям"""
    text = f"🔹 {day_name}:\n\n"
    week1_lessons = pairs_by_week.get("1", [])
    week2_lessons = pairs_by_week.get("2", [])

    has_lessons = False
    if week1_lessons:
        has_lessons = True
        text += "📅 Первая неделя:\n\n" + format_lessons(week1_lessons) + "\n\n"

    if week2_lessons:
        has_lessons = True
        text += "📅 Вторая неделя:\n\n" + format_lessons(week2_lessons) + "\n\n"

    if not has_lessons:
        text += "Нет пар.\n\n"

    return text


@require_auth
async def teachers_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    uid = query.from_user.id
    username = query.from_user.username or query.from_user.full_name

    await query.answer()
    await fetch_teachers(context.application)

    keyboard = []
    for tid, t in teachers_cache.items():
        display_name = t.get("name") or f"Преподаватель {tid}"
        keyboard.append([InlineKeyboardButton(display_name, callback_data=f"teacher_{tid}")])

    keyboard.append([InlineKeyboardButton("⬅ Назад", callback_data="back_to_week")])

    await safe_edit_message(query, "Список преподавателей:", InlineKeyboardMarkup(keyboard))
    logger.info(f"✅ {username} ({uid}) открыл список преподавателей.")


@require_auth
async def teacher_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    uid = query.from_user.id
    username = query.from_user.username or query.from_user.full_name

    await query.answer()
    try:
        _, teacher_id = query.data.split("_", 1)
    except ValueError:
        await safe_edit_message(query, "Некорректный запрос.")
        logger.warning(f"❌ {username} ({uid}) отправил некорректный callback: {query.data}")
        return

    teacher = ensure_teacher_cache(teacher_id)
    if not teacher.get("name"):
        await fetch_teachers(context.application)
        teacher = teachers_cache.get(teacher_id, teacher)

    if not teacher.get("name"):
        await safe_edit_message(query, "Преподаватель не найден.")
        logger.warning(f"❌ {username} ({uid}) запросил несуществующего преподавателя: {teacher_id}")
        return

    keyboard = [
        [
            InlineKeyboardButton("Пары", callback_data=f"teacher_pairs_{teacher_id}"),
            InlineKeyboardButton("Консультации", callback_data=f"teacher_consult_{teacher_id}"),
        ],
        [InlineKeyboardButton("⬅ Назад", callback_data="teachers_list")],
    ]

    await safe_edit_message(query, f"Преподаватель: {teacher['name']}", InlineKeyboardMarkup(keyboard))
    logger.info(f"✅ {username} ({uid}) открыл профиль преподавателя: {teacher['name']} (ID: {teacher_id}).")


@require_auth
async def teacher_pairs_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    uid = query.from_user.id
    username = query.from_user.username or query.from_user.full_name

    await query.answer()
    try:
        _, _, teacher_id = query.data.split("_", 2)
    except ValueError:
        await safe_edit_message(query, "Неправильный callback.")
        logger.warning(f"❌ {username} ({uid}) отправил некорректный callback: {query.data}")
        return

    if teacher_id not in teachers_cache:
        await fetch_teachers(context.application)
    teacher = teachers_cache.get(teacher_id)
    if not teacher:
        await safe_edit_message(query, "Преподаватель не найден.")
        logger.warning(f"❌ {username} ({uid}) запросил несуществующего преподавателя: {teacher_id}")
        return

    pairs = await fetch_pairs_for_teacher(teacher_id)
    teacher["pairs"] = pairs

    keyboard = [[InlineKeyboardButton(day, callback_data=f"teacher_day_{teacher_id}_{day}")] for day in RU_WEEKDAYS_ORDER]
    keyboard.append([InlineKeyboardButton("📅 Все дни", callback_data=f"teacher_day_{teacher_id}_all")])
    keyboard.append([InlineKeyboardButton("⬅ Назад", callback_data=f"teacher_{teacher_id}")])

    await safe_edit_message(query, f"Выберите день у {teacher['name']}:", InlineKeyboardMarkup(keyboard))
    logger.info(f"✅ {username} ({uid}) запросил пары преподавателя: {teacher['name']} (ID: {teacher_id}).")


@require_auth
async def teacher_day_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    uid = query.from_user.id
    username = query.from_user.username or query.from_user.full_name

    await query.answer()
    parts = query.data.split("_")
    if len(parts) < 4 or parts[0] != "teacher" or parts[1] != "day":
        await safe_edit_message(query, "Неверный callback.")
        logger.warning(f"❌ {username} ({uid}) отправил некорректный callback: {query.data}")
        return

    if parts[2] == "all":
        teacher_id = parts[3]
        requested = "all"
    elif parts[-1] == "all":
        teacher_id = parts[2]
        requested = "all"
    else:
        teacher_id = parts[2]
        requested = "_".join(parts[3:])

    teacher = ensure_teacher_cache(teacher_id)
    if not teacher.get("pairs"):
        teacher["pairs"] = await fetch_pairs_for_teacher(teacher_id)

    pairs = teacher.get("pairs", {})

    if requested == "all":
        text = f"📅 Все пары ({teacher.get('name', teacher_id)}):\n\n"
        for d in RU_WEEKDAYS_ORDER:
            text += format_teacher_day_schedule(d, pairs.get(d, {"1": [], "2": []}))
    else:
        text = format_teacher_day_schedule(requested, pairs.get(requested, {"1": [], "2": []}))

    if len(text) > 4000:
        text = text[:3950] + "...\n(текст обрезан из-за ограничений Telegram)"

    keyboard = [[InlineKeyboardButton("⬅ Назад", callback_data=f"teacher_pairs_{teacher_id}")]]
    await safe_edit_message(query, text or "Нет пар.", InlineKeyboardMarkup(keyboard))
    logger.info(f"✅ {username} ({uid}) запросил расписание преподавателя {teacher_id} на {requested}.")


@require_auth
async def teacher_day_all_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Алиас для обратной совместимости"""
    await teacher_day_handler(update, context)


@require_auth
async def teacher_consult_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    uid = query.from_user.id
    username = query.from_user.username or query.from_user.full_name

    await query.answer()
    try:
        _, _, teacher_id = query.data.split("_", 2)
    except ValueError:
        await safe_edit_message(query, "Некорректный запрос.")
        logger.warning(f"❌ {username} ({uid}) отправил некорректный callback: {query.data}")
        return

    teacher = ensure_teacher_cache(teacher_id)
    if not teacher.get("consultations"):
        teacher["consultations"] = await fetch_consultations_for_teacher(teacher_id)

    consults = teacher.get("consultations", [])
    text = f"Консультации ({teacher.get('name', teacher_id)}):\n\n"
    if consults:
        for c in consults:
            text += f"📅 {c['date']} ⏰ {c['time']}\n{c['info']}\n\n"
    else:
        text += "Нет доступных консультаций."

    keyboard = [[InlineKeyboardButton("⬅ Назад", callback_data=f"teacher_{teacher_id}")]]
    await safe_edit_message(query, text, InlineKeyboardMarkup(keyboard))
    logger.info(f"✅ {username} ({uid}) запросил консультации преподавателя {teacher_id}.")
