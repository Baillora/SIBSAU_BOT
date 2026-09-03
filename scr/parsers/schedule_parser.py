import re
import os
import json
import tempfile
import datetime
from typing import Dict, Any, Optional, Tuple, List
import httpx
from bs4 import BeautifulSoup
from cachetools import TTLCache

from scr.core.settings import (
    SCHEDULE_URL,
    SCHEDULE_BACKUP_FILE,
    WEEKDAYS,
    EXPECTED_DAYS,
    LESSON_SCHEDULE,
    CACHE_EXPIRY,
    OWNER_ID,
    BOT_TIMEZONE,
    get_semester_start_date,
)
from scr.core.logger import logger

# TTL-кэш для расписания
schedule_cache = TTLCache(maxsize=100, ttl=CACHE_EXPIRY)


def save_schedule_backup(schedule: Dict[str, Any]) -> None:
    """Сохраняет успешную копию расписания на диск в schedule_backup.json"""
    try:
        clean_data = {}
        for k, v in schedule.items():
            if not k.startswith("_"):
                clean_data[k] = v
        if "_current_week" in schedule:
            clean_data["_current_week"] = schedule["_current_week"]

        now = datetime.datetime.now(BOT_TIMEZONE)
        payload = {
            "saved_at": now.isoformat(),
            "saved_at_formatted": now.strftime("%d.%m.%Y в %H:%M"),
            "schedule": clean_data
        }
        SCHEDULE_BACKUP_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp_fd, temp_path = tempfile.mkstemp(
            dir=SCHEDULE_BACKUP_FILE.parent, prefix="sched_bak_", suffix=".tmp"
        )
        with open(temp_fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, SCHEDULE_BACKUP_FILE)
        logger.info(f"💾 Резервная копия расписания успешно сохранена в {SCHEDULE_BACKUP_FILE}")
    except Exception as e:
        logger.error(f"Не удалось сохранить резервную копию расписания: {e}")


