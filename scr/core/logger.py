import logging
import sys
from logging.handlers import RotatingFileHandler
from scr.core.settings import LOG_FILE

class TelegramFilter(logging.Filter):
    def filter(self, record):
        return "https://api.telegram.org" not in record.getMessage()

def setup_logger():
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(TelegramFilter())

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=1 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.WARNING)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(TelegramFilter())

    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        handler.close()
        root_logger.removeHandler(handler)

    logging.basicConfig(
        level=logging.INFO,
        handlers=[console_handler, file_handler],
        force=True
    )

    return logging.getLogger("bot")

# Инициализация при импорте
logger = setup_logger()