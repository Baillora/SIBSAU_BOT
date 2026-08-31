import uuid
from typing import List
from telegram import Update, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import ContextTypes

from scr.parsers.schedule_parser import (
    fetch_schedule,
    get_current_week_and_day,
    get_tomorrow_week_and_day,
    get_current_and_next_lesson,
)
from scr.parsers.teacher_parser import fetch_teachers, teachers_cache
from scr.core.users import user_manager
from scr.core.stats import stats_manager
from scr.core.logger import logger
from scr.bot.handlers.utils import format_day_schedule, format_lessons, render_progress_bar


async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик Inline-запросов (@bot_name <query>)"""
    query_obj = update.inline_query
    if not query_obj:
        return

    uid = query_obj.from_user.id
    raw_query = query_obj.query.strip().lower()

    stats_manager.record_activity(uid, is_command=False)
    stats_manager.save()

    if not user_manager.is_allowed(uid):
        results = [
            InlineQueryResultArticle(
                id=str(uuid.uuid4()),
                title="🔒 Доступ ограничен",
                description="Вы не авторизованы для использования этого бота.",
                input_message_content=InputTextMessageContent(
                    f"⚠️ У вас нет доступа к расписанию.\nСообщите ваш ID: `{uid}` администратору.",
                    parse_mode="Markdown"
                )
            )
        ]
        await query_obj.answer(results, cache_time=10, is_personal=True)
        return

    user_subgroup = user_manager.get_subgroup(uid)
    schedule = await fetch_schedule(context.application)
    results: List[InlineQueryResultArticle] = []

    # 1. Если запрос пустой — показываем быстрые сводки (Сегодня, Завтра, Сейчас, Недели)
    if not raw_query:
        # Сегодня
        date_str, day_name, current_week = get_current_week_and_day(schedule)
        today_lessons = schedule.get(current_week, {}).get(day_name, []) if schedule else []
        today_text = f"📅 *Расписание на сегодня* ({date_str}, {day_name}):\n\n" + format_day_schedule(day_name, today_lessons, user_subgroup=user_subgroup)

        results.append(
            InlineQueryResultArticle(
                id="today_schedule",
                title="📅 Расписание на сегодня",
                description=f"{date_str}, {day_name} ({'1-я' if current_week == 'week_1' else '2-я'} неделя)",
                input_message_content=InputTextMessageContent(today_text, parse_mode="Markdown")
            )
        )

        # Завтра
        t_date, t_day, t_week = get_tomorrow_week_and_day(schedule)
        tomorrow_lessons = schedule.get(t_week, {}).get(t_day, []) if schedule else []
        tomorrow_text = f"📅 *Расписание на завтра* ({t_date}, {t_day}):\n\n" + format_day_schedule(t_day, tomorrow_lessons, user_subgroup=user_subgroup)

        results.append(
            InlineQueryResultArticle(
                id="tomorrow_schedule",
                title="🔜 Расписание на завтра",
                description=f"{t_date}, {t_day}",
                input_message_content=InputTextMessageContent(tomorrow_text, parse_mode="Markdown")
            )
        )

        # Текущая пара
        current_l, time_until_end, next_l, time_until_next = get_current_and_next_lesson(schedule, current_week, day_name) if schedule else (None, None, None, None)
        status_text = "🎓 *Текущий статус пар:*\n\n"
        if current_l:
            info_lines = [ln.strip() for ln in (current_l.get("info") or "").split("\n") if ln.strip()]
            subject = info_lines[0].replace("*", "").strip() if info_lines else "Пара"
            classroom = current_l.get("classroom", "")
            status_text += f"🟢 *Сейчас идёт:* {subject}\n"
            if time_until_end is not None:
                status_text += f"⏳ До конца: {time_until_end} мин\n"
            if classroom:
                status_text += f"📍 {classroom}\n"
        else:
            status_text += "⚪ Сейчас пар нет.\n"

        if next_l:
            info_lines = [ln.strip() for ln in (next_l.get("info") or "").split("\n") if ln.strip()]
            subject = info_lines[0].replace("*", "").strip() if info_lines else "Пара"
            classroom = next_l.get("classroom", "")
            status_text += f"\n🔜 *Следующая пара:* {subject}\n"
            if time_until_next is not None:
                status_text += f"⏰ Через: {time_until_next} мин\n"
            if classroom:
                status_text += f"📍 {classroom}\n"

        results.append(
            InlineQueryResultArticle(
                id="current_status",
                title="🎓 Текущая и следующая пара",
                description="Статус пар прямо сейчас",
                input_message_content=InputTextMessageContent(status_text, parse_mode="Markdown")
            )
        )

    # 2. Если запрос задан — поиск по расписанию и преподавателям
    else:
        # Поиск по расписанию
        if schedule:
            for week_k in ["week_1", "week_2"]:
                week_title = "1-я неделя" if week_k == "week_1" else "2-я неделя"
                for day_n, lessons in schedule.get(week_k, {}).items():
                    if str(day_n).startswith("_"):
                        continue
                    matching_lessons = []
                    for l in lessons:
                        full_info = (l.get("info", "") + " " + l.get("classroom", "") + " " + (l.get("subgroup") or "")).lower()
                        if raw_query in full_info:
                            matching_lessons.append(l)

                    if matching_lessons:
                        msg_text = f"🔍 *Найдено в расписании* ({week_title} — {day_n}):\n\n" + format_lessons(matching_lessons, user_subgroup=user_subgroup)
                        results.append(
                            InlineQueryResultArticle(
                                id=str(uuid.uuid4()),
                                title=f"📅 {week_title} — {day_n}",
                                description=f"Найдено {len(matching_lessons)} пар(ы) по запросу '{raw_query}'",
                                input_message_content=InputTextMessageContent(msg_text, parse_mode="Markdown")
                            )
                        )

        # Поиск по преподавателям
        await fetch_teachers(context.application)
        for tid, t in teachers_cache.items():
            t_name = t.get("name") or ""
            if raw_query in t_name.lower():
                teacher_text = (
                    f"👨‍🏫 *Преподаватель:* {t_name}\n"
                    f"🔗 [Профиль на сайте Паллада]({t.get('href')})\n\n"
                    f"Для просмотра консультаций и пар откройте бота."
                )
                results.append(
                    InlineQueryResultArticle(
                        id=f"teacher_{tid}",
                        title=f"👨‍🏫 {t_name}",
                        description="Преподаватель СибГУ",
                        input_message_content=InputTextMessageContent(teacher_text, parse_mode="Markdown")
                    )
                )

    await query_obj.answer(results[:25], cache_time=15, is_personal=True)
    logger.info(f"✅ Inline-запрос от {uid}: '{raw_query}' -> {len(results)} ответов.")
