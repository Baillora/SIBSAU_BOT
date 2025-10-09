import os
from pathlib import Path
from dotenv import load_dotenv

# Определяем корень проекта (где лежит .env)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = BASE_DIR / ".env"

# Загружаем .env из корня проекта
load_dotenv()

# Основные настройки бота
TOKEN = os.getenv("TOKEN")
SCHEDULE_URL = os.getenv("SCHEDULE_URL")
PLAN_URL = os.getenv("PLAN_URL", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# Flask-панель
FLASK_SECRET = os.getenv("FLASK_SECRET", "supersecretkey")
PANEL_USER = os.getenv("PANEL_USER", "admin")
PANEL_PASS = os.getenv("PANEL_PASS", "admin")

# SSL
SSL_CERT = os.getenv("SSL_CERT", "self_signed.crt")
SSL_KEY = os.getenv("SSL_KEY", "self_signed.key")

# 2FA
TOTP_SECRET = os.getenv("TOTP_SECRET", "")

# Файлы данных
ALLOWED_USERS_FILE = BASE_DIR / "allowed_users.json"
STATS_FILE = BASE_DIR / "stats.json"
LOG_FILE = BASE_DIR / "warning.log"

# Уровень логгирования
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Кэши
CACHE_EXPIRY = 60 * 30              # 30 минут для расписания
TEACHERS_CACHE_EXPIRY = 24 * 60 * 60 # 24 часа для списка преподавателей

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

LESSON_SCHEDULE = [
    (8 * 60, 9 * 60 + 30),     # 08:00–09:30
    (9 * 60 + 40, 11 * 60 + 10),  # 09:40–11:10
    (11 * 60 + 30, 13 * 60),      # 11:30–13:00
    (13 * 60 + 30, 15 * 60),      # 13:30–15:00
    (15 * 60 + 10, 16 * 60 + 40), # 15:10–16:40
    (16 * 60 + 50, 18 * 60 + 20), # 16:50–18:20
    (18 * 60 + 30, 20 * 60),      # 18:30–20:00
    (20 * 60 + 10, 21 * 60 + 40), # 20:10–21:40
]

EXPECTED_DAYS = list(WEEKDAYS.keys())
