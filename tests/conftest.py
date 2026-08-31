import os
import tempfile
import pytest
import logging
from pathlib import Path
from unittest.mock import patch, AsyncMock
from telegram import Bot, Update, User, Chat

from scr.core.users import UserManager
from scr.core.stats import StatsManager
from scr.core.notes import NotesManager


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp).resolve()


@pytest.fixture
def mock_settings(temp_dir, monkeypatch):
    allowed = temp_dir / "allowed_users.json"
    stats = temp_dir / "stats.json"
    log = temp_dir / "warning.log"
    twofa = temp_dir / "2fa_status.json"
    notes = temp_dir / "notes.json"

    # Мокаем пути в settings
    monkeypatch.setattr("scr.core.settings.ALLOWED_USERS_FILE", allowed)
    monkeypatch.setattr("scr.core.settings.STATS_FILE", stats)
    monkeypatch.setattr("scr.core.settings.LOG_FILE", log)
    monkeypatch.setattr("scr.core.settings.TWOFA_FILE", twofa)
    monkeypatch.setattr("scr.core.settings.NOTES_FILE", notes)
    monkeypatch.setattr("scr.core.settings.OWNER_ID", 1000000000)

    # Пересоздаем синглтоны
    import scr.core.users
    import scr.core.stats
    import scr.core.notes
    import scr.core.logger

    new_user_manager = UserManager(owner_id=1000000000, file_path=allowed)
    new_stats_manager = StatsManager(file_path=stats)
    new_notes_manager = NotesManager(file_path=notes)

    monkeypatch.setattr("scr.core.users.user_manager", new_user_manager)
    monkeypatch.setattr("scr.bot.handlers.utils.user_manager", new_user_manager)
    monkeypatch.setattr("scr.bot.handlers.admin.user_manager", new_user_manager)
    monkeypatch.setattr("scr.bot.handlers.misc.user_manager", new_user_manager)
    monkeypatch.setattr("scr.bot.handlers.start.user_manager", new_user_manager)
    monkeypatch.setattr("scr.bot.handlers.schedule.user_manager", new_user_manager)
    monkeypatch.setattr("scr.bot.handlers.inline.user_manager", new_user_manager)
    monkeypatch.setattr("scr.bot.handlers.calendar_export.user_manager", new_user_manager)
    monkeypatch.setattr("scr.admin_panel.app.user_manager", new_user_manager)

    monkeypatch.setattr("scr.core.stats.stats_manager", new_stats_manager)
    monkeypatch.setattr("scr.bot.handlers.utils.stats_manager", new_stats_manager)
    monkeypatch.setattr("scr.bot.handlers.admin.stats_manager", new_stats_manager)
    monkeypatch.setattr("scr.bot.handlers.misc.stats_manager", new_stats_manager)
    monkeypatch.setattr("scr.bot.handlers.schedule.stats_manager", new_stats_manager)
    monkeypatch.setattr("scr.bot.handlers.inline.stats_manager", new_stats_manager)
    monkeypatch.setattr("scr.admin_panel.app.stats_manager", new_stats_manager)

    monkeypatch.setattr("scr.core.notes.notes_manager", new_notes_manager)
    monkeypatch.setattr("scr.bot.handlers.schedule.notes_manager", new_notes_manager)
    monkeypatch.setattr("scr.bot.handlers.misc.notes_manager", new_notes_manager)

    monkeypatch.setattr("scr.core.users.OWNER_ID", 1000000000)
    monkeypatch.setattr("scr.bot.handlers.admin.OWNER_ID", 1000000000)
    monkeypatch.setattr("scr.bot.handlers.utils.OWNER_ID", 1000000000)

    scr.core.logger.logger = scr.core.logger.setup_logger()

    yield {
        "allowed_users": allowed,
        "stats": stats,
        "log": log,
        "twofa": twofa,
        "notes": notes,
        "user_manager": new_user_manager,
        "stats_manager": new_stats_manager,
        "notes_manager": new_notes_manager,
        "owner_id": 1000000000
    }


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


def create_mock_update(user_id: int, text: str = "", is_callback: bool = False):
    bot = AsyncMock(spec=Bot)
    user = User(id=user_id, is_bot=False, first_name="TestUser", username="testuser")
    chat = Chat(id=user_id, type="private")

    if is_callback:
        query = AsyncMock()
        query.from_user = user
        query.data = text
        query.message = AsyncMock()
        query.message.message_id = 1
        query.message.chat_id = user_id
        query.message.chat = chat
        query.message.text = ""
        query.message.reply_text = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.answer = AsyncMock()

        update = AsyncMock(spec=Update)
        update.effective_user = user
        update.effective_chat = chat
        update.callback_query = query
        update.message = None
    else:
        message = AsyncMock()
        message.message_id = 1
        message.from_user = user
        message.chat_id = user_id
        message.chat = chat
        message.text = text
        message.reply_text = AsyncMock()

        update = AsyncMock(spec=Update)
        update.effective_user = user
        update.effective_chat = chat
        update.message = message
        update.callback_query = None

    context = AsyncMock()
    context.bot = bot
    context.application = AsyncMock()
    context.application.bot = bot

    return update, context, bot
