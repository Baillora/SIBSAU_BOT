import logging
import sys
import re
from pathlib import Path
from logging.handlers import RotatingFileHandler
from scr.core.settings import LOG_FILE, LOG_LEVEL

# Регулярное выражение для поиска и маскирования токенов Telegram Bot API
TOKEN_REGEX = re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")


class TelegramFilter(logging.Filter):
    """Фильтрует и маскирует токены Telegram Bot API и конфиденциальные данные в логах"""
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = TOKEN_REGEX.sub("<BOT_TOKEN_REDACTED>", record.msg)
            # Скрываем прямые обращения к api.telegram.org с токенами
            if "api.telegram.org/bot" in record.msg:
                record.msg = re.sub(r"bot[^\s/]+", "bot<REDACTED>", record.msg)
        return True


def setup_logger(name: str = "bot") -> logging.Logger:
    """Настройка логгера с выводом в консоль, ротацией и фильтрацией конфиденциальных данных"""
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(TelegramFilter())

    log_path = Path(LOG_FILE)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.WARNING)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(TelegramFilter())

    logger_instance = logging.getLogger(name)
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    logger_instance.setLevel(level)

    for handler in logger_instance.handlers[:]:
        handler.close()
        logger_instance.removeHandler(handler)

    logger_instance.addHandler(console_handler)
    logger_instance.addHandler(file_handler)
    logger_instance.propagate = True

    return logger_instance


logger = setup_logger()