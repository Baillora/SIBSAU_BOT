import pytest
from tests.conftest import create_mock_update
from scr.bot.handlers.admin import adduser

@pytest.mark.asyncio
async def test_warning_log_written(caplog):
    user_id = 777777777
    update, context, bot = create_mock_update(user_id, "/adduser")
    context.args = ["123"]
    
    with caplog.at_level("WARNING"):
        await adduser(update, context)

    assert any("попытался выполнить /adduser без прав" in msg for msg in caplog.messages)