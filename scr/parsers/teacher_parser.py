import httpx, re
from bs4 import BeautifulSoup
from cachetools import TTLCache
from scr.core.settings import SCHEDULE_URL, WEEKDAYS, RU_WEEKDAYS_ORDER, TEACHERS_CACHE_EXPIRY
from scr.core.logger import logger
from scr.parsers.schedule_parser import notify_admin

# TTL-кэш для преподавателей
teachers_cache = TTLCache(maxsize=100, ttl=TEACHERS_CACHE_EXPIRY)

async def fetch_teachers(application):
    """Парсинг списка преподавателей"""
    if len(teachers_cache) > 0:
        logger.info("Используется TTLCache преподавателей 24 часа.")
        return teachers_cache

    logger.info("Обновление списка преподавателей с сайта...")
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.get(SCHEDULE_URL)
            response.raise_for_status()
        except httpx.RequestError as e:
            logger.error(f"Ошибка при получении страницы расписания: {e}")
            await notify_admin(application, f"Ошибка при получении списка преподавателей: {e}")
            return teachers_cache

    soup = BeautifulSoup(response.text, "html.parser")
    professor_links = soup.find_all("a", href=re.compile(r"/timetable/professor/\d+"))
    logger.info(f"Найдено ссылок на преподавателей: {len(professor_links)}")

    teachers_cache.clear()
    for link in professor_links:
        full_name = link.get_text(strip=True)
        href = link.get("href")
        match = re.search(r"professor/(\d+)", href)
        if match:
            teacher_id = match.group(1)
            teachers_cache[teacher_id] = {
                "name": full_name,
                "href": f"https://timetable.pallada.sibsau.ru{href}",
                "pairs": {},
                "consultations": []
            }

    logger.info("Список преподавателей успешно обновлён.")
    return teachers_cache


async def fetch_consultations_for_teacher(teacher_id: str):
    """Парсинг консультаций конкретного преподавателя"""
    consultations = []
    try:
        url = f"https://timetable.pallada.sibsau.ru/timetable/professor/{teacher_id}"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url)
            response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        consultation_tab = soup.find("div", {"id": "consultation_tab"})
        if not consultation_tab:
            return consultations

        for day_block in consultation_tab.find_all("div", class_="day"):
            date_text = day_block.find("div", class_="name").get_text(strip=True)
            for line in day_block.find_all("div", class_="line"):
                time_div, discipline_div = line.find("div", class_="time"), line.find("div", class_="discipline")
                if not time_div or not discipline_div:
                    continue
                time_text = _extract_time(time_div.get_text(separator=" ", strip=True))
                discipline_info = discipline_div.get_text(separator="\n", strip=True)
                consultations.append({"date": date_text, "time": time_text, "info": discipline_info})
    except Exception as e:
        logger.error(f"Ошибка при получении консультаций {teacher_id}: {e}")
    return consultations


async def fetch_pairs_for_teacher(teacher_id: str):
    """Парсинг пар по дням для преподавателя (1 и 2 недели отдельно)."""
    result = {day: {"1": [], "2": []} for day in RU_WEEKDAYS_ORDER}
    try:
        url = f"https://timetable.pallada.sibsau.ru/timetable/professor/{teacher_id}"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url)
            response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")

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
                    time_div, discipline_div = line.find("div", class_="time"), line.find("div", class_="discipline")
                    if not time_div or not discipline_div:
                        continue
                    time_text = _extract_time(time_div.get_text(separator=" ", strip=True))
                    discipline_info = discipline_div.get_text(separator="\n", strip=True)
                    result[day_name_ru][week_num].append({
                        "time": time_text,
                        "info": discipline_info
                    })

    except Exception as e:
        logger.error(f"Ошибка при получении пар {teacher_id}: {e}")
    return result


def _extract_time(raw_text: str) -> str:
    match = re.search(r"\d{2}:\d{2}(?:-\d{2}:\d{2})?", raw_text)
    return match.group(0) if match else raw_text