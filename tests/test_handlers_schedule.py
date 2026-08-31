import pytest
from tests.conftest import create_mock_update
from scr.bot.handlers.schedule import today_handler, week_handler, day_handler, session_handler


@pytest.mark.asyncio
async def test_today_handler_unauthorized(mock_settings):
    user_id = 888888888
    update, context, bot = create_mock_update(user_id, is_callback=True)
    update.callback_query.data = "today"
    await today_handler(update, context)
    update.callback_query.answer.assert_called_with("У вас нет доступа к боту.", show_alert=True)


@pytest.mark.asyncio
async def test_week_handler_authorized(mock_settings, monkeypatch):
    owner_id = mock_settings["owner_id"]
    update, context, bot = create_mock_update(owner_id, is_callback=True)
    update.callback_query.data = "week_1"

    async def mock_fetch(*args, **kwargs):
        return {"week_1": {"Понедельник": []}}

    monkeypatch.setattr("scr.bot.handlers.schedule.fetch_schedule", mock_fetch)
    await week_handler(update, context)
    update.callback_query.edit_message_text.assert_called()


@pytest.mark.asyncio
async def test_day_handler_authorized(mock_settings, monkeypatch):
    owner_id = mock_settings["owner_id"]
    update, context, bot = create_mock_update(owner_id, is_callback=True)
    update.callback_query.data = "week_1_Понедельник"

    async def mock_fetch(*args, **kwargs):
        return {
            "week_1": {
                "Понедельник": [
                    {"time": "08:00-09:30", "info": "Высшая математика\nИванов И.И.", "subgroup": "1 подгруппа", "classroom": "каб. Л-404"}
                ]
            }
        }

    monkeypatch.setattr("scr.bot.handlers.schedule.fetch_schedule", mock_fetch)
    await day_handler(update, context)
    update.callback_query.edit_message_text.assert_called()
    call_args = update.callback_query.edit_message_text.call_args[1]
    assert "Высшая математика" in call_args["text"]
    assert "каб. Л-404" in call_args["text"]