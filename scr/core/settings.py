import os
import re
import datetime
from pathlib import Path
from typing import Dict, Optional, Any
from dotenv import load_dotenv

# Корень проекта
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR
ENV_PATH = BASE_DIR / ".env"

# Загружаем .env из корня проекта
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    load_dotenv()

# Основные настройки бота
TOKEN = os.getenv("TOKEN", "")
SCHEDULE_URL = os.getenv("SCHEDULE_URL", "")
PLAN_URL = os.getenv("PLAN_URL", "")
PROXY_URL = os.getenv("PROXY_URL", "")
try:
    OWNER_ID = int(os.getenv("OWNER_ID", "0"))
except ValueError:
    OWNER_ID = 0

# Flask-панель
FLASK_SECRET = os.getenv("FLASK_SECRET", "supersecretkey")
PANEL_USER = os.getenv("PANEL_USER", "admin")
PANEL_PASS = os.getenv("PANEL_PASS", "admin")

# SSL
SSL_CERT = os.getenv("SSL_CERT", "self_signed.crt")
SSL_KEY = os.getenv("SSL_KEY", "self_signed.key")

# 2FA
TOTP_SECRET = os.getenv("TOTP_SECRET", "")

# Семестр
SEMESTER_START = os.getenv("SEMESTER_START", "")

# Часовой пояс бота (по умолчанию Красноярск Asia/Krasnoyarsk UTC+7)
TIMEZONE_NAME = os.getenv("TIMEZONE", "Asia/Krasnoyarsk")
try:
    import zoneinfo
    BOT_TIMEZONE = zoneinfo.ZoneInfo(TIMEZONE_NAME)
except Exception:
    BOT_TIMEZONE = datetime.timezone(datetime.timedelta(hours=7))

# Файлы данных
ALLOWED_USERS_FILE = BASE_DIR / "allowed_users.json"
STATS_FILE = BASE_DIR / "stats.json"
LOG_FILE = BASE_DIR / "warning.log"
TWOFA_FILE = BASE_DIR / "2fa_status.json"
NOTES_FILE = BASE_DIR / "notes.json"

# Уровень логгирования
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Кэши
CACHE_EXPIRY = int(os.getenv("CACHE_EXPIRY", str(60 * 30)))                # 30 минут для расписания
TEACHERS_CACHE_EXPIRY = int(os.getenv("TEACHERS_CACHE_EXPIRY", str(24 * 60 * 60))) # 24 часа для преподавателей

# Локализация дней недели
WEEKDAYS = {
    'Monday': 'Понедельник',
    'Tuesday': 'Вторник',
    'Wednesday': 'Среда',
    'Thursday': 'Четверг',
    'Friday': 'Пятница',
    'Saturday': 'Суббота',
    'Sunday': 'Воскресенье'
}

RU_WEEKDAYS_ORDER = [
    'Понедельник',
    'Вторник',
    'Среда',
    'Четверг',
    'Пятница',
    'Суббота',
    'Воскресенье'
]

EXPECTED_DAYS = list(WEEKDAYS.keys())

LESSON_SCHEDULE = [
    (8 * 60, 9 * 60 + 30),        # 08:00–09:30
    (9 * 60 + 40, 11 * 60 + 10),  # 09:40–11:10
    (11 * 60 + 30, 13 * 60),      # 11:30–13:00
    (13 * 60 + 30, 15 * 60),      # 13:30–15:00
    (15 * 60 + 10, 16 * 60 + 40), # 15:10–16:40
    (16 * 60 + 50, 18 * 60 + 20), # 16:50–18:20
    (18 * 60 + 30, 20 * 60),      # 18:30–20:00
    (20 * 60 + 10, 21 * 60 + 40), # 20:10–21:40
]

# Справочник корпусов СибГУ с точными гео-ссылками Яндекс.Карт
CAMPUS_DIRECTORY = {
    "С3": {
        "name": 'Корпус "С3"',
        "address": "ул. Семафорная, 123",
        "description": "Институт космических и информационных технологий (ИИТК), лаборатории и кафедры ИБ",
        "map_url": "https://yandex.ru/maps/-/CTTmyZYR"
    },
    "С1": {
        "name": 'Корпус "С1"',
        "address": "ул. Семафорная, 433/1",
        "description": "Военный учебный центр (ВУЦ)",
        "map_url": "https://yandex.ru/maps/-/CTTmyT8Q"
    },
    "Н": {
        "name": 'Корпус "Н"',
        "address": "пр. им. газеты Красноярский рабочий, 31, стр. 5",
        "description": "Учебный корпус (аудитории 100–400)",
        "map_url": "https://yandex.ru/maps/-/CTTm5B50"
    },
    "А": {
        "name": 'Корпус "А"',
        "address": "пр. им. газеты Красноярский рабочий, 31",
        "description": "Главный корпус правобережной площадки СибГУ",
        "map_url": "https://yandex.ru/maps/-/CTTmBK2J"
    },
    "П": {
        "name": 'Корпус "П"',
        "address": "пр. им. газеты Красноярский рабочий, 31, стр. 5",
        "description": "Лабораторный корпус прикладной математики и физики",
        "map_url": "https://yandex.ru/maps/-/CTTm5B50"
    },
    "ДВС": {
        "name": 'Корпус "ДВС"',
        "address": "ул. Центральный проезд, 7",
        "description": "Дворец водного спорта / Спортивный комплекс",
        "map_url": "https://yandex.ru/maps/-/CTTmFNYz"
    },
    "ГЛ": {
        "name": 'Главный корпус (Левый берег)',
        "address": "пр. Мира, 82",
        "description": "Левобережная площадка СибГУ",
        "map_url": "https://yandex.ru/maps/-/CTTmFXIM"
    },
    "Л": {
        "name": 'Корпус "Л"',
        "address": "пр. Мира, 82",
        "description": "Лесоинженерный корпус",
        "map_url": "https://yandex.ru/maps/-/CTTmFXIM"
    }
}


def lookup_campus(query: str) -> Optional[Dict[str, str]]:
    """Поиск корпуса по коду аудитории (например 'С3-504', 'корп. \"С3\"', 'Н-304')"""
    q = query.upper().replace('"', '').replace("'", "").strip()

    # Заменяем латинские буквы на похожие русские
    latin_to_ru = {"C": "С", "H": "Н", "A": "А", "P": "П", "K": "К", "M": "М", "T": "Т", "B": "В"}
    for l_char, r_char in latin_to_ru.items():
        q = q.replace(l_char, r_char)

    # 1. Приоритет: точные совпадения и многобуквенные префиксы (С3, С1, ДВС, ГЛ)
    for code in ["С3", "С1", "ДВС", "ГЛ"]:
        info = CAMPUS_DIRECTORY[code]
        if code == q or f"КОРП. {code}" in q or f"КОРП.{code}" in q or q.startswith(f"{code}-") or q.startswith(f"{code} ") or code in q:
            return info

    # 2. Однобуквенные корпуса (Н, А, П, Л): строгое совпадение с границами
    for code in ["Н", "А", "П", "Л"]:
        info = CAMPUS_DIRECTORY[code]
        pattern = rf"(^|[\s\"'«».,-])({code})($|[\s\"'«».,\-\d])"
        if re.search(pattern, q):
            return info

    return None


def get_semester_start_date(ref_date: datetime.date = None) -> datetime.date:
    """
    Возвращает дату начала текущего семестра.
    Если задано SEMESTER_START в .env — используется оно.
    Иначе рассчитывается динамически для текущего учебного года.
    """
    if SEMESTER_START:
        try:
            return datetime.datetime.strptime(SEMESTER_START, "%Y-%m-%d").date()
        except ValueError:
            pass

    if ref_date is None:
        ref_date = datetime.date.today()

    year = ref_date.year
    month = ref_date.month

    # Весенний семестр: февраль - август (начинается ориентировочно 1 февраля / первый понедельник февраля)
    if 2 <= month <= 8:
        return datetime.date(year, 2, 1)
    # Осенний семестр: сентябрь - декабрь (начинается 1 сентября)
    elif month >= 9:
        return datetime.date(year, 9, 1)
    # Январь — продолжение осеннего семестра предыдущего года
    else:
        return datetime.date(year - 1, 9, 1)
