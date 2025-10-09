import httpx, re, datetime
from bs4 import BeautifulSoup
from cachetools import TTLCache
from scr.core.settings import SCHEDULE_URL, WEEKDAYS, EXPECTED_DAYS, LESSON_SCHEDULE, CACHE_EXPIRY
from scr.core.logger import logger

# TTL-кэши
schedule_cache = TTLCache(maxsize=100, ttl=CACHE_EXPIRY)


async def notify_admin(application, message: str):
    """Отправка ошибок админу"""
    from scr.core.settings import OWNER_ID
    try:
        await application.bot.send_message(chat_id=OWNER_ID, text=message)
    except Exception as e:
        logger.error(f"Не удалось уведомить администратора: {e}")


async def fetch_schedule(application):
    """Основной парсинг расписания"""
    if len(schedule_cache) > 0:
        logger.info("Используется кэш расписания (TTLCache).")
        return schedule_cache

    logger.info("Обновление расписания с сайта.")
    schedule = {}

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.get(SCHEDULE_URL)
            response.raise_for_status()
        except httpx.RequestError as e:
            logger.error(f"Ошибка при получении страницы расписания: {e}")
            await notify_admin(application, f"Ошибка при получении страницы расписания: {e}")
            return schedule_cache

    soup = BeautifulSoup(response.content, "html.parser")

    try:
        for week_num in [1, 2]:
            week_key = f"week_{week_num}"
            week_tab = soup.find("div", {"id": f"week_{week_num}_tab"})
            schedule[week_key] = {}

            if not week_tab:
                logger.warning(f"Вкладка недели {week_key} не найдена.")
                for day in EXPECTED_DAYS:
                    schedule[week_key][WEEKDAYS[day]] = []
                continue

            days = week_tab.find_all("div", class_="day")
            for day in days:
                day_classes_lower = [c.lower() for c in day.get("class", [])]
                weekday_class = next((c for c in EXPECTED_DAYS if c.lower() in day_classes_lower), None)
                if not weekday_class:
                    continue
                day_name_ru = WEEKDAYS[weekday_class]

                if "today" in day_classes_lower:
                    schedule[week_key]["_today_day"] = day_name_ru

                schedule[week_key][day_name_ru] = []
                lines = day.find_all("div", class_="line")

                seen_lessons = set()

                for line in lines:
                    time_div = line.find("div", class_="time")
                    discipline_div = line.find("div", class_="discipline")
                    if not time_div or not discipline_div:
                        continue

                    time_text = _extract_time(time_div.get_text(separator=" ", strip=True))

                    # Получаем все блоки (подгруппы или один блок)
                    subgroup_blocks = discipline_div.find_all("div", class_=re.compile(r"col-md"))
                    blocks_to_process = subgroup_blocks if subgroup_blocks else [discipline_div]

                    for block in blocks_to_process:
                        # Извлекаем "чистый" текст для сравнения
                        raw_text = block.get_text(separator="|", strip=True)
                        lesson_key = (time_text, raw_text)

                        if lesson_key in seen_lessons:
                            continue  # пропускаем дубль
                        seen_lessons.add(lesson_key)

                        _append_lesson(schedule, week_key, day_name_ru, time_text, block)

            # добиваем пустые дни
            for day in EXPECTED_DAYS:
                schedule[week_key].setdefault(WEEKDAYS[day], [])

        # Парсим сессию
        session_tab = soup.find("div", {"id": "session_tab"})
        schedule["session"] = {}
        if session_tab:
            for day in session_tab.find_all("div", class_="day"):
                day_name_div = day.find("div", class_="name")
                if not day_name_div:
                    continue
                day_name_ru = day_name_div.get_text(strip=True)
                schedule["session"][day_name_ru] = []
                for line in day.find_all("div", class_="line"):
                    time_div, discipline_div = line.find("div", class_="time"), line.find("div", class_="discipline")
                    if not time_div or not discipline_div:
                        continue
                    time_text = _extract_time(time_div.get_text(separator=" ", strip=True))
                    _append_lesson(schedule, "session", day_name_ru, time_text, discipline_div)

    except Exception as e:
        logger.error(f"Ошибка при парсинге расписания: {e}")
        await notify_admin(application, f"Ошибка при парсинге расписания: {e}")
        return schedule_cache

    schedule_cache.clear()
    for k, v in schedule.items():
        schedule_cache[k] = v

    logger.info("Расписание успешно обновлено.")
    return schedule_cache


