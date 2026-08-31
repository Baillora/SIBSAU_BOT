import pytest
from tests.conftest import create_mock_update
from scr.bot.handlers.admin import adduser


@pytest.mark.asyncio
async def test_warning_log_written(caplog, mock_settings):
    user_id = 777777777
    update, context, bot = create_mock_update(user_id, "/adduser")
    context.args = ["123"]

    with caplog.at_level("WARNING", logger="bot"):
        await adduser(update, context)

    assert any("777777777" in msg and "adduser" in msg for msg in caplog.messages)