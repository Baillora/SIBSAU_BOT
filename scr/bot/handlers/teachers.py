from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from scr.parsers.teacher_parser import (
    fetch_teachers,
    fetch_consultations_for_teacher,
    fetch_pairs_for_teacher,
    teachers_cache,
)
from scr.core.users import UserManager, is_user_allowed
from scr.core.settings import OWNER_ID, RU_WEEKDAYS_ORDER
from scr.core.logger import logger

from .utils import safe_edit_message

users = UserManager(owner_id=OWNER_ID)

def ensure_teacher_cache(teacher_id: str):
    """Гарантирует, что структура в кэше есть даже после рестарта"""
    if teacher_id not in teachers_cache:
        teachers_cache[teacher_id] = {
            "name": None,
            "pairs": {},
            "consultations": [],
        }
    return teachers_cache[teacher_id]


async def teachers_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    username = query.from_user.username or query.from_user.full_name

    if not is_user_allowed(uid):
        await query.answer("Нет доступа.", show_alert=True)
        await query.edit_message_text("Нет доступа.")
        logger.warning(f"❌ {username} ({uid}) попытался открыть список преподавателей без доступа.")
        return

    await query.answer()

    if not users.is_allowed(update.effective_user.id):
        await safe_edit_message(query, "Нет доступа.")
        return

    await fetch_teachers(context.application)

    keyboard = []
    for tid, t in teachers_cache.items():
        display_name = t.get("name") or f"Преподаватель {tid}"
        keyboard.append([InlineKeyboardButton(display_name, callback_data=f"teacher_{tid}")])

    keyboard.append([InlineKeyboardButton("⬅ Назад", callback_data="back_to_week")])

    await safe_edit_message(query, "Список преподавателей:", InlineKeyboardMarkup(keyboard))
    logger.info(f"✅ {username} ({uid}) открыл список преподавателей.")


async def teacher_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    username = query.from_user.username or query.from_user.full_name

    if not is_user_allowed(uid):
        await query.answer("Нет доступа.", show_alert=True)
        logger.warning(f"❌ {username} ({uid}) попытался открыть профиль преподавателя без доступа.")
        return

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


async def teacher_pairs_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    username = query.from_user.username or query.from_user.full_name

    if not is_user_allowed(uid):
        await query.answer("Нет доступа.", show_alert=True)
        logger.warning(f"❌ {username} ({uid}) попытался открыть пары преподавателя без доступа.")
        return

    await query.answer()
    # ожидаем callback "teacher_pairs_{teacher_id}"
    try:
        _, _, teacher_id = query.data.split("_", 2)
    except ValueError:
        await safe_edit_message(query, "Неправильный callback.")
        logger.warning(f"❌ {username} ({uid}) отправил некорректный callback: {query.data}")
        return

    # гарантируем, что преподаватель в кэше
    if teacher_id not in teachers_cache:
        await fetch_teachers(context.application)
    teacher = teachers_cache.get(teacher_id)
    if not teacher:
        await safe_edit_message(query, "Преподаватель не найден.")
        logger.warning(f"❌ {username} ({uid}) запросил несуществующего преподавателя: {teacher_id}")
        return

    # получить пары (парсер возвращает структуру {day: {"1": [], "2": []}})
    pairs = await fetch_pairs_for_teacher(teacher_id)
    teacher["pairs"] = pairs  # обновляем внутри кэша

    # Кнопки — дни + Все дни
    keyboard = [[InlineKeyboardButton(day, callback_data=f"teacher_day_{teacher_id}_{day}")] for day in RU_WEEKDAYS_ORDER]
    # оставляем формат callback как teacher_day_{teacher_id}_all — handler умеет его разбирать
    keyboard.append([InlineKeyboardButton("Все дни", callback_data=f"teacher_day_{teacher_id}_all")])
    keyboard.append([InlineKeyboardButton("⬅ Назад", callback_data=f"teacher_{teacher_id}")])

    await safe_edit_message(query, f"Выберите день у {teacher['name']}", InlineKeyboardMarkup(keyboard))
    logger.info(f"✅ {username} ({uid}) запросил пары преподавателя: {teacher['name']} (ID: {teacher_id}).")


async def teacher_day_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
      - teacher_day_{teacher_id}_{day}
      - teacher_day_{teacher_id}_all
      - teacher_day_all_{teacher_id}
    """
    query = update.callback_query
    uid = query.from_user.id
    username = query.from_user.username or query.from_user.full_name

    if not is_user_allowed(uid):
        await query.answer("Нет доступа.", show_alert=True)
        logger.warning(f"❌ {username} ({uid}) попытался открыть расписание преподавателя без доступа.")
        return

    await query.answer()
    parts = query.data.split("_")
    # минимальная длина "teacher_day_x_y" -> >=4
    if len(parts) < 4 or parts[0] != "teacher" or parts[1] != "day":
        await safe_edit_message(query, "Неверный callback.")
        logger.warning(f"❌ {username} ({uid}) отправил некорректный callback: {query.data}")
        return

    # Форматы
    # teacher_day_{teacher_id}_{day}
    # teacher_day_{teacher_id}_all
    # teacher_day_all_{teacher_id}

    if parts[2] == "all" and len(parts) >= 4:
        #teacher_day_all_{teacher_id}
        teacher_id = parts[3]
        requested = "all"
    elif parts[-1] == "all":
        #teacher_day_{teacher_id}_all
        teacher_id = parts[2]
        requested = "all"
    else:
        teacher_id = parts[2]
        requested = "_".join(parts[3:])  # имя дня

    teacher = ensure_teacher_cache(teacher_id)
    pairs = teacher.get("pairs", {})

    text = ""
    if requested == "all":
        for d in RU_WEEKDAYS_ORDER:
            text += format_day_schedule(d, pairs.get(d, {"1": [], "2": []}))
    else:
        text = format_day_schedule(requested, pairs.get(requested, {"1": [], "2": []}))

    await safe_edit_message(
        query,
        text or "Нет пар.",
        InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Назад", callback_data=f"teacher_pairs_{teacher_id}")]])
    )
    logger.info(f"✅ {username} ({uid}) запросил расписание преподавателя {teacher_id} на {requested}.")


def format_day_schedule(day_name: str, pairs_by_week: dict) -> str:
    """Форматирование пар преподавателя в стиле расписания студентов"""
    text = f"🔹 {day_name}:\n\n"

    def format_lessons(lessons):
        out = ""
        # сгруппируем по времени (если несколько записей на одно время => подгруппы)
        grouped = {}
        order = []
        for l in lessons:
            t = l.get("time", "")
            if t not in grouped:
                grouped[t] = []
                order.append(t)
            grouped[t].append(l)

        for t in order:
            out += f"⏰ {t}\n"
            for entry in grouped[t]:
                subgroup = entry.get("subgroup")
                # info — уже форматирован в парсере (subject + остальные строки)
                info_lines = [ln for ln in (entry.get("info") or "").split("\n") if ln.strip()]
                subject = info_lines[0] if info_lines else ""
                rest = "\n".join(info_lines[1:]) if len(info_lines) > 1 else ""

                if subgroup:
                    # делаем замену 1 подгруппа -> 1️⃣ подгруппа в парсере
                    subgroup = subgroup.replace("1 подгруппа", "1️⃣ подгруппа").replace("2 подгруппа", "2️⃣ подгруппа")
                    out += f"🔸 {subgroup}\n"

                if subject:
                    out += f"📚 *{subject}\n"
                if rest:
                    out += rest + "\n"

                out += "\n"
        return out

    if pairs_by_week.get("1"):
        text += "📅 Первая неделя\n\n" + format_lessons(pairs_by_week["1"])
    if pairs_by_week.get("2"):
        text += "📅 Вторая неделя\n\n" + format_lessons(pairs_by_week["2"])
    if not pairs_by_week.get("1") and not pairs_by_week.get("2"):
        text += "Нет пар.\n"

    return text + "\n"


async def teacher_day_all_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Доп. обработчик на случай, если где-то зарегистрирован отдельный хэндлер
    с другим форматом callback
    Поддерживает форматы:
      - teacher_day_all_{teacher_id}
      - teacher_day_{teacher_id}_all
    """
    query = update.callback_query
    uid = query.from_user.id
    username = query.from_user.username or query.from_user.full_name

    if not is_user_allowed(uid):
        await query.answer("Нет доступа.", show_alert=True)
        logger.warning(f"❌ {username} ({uid}) попытался открыть все пары преподавателя без доступа.")
        return

    await query.answer()
    parts = query.data.split("_")
    teacher_id = None
    if len(parts) >= 4:
        if parts[2] == "all":
            teacher_id = parts[3]
        elif parts[-1] == "all":
            teacher_id = parts[2]
    if not teacher_id:
        await safe_edit_message(query, "Неверный callback.")
        logger.warning(f"❌ {username} ({uid}) отправил некорректный callback: {query.data}")
        return

    teacher = ensure_teacher_cache(teacher_id)
    pairs = teacher.get("pairs", {})
    text = f"📅 Все пары у {teacher.get('name', teacher_id)}:\n\n"

    for day in RU_WEEKDAYS_ORDER:
        text += format_day_schedule(day, pairs.get(day, {"1": [], "2": []}))

    if not pairs or all((not lessons.get("1") and not lessons.get("2")) for lessons in pairs.values()):
        text += "Нет пар."

    if len(text) > 4000:
        text = text[:3990] + "...\n(дальше см. следующую страницу)"

    keyboard = [[InlineKeyboardButton("⬅ Назад", callback_data=f"teacher_pairs_{teacher_id}")]]
    await safe_edit_message(query, text, InlineKeyboardMarkup(keyboard))
    logger.info(f"✅ {username} ({uid}) запросил все пары преподавателя {teacher_id}.")


async def teacher_consult_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    username = query.from_user.username or query.from_user.full_name

    if not is_user_allowed(uid):
        await query.answer("Нет доступа.", show_alert=True)
        logger.warning(f"❌ {username} ({uid}) попытался открыть консультации преподавателя без доступа.")
        return

    await query.answer()
    try:
        _, _, teacher_id = query.data.split("_", 2)
    except ValueError:
        await safe_edit_message(query, "Некорректный запрос.")
        logger.warning(f"❌ {username} ({uid}) отправил некорректный callback: {query.data}")
        return

    teacher = ensure_teacher_cache(teacher_id)
    if not teacher["consultations"]:
        teacher["consultations"] = await fetch_consultations_for_teacher(teacher_id)

    consults = teacher["consultations"]
    text = f"Консультации {teacher.get('name', teacher_id)}:\n\n"
    if consults:
        for c in consults:
            text += f"{c['date']} ⏰ {c['time']}\n{c['info']}\n\n"
    else:
        text += "Нет доступных консультаций."

    await safe_edit_message(query, text, InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅ Назад", callback_data=f"teacher_{teacher_id}")]]
    ))
    logger.info(f"✅ {username} ({uid}) запросил консультации преподавателя {teacher_id}.")