def _append_lesson(schedule, week_key, day_name_ru, time_text, block):
    """Обработка блока пары (включая подгруппы)"""
    subgroup = None
    classroom = None

    # Извлекаем подгруппу
    subgroup_el = block.find("li", class_="bold num_pdgrp")
    if subgroup_el:
        subgroup = subgroup_el.get_text(strip=True)
    else:
        for li in block.find_all("li"):
            txt = li.get_text(strip=True)
            if "подгруппа" in txt:
                subgroup = txt
                break

    # Извлекаем "сырой" текст
    raw_lines = [ln.strip() for ln in block.get_text(separator="\n", strip=True).split("\n") if ln.strip()]

    # Удаляем упоминания подгрупп из текста
    cleaned_lines = []
    for line in raw_lines:
        if "подгруппа" in line.lower() or re.match(r"\d+\s*подгруппа", line, re.I):
            continue
        cleaned_lines.append(line)

    # Извлекаем кабинет: ищем строку с "каб." или "корп."
    info_lines = []
    for line in cleaned_lines:
        if "каб." in line.lower() or "корп." in line.lower():
            classroom = line
        else:
            info_lines.append(line)

    if subgroup:
        subgroup = subgroup.replace("1 подгруппа", "1️⃣ подгруппа").replace("2 подгруппа", "2️⃣ подгруппа")

    if info_lines:
        subject = info_lines[0]
        escaped_subject = subject.replace('\\', '\\\\').replace('*', '\\*').replace('_', '\\_').replace('`', '\\`').replace('[', '\\[').replace(']', '\\]')
        info_lines[0] = f"*{escaped_subject}*"

    discipline_info = "\n".join(info_lines)

    schedule[week_key][day_name_ru].append({
        "time": time_text,
        "info": discipline_info,
        "subgroup": subgroup,
        "classroom": classroom
    })


def _extract_time(raw_text: str) -> str:
    match = re.search(r"\d{2}:\d{2}(?:-\d{2}:\d{2})?", raw_text)
    return match.group(0) if match else raw_text


def get_current_week_and_day():
    """Определяет текущую неделю и день"""
    try:
        today = datetime.date.today()
        weekday_en = today.strftime("%A")
        day_name_ru = WEEKDAYS.get(weekday_en, weekday_en)
        semester_start = datetime.date(2024, 9, 1)
        delta_weeks = (today - semester_start).days // 7
        current_week = "week_1" if delta_weeks % 2 == 0 else "week_2"
        return today.strftime("%d.%m.%Y"), day_name_ru, current_week
    except Exception as e:
        logger.error(f"Ошибка при определении текущей недели/дня: {e}")
        return None, None, None


def get_tomorrow_week_and_day():
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    weekday_en = tomorrow.strftime("%A")
    day_name_ru = WEEKDAYS.get(weekday_en, weekday_en)
    semester_start = datetime.date(2024, 9, 1)
    delta_weeks = (tomorrow - semester_start).days // 7
    current_week = "week_1" if delta_weeks % 2 == 0 else "week_2"
    return tomorrow.strftime("%d.%m.%Y"), day_name_ru, current_week

def get_current_and_next_lesson(schedule, current_week: str, day_name_ru: str):
    """
    Возвращает:
    - current_lesson
    - minutes_until_current_end (None если пара не идёт)
    - next_lesson
    - minutes_until_next_start
    """
    from datetime import datetime

    now = datetime.now()
    current_minutes = now.hour * 60 + now.minute

    today_lessons = schedule.get(current_week, {}).get(day_name_ru, [])
    if not today_lessons:
        return None, None, None, None

    # Группируем по времени начала
    time_to_lessons = {}
    for lesson in today_lessons:
        time_str = lesson.get("time", "").strip()
        if not time_str:
            continue
        start_str = time_str.split("-")[0].strip()
        try:
            start_h, start_m = map(int, start_str.split(":"))
            start_minutes = start_h * 60 + start_m
            if start_minutes not in time_to_lessons:
                time_to_lessons[start_minutes] = []
            time_to_lessons[start_minutes].append(lesson)
        except (ValueError, IndexError):
            continue

    current_lesson = None
    minutes_until_current_end = None
    next_lesson = None
    minutes_until_next_start = None

    for start_min, end_min in LESSON_SCHEDULE:
        lessons_here = time_to_lessons.get(start_min, [])

        if current_minutes >= start_min and current_minutes < end_min:
            # Сейчас идёт пара
            if lessons_here:
                current_lesson = lessons_here[0]
                minutes_until_current_end = end_min - current_minutes
        elif current_minutes < start_min:
            # Следующая пара
            if lessons_here and next_lesson is None:
                next_lesson = lessons_here[0]
                minutes_until_next_start = start_min - current_minutes

    return current_lesson, minutes_until_current_end, next_lesson, minutes_until_next_start