import re
from typing import Dict, Any, List
import httpx
from bs4 import BeautifulSoup
from cachetools import TTLCache

from scr.core.settings import SCHEDULE_URL, WEEKDAYS, RU_WEEKDAYS_ORDER, TEACHERS_CACHE_EXPIRY
from scr.core.logger import logger
from scr.parsers.schedule_parser import notify_admin, extract_time

# TTL-кэш для преподавателей
teachers_cache = TTLCache(maxsize=100, ttl=TEACHERS_CACHE_EXPIRY)


async def fetch_teachers(application=None) -> Dict[str, Any]:
    """Парсинг списка преподавателей с сайта"""
    if len(teachers_cache) > 0:
        logger.info("Используется TTLCache преподавателей.")
        return dict(teachers_cache)

    if not SCHEDULE_URL:
        logger.warning("SCHEDULE_URL не задан в конфигурации.")
        return dict(teachers_cache)

    logger.info("Обновление списка преподавателей с сайта...")
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(SCHEDULE_URL)
            response.raise_for_status()
            content = response.text
    except httpx.RequestError as e:
        logger.error(f"Ошибка при получении списка преподавателей: {e}")
        await notify_admin(application, f"Ошибка при получении списка преподавателей: {e}")
        return dict(teachers_cache)

    soup = BeautifulSoup(content, "html.parser")
    professor_links = soup.find_all("a", href=re.compile(r"/timetable/professor/\d+"))
    logger.info(f"Найдено ссылок на преподавателей: {len(professor_links)}")

    teachers_cache.clear()
    for link in professor_links:
        full_name = link.get_text(strip=True)
        href = link.get("href", "")
        match = re.search(r"professor/(\d+)", href)
        if match:
            teacher_id = match.group(1)
            teachers_cache[teacher_id] = {
                "name": full_name,
                "href": f"https://timetable.pallada.sibsau.ru{href}" if href.startswith("/") else href,
                "pairs": {},
                "consultations": []
            }

    logger.info("Список преподавателей успешно обновлён.")
    return dict(teachers_cache)


async def fetch_consultations_for_teacher(teacher_id: str) -> List[Dict[str, str]]:
    """Парсинг консультаций конкретного преподавателя"""
    consultations = []
    try:
        url = f"https://timetable.pallada.sibsau.ru/timetable/professor/{teacher_id}"
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            content = response.content

        soup = BeautifulSoup(content, "html.parser")
        consultation_tab = soup.find("div", {"id": "consultation_tab"})
        if not consultation_tab:
            return consultations

        for day_block in consultation_tab.find_all("div", class_="day"):
            date_div = day_block.find("div", class_="name")
            date_text = date_div.get_text(strip=True) if date_div else ""

            for line in day_block.find_all("div", class_="line"):
                time_div = line.find("div", class_="time")
                discipline_div = line.find("div", class_="discipline")
                if not time_div or not discipline_div:
                    continue

                time_text = extract_time(time_div.get_text(separator=" ", strip=True))
                discipline_info = discipline_div.get_text(separator="\n", strip=True)
                consultations.append({
                    "date": date_text,
                    "time": time_text,
                    "info": discipline_info
                })
    except Exception as e:
        logger.error(f"Ошибка при получении консультаций для преподавателя {teacher_id}: {e}")

    return consultations


async def fetch_pairs_for_teacher(teacher_id: str) -> Dict[str, Dict[str, List[Dict[str, str]]]]:
    """Парсинг пар преподавателя по дням недели (для 1-й и 2-й недели)"""
    result = {day: {"1": [], "2": []} for day in RU_WEEKDAYS_ORDER}
    try:
        url = f"https://timetable.pallada.sibsau.ru/timetable/professor/{teacher_id}"
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            content = response.content

        soup = BeautifulSoup(content, "html.parser")

        for week_num in ("1", "2"):
            week_tab = soup.find("div", {"id": f"week_{week_num}_tab"})
            if not week_tab:
                continue

            for day_block in week_tab.find_all("div", class_="day"):
                day_classes_lower = [c.lower() for c in day_block.get("class", [])]
                weekday_class = next(
                    (c for c in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
                     if c in day_classes_lower),
                    None
                )
                if not weekday_class:
                    continue
                day_name_ru = WEEKDAYS.get(weekday_class.capitalize(), weekday_class)

                for line in day_block.find_all("div", class_="line"):
                    time_div = line.find("div", class_="time")
                    discipline_div = line.find("div", class_="discipline")
                    if not time_div or not discipline_div:
                        continue

                    time_text = extract_time(time_div.get_text(separator=" ", strip=True))
                    discipline_info = discipline_div.get_text(separator="\n", strip=True)
                    result[day_name_ru][week_num].append({
                        "time": time_text,
                        "info": discipline_info
                    })
    except Exception as e:
        logger.error(f"Ошибка при получении пар для преподавателя {teacher_id}: {e}")

    return result