import pytest
from tests.conftest import create_mock_update
from scr.bot.handlers.misc import help_command, search_command, plan_command, map_command
from scr.bot.handlers.start import start


@pytest.mark.asyncio
async def test_start_unauthorized(mock_settings):
    user_id = 999999999
    update, context, bot = create_mock_update(user_id, "/start")
    await start(update, context)
    update.message.reply_text.assert_called()
    assert "Ваш ID" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_help_authorized(mock_settings):
    owner_id = mock_settings["owner_id"]
    update, context, bot = create_mock_update(owner_id, "/help")
    await help_command(update, context)
    update.message.reply_text.assert_called()
    assert "/adduser" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_search_no_access(mock_settings):
    user_id = 888888888
    update, context, bot = create_mock_update(user_id, "/search")
    context.args = ["математика"]
    await search_command(update, context)
    update.message.reply_text.assert_called()
    assert "Ваш ID" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_plan_no_access(mock_settings):
    user_id = 888888887
    update, context, bot = create_mock_update(user_id, "/plan")
    await plan_command(update, context)
    update.message.reply_text.assert_called()
    assert "Ваш ID" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_map_no_access(mock_settings):
    user_id = 888888886
    update, context, bot = create_mock_update(user_id, "/map")
    await map_command(update, context)
    update.message.reply_text.assert_called()
    assert "Ваш ID" in update.message.reply_text.call_args[0][0]