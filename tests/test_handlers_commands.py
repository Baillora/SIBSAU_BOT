import pytest
from tests.conftest import create_mock_update
from scr.bot.handlers.misc import help_command, search_command, plan_command, map_command
from scr.bot.handlers.start import start

@pytest.mark.asyncio
async def test_start_unauthorized(mock_settings):
    user_id = 999999999
    update, context, bot = create_mock_update(user_id, "/start")
    await start(update, context)
    assert "Ваш ID" in bot.send_message.call_args[1]["text"]

@pytest.mark.asyncio
async def test_help_authorized(mock_settings):
    from scr.core.settings import OWNER_ID
    owner_id = OWNER_ID
    from scr.core.users import UserManager
    users = UserManager(owner_id)
    users.add_user(owner_id, "owner")
    update, context, bot = create_mock_update(owner_id, "/help")
    await help_command(update, context)
    text = bot.send_message.call_args[1]["text"]
    assert "/adduser" in text

@pytest.mark.asyncio
async def test_search_no_access(mock_settings):
    user_id = 888888888
    update, context, bot = create_mock_update(user_id, "/search")
    context.args = ["математика"]
    await search_command(update, context)
    assert "нет доступа" in bot.send_message.call_args[1]["text"]

@pytest.mark.asyncio
async def test_plan_no_access(mock_settings):
    user_id = 888888887
    update, context, bot = create_mock_update(user_id, "/plan")
    await plan_command(update, context)
    assert "нет доступа" in bot.send_message.call_args[1]["text"]

@pytest.mark.asyncio
async def test_map_no_access(mock_settings):
    user_id = 888888886
    update, context, bot = create_mock_update(user_id, "/map")
    await map_command(update, context)
    assert "нет доступа" in bot.send_message.call_args[1]["text"]