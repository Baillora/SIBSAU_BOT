import pytest
from tests.conftest import create_mock_update
from scr.bot.handlers.admin import (
    adduser, removeuser, listusers_handler, mod_command, unmod_command,
    adm_command, unadm_command, broadcast, stats_command, showlog
)
from scr.core.settings import OWNER_ID
from dotenv import load_dotenv

load_dotenv()

@pytest.mark.asyncio
async def test_adduser_success(mock_settings):
    from scr.core.settings import OWNER_ID
    owner_id = OWNER_ID
    update, context, bot = create_mock_update(owner_id, "/adduser")
    context.args = ["2000000000"]
    await adduser(update, context)
    assert "добавлен" in bot.send_message.call_args[1]["text"]

@pytest.mark.asyncio
async def test_adduser_no_args(mock_settings):
    from scr.core.settings import OWNER_ID
    owner_id = OWNER_ID
    update, context, bot = create_mock_update(owner_id, "/adduser")
    context.args = []
    await adduser(update, context)
    assert "Использование" in bot.send_message.call_args[1]["text"]

@pytest.mark.asyncio
async def test_removeuser_success(mock_settings):
    from scr.core.settings import OWNER_ID
    owner_id = OWNER_ID
    from scr.core.users import UserManager
    users = UserManager(owner_id)
    users.add_user(3000000000, "user")
    update, context, bot = create_mock_update(owner_id, "/removeuser")
    context.args = ["3000000000"]
    await removeuser(update, context)
    assert "удалён" in bot.send_message.call_args[1]["text"]

@pytest.mark.asyncio
async def test_mod_command_no_rights(mock_settings):
    user_id = 4000000000
    update, context, bot = create_mock_update(user_id, "/mod")
    context.args = ["5000000000"]
    await mod_command(update, context)
    assert "Нет прав" in bot.send_message.call_args[1]["text"]

@pytest.mark.asyncio
async def test_broadcast_success(mock_settings):
    from scr.core.settings import OWNER_ID
    owner_id = OWNER_ID
    from scr.core.users import UserManager
    users = UserManager(owner_id)
    users.add_user(6000000000, "user")
    update, context, bot = create_mock_update(owner_id, "/broadcast")
    context.args = ["Тестовое сообщение"]
    await broadcast(update, context)
    assert "Рассылка завершена" in bot.send_message.call_args[1]["text"]

@pytest.mark.asyncio
async def test_stats_command_no_rights(mock_settings):
    user_id = 7000000000
    update, context, bot = create_mock_update(user_id, "/stats")
    await stats_command(update, context)
    assert "нет прав" in bot.send_message.call_args[1]["text"].lower()

@pytest.mark.asyncio
async def test_showlog_success(mock_settings):
    from scr.core.settings import OWNER_ID
    owner_id = OWNER_ID
    update, context, bot = create_mock_update(owner_id, "/showlog")
    context.args = ["5"]
    await showlog(update, context)
    bot.send_message.assert_called()