import pytest
from tests.conftest import create_mock_update
from scr.bot.handlers.teachers import teachers_list_handler, teacher_handler


@pytest.mark.asyncio
async def test_teachers_list_unauthorized(mock_settings):
    user_id = 777777777
    update, context, bot = create_mock_update(user_id, is_callback=True)
    update.callback_query.data = "teachers_list"
    await teachers_list_handler(update, context)
    update.callback_query.answer.assert_called_with("У вас нет доступа к боту.", show_alert=True)


@pytest.mark.asyncio
async def test_teachers_list_authorized(mock_settings, monkeypatch):
    owner_id = mock_settings["owner_id"]
    update, context, bot = create_mock_update(owner_id, is_callback=True)
    update.callback_query.data = "teachers_list"

    async def mock_fetch(*args, **kwargs):
        from scr.parsers.teacher_parser import teachers_cache
        teachers_cache["123"] = {"name": "Сидоров С.С.", "href": "", "pairs": {}, "consultations": []}
        return teachers_cache

    monkeypatch.setattr("scr.bot.handlers.teachers.fetch_teachers", mock_fetch)
    await teachers_list_handler(update, context)
    update.callback_query.edit_message_text.assert_called()
    assert "Сидоров С.С." in str(update.callback_query.edit_message_text.call_args)