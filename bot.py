import logging
from logging.handlers import RotatingFileHandler
import httpx
from bs4 import BeautifulSoup
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    InlineQueryHandler
)
import time
import datetime
import os
import json
import asyncio
import re
from pystyle import Colorate, Colors, Center
from dotenv import load_dotenv
from telegram.error import BadRequest
import sys
import subprocess
from cachetools import TTLCache
from uuid import uuid4
import structlog
from admin_panel.app import run_flask
import threading

load_dotenv()

class TelegramFilter(logging.Filter):
    def filter(self, record):
        return "https://api.telegram.org" not in record.getMessage()

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    format="%(message)s",
    stream=sys.stdout,
    level=LOG_LEVEL,
)

root_logger = logging.getLogger()
for handler in root_logger.handlers:
    handler.addFilter(TelegramFilter())

def drop_telegram_requests(logger, method_name, event_dict):
    event = event_dict.get("event", "")
    if "https://api.telegram.org" in event:
        raise structlog.DropEvent
    return event_dict

structlog.configure(
    processors=[
        drop_telegram_requests,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.JSONRenderer(ensure_ascii=False)
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)
logger = structlog.get_logger(__name__)

file_handler = RotatingFileHandler('warning.log', maxBytes=1 * 1024 * 1024, backupCount=5, encoding='utf-8')
file_handler.setLevel(logging.WARNING)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
file_handler.addFilter(TelegramFilter())
logging.getLogger().addHandler(file_handler)
 

SCHEDULE_URL = os.environ.get("SCHEDULE_URL")
if not SCHEDULE_URL:
    logger.error("Пожалуйста, установите ссылку на расписание в .env (SCHEDULE_URL).")
    exit(1)

PLAN_URL = os.environ.get("PLAN_URL")
if not PLAN_URL:
    logger.error("Пожалуйста, установите ссылку на учебный план в .env (PLAN_URL).")

OWNER_ID_ENV = os.environ.get("OWNER_ID")
if not OWNER_ID_ENV:
    logger.error("Пожалуйста, установите ваш OWNER_ID в .env.")
    exit(1)

try:
    OWNER_ID = int(OWNER_ID_ENV)
except ValueError:
    logger.error("OWNER_ID должен быть числом.")
    exit(1)

ALLOWED_USERS_FILE = 'allowed_users.json'

# Параметры кэша
cache_expiry = 60 * 30  # 30 минут
teachers_cache_expiry = 24 * 60 * 60  # 24 часа

schedule_cache = TTLCache(maxsize=100, ttl=cache_expiry)
teachers_cache = TTLCache(maxsize=100, ttl=teachers_cache_expiry)

STATS_FILE = 'stats.json'

WEEKDAYS = {
    'Monday': 'Понедельник',
    'Tuesday': 'Вторник',
    'Wednesday': 'Среда',
    'Thursday': 'Четверг',
    'Friday': 'Пятница',
    'Saturday': 'Суббота',
    'Sunday': 'Воскресенье'
}

RU_WEEKDAYS_ORDER = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
EXPECTED_DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

stats = {
    'unique_users': set(),
    'schedule_requests': 0,
    'search_queries': 0,
    'commands_executed': 0,
    'errors': 0,
    'total_messages': 0,
    'commands_per_user': {},
    'peak_usage': {},
    'daily_active_users': {}
}

def load_allowed_users():
    """
    Загружает актуальный список пользователей из allowed_users.json.
    """
    try:
        with open("allowed_users.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("users", {})
    except Exception:
        return {}


def save_allowed_users(users: dict):
    """
    Сохраняет пользователей в allowed_users.json.
    """
    try:
        with open("allowed_users.json", "w", encoding="utf-8") as f:
            json.dump({"users": users}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения allowed_users.json: {e}")


def get_user_role(user_id: int) -> str:
    """
    Возвращает роль пользователя. Если это OWNER_ID из .env -> всегда owner.
    """
    if str(user_id) == str(OWNER_ID):
        return "owner"

    users = load_allowed_users()
    if str(user_id) in users:
        udata = users[str(user_id)]
        if isinstance(udata, str):
            return udata
        return udata.get("role", "user")

    return "unknown"


def is_user_allowed(user_id: int) -> bool:
    """
    Проверяет, есть ли пользователь в списке или он OWNER.
    """
    if str(user_id) == str(OWNER_ID):
        return True
    users = load_allowed_users()
    return str(user_id) in users


def is_mod_or_admin(user_id: int) -> bool:
    """
    Проверка, является ли пользователь модератором, админом или владельцем.
    """
    role = get_user_role(user_id)
    return role in ["mod", "admin", "owner"]


def migrate_users_format():
    """
    Приводит allowed_users.json к новому формату:
    { "123": {"role": "admin", "username": "@test"} }
    """
    users = load_allowed_users()
    new_data = {}

    for uid, val in users.items():
        if isinstance(val, str):
            new_data[uid] = {"role": val, "username": ""}
        elif isinstance(val, dict):
            new_data[uid] = {
                "role": val.get("role", "user"),
                "username": val.get("username", "")
            }

    # Добавляем OWNER в JSON если его нет
    if str(OWNER_ID) not in new_data:
        new_data[str(OWNER_ID)] = {"role": "owner", "username": ""}

    save_allowed_users(new_data)


def load_stats():
    global stats
    if not os.path.exists(STATS_FILE):
        save_stats()
        return
    with open(STATS_FILE, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
            stats['unique_users'] = set(data.get('unique_users', []))
            stats['schedule_requests'] = data.get('schedule_requests', 0)
            stats['search_queries'] = data.get('search_queries', 0)
            stats['commands_executed'] = data.get('commands_executed', 0)
            stats['errors'] = data.get('errors', 0)
            stats['total_messages'] = data.get('total_messages', 0)
            stats['commands_per_user'] = data.get('commands_per_user', {})
            stats['peak_usage'] = data.get('peak_usage', {})
            daily_active = data.get('daily_active_users', {})
            stats['daily_active_users'] = {k: set(v) for k, v in daily_active.items()}
        except json.JSONDecodeError:
            logger.error("Не удалось загрузить статистику из stats.json.")

def save_stats():
    data = {
        'unique_users': list(stats['unique_users']),
        'schedule_requests': stats['schedule_requests'],
        'search_queries': stats['search_queries'],
        'commands_executed': stats['commands_executed'],
        'errors': stats['errors'],
        'total_messages': stats['total_messages'],
        'commands_per_user': stats['commands_per_user'],
        'peak_usage': stats['peak_usage'],
        'daily_active_users': {k: list(v) for k, v in stats['daily_active_users'].items()}
    }
    with open(STATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

load_stats()

def increment_user_commands(user_id: int):
    if user_id in stats['commands_per_user']:
        stats['commands_per_user'][user_id] += 1
    else:
        stats['commands_per_user'][user_id] = 1

def record_peak_usage():
    current_hour = datetime.datetime.now().strftime('%H')
    if current_hour in stats['peak_usage']:
        stats['peak_usage'][current_hour] += 1
    else:
        stats['peak_usage'][current_hour] = 1

def record_daily_active(user_id: int):
    today = datetime.date.today().isoformat()
    if today not in stats['daily_active_users']:
        stats['daily_active_users'][today] = set()
    stats['daily_active_users'][today].add(user_id)

def escape_markdown(text: str) -> str:
    escape_chars = r"\_*[]()~`>#+-=|{}.!"
    return ''.join(['\\' + c if c in escape_chars else c for c in text])

def highlight_query(text: str, query: str) -> str:
    words = query.split()
    highlighted = escape_markdown(text)
    for w in words:
        pattern = re.compile(r'(' + re.escape(w) + r')', re.IGNORECASE)
        highlighted = pattern.sub(r'*\1*', highlighted)
    return highlighted

def get_next_day_ru(current_day_ru: str) -> str:
    try:
        index = RU_WEEKDAYS_ORDER.index(current_day_ru)
        next_index = (index + 1) % 7
        return RU_WEEKDAYS_ORDER[next_index]
    except ValueError:
        logger.error(f"Неверный день недели: {current_day_ru}")
        return current_day_ru

async def notify_admin(application, message: str):
    try:
        await application.bot.send_message(chat_id=OWNER_ID, text=message)
    except Exception as e:
        logger.error(f"Не удалось уведомить администратора: {e}")

def chunk_text_by_lines(text: str, chunk_size=4000) -> list[str]:
    lines = text.split('\n')
    chunks = []
    current_chunk = ""

    for line in lines:
        if len(line) > chunk_size:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""
            start = 0
            while start < len(line):
                end = start + chunk_size
                chunks.append(line[start:end])
                start = end
        else:
            if not current_chunk:
                current_chunk = line
            elif len(current_chunk) + len(line) + 1 <= chunk_size:
                current_chunk += "\n" + line
            else:
                chunks.append(current_chunk)
                current_chunk = line

    if current_chunk:
        chunks.append(current_chunk)

    return chunks

async def safe_edit_message(query, text, reply_markup=None):
    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            pass
        else:
            logger.error(f"Ошибка при редактировании сообщения: {e}")


async def safe_message_send(context: ContextTypes.DEFAULT_TYPE, chat_id, text, parse_mode=None):
    try:
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            logger.error(f"Ошибка отправки сообщения: {e}")
            await context.bot.send_message(chat_id=OWNER_ID, text=f"Ошибка отправки: {e}\n\n{text[:100]}")
    except Exception as e:
        logger.error(f"Неожиданная ошибка отправки: {e}")
        await context.bot.send_message(chat_id=OWNER_ID, text=f"Критическая ошибка: {e}")


# ----------------------------------------- парсинг преподав -----------------------------------------------
async def fetch_teachers(application):
    
    if len(teachers_cache) > 0:
        logger.info("Используется TTLCache преподавателей 24 часа.")
        return teachers_cache

    logger.info("Обновление списка преподавателей с сайта...")
    main_url = "https://timetable.pallada.sibsau.ru/timetable/"

    async with httpx.AsyncClient(timeout=30) as client:
        attempts = 3
        for attempt in range(attempts):
            try:
                response = await client.get(SCHEDULE_URL)
                response.raise_for_status()
                break
            except httpx.RequestError as e:
                logger.error(f"Ошибка при получении страницы расписания (попытка {attempt + 1}/{attempts}): {e}")
                if attempt < attempts - 1:
                    await asyncio.sleep(2)
                else:
                    await notify_admin(application, f"Ошибка при получении страницы расписания после {attempts} попыток: {e}")
                    return schedule_cache

        url = os.getenv("SCHEDULE_URL")
        try:
            response_schedule = await client.get(url)
            response_schedule.raise_for_status()
        except httpx.RequestError as e:
            logger.error(f"Ошибка при получении списка преподавателей: {e}")
            await notify_admin(application, f"Ошибка при получении списка преподавателей: {e}")
            return teachers_cache

        soup = BeautifulSoup(response_schedule.text, "html.parser")
        professor_links = soup.find_all("a", href=re.compile(r"/timetable/professor/\d+"))
        logger.info(f"Найдено ссылок на преподавателей: {len(professor_links)}")

        teachers_cache.clear()

        for link in professor_links:
            full_name = link.get_text(strip=True)
            href = link.get("href")
            match = re.search(r'professor/(\d+)', href)
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

# ----------------------------------------- Парсинг консультаций препода -----------------------------------------------
async def fetch_consultations_for_teacher(teacher_id: str) -> list:
    """
    [
      {
        "date": "...",
        "time": "...",
        "info": "..."
      },
      ...
    ]
"""
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

        day_blocks = consultation_tab.find_all("div", class_="day")
        for day_block in day_blocks:
            date_div = day_block.find("div", class_="name")
            if not date_div:
                continue

            date_text = date_div.get_text(strip=True)
            lines = day_block.find_all("div", class_="line")
            for line_ in lines:
                time_div = line_.find("div", class_="time")
                discipline_div = line_.find("div", class_="discipline")
                if not time_div or not discipline_div:
                    continue

                time_text_raw = time_div.get_text(separator=' ', strip=True)
                match_time = re.search(r'\d{2}:\d{2}(?:-\d{2}:\d{2})?', time_text_raw)
                if match_time:
                    time_text = match_time.group(0)
                else:
                    time_text = time_text_raw

                discipline_info = discipline_div.get_text(separator="\n", strip=True)

                consultations.append({
                    "date": date_text,
                    "time": time_text,
                    "info": discipline_info
                })

    except Exception as e:
        logger.error(f"Ошибка при получении консультаций для преподавателя {teacher_id}: {e}")

    return consultations

# -------------------------------------------- Парсинг пар препода по дням --------------------------------------------
async def fetch_pairs_for_teacher(teacher_id: str) -> dict:
    """
    Возвращает:
    {
      'Понедельник': [ { 'time': '...', 'info': '...' }, ... ],
      ...
    }
"""
    result = {
        'Понедельник': [],
        'Вторник': [],
        'Среда': [],
        'Четверг': [],
        'Пятница': [],
        'Суббота': [],
        'Воскресенье': []
    }
    try:
        url = f"https://timetable.pallada.sibsau.ru/timetable/professor/{teacher_id}"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url)
            response.raise_for_status()

        soup = BeautifulSoup(response.content, "html.parser")

        day_blocks = soup.find_all("div", class_="day")
        for day_block in day_blocks:
            day_classes = day_block.get("class", [])
            day_classes_lower = [c.lower() for c in day_classes]
            weekday_class = next(
                (c for c in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
                 if c in day_classes_lower),
                None
            )
            if not weekday_class:
                continue
            day_name_en = weekday_class.capitalize()
            day_name_ru = WEEKDAYS.get(day_name_en, day_name_en)

            lines = day_block.find_all("div", class_="line")
            for line_ in lines:
                time_div = line_.find("div", class_="time")
                discipline_div = line_.find("div", class_="discipline")
                if not time_div or not discipline_div:
                    continue
                time_text_raw = time_div.get_text(separator=' ', strip=True)
                match_time = re.search(r'\d{2}:\d{2}(?:-\d{2}:\d{2})?', time_text_raw)
                if match_time:
                    time_text = match_time.group(0)
                else:
                    time_text = time_text_raw

                discipline_info = discipline_div.get_text(separator="\n", strip=True)
                result[day_name_ru].append({
                    "time": time_text,
                    "info": discipline_info
                })

    except Exception as e:
        logger.error(f"Ошибка при получении пар для преподавателя {teacher_id}: {e}")

    return result

# --------------------------------------- Основной парсинг расписания ----------------------------------------
async def fetch_schedule(application):

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
            if not week_tab:
                logger.warning(f"Вкладка недели {week_key} не найдена.")
                schedule[week_key] = {}
                for day in EXPECTED_DAYS:
                    schedule[week_key][WEEKDAYS[day]] = []
                continue

            schedule[week_key] = {}
            days = week_tab.find_all("div", class_="day")

            for day in days:
                day_classes = day.get("class", [])
                day_classes_lower = [c.lower() for c in day_classes]
                weekday_class = next(
                    (c for c in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
                     if c in day_classes_lower),
                    None
                )
                if not weekday_class:
                    continue
                day_name_en = weekday_class.capitalize()
                day_name_ru = WEEKDAYS.get(day_name_en, day_name_en)

                is_today = 'today' in day_classes_lower
                if is_today:
                    schedule[week_key]['_today_day'] = day_name_ru

                schedule[week_key][day_name_ru] = []
                lines = day.find_all("div", class_="line")
                for line_ in lines:
                    time_div = line_.find("div", class_="time")
                    discipline_div = line_.find("div", class_="discipline")
                    if not time_div or not discipline_div:
                        continue
                    time_text_raw = time_div.get_text(separator=' ', strip=True)
                    match = re.search(r'\d{2}:\d{2}(?:-\d{2}:\d{2})?', time_text_raw)
                    if match:
                        time_text = match.group(0)
                    else:
                        time_text = time_text_raw

                    discipline_info = discipline_div.get_text(separator="\n", strip=True)
                    lesson_entry = {
                        "time": time_text,
                        "info": discipline_info
                    }
                    schedule[week_key][day_name_ru].append(lesson_entry)

            for day in EXPECTED_DAYS:
                day_ru = WEEKDAYS[day]
                if day_ru not in schedule[week_key]:
                    schedule[week_key][day_ru] = []

        # Сессия
        session_tab = soup.find("div", {"id": "session_tab"})
        if session_tab:
            schedule["session"] = {}
            session_days = session_tab.find_all("div", class_="day")
            for day_ in session_days:
                day_name_div = day_.find("div", class_="name")
                if not day_name_div:
                    continue
                day_name_raw = day_name_div.get_text(strip=True)
                day_name_ru = day_name_raw
                schedule["session"][day_name_ru] = []
                lines = day_.find_all("div", class_="line")
                for line_ in lines:
                    time_div = line_.find("div", class_="time")
                    discipline_div = line_.find("div", class_="discipline")
                    if not time_div or not discipline_div:
                        continue
                    time_text_raw = time_div.get_text(separator=' ', strip=True)
                    match = re.search(r'\d{2}:\d{2}(?:-\d{2}:\d{2})?', time_text_raw)
                    if match:
                        time_text = match.group(0)
                    else:
                        time_text = time_text_raw
                    discipline_info = discipline_div.get_text(separator="\n", strip=True)
                    lesson_entry = {
                        "time": time_text,
                        "info": discipline_info
                    }
                    schedule["session"][day_name_ru].append(lesson_entry)
        else:
            schedule["session"] = {}
            for day in EXPECTED_DAYS:
                day_ru = WEEKDAYS[day]
                schedule["session"][day_ru] = []

    except Exception as e:
        logger.error(f"Ошибка при парсинге расписания: {e}")
        await notify_admin(application, f"Ошибка при парсинге расписания: {e}")
        return schedule_cache

    schedule_cache.clear()
    for k, v in schedule.items():
        schedule_cache[k] = v

    logger.info("Расписание успешно обновлено.")
    return schedule_cache

def get_current_week_and_day():
    try:
        today = datetime.date.today()
        weekday_en = today.strftime('%A')
        day_name_ru = WEEKDAYS.get(weekday_en, weekday_en)

        semester_start = datetime.date(2024, 9, 1)
        if today < semester_start:
            raise ValueError("Семестр еще не начался")

        delta_weeks = (today - semester_start).days // 7
        current_week = 'week_1' if delta_weeks % 2 == 0 else 'week_2'
        date_str = today.strftime('%d.%m.%Y')
        return date_str, day_name_ru, current_week
    except Exception as e:
        logger.error(f"Ошибка при определении текущей недели/дня: {e}")
        return None, None, None

def get_tomorrow_week_and_day():
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    weekday_en = tomorrow.strftime('%A')
    day_name_ru = WEEKDAYS.get(weekday_en, weekday_en)
    semester_start = datetime.date(2024, 9, 1)
    delta_weeks = (tomorrow - semester_start).days // 7
    current_week = 'week_1' if delta_weeks % 2 == 0 else 'week_2'
    date_str = tomorrow.strftime('%d.%m.%Y')
    return date_str, day_name_ru, current_week

def print_startup_messages():
    ascii_art = """

      :::::::::           :::        :::::::::::       :::        :::        ::::::::       :::::::::           :::
     :+:    :+:        :+: :+:          :+:           :+:        :+:       :+:    :+:      :+:    :+:        :+: :+:
    +:+    +:+       +:+   +:+         +:+           +:+        +:+       +:+    +:+      +:+    +:+       +:+   +:+
   +#++:++#+       +#++:++#++:        +#+           +#+        +#+       +#+    +:+      +#++:++#:       +#++:++#++:
  +#+    +#+      +#+     +#+        +#+           +#+        +#+       +#+    +#+      +#+    +#+      +#+     +#+
 #+#    #+#      #+#     #+#        #+#           #+#        #+#       #+#    #+#      #+#    #+#      #+#     #+#
#########       ###     ###    ###########       ########## ########## ########       ###    ###      ###     ###
    
                Improvements can be made to the code. If you're getting an error, visit my tg.
                                    Github: https://github.com/Baillora
                                       Telegram: https://t.me/lssued
    """
    print(Colorate.Vertical(Colors.red_to_yellow, Center.XCenter(ascii_art)))

# --------------------------- Команды бота ---------------------------

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    stats['unique_users'].add(user_id)
    stats['total_messages'] += 1
    increment_user_commands(user_id)
    record_peak_usage()
    record_daily_active(user_id)
    save_stats()

    role = get_user_role(user_id)
    if not is_user_allowed(user_id):
        stats['commands_executed'] += 1
        save_stats()
        try:
            owner_user = await context.bot.get_chat(OWNER_ID)
            owner_username = f"@{owner_user.username}" if owner_user.username else owner_user.full_name
        except Exception as e:
            logger.error(f"Ошибка при получении информации о владельце: {e}")
            owner_username = "администратору"

        await update.message.reply_text(
            f"Ваш ID: {user_id}\n\n"
            f"Для использования бота сообщите ваш ID администратору {owner_username}.\n\n"
            "Разработчик @lssued"
        )
        return

    stats['commands_executed'] += 1
    save_stats()

    date_str, day_name, current_week = get_current_week_and_day()
    week_text = "1-ая неделя" if current_week == 'week_1' else "2-ая неделя"
    welcome_message = (
        f"⏱️ Сегодня: {date_str}, {day_name}, {week_text}.\n\n"
        "💻 Разработчик @lssued\n\n"
        "🤖 https://github.com/Baillora\n\n"
    )
    keyboard = [
        [
            InlineKeyboardButton("1 неделя", callback_data='week_1'),
            InlineKeyboardButton("2 неделя", callback_data='week_2'),
            InlineKeyboardButton("Сессия", callback_data='session')
        ],
        [
            InlineKeyboardButton("Сегодня", callback_data='today'),
            InlineKeyboardButton("Завтра", callback_data='tomorrow')
        ],
        [
            InlineKeyboardButton("Преподаватели", callback_data='teachers_list')
        ]
    ]
    await update.message.reply_text(welcome_message, reply_markup=InlineKeyboardMarkup(keyboard))

# /broadcast
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    role = get_user_role(user_id)
    if role not in ["admin", "owner"]:
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    if len(context.args) < 1:
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("Использование: /broadcast <сообщение>")
        return

    message = ' '.join(context.args)
    success_count = 0
    failure_count = 0
    for uid, user_info in allowed_users.items():
        try:
            await context.bot.send_message(chat_id=int(uid), text=f"🔔 Объявление:\n{message}")
            success_count += 1
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение пользователю {uid}: {e}")
            failure_count += 1

    if str(OWNER_ID) not in allowed_users:
        try:
            await context.bot.send_message(chat_id=OWNER_ID, text=f"🔔 Объявление:\n{message}")
            success_count += 1
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение владельцу {OWNER_ID}: {e}")
            failure_count += 1

    stats['commands_executed'] += 1
    save_stats()
    await update.message.reply_text(f"Объявление отправлено: успешно {success_count}, не удалось {failure_count}.")


# /plan
async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_user_allowed(user_id):
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("У вас нет доступа к этой команде.")
        return

    stats['commands_executed'] += 1
    save_stats()
    plan_message = f"Учебный план: {PLAN_URL}"
    await update.message.reply_text(plan_message)

# /map
async def map_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_user_allowed(user_id):
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("У вас нет доступа к этой команде.")
        return

    stats['commands_executed'] += 1
    save_stats()
    map_link = "https://cloud.sibsau.ru/s/KsYWFjEig2emNwH"
    await update.message.reply_text(f"🗺️ Карта корпусов:\n{map_link}")

# ---------------- Обработчики кнопок  ----------------
async def week_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    week = query.data
    application = context.application
    schedule = await fetch_schedule(application)
    stats['schedule_requests'] += 1
    stats['commands_executed'] += 1
    save_stats()

    if not schedule:
        await safe_edit_message(query, text="Не удалось получить расписание. Попробуйте позже.")
        return

    if week not in schedule:
        await safe_edit_message(query, text="Расписание для выбранной недели не найдено.")
        return

    keyboard = []
    for day in EXPECTED_DAYS:
        day_ru = WEEKDAYS[day]
        if day_ru in schedule[week]:
            keyboard.append([InlineKeyboardButton(day_ru, callback_data=f"{week}_{day_ru}")])

    keyboard.append([InlineKeyboardButton("⬅ Назад", callback_data='back_to_week')])
    week_number = '1' if week == 'week_1' else '2'
    new_text = f"Вы выбрали {week_number}-ю неделю. Выберите день:"

    await safe_edit_message(query, text=new_text, reply_markup=InlineKeyboardMarkup(keyboard))

async def today_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    application = context.application
    date_str, day_name, current_week = get_current_week_and_day()
    schedule = await fetch_schedule(application)
    stats['schedule_requests'] += 1
    stats['commands_executed'] += 1
    save_stats()

    if not schedule:
        await safe_edit_message(query, text="Не удалось получить расписание. Попробуйте позже.")
        return

    if current_week not in schedule:
        await safe_edit_message(query, text="Расписание для текущей недели не найдено.")
        return

    if '_today_day' in schedule[current_week]:
        day_name_today = schedule[current_week]['_today_day']
    else:
        day_name_today = day_name

    lessons = schedule[current_week].get(day_name_today, [])
    if not lessons:
        message = f"📅 Расписание на {day_name_today} отсутствует."
    else:
        message = f"📅 Расписание на {day_name_today} ({date_str}):\n\n"
        for lesson in lessons:
            message += f"⏰ {lesson['time']}\n📅 {lesson['info']}\n\n"

    keyboard = [
        [InlineKeyboardButton("⬅ Назад к меню", callback_data='back_to_week')],
    ]
    await safe_edit_message(query, text=message, reply_markup=InlineKeyboardMarkup(keyboard))

async def tomorrow_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    application = context.application
    schedule = await fetch_schedule(application)
    stats['schedule_requests'] += 1
    stats['commands_executed'] += 1
    save_stats()

    if not schedule:
        await safe_edit_message(query, text="Не удалось получить расписание. Попробуйте позже.")
        return

    date_str, day_name, current_week = get_current_week_and_day()

    if current_week not in schedule:
        await safe_edit_message(query, text="Расписание для текущей недели не найдено.")
        return

    if '_today_day' in schedule[current_week]:
        today_day_ru = schedule[current_week]['_today_day']
        tomorrow_day_ru = get_next_day_ru(today_day_ru)
        if tomorrow_day_ru == 'Понедельник':
            next_week = 'week_2' if current_week == 'week_1' else 'week_1'
            date_obj = datetime.datetime.strptime(date_str, '%d.%m.%Y').date() + datetime.timedelta(days=1)
            new_date_str = date_obj.strftime('%d.%m.%Y')
            lessons = schedule[next_week].get(tomorrow_day_ru, [])
        else:
            next_week = current_week
            date_obj = datetime.datetime.strptime(date_str, '%d.%m.%Y').date() + datetime.timedelta(days=1)
            new_date_str = date_obj.strftime('%d.%m.%Y')
            lessons = schedule[next_week].get(tomorrow_day_ru, [])
    else:
        date_str_tomorrow, day_name_ru, current_week = get_tomorrow_week_and_day()
        tomorrow_day_ru = day_name_ru
        lessons = schedule[current_week].get(tomorrow_day_ru, [])
        new_date_str = date_str_tomorrow

    if not lessons:
        message = f"Расписание на {tomorrow_day_ru} отсутствует."
    else:
        message = f"Расписание на {tomorrow_day_ru} ({new_date_str}):\n\n"
        for lesson in lessons:
            message += f"⏰ {lesson['time']}\n📅 {lesson['info']}\n\n"

    keyboard = [[InlineKeyboardButton("⬅ Назад к меню", callback_data='back_to_week')]]
    await safe_edit_message(query, text=message, reply_markup=InlineKeyboardMarkup(keyboard))

async def session_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    application = context.application
    schedule = await fetch_schedule(application)
    stats['schedule_requests'] += 1
    stats['commands_executed'] += 1
    save_stats()

    if not schedule:
        await safe_edit_message(query, text="Не удалось получить расписание. Попробуйте позже.")
        return

    if "session" not in schedule:
        await safe_edit_message(query, text="Расписание сессии не найдено.")
        return

    session_schedule = schedule["session"]
    message = "Расписание сессии:\n\n"
    for day_ru, lessons in session_schedule.items():
        message += f"{day_ru}:\n"
        if lessons:
            for lesson in lessons:
                message += f"⏰ {lesson['time']}\n📅 {lesson['info']}\n\n"
        else:
            message += "Расписание отсутствует.\n\n"

    keyboard = [[InlineKeyboardButton("⬅ Назад к меню", callback_data='back_to_week')]]
    await safe_edit_message(query, text=message, reply_markup=InlineKeyboardMarkup(keyboard))


async def day_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    application = context.application
    data = query.data
    parts = data.rsplit('_', 1)
    if len(parts) != 2:
        await safe_edit_message(query, text="Неверный формат данных.")
        return

    week, day = parts
    schedule = await fetch_schedule(application)
    stats['schedule_requests'] += 1
    stats['commands_executed'] += 1
    save_stats()

    if not schedule:
        await safe_edit_message(query, text="Не удалось получить расписание. Попробуйте позже.")
        return

    if week not in schedule:
        await safe_edit_message(query, text="Расписание для выбранной недели не найдено.")
        return

    lessons = schedule[week].get(day, [])
    if not lessons:
        message = f"Расписание на {day} отсутствует."
    else:
        message = f"Расписание на {day}:\n\n"
        for lesson in lessons:
            message += f"⏰ {lesson['time']}\n📅 {lesson['info']}\n\n"

    keyboard = [[InlineKeyboardButton("⬅ Назад к неделям", callback_data='back_to_week')]]
    await safe_edit_message(query, text=message, reply_markup=InlineKeyboardMarkup(keyboard))


async def back_to_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    date_str, day_name, current_week = get_current_week_and_day()
    week_text = "1-ая неделя" if current_week == 'week_1' else "2-ая неделя"
    welcome_message = (
        f"⏱️ Сегодня: {date_str}, {day_name}, {week_text}.\n\n"
        "💻 Разработчик @lssued\n\n"
        "🤖 https://github.com/Baillora\n\n"
    )
    keyboard = [
        [
            InlineKeyboardButton("1 неделя", callback_data='week_1'),
            InlineKeyboardButton("2 неделя", callback_data='week_2'),
            InlineKeyboardButton("Сессия", callback_data='session')
        ],
        [
            InlineKeyboardButton("Сегодня", callback_data='today'),
            InlineKeyboardButton("Завтра", callback_data='tomorrow')
        ],
        [
            InlineKeyboardButton("Преподаватели", callback_data='teachers_list')
        ]
    ]
    await safe_edit_message(query, text=welcome_message, reply_markup=InlineKeyboardMarkup(keyboard))

# ------------------------- Преподаватели -------------------------
async def teachers_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    if not is_user_allowed(user_id):
        await safe_edit_message(query, text="У вас нет доступа к информации о преподавателях.")
        return

    application = context.application
    await fetch_teachers(application)

    keyboard = []
    limit = 100  # ограничение по отображаемым преподавателям
    count = 0
    for teacher_id, data in teachers_cache.items():
        name = data["name"]
        keyboard.append([InlineKeyboardButton(name, callback_data=f"teacher_{teacher_id}")])
        count += 1
        if count >= limit:
            break

    keyboard.append([InlineKeyboardButton("⬅ Назад к меню", callback_data='back_to_week')])

    await safe_edit_message(
        query,
        text="Список преподавателей. \n\nВыберите преподавателя:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def teacher_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if not is_user_allowed(user_id):
        await safe_edit_message(query, text="У вас нет доступа к этой функции.")
        return

    data = query.data
    _, teacher_id = data.split('_', 1)

    if teacher_id not in teachers_cache:
        await safe_edit_message(query, text="Преподаватель не найден в кэше.")
        return

    teacher_name = teachers_cache[teacher_id]["name"]
    keyboard = [
        [
            InlineKeyboardButton("Пары", callback_data=f"teacher_pairs_{teacher_id}"),
            InlineKeyboardButton("Консультации", callback_data=f"teacher_consult_{teacher_id}")
        ],
        [
            InlineKeyboardButton("⬅ Назад к списку", callback_data='teachers_list')
        ]
    ]
    await safe_edit_message(
        query,
        text=f"Преподаватель: {teacher_name}\nВыберите действие:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def teacher_pairs_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if not is_user_allowed(user_id):
        await safe_edit_message(query, text="У вас нет доступа.")
        return

    data = query.data
    _, _, teacher_id = data.split('_', 2)

    pairs = await fetch_pairs_for_teacher(teacher_id)
    teachers_cache[teacher_id]["pairs"] = pairs

    teacher_name = teachers_cache[teacher_id]["name"]

    keyboard = []
    for day_ru in RU_WEEKDAYS_ORDER:
        keyboard.append([InlineKeyboardButton(day_ru, callback_data=f"teacher_day_{teacher_id}_{day_ru}")])

    keyboard.append([InlineKeyboardButton("Все дни", callback_data=f"teacher_day_{teacher_id}_ALL_DAYS")])
    keyboard.append([InlineKeyboardButton("Сегодня", callback_data=f"teacher_day_{teacher_id}_TODAY")])
    keyboard.append([InlineKeyboardButton("⬅ Назад к преподавателю", callback_data=f"teacher_{teacher_id}")])

    await safe_edit_message(
        query,
        text=f"Выберите день, чтобы посмотреть пары у {teacher_name}:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def teacher_consult_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data
    _, _, teacher_id = data.split('_', 2)

    teacher_name = teachers_cache.get(teacher_id, {}).get("name", "Неизвестен")

    consultations = await fetch_consultations_for_teacher(teacher_id)
    message = f"Консультации {teacher_name}:\n\n"
    if not consultations:
        message += "Нет доступных консультаций или они ещё не выложены.\n"
    else:
        for c in consultations:
            message += f"📅 {c['date']}\n⏰ {c['time']}\n{c['info']}\n\n"

    keyboard = [[InlineKeyboardButton("⬅ Назад к преподавателю", callback_data=f"teacher_{teacher_id}")]]
    await safe_edit_message(query, text=message, reply_markup=InlineKeyboardMarkup(keyboard))

async def teacher_day_pairs_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    _, _, teacher_id, day_ru = data.split('_', 3)

    teacher_name = teachers_cache.get(teacher_id, {}).get("name", "Неизвестен")
    pairs = teachers_cache[teacher_id].get("pairs", {})

    user_id = update.effective_user.id

    # Обработка "Сегодня"
    if day_ru == "TODAY":
        _, day_name_ru, _ = get_current_week_and_day()
        day_ru = day_name_ru

    if day_ru == "ALL_DAYS":
        full_text = f"Все дни, когда у {teacher_name} есть пары:\n\n"
        empty_check = True
        for weekday_name, lessons in pairs.items():
            if not lessons:
                continue
            empty_check = False
            full_text += f"--- {weekday_name} ---\n\n"
            for lesson in lessons:
                time_ = lesson['time']
                info_ = lesson['info']
                full_text += f"⏰ {time_}\n{info_}\n\n"

        if empty_check:
            full_text += "\nНет пар ни в один день."

        pages = chunk_text_by_lines(full_text, 4000)
        context.user_data.setdefault("teacher_pages", {})
        context.user_data["teacher_pages"][(user_id, teacher_id, "all_days")] = pages

        page_index = 0
        text_page = pages[page_index]
        keyboard = []
        if len(pages) > 1:
            keyboard = [
                [
                    InlineKeyboardButton("Далее ➡️", callback_data=f"teacher_all_days_page_{teacher_id}_{page_index+1}")
                ]
            ]
        keyboard.append([InlineKeyboardButton("⬅ Назад к списку дней", callback_data=f"teacher_pairs_{teacher_id}")])

        await safe_edit_message(query, text=text_page, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # Если обычный день
    if day_ru not in pairs:
        await safe_edit_message(query, text=f"Для {day_ru} нет данных о парах.")
        return

    lessons = pairs[day_ru]
    message = f"Пары у {teacher_name} на {day_ru}:\n\n"
    if not lessons:
        message += "Нет пар в этот день.\n"
    else:
        for lesson in lessons:
            message += f"⏰ {lesson['time']}\n{lesson['info']}\n\n"

    keyboard = [[InlineKeyboardButton("⬅ Назад к списку дней", callback_data=f"teacher_pairs_{teacher_id}")]]
    await safe_edit_message(query, text=message, reply_markup=InlineKeyboardMarkup(keyboard))

async def teacher_all_days_pagination_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    data = query.data
    parts = data.split('_')
    teacher_id = parts[4]
    page_index_str = parts[5]

    page_index = int(page_index_str)

    pages_dict = context.user_data.get("teacher_pages", {})
    pages = pages_dict.get((user_id, teacher_id, "all_days"), [])

    if not pages:
        await safe_edit_message(query, text="Данные о страницах не найдены или устарели.")
        return

    if page_index < 0 or page_index >= len(pages):
        await safe_edit_message(query, text="Страница не найдена.")
        return

    text_page = pages[page_index]

    keyboard = []
    if page_index > 0:
        keyboard.append([
            InlineKeyboardButton("⬅️ Назад", callback_data=f"teacher_all_days_page_{teacher_id}_{page_index-1}")
        ])
    if page_index < len(pages) - 1:
        if keyboard:
            keyboard[0].append(
                InlineKeyboardButton("Далее ➡️", callback_data=f"teacher_all_days_page_{teacher_id}_{page_index+1}")
            )
        else:
            keyboard = [[
                InlineKeyboardButton("Далее ➡️", callback_data=f"teacher_all_days_page_{teacher_id}_{page_index+1}")
            ]]

    keyboard.append([InlineKeyboardButton("⬅ Назад к списку дней", callback_data=f"teacher_pairs_{teacher_id}")])

    await safe_edit_message(query, text=text_page, reply_markup=InlineKeyboardMarkup(keyboard))


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    stats['errors'] += 1
    save_stats()

    try:
        error_message = escape_markdown(str(context.error))
        error_text = f"Произошла ошибка:\n```\n{error_message}\n```"
        await context.bot.send_message(chat_id=OWNER_ID, text=error_text, parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"Не удалось уведомить администратора о ошибке: {e}")


# ---------------- Команды управления доступом ----------------
# /adduser
async def adduser(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    if not is_mod_or_admin(user_id):
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    if len(context.args) != 1:
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("Использование: /adduser <user_id>")
        return

    try:
        new_user_id = int(context.args[0])
    except ValueError:
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("User ID должен быть числом.")
        return

    if is_user_allowed(new_user_id):
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("Этот пользователь уже имеет доступ.")
        return

    try:
        new_user = await context.bot.get_chat(new_user_id)
        new_username = f"@{new_user.username}" if new_user.username else new_user.full_name
    except Exception as e:
        logger.error(f"Ошибка при получении пользователя {new_user_id}: {e}")
        new_username = "Не доступен"

    set_user_role(new_user_id, "user")
    logger.warning(f"/adduser: {username} ({user_id}) добавил {new_user_id} ({new_username})")
    stats['commands_executed'] += 1
    save_stats()

    await update.message.reply_text(f"✅ Пользователь {new_username} (ID {new_user_id}) добавлен.")

    await listusers_handler(update, context)

# /removeuser
async def removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    if not is_mod_or_admin(user_id):
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    if len(context.args) != 1:
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("Использование: /removeuser <user_id>")
        return

    try:
        remove_user_id = int(context.args[0])
    except ValueError:
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("User ID должен быть числом.")
        return

    if not is_user_allowed(remove_user_id):
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("Этот пользователь не имеет доступа.")
        return

    try:
        removed_user = await context.bot.get_chat(remove_user_id)
        removed_username = f"@{removed_user.username}" if removed_user.username else removed_user.full_name
    except Exception as e:
        logger.error(f"Ошибка при получении пользователя {remove_user_id}: {e}")
        removed_username = "Не доступен"

    del allowed_users[str(remove_user_id)]
    save_allowed_users(allowed_users)
    logger.warning(f"Команда /removeuser выполнена {username} ({user_id}) для удаления ID {remove_user_id} ({removed_username})")
    stats['commands_executed'] += 1
    save_stats()
    await update.message.reply_text(f"Пользователь с ID {remove_user_id} ({removed_username}) удалён.\n\nРазработчик @lssued")

# /listusers
async def listusers_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    if not is_mod_or_admin(user_id):
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    message_lines = []

    # Владелец
    owner_username = "Владелец"
    try:
        owner_user = await context.bot.get_chat(OWNER_ID)
        owner_username = f"@{owner_user.username}" if owner_user.username else owner_user.full_name
    except Exception as e:
        logger.error(f"Ошибка при получении владельца: {e}")

    message_lines.append(f"ID: {OWNER_ID}, Роль: owner, Username: {owner_username}")

    # Остальные пользователи
    users = load_allowed_users()
    for uid, udata in users.items():
        try:
            user = await context.bot.get_chat(int(uid))
            user_username = f"@{user.username}" if user.username else user.full_name
        except Exception as e:
            logger.error(f"Ошибка при получении {uid}: {e}")
            user_username = "Не доступен"

        role = udata.get("role", "user")
        message_lines.append(f"ID: {uid}, Роль: {role}, Username: {user_username}")

        # обновляем username в JSON
        users[uid]["username"] = user_username

    save_allowed_users(users)

    if not users and OWNER_ID:
        message_lines.append("Список разрешённых пользователей пуст.")

    message = "\n".join(message_lines)
    if len(message) > 4096:
        for i in range(0, len(message), 4096):
            await update.message.reply_text(message[i:i+4096])
    else:
        message += "\n\nРазработчик @lssued"
        await update.message.reply_text(message)

    logger.warning(f"/listusers выполнена {username} ({user_id})")
    stats['commands_executed'] += 1
    save_stats()

# /reload
async def reload_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    if not is_mod_or_admin(user_id):
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    application = context.application
    # Очищаем кэш расписания и заново загружаем
    schedule_cache.clear()
    await fetch_schedule(application)

    logger.warning(f"Команда /reload выполнена {username} ({user_id}) - Кэш расписания перезагружен.")
    stats['commands_executed'] += 1
    save_stats()
    await update.message.reply_text("Кэш расписания перезагружен.")

# /fullreload
async def fullreload_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if get_user_role(user_id) not in ["admin", "owner"]:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    application = context.application
    # кэш расписания
    schedule_cache.clear()
    await fetch_schedule(application)

    # кэш преподавателей
    teachers_cache.clear()
    await fetch_teachers(application)

    await update.message.reply_text("Полная перезагрузка расписания и списка преподавателей завершена.")

# /showlog
async def showlog_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name
    role = get_user_role(user_id)

    if get_user_role(user_id) not in ["admin", "owner"]:
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    num_lines = 100
    if len(context.args) == 1:
        try:
            num_lines = int(context.args[0])
        except ValueError:
            stats['commands_executed'] += 1
            save_stats()
            await update.message.reply_text("Использование: /showlog <число_строк>")
            return

    try:
        with open('warning.log', 'r', encoding='utf-8') as f:
            lines = f.readlines()
            last_lines = ''.join(lines[-num_lines:])
    except Exception as e:
        logger.error(f"Ошибка при чтении warning.log: {e}")
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("Не удалось прочитать файл логов.")
        return

    if not last_lines:
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("Файл логов пуст.")
        return

    if len(last_lines) > 4096:
        for i in range(0, len(last_lines), 4096):
            await update.message.reply_text(last_lines[i:i+4096])
    else:
        await update.message.reply_text(last_lines)

    logger.warning(f"Команда /showlog выполнена {username} ({user_id}) для отображения последних {num_lines} строк.")
    stats['commands_executed'] += 1
    save_stats()

# /stats
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name
    role = get_user_role(user_id)

    if get_user_role(user_id) not in ["admin", "owner"]:
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    unique_users_count = len(stats['unique_users'])
    schedule_requests = stats['schedule_requests']
    search_queries = stats['search_queries']
    commands_executed = stats['commands_executed']
    errors = stats['errors']
    total_messages = stats['total_messages']

    sorted_commands = sorted(stats['commands_per_user'].items(), key=lambda item: item[1], reverse=True)
    top_commands = "\n".join([f"• User ID {uid}: {count} команд" for uid, count in sorted_commands[:5]]) or "Нет данных"

    sorted_peak = sorted(stats['peak_usage'].items(), key=lambda item: item[1], reverse=True)
    peak_times = "\n".join([f"• Час {hour}: {count} команд" for hour, count in sorted_peak[:5]]) or "Нет данных"

    sorted_daily = sorted(stats['daily_active_users'].items(), key=lambda item: len(item[1]), reverse=True)
    daily_active = "\n".join([f"• {day}: {len(users)} пользователей" for day, users in sorted_daily[:5]]) or "Нет данных"

    message = (
        f"📊 **Статистика использования** 📊\n\n"
        f"👥 **Уникальных пользователей:** {unique_users_count}\n"
        f"💬 **Общее количество сообщений:** {total_messages}\n"
        f"🔄 **Запросов расписания:** {schedule_requests}\n"
        f"🔍 **Поисковых запросов:** {search_queries}\n"
        f"📌 **Выполнено команд:** {commands_executed}\n"
        f"⚠️ **Ошибок:** {errors}\n\n"
        f"🔝 **Топ 5 пользователей по выполненным командам:**\n{top_commands}\n\n"
        f"⏰ **Пиковые времена использования (топ 5):**\n{peak_times}\n\n"
        f"📅 **Ежедневная активность (топ 5 дней):**\n{daily_active}\n"
    )

    await update.message.reply_text(message, parse_mode='Markdown')
    logger.warning(f"Команда /stats выполнена {username} ({user_id})")
    stats['commands_executed'] += 1
    save_stats()

# /search
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name
    stats['search_queries'] += 1

    role = get_user_role(user_id)
    if role not in ["user", "mod", "admin", "owner"]:
        await update.message.reply_text("У вас нет доступа к использованию этого бота.")
        return

    if len(context.args) < 1:
        await update.message.reply_text("Использование: /search <запрос>")
        return

    query = ' '.join(context.args).lower()
    application = context.application
    schedule = await fetch_schedule(application)

    if not schedule:
        await update.message.reply_text("Не удалось получить расписание. Попробуйте позже.")
        return

    results = []
    for week_key in ['week_1', 'week_2', 'session']:
        if week_key not in schedule:
            continue
        for day, lessons in schedule[week_key].items():
            if day.startswith("_"):
                continue
            for lesson in lessons:
                if isinstance(lesson, dict):
                    info_lower = lesson['info'].lower()
                    if query in info_lower:
                        results.append({
                            'week': week_key,
                            'day': day,
                            'time': lesson['time'],
                            'info': lesson['info']
                        })
                else:
                    logger.error(f"Unexpected lesson format: {lesson} in week {week_key}, day {day}")

    if not results:
        await update.message.reply_text("Совпадений не найдено.")
        return

    message = f"🔍 **Результаты поиска для '{query}':**\n\n"
    for res in results:
        if res['week'] == 'week_1':
            week_text = "1-ая неделя"
        elif res['week'] == 'week_2':
            week_text = "2-ая неделя"
        else:
            week_text = "Сессия"
        message += (
            f"**{week_text}** - **{res['day']}**\n"
            f"⏰ {res['time']}\n{res['info']}\n\n"
        )

    if len(message) > 4096:
        for i in range(0, len(message), 4096):
            await update.message.reply_text(message[i:i+4096], parse_mode='Markdown')
    else:
        await update.message.reply_text(message, parse_mode='Markdown')

    logger.info(f"Пользователь {username} ({user_id}) выполнил поиск по запросу: '{query}'")

# /mod
async def mod_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    if get_user_role(user_id) not in ["admin", "owner"]:
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    if len(context.args) != 1:
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("Использование: /mod <user_id>")
        return

    try:
        target_user_id = int(context.args[0])
    except ValueError:
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("User ID должен быть числом.")
        return

    if not is_user_allowed(target_user_id):
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("Этот пользователь не имеет доступа. Сначала добавьте через /adduser.")
        return

    set_user_role(target_user_id, "mod", allowed_users[str(target_user_id)].get("username", ""))
    logger.warning(f"Команда /mod выполнена {username} ({user_id}) для назначения пользователя {target_user_id} модератором")
    stats['commands_executed'] += 1
    save_stats()
    await update.message.reply_text(f"Пользователь с ID {target_user_id} назначен модератором.\n\nРазработчик @lssued")

# /unmod
async def unmod_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    if get_user_role(user_id) not in ["admin", "owner"]:
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    if len(context.args) != 1:
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("Использование: /unmod <user_id>")
        return

    try:
        target_user_id = int(context.args[0])
    except ValueError:
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("User ID должен быть числом.")
        return

    current_role = get_user_role(target_user_id)
    if current_role != "mod":
        stats['commands_executed'] += 1
        save_stats()
        await update.message.reply_text("Этот пользователь не является модератором.")
        return

    set_user_role(target_user_id, "user", allowed_users[str(target_user_id)].get("username", ""))
    logger.warning(f"Команда /unmod выполнена {username} ({user_id}) для снятия роли модератора с пользователя {target_user_id}")
    stats['commands_executed'] += 1
    save_stats()
    await update.message.reply_text(f"Роль пользователя с ID {target_user_id} возвращена к `user`.\n\nРазработчик @lssued")

# /adm
async def adm_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    if user_id != OWNER_ID:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("Использование: /adm <user_id>")
        return

    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("User ID должен быть числом.")
        return

    set_user_role(target_user_id, "admin", allowed_users[str(target_user_id)].get("username", ""))
    stats['commands_executed'] += 1
    save_stats()
    await update.message.reply_text(f"Пользователь с ID {target_user_id} назначен администратором.\n\nРазработчик @lssued")
    logger.warning(f"Команда /adm выполнена {username} ({user_id}): назначен администратор {target_user_id}")

# /unadm
async def unadm_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    if user_id != OWNER_ID:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("Использование: /unadm <user_id>")
        return

    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("User ID должен быть числом.")
        return

    current_role = get_user_role(target_user_id)
    if current_role != "admin":
        await update.message.reply_text("Этот пользователь не является администратором.")
        return

    set_user_role(target_user_id, "user", allowed_users[str(target_user_id)].get("username", ""))
    stats['commands_executed'] += 1
    save_stats()
    await update.message.reply_text(f"Пользователь с ID {target_user_id} снят с роли администратора.\n\nРазработчик @lssued")
    logger.warning(f"Команда /unadm выполнена {username} ({user_id}): снята роль администратора с {target_user_id}")

# /restart
async def restart_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if get_user_role(user_id) != "owner":
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    await update.message.reply_text("Перезагрузка бота...")
    logger.info(f"Пользователь {user_id} инициировал перезагрузку бота.")
    save_stats()
    python = sys.executable
    os.execl(python, python, *sys.argv)

# /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    role = get_user_role(user_id)

    # Базовый набор
    public_commands = [
        "/start - Запустить бота",
        "/help - Показать доступные команды",
    ]

    # Для обычных юзеров
    user_commands = [
        "/search <запрос> - Поиск по предметам и преподавателям",
        "/plan - Показать учебный план",
        "/map - Показать карту корпусов"
    ]

    # Модер/админ
    mod_admin_commands = [
        "/adduser <user_id> - Добавить пользователя",
        "/removeuser <user_id> - Удалить пользователя",
        "/listusers - Показать список пользователей",
        "/reload - Перезагрузить кэш расписания",
        "/fullreload - Полная перезагрузка (расписание + преподаватели)"
    ]

    # Админ
    admin_commands = [
        "/showlog [число] - Показать последние записи из логов",
        "/stats - Показать статистику",
        "/mod <user_id> - Назначить пользователя модератором",
        "/unmod <user_id> - Снять пользователя с роли модератора",
        "/broadcast <сообщение> - Рассылка объявления"
    ]

    # Владелец
    owner_commands = [
        "/adm <user_id> - Назначить пользователя администратором",
        "/unadm <user_id> - Снять пользователя с роли администратора",
        "/restart - Перезагрузить бота"
    ]

    if role == "owner":
        commands_list = public_commands + user_commands + mod_admin_commands + admin_commands + owner_commands
    elif role == "admin":
        commands_list = public_commands + user_commands + mod_admin_commands + admin_commands
    elif role == "mod":
        commands_list = public_commands + user_commands + mod_admin_commands
    elif role == "user":
        commands_list = public_commands + user_commands
    else:
        commands_list = public_commands

    message = "\n".join(commands_list)
    await update.message.reply_text(message)
    stats['commands_executed'] += 1
    save_stats()

"""
# ------------------------- Inline -------------------------
async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.inline_query.query
    if not query:
        return

    results = []
    if query.startswith('/'):
        command, *args = query.split()
        args = ' '.join(args)

        commands_map = {
            '/today': ("Расписание на сегодня", today_handler),
            '/tomorrow': ("Расписание на завтра", tomorrow_handler),
            '/search': (f"Поиск: {args}", search_command),
        }

        if command in commands_map:
            description, handler = commands_map[command]
            results.append(
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title=command,
                    description=description,
                    input_message_content=InputTextMessageContent(query)
                )
            )

    await update.inline_query.answer(results)

"""


# --------------------------- Запуск приложения ---------------------------
def main():
    TOKEN = os.environ.get("TOKEN")  # Токен бота из .env
    if not TOKEN:
        logger.error("Пожалуйста, установите ваш Telegram Bot Token в .env (переменная TOKEN).")
        exit(1)

    try:
        migrate_users_format()
        logger.info("Миграция пользователей выполнена успешно.")
    except Exception as e:
        logger.error(f"Ошибка миграции пользователей: {e}")


    print_startup_messages()

    application = ApplicationBuilder().token(TOKEN).build()

    # Команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("adduser", adduser))
    application.add_handler(CommandHandler("removeuser", removeuser))
    application.add_handler(CommandHandler("listusers", listusers_handler))
    application.add_handler(CommandHandler("reload", reload_command))
    application.add_handler(CommandHandler("fullreload", fullreload_command))
    application.add_handler(CommandHandler("showlog", showlog_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("mod", mod_command))
    application.add_handler(CommandHandler("unmod", unmod_command))
    application.add_handler(CommandHandler("adm", adm_command))
    application.add_handler(CommandHandler("unadm", unadm_command))
    application.add_handler(CommandHandler("plan", plan_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("restart", restart_command))
    application.add_handler(CommandHandler("map", map_command))

    # Callback-кнопки
    application.add_handler(CallbackQueryHandler(back_to_week, pattern='^back_to_week$'))
    application.add_handler(CallbackQueryHandler(week_handler, pattern='^week_[12]$'))
    application.add_handler(CallbackQueryHandler(today_handler, pattern='^today$'))
    application.add_handler(CallbackQueryHandler(tomorrow_handler, pattern='^tomorrow$'))
    application.add_handler(CallbackQueryHandler(session_handler, pattern='^session$'))
    application.add_handler(CallbackQueryHandler(day_handler, pattern='^week_[12]_.+$'))
    application.add_handler(CallbackQueryHandler(teachers_list_handler, pattern='^teachers_list$'))
    application.add_handler(CallbackQueryHandler(teacher_handler, pattern=r'^teacher_\d+$'))
    application.add_handler(CallbackQueryHandler(teacher_pairs_handler, pattern=r'^teacher_pairs_\d+$'))
    application.add_handler(CallbackQueryHandler(teacher_consult_handler, pattern=r'^teacher_consult_\d+$'))
    application.add_handler(CallbackQueryHandler(teacher_day_pairs_handler, pattern=r'^teacher_day_\d+_.+$'))
    application.add_handler(CallbackQueryHandler(teacher_all_days_pagination_handler, pattern=r'^teacher_all_days_page_\d+_\d+$'))
    #application.add_handler(InlineQueryHandler(inline_query))

    # Обработчик ошибок
    application.add_error_handler(error_handler)


    # Передаём application в панель
    from admin_panel import app as admin_app
    admin_app.application = application

    # event loop для панели 
    async def _on_startup(app):
        from admin_panel import app as admin_app
        admin_app.bot_loop = asyncio.get_running_loop()

    application.post_init = _on_startup

    threading.Thread(target=run_flask, daemon=True).start()

    application.run_polling(close_loop=False)


if __name__ == '__main__':
    main()