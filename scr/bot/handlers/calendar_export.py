import io
import uuid
import datetime
from typing import Dict, Any, List
from telegram import Update
from telegram.ext import ContextTypes

from scr.core.settings import get_semester_start_date, WEEKDAYS, RU_WEEKDAYS_ORDER
from scr.core.users import user_manager
from scr.core.logger import logger
from scr.parsers.schedule_parser import fetch_schedule
from scr.bot.handlers.utils import require_auth


def escape_ical_text(text: str) -> str:
    """Экранирование специальных символов iCalendar (RFC 5545) для защиты от инъекций"""
    if not text:
        return ""
    text = text.replace("\\", "\\\\")
    text = text.replace(";", "\\;")
    text = text.replace(",", "\\,")
    text = text.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")
    return text.strip()


def generate_ical(schedule: Dict[str, Any], user_subgroup: str = "all", weeks_count: int = 18) -> str:
    """Генерация стандартного iCalendar (.ics) файла для всего семестра"""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//SIBSAU_BOT//Timetable//RU",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Расписание СибГУ",
        "X-WR-TIMEZONE:Asia/Krasnoyarsk",
    ]

    semester_start = get_semester_start_date()
    # Находим понедельник первой недели
    start_monday = semester_start - datetime.timedelta(days=semester_start.weekday())

    # Соответствие дня недели индексу (0 - Monday, ..., 6 - Sunday)
    day_to_idx = {
        "Понедельник": 0,
        "Вторник": 1,
        "Среда": 2,
        "Четверг": 3,
        "Пятница": 4,
        "Суббота": 5,
        "Воскресенье": 6,
    }

    now_utc_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    for week_offset in range(weeks_count):
        current_week_date = start_monday + datetime.timedelta(weeks=week_offset)
        week_key = "week_1" if (week_offset % 2 == 0) else "week_2"
        week_schedule = schedule.get(week_key, {})

        for day_name, day_lessons in week_schedule.items():
            if day_name not in day_to_idx:
                continue

            day_idx = day_to_idx[day_name]
            lesson_date = current_week_date + datetime.timedelta(days=day_idx)
            date_prefix = lesson_date.strftime("%Y%m%d")

            for lesson in day_lessons:
                subgroup = lesson.get("subgroup")
                if user_subgroup in ("1", "2") and subgroup:
                    if user_subgroup == "1" and ("1" not in subgroup and "1️⃣" not in subgroup):
                        continue
                    elif user_subgroup == "2" and ("2" not in subgroup and "2️⃣" not in subgroup):
                        continue

                time_str = lesson.get("time", "").strip()
                if "-" not in time_str:
                    continue

                start_time_str, end_time_str = time_str.split("-")
                try:
                    start_h, start_m = map(int, start_time_str.strip().split(":"))
                    end_h, end_m = map(int, end_time_str.strip().split(":"))
                except ValueError:
                    continue

                dtstart = f"{date_prefix}T{start_h:02d}{start_m:02d}00"
                dtend = f"{date_prefix}T{end_h:02d}{end_m:02d}00"

                info_lines = [ln.strip() for ln in (lesson.get("info") or "").split("\n") if ln.strip()]
                summary = info_lines[0].replace("*", "").strip() if info_lines else "Занятие"
                if subgroup:
                    summary += f" ({subgroup})"

                description_lines = []
                if len(info_lines) > 1:
                    description_lines.extend(info_lines[1:])
                if subgroup:
                    description_lines.append(f"Подгруппа: {subgroup}")
                raw_description = "\n".join(description_lines)

                summary_escaped = escape_ical_text(summary)
                description_escaped = escape_ical_text(raw_description)
                location_escaped = escape_ical_text(lesson.get("classroom") or "")

                uid = f"{uuid.uuid4()}@sibsau_bot"

                lines.extend([
                    "BEGIN:VEVENT",
                    f"UID:{uid}",
                    f"DTSTAMP:{now_utc_str}",
                    f"DTSTART:{dtstart}",
                    f"DTEND:{dtend}",
                    f"SUMMARY:{summary_escaped}",
                    f"DESCRIPTION:{description_escaped}",
                    f"LOCATION:{location_escaped}",
                    "STATUS:CONFIRMED",
                    "END:VEVENT",
                ])

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


@require_auth
async def export_calendar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Генерация и отправка файла .ics с расписанием (работает для команды и callback-кнопки)"""
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    query = update.callback_query
    if query:
        await query.answer("⏳ Генерирую календарь (.ics)...", show_alert=False)

    schedule = await fetch_schedule(context.application)
    if not schedule:
        msg = "Расписание недоступно для экспорта."
        if query and query.message:
            await query.message.reply_text(msg)
        elif update.message:
            await update.message.reply_text(msg)
        return

    subgroup = user_manager.get_subgroup(uid)
    subgroup_label = f"{subgroup} подгруппа" if subgroup in ("1", "2") else "все подгруппы"

    if update.message:
        await update.message.reply_text(f"⏳ Генерирую календарь (.ics) на семестр (фильтр: {subgroup_label})...")

    ics_content = generate_ical(schedule, user_subgroup=subgroup)
    file_bytes = io.BytesIO(ics_content.encode("utf-8"))
    file_bytes.name = f"schedule_sibsau_{subgroup}.ics"

    caption = (
        "📅 *Ваше расписание в формате iCalendar (.ics)*\n\n"
        "📥 *Как использовать:*\n"
        "1. Скачайте файл на телефон или компьютер.\n"
        "2. Откройте его через Google Calendar, Apple Calendar или Яндекс.Календарь.\n"
        "3. Все пары на семестр появятся в вашем календаре с напоминаниями!"
    )

    await context.bot.send_document(
        chat_id=uid,
        document=file_bytes,
        filename=f"schedule_sibsau_{subgroup}.ics",
        caption=caption,
        parse_mode="Markdown"
    )
    logger.info(f"✅ {username} ({uid}) экспортировал расписание в iCal ({subgroup_label}).")