def load_schedule_backup() -> Optional[Dict[str, Any]]:
    """Загружает резервную копию расписания с диска, если сайт недоступен"""
    if not SCHEDULE_BACKUP_FILE.exists():
        return None
    try:
        with open(SCHEDULE_BACKUP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        sched = data.get("schedule", {})
        if sched:
            sched["_is_backup"] = True
            sched["_backup_time"] = data.get("saved_at_formatted", "ранее")
            logger.warning(f"⚠️ Использована резервная копия расписания от {sched['_backup_time']}")
            return sched
    except Exception as e:
        logger.error(f"Ошибка загрузки резервной копии расписания: {e}")
    return None


def extract_time(raw_text: str) -> str:
    """Извлекает временной интервал (например 08:00-09:30) из строки"""
    match = re.search(r"\d{2}:\d{2}(?:-\d{2}:\d{2})?", raw_text)
    return match.group(0) if match else raw_text.strip()


async def notify_admin(application, message: str) -> None:
    """Безопасная отправка сообщения об ошибке администратору"""
    if not OWNER_ID:
        return
    try:
        if application is not None and hasattr(application, "bot") and application.bot:
            await application.bot.send_message(chat_id=OWNER_ID, text=message)
    except Exception as e:
        logger.error(f"Не удалось уведомить администратора: {e}")


def _append_lesson(schedule: Dict[str, Any], week_key: str, day_name_ru: str, time_text: str, block) -> None:
    """Обработка блока пары и добавление в структуру расписания"""
    subgroup = None
    classroom = None

    # Извлекаем подгруппу
    subgroup_el = block.find("li", class_="bold num_pdgrp")
    if subgroup_el:
        subgroup = subgroup_el.get_text(strip=True)
    else:
        for li in block.find_all("li"):
            txt = li.get_text(strip=True)
            if "подгруппа" in txt.lower():
                subgroup = txt
                break

    # Извлекаем строки текста
    raw_lines = [ln.strip() for ln in block.get_text(separator="\n", strip=True).split("\n") if ln.strip()]

    # Удаляем строки с упоминанием подгрупп
    cleaned_lines = []
    for line in raw_lines:
        if "подгруппа" in line.lower() or re.match(r"\d+\s*подгруппа", line, re.I):
            continue
        cleaned_lines.append(line)

    # Извлекаем кабинет / корпус
    info_lines = []
    for line in cleaned_lines:
        if "каб." in line.lower() or "корп." in line.lower():
            classroom = line
        else:
            info_lines.append(line)

    if subgroup:
        subgroup = subgroup.replace("1 подгруппа", "1️⃣ подгруппа").replace("2 подгруппа", "2️⃣ подгруппа")

    discipline_info = "\n".join(info_lines)

    schedule.setdefault(week_key, {}).setdefault(day_name_ru, []).append({
        "time": time_text,
        "info": discipline_info,
        "subgroup": subgroup,
        "classroom": classroom
    })


async def fetch_schedule(application=None) -> Dict[str, Any]:
    """Парсинг расписания с сайта СИБГУ"""
    if len(schedule_cache) > 0:
        logger.info("Используется кэш расписания (TTLCache).")
        return dict(schedule_cache)

    if not SCHEDULE_URL:
        logger.warning("SCHEDULE_URL не задан в конфигурации.")
        if len(schedule_cache) > 0:
            return dict(schedule_cache)
        backup = load_schedule_backup()
        if backup:
            for k, v in backup.items():
                schedule_cache[k] = v
            return backup
        return dict(schedule_cache)

    logger.info("Обновление расписания с сайта.")
    schedule: Dict[str, Any] = {}

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(SCHEDULE_URL)
            response.raise_for_status()
            content = response.content
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.error(f"Ошибка при получении страницы расписания: {e}")
        await notify_admin(application, f"Ошибка при получении страницы расписания: {e}")
        if len(schedule_cache) > 0:
            return dict(schedule_cache)
        backup = load_schedule_backup()
        if backup:
            schedule_cache.clear()
            for k, v in backup.items():
                schedule_cache[k] = v
            return backup
        return dict(schedule_cache)

    soup = BeautifulSoup(content, "html.parser")

    try:
        # Извлечение активной недели с сайта
        week_header = soup.find("h4", class_="text-center")
        if week_header:
            header_text = week_header.get_text()
            if "1 неделя" in header_text:
                schedule["_current_week"] = "week_1"
            elif "2 неделя" in header_text:
                schedule["_current_week"] = "week_2"

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
                    if "_current_week" not in schedule:
                        schedule["_current_week"] = week_key

                schedule[week_key][day_name_ru] = []
                lines = day.find_all("div", class_="line")
                seen_lessons = set()

                for line in lines:
                    time_div = line.find("div", class_="time")
                    discipline_div = line.find("div", class_="discipline")
                    if not time_div or not discipline_div:
                        continue

                    time_text = extract_time(time_div.get_text(separator=" ", strip=True))
                    subgroup_blocks = discipline_div.find_all("div", class_=re.compile(r"col-md"))
                    blocks_to_process = subgroup_blocks if subgroup_blocks else [discipline_div]

                    for block in blocks_to_process:
                        raw_text = block.get_text(separator="|", strip=True)
                        lesson_key = (time_text, raw_text)

                        if lesson_key in seen_lessons:
                            continue
                        seen_lessons.add(lesson_key)

                        _append_lesson(schedule, week_key, day_name_ru, time_text, block)

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
                    time_div = line.find("div", class_="time")
                    discipline_div = line.find("div", class_="discipline")
                    if not time_div or not discipline_div:
                        continue
                    time_text = extract_time(time_div.get_text(separator=" ", strip=True))
                    _append_lesson(schedule, "session", day_name_ru, time_text, discipline_div)

    except Exception as e:
        logger.error(f"Ошибка при парсинге расписания: {e}")
        await notify_admin(application, f"Ошибка при парсинге расписания: {e}")
        if len(schedule_cache) > 0:
            return dict(schedule_cache)
        backup = load_schedule_backup()
        if backup:
            schedule_cache.clear()
            for k, v in backup.items():
                schedule_cache[k] = v
            return backup
        return dict(schedule_cache)

    schedule_cache.clear()
    for k, v in schedule.items():
        schedule_cache[k] = v

    # Сохраняем в резервную копию на диск
    save_schedule_backup(schedule)

    logger.info("Расписание успешно обновлено.")
    return dict(schedule_cache)


def get_current_week_and_day(schedule: Optional[Dict[str, Any]] = None) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Определяет текущую дату, день недели и четность недели (week_1 / week_2) в часовом поясе Красноярска"""
    try:
        now_local = datetime.datetime.now(BOT_TIMEZONE)
        today = now_local.date()
        weekday_en = today.strftime("%A")
        day_name_ru = WEEKDAYS.get(weekday_en, weekday_en)

        # Если есть кэшированная активная неделя с сайта
        if schedule and "_current_week" in schedule:
            current_week = schedule["_current_week"]
        elif "_current_week" in schedule_cache:
            current_week = schedule_cache["_current_week"]
        else:
            semester_start = get_semester_start_date(today)
            delta_weeks = (today - semester_start).days // 7
            current_week = "week_1" if delta_weeks % 2 == 0 else "week_2"

        return today.strftime("%d.%m.%Y"), day_name_ru, current_week
    except Exception as e:
        logger.error(f"Ошибка при определении текущей недели/дня: {e}")
        return None, None, None


def get_tomorrow_week_and_day(schedule: Optional[Dict[str, Any]] = None) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Определяет дату, день недели и четность недели для завтрашнего дня в часовом поясе Красноярска"""
    try:
        now_local = datetime.datetime.now(BOT_TIMEZONE)
        tomorrow = now_local.date() + datetime.timedelta(days=1)
        weekday_en = tomorrow.strftime("%A")
        day_name_ru = WEEKDAYS.get(weekday_en, weekday_en)

        # Если завтра воскресенье или понедельник
        # При переходе на понедельник меняется неделя
        today_date_str, today_day_name, current_week = get_current_week_and_day(schedule)
        if weekday_en == "Monday":
            week = "week_2" if current_week == "week_1" else "week_1"
        else:
            week = current_week

        return tomorrow.strftime("%d.%m.%Y"), day_name_ru, week
    except Exception as e:
        logger.error(f"Ошибка при определении завтрашней недели/дня: {e}")
        return None, None, None


def get_current_and_next_lesson(schedule: Dict[str, Any], current_week: str, day_name_ru: str):
    """
    Возвращает:
    - current_lesson
    - minutes_until_current_end (None если пара не идёт)
    - next_lesson
    - minutes_until_next_start
    """
    now = datetime.datetime.now(BOT_TIMEZONE)
    current_minutes = now.hour * 60 + now.minute

    today_lessons = schedule.get(current_week, {}).get(day_name_ru, [])
    if not today_lessons:
        return None, None, None, None

    time_to_lessons: Dict[int, List[Dict[str, Any]]] = {}
    for lesson in today_lessons:
        time_str = lesson.get("time", "").strip()
        if not time_str:
            continue
        start_str = time_str.split("-")[0].strip()
        try:
            start_h, start_m = map(int, start_str.split(":"))
            start_minutes = start_h * 60 + start_m
            time_to_lessons.setdefault(start_minutes, []).append(lesson)
        except (ValueError, IndexError):
            continue

    current_lesson = None
    minutes_until_current_end = None
    next_lesson = None
    minutes_until_next_start = None

    for start_min, end_min in LESSON_SCHEDULE:
        lessons_here = time_to_lessons.get(start_min, [])

        if start_min <= current_minutes < end_min:
            if lessons_here:
                current_lesson = lessons_here[0]
                minutes_until_current_end = end_min - current_minutes
        elif current_minutes < start_min:
            if lessons_here and next_lesson is None:
                next_lesson = lessons_here[0]
                minutes_until_next_start = start_min - current_minutes

    return current_lesson, minutes_until_current_end, next_lesson, minutes_until_next_start