import logging
from logging.handlers import RotatingFileHandler
import httpx
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
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

load_dotenv()

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

file_handler = RotatingFileHandler('warning.log', maxBytes=1*1024*1024, backupCount=5, encoding='utf-8')
file_handler.setLevel(logging.WARNING)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

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

schedule_cache = {}
cache_expiry = 60 * 60 * 12 
last_fetch_time = 0

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
    if not os.path.exists(ALLOWED_USERS_FILE):
        return {}
    with open(ALLOWED_USERS_FILE, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
            if "users" in data and isinstance(data["users"], dict):
                return data["users"]
            else:
                return {}
        except json.JSONDecodeError:
            return {}

def save_allowed_users(users_dict):
    data = {"users": users_dict}
    with open(ALLOWED_USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

allowed_users = load_allowed_users()

def get_user_role(user_id: int) -> str:
    if user_id == OWNER_ID:
        return "owner"
    return allowed_users.get(str(user_id), None)

def is_user_allowed(user_id: int) -> bool:
    return get_user_role(user_id) in ["user", "mod", "admin", "owner"]

def is_mod_or_admin(user_id: int) -> bool:
    role = get_user_role(user_id)
    return role in ["mod", "admin", "owner"]

def set_user_role(user_id: int, role: str):
    if user_id == OWNER_ID:
        return

    if role in ["admin", "mod", "user"]:
        allowed_users[str(user_id)] = role
    else:
        allowed_users.pop(str(user_id), None)
    save_allowed_users(allowed_users)

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

async def fetch_schedule(application):
    global schedule_cache, last_fetch_time
    current_time = time.time()

    if current_time - last_fetch_time < cache_expiry:
        logger.info("Используется кэш расписания.")
        return schedule_cache

    logger.info("Обновление расписания с сайта.")

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.get(SCHEDULE_URL)
            response.raise_for_status()
        except httpx.RequestError as e:
            logger.error(f"Ошибка при получении страницы расписания: {e}")
            await notify_admin(application, f"Ошибка при получении страницы расписания: {e}")
            return schedule_cache

    soup = BeautifulSoup(response.content, "html.parser")
    schedule = {}

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
                weekday_class = next((c for c in ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"] if c in day_classes_lower), None)
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
                    logger.debug(f"Добавлено занятие: {lesson_entry} в неделю {week_key}, день {day_name_ru}")

            for day in EXPECTED_DAYS:
                day_ru = WEEKDAYS[day]
                if day_ru not in schedule[week_key]:
                    schedule[week_key][day_ru] = []

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
                    logger.debug(f"Добавлено занятие: {lesson_entry} в сессию, день {day_name_ru}")
        else:
            schedule["session"] = {}
            for day in EXPECTED_DAYS:
                day_ru = WEEKDAYS[day]
                schedule["session"][day_ru] = []

    except Exception as e:
        logger.error(f"Ошибка при парсинге расписания: {e}")
        await notify_admin(application, f"Ошибка при парсинге расписания: {e}")
        return schedule_cache

    schedule_cache = schedule
    last_fetch_time = current_time
    logger.info("Расписание успешно обновлено.")
    return schedule_cache

def get_current_week_and_day():
    today = datetime.date.today()
    weekday_en = today.strftime('%A')
    day_name_ru = WEEKDAYS.get(weekday_en, weekday_en)
    semester_start = datetime.date(2024, 9, 1)
    delta_weeks = (today - semester_start).days // 7
    current_week = 'week_1' if delta_weeks % 2 == 0 else 'week_2'
    date_str = today.strftime('%d.%m.%Y')
    return date_str, day_name_ru, current_week

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
            f"Ваш ID: {user_id}\n\nДля использования бота сообщите ваш ID администратору {owner_username}.\n\nРазработчик @lssued"
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
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_message, reply_markup=reply_markup)

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

# Выбор недели
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
        await query.edit_message_text(text="Не удалось получить расписание. Попробуйте позже.")
        return

    if week not in schedule:
        await query.edit_message_text(text="Расписание для выбранной недели не найдено.")
        return

    keyboard = []
    for day in EXPECTED_DAYS:
        day_ru = WEEKDAYS[day]
        if day_ru in schedule[week]:
            keyboard.append([InlineKeyboardButton(day_ru, callback_data=f"{week}_{day_ru}")])

    keyboard.append([InlineKeyboardButton("⬅ Назад", callback_data='back_to_week')])
    week_number = '1' if week == 'week_1' else '2'
    new_text = f"Вы выбрали {week_number}-ю неделю. Выберите день:"

    try:
        await query.edit_message_text(text=new_text, reply_markup=InlineKeyboardMarkup(keyboard))
    except BadRequest as e:
        if "Message is not modified" in str(e):
            pass
        else:
            logger.error(f"Ошибка при редактировании сообщения: {e}")
            await notify_admin(application, f"Ошибка при редактировании сообщения: {e}")

# Сегодня
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
        await query.edit_message_text(text="Не удалось получить расписание. Попробуйте позже.")
        return

    if current_week not in schedule:
        await query.edit_message_text(text="Расписание для текущей недели не найдено.")
        return

    if '_today_day' in schedule[current_week]:
        day_name_today = schedule[current_week]['_today_day']
        logger.debug(f"Используем день с классом 'today': {day_name_today}")
    else:
        day_name_today = day_name
        logger.debug(f"Используем день по дате: {day_name_today}")

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
    await query.edit_message_text(text=message, reply_markup=InlineKeyboardMarkup(keyboard))

# Завтра
async def tomorrow_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    application = context.application
    schedule = await fetch_schedule(application)
    stats['schedule_requests'] += 1
    stats['commands_executed'] += 1
    save_stats()

    if not schedule:
        await query.edit_message_text(text="Не удалось получить расписание. Попробуйте позже.")
        return

    date_str, day_name, current_week = get_current_week_and_day()

    if current_week not in schedule:
        await query.edit_message_text(text="Расписание для текущей недели не найдено.")
        return

    if '_today_day' in schedule[current_week]:
        today_day_ru = schedule[current_week]['_today_day']
        tomorrow_day_ru = get_next_day_ru(today_day_ru)
        logger.debug(f"Используем день с классом 'today': {today_day_ru}, завтрашний день: {tomorrow_day_ru}")

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
        logger.debug(f"Используем день по дате: {tomorrow_day_ru}")

    if not lessons:
        message = f"Расписание на {tomorrow_day_ru} отсутствует."
    else:
        message = f"Расписание на {tomorrow_day_ru} ({new_date_str}):\n\n"
        for lesson in lessons:
            message += f"⏰ {lesson['time']}\n📅 {lesson['info']}\n\n"

    keyboard = [[InlineKeyboardButton("⬅ Назад к меню", callback_data='back_to_week')]]
    await query.edit_message_text(text=message, reply_markup=InlineKeyboardMarkup(keyboard))

# Сессия
async def session_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    application = context.application
    schedule = await fetch_schedule(application)
    stats['schedule_requests'] += 1
    stats['commands_executed'] += 1
    save_stats()

    if not schedule:
        await query.edit_message_text(text="Не удалось получить расписание. Попробуйте позже.")
        return

    if "session" not in schedule:
        await query.edit_message_text(text="Расписание сессии не найдено.")
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
    await query.edit_message_text(text=message, reply_markup=InlineKeyboardMarkup(keyboard))

# Выбор дня
async def day_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    application = context.application
    data = query.data
    parts = data.rsplit('_', 1)
    if len(parts) != 2:
        await query.edit_message_text(text="Неверный формат данных.")
        return

    week, day = parts
    schedule = await fetch_schedule(application)
    stats['schedule_requests'] += 1
    stats['commands_executed'] += 1
    save_stats()

    if not schedule:
        await query.edit_message_text(text="Не удалось получить расписание. Попробуйте позже.")
        return

    if week not in schedule:
        await query.edit_message_text(text="Расписание для выбранной недели не найдено.")
        return

    lessons = schedule[week].get(day, [])
    if not lessons:
        message = f"Расписание на {day} отсутствует."
    else:
        message = f"Расписание на {day}:\n\n"
        for lesson in lessons:
            message += f"⏰ {lesson['time']}\n📅 {lesson['info']}\n\n"

    keyboard = [[InlineKeyboardButton("⬅ Назад к неделям", callback_data='back_to_week')]]
    await query.edit_message_text(text=message, reply_markup=InlineKeyboardMarkup(keyboard))

# Назад
async def back_to_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    application = context.application
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
        ]
    ]
    await query.edit_message_text(welcome_message, reply_markup=InlineKeyboardMarkup(keyboard))

# Обработчик ошибок
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик ошибок, который логирует ошибки и уведомляет администратора."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    stats['errors'] += 1
    save_stats()

    try:
        error_text = f"Произошла ошибка:\n```\n{context.error}\n```"
        await context.bot.send_message(chat_id=OWNER_ID, text=error_text, parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"Не удалось уведомить администратора о ошибке: {e}")

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
    logger.warning(f"Команда /adduser выполнена {username} ({user_id}) для добавления ID {new_user_id} ({new_username})")
    stats['commands_executed'] += 1
    save_stats()
    await update.message.reply_text(f"Пользователь с ID {new_user_id} ({new_username}) добавлен.\n\nРазработчик @lssued")

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

# Включение владельца
    owner_username = "Владелец"
    try:
        owner_user = await context.bot.get_chat(OWNER_ID)
        owner_username = f"@{owner_user.username}" if owner_user.username else owner_user.full_name
    except Exception as e:
        logger.error(f"Ошибка при получении информации о владельце: {e}")

    message_lines.append(f"ID: {OWNER_ID}, Роль: owner, Username: {owner_username}")

    for uid, urole in allowed_users.items():
        try:
            user = await context.bot.get_chat(int(uid))
            user_username = f"@{user.username}" if user.username else user.full_name
        except Exception as e:
            logger.error(f"Ошибка при получении пользователя {uid}: {e}")
            user_username = "Не доступен"

        message_lines.append(f"ID: {uid}, Роль: {urole}, Username: {user_username}")

    if not allowed_users and OWNER_ID:
        message_lines.append("Список разрешённых пользователей пуст.")

    MAX_MESSAGE_LENGTH = 4096
    message = "\n".join(message_lines)
    if len(message) > MAX_MESSAGE_LENGTH:
        for i in range(0, len(message), MAX_MESSAGE_LENGTH):
            await update.message.reply_text(message[i:i+MAX_MESSAGE_LENGTH])
    else:
        message += "\n\nРазработчик @lssued"
        await update.message.reply_text(message)

    logger.warning(f"Команда /listusers выполнена {username} ({user_id})")
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
    global schedule_cache, last_fetch_time
    schedule_cache = {}
    last_fetch_time = 0
    await fetch_schedule(application)
    logger.warning(f"Команда /reload выполнена {username} ({user_id}) - Кэш расписания перезагружен.")
    stats['commands_executed'] += 1
    save_stats()
    await update.message.reply_text("Кэш расписания перезагружен.")

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

# Команда /search
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
        for day, lessons in schedule.get(week_key, {}).items():
            for lesson in lessons:
                if isinstance(lesson, dict):
                    if query in lesson['info'].lower():
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
        await update.message.reply_text("Этот пользователь не имеет доступа, сначала добавьте его через /adduser <user_id>.")
        return

    set_user_role(target_user_id, "mod")
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

    set_user_role(target_user_id, "user")
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

    set_user_role(target_user_id, "admin")
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

    set_user_role(target_user_id, "user")
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
    await context.application.stop()
    sys.exit(0)

# /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    role = get_user_role(user_id)

    # Не авторизированны
    public_commands = [
        "/start - Запустить бота",
        "/help - Показать доступные команды",
    ]

    # Авторизованны
    user_commands = [
        "/search <запрос> - Поиск по предметам и преподавателям",
        "/plan - Показать учебный план"
    ]

    # Модератор и администратор
    mod_admin_commands = [
        "/adduser <user_id> - Добавить пользователя",
        "/removeuser <user_id> - Удалить пользователя",
        "/listusers - Показать список пользователей",
        "/reload - Перезагрузить кэш расписания"
    ]

    # Администратор
    admin_commands = [
        "/showlog [число] - Показать последние записи из логов",
        "/stats - Показать статистику",
        "/mod <user_id> - Назначить пользователя модератором",
        "/unmod <user_id> - Снять пользователя с роли модератора",
        "/broadcast <сообщение> - Рассылка объявления"
    ]

    # овнер
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

def main():
    TOKEN = os.environ.get("TOKEN")  # Токен бота из .env

    if not TOKEN:
        logger.error("Пожалуйста, установите ваш Telegram Bot Token в .env (переменная TOKEN).")
        exit(1)

    print_startup_messages()

    application = ApplicationBuilder().token(TOKEN).build()

    # команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("adduser", adduser))
    application.add_handler(CommandHandler("removeuser", removeuser))
    application.add_handler(CommandHandler("listusers", listusers_handler))
    application.add_handler(CommandHandler("reload", reload_command))
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

    # кнопоки
    application.add_handler(CallbackQueryHandler(back_to_week, pattern='^back_to_week$'))
    application.add_handler(CallbackQueryHandler(week_handler, pattern='^week_[12]$'))
    application.add_handler(CallbackQueryHandler(today_handler, pattern='^today$'))
    application.add_handler(CallbackQueryHandler(tomorrow_handler, pattern='^tomorrow$'))
    application.add_handler(CallbackQueryHandler(session_handler, pattern='^session$'))
    application.add_handler(CallbackQueryHandler(day_handler, pattern='^week_[12]_.+$'))

    application.add_error_handler(error_handler)

    application.run_polling()

if __name__ == '__main__':
    main()