import pytest
from tests.conftest import create_mock_update
from scr.bot.handlers.teachers import teachers_list_handler

@pytest.mark.asyncio
async def test_teachers_list_unauthorized(mock_settings):
    user_id = 777777777
    update, context, bot = create_mock_update(user_id, is_callback=True)
    update.callback_query.data = "teachers_list"
    await teachers_list_handler(update, context)
    update.callback_query.edit_message_text.assert_called_with("Нет доступа.")