import os
import tempfile
import pytest
import logging
from pathlib import Path
from unittest.mock import patch, AsyncMock
from telegram import Bot, Update, User, Message, Chat

@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp).resolve()

@pytest.fixture
def mock_settings(temp_dir, monkeypatch):
    allowed = temp_dir / "allowed_users.json"
    stats = temp_dir / "stats.json"
    log = temp_dir / "warning.log"

    # Мокаем пути
    monkeypatch.setattr("scr.core.settings.ALLOWED_USERS_FILE", allowed)
    monkeypatch.setattr("scr.core.settings.STATS_FILE", stats)
    monkeypatch.setattr("scr.core.settings.LOG_FILE", log)

    # Перезагружаем модули
    import importlib
    import scr.core.settings
    import scr.core.users
    import scr.core.stats
    import scr.core.logger
    importlib.reload(scr.core.settings)
    importlib.reload(scr.core.users)
    importlib.reload(scr.core.stats)

    # Пересоздаём логгер
    import scr.core.logger
    scr.core.logger.logger = scr.core.logger.setup_logger()

    yield {
        "allowed_users": allowed,
        "stats": stats,
        "log": log,
    }

# закрытие логгеров
@pytest.fixture(autouse=True)
def close_log_handlers():
    yield
    for handler in logging.root.handlers[:]:
        handler.close()
        logging.root.removeHandler(handler)
    bot_logger = logging.getLogger("bot")
    for handler in bot_logger.handlers[:]:
        handler.close()
        bot_logger.removeHandler(handler)

# Хелпер для моков
def create_mock_update(user_id: int, text: str = "", is_callback: bool = False):
    bot = AsyncMock(spec=Bot)
    user = User(id=user_id, is_bot=False, first_name="TestUser")
    chat = Chat(id=user_id, type="private")

    if is_callback:
        query = AsyncMock()
        query.from_user = user
        query.message = Message(message_id=1, date=None, chat=chat, from_user=user, text="")
        query.message.set_bot(bot)
        update = Update(update_id=1, callback_query=query)
    else:
        message = Message(message_id=1, date=None, chat=chat, from_user=user, text=text)
        message.set_bot(bot)
        update = Update(update_id=1, message=message)

    context = AsyncMock()
    context.bot = bot

    return update, context, bot
