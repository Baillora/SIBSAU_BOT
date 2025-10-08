import pytest
from tests.conftest import create_mock_update
from scr.bot.handlers.schedule import today_handler, week_handler

@pytest.mark.asyncio
async def test_today_handler_unauthorized(mock_settings):
    user_id = 888888888
    update, context, bot = create_mock_update(user_id, is_callback=True)
    update.callback_query.data = "today"
    await today_handler(update, context)
    update.callback_query.answer.assert_called_with("У вас нет доступа к расписанию.", show_alert=True)

@pytest.mark.asyncio
async def test_week_handler_authorized(mock_settings):
    from scr.core.settings import OWNER_ID
    owner_id = OWNER_ID
    from scr.core.users import UserManager
    users = UserManager(owner_id)
    users.add_user(owner_id, "owner")
    update, context, bot = create_mock_update(owner_id, is_callback=True)
    update.callback_query.data = "week_1"
    # Мокаем fetch_schedule
    with pytest.MonkeyPatch.context() as mp:
        async def mock_fetch(*args, **kwargs):
            return {"week_1": {"Понедельник": []}}
        mp.setattr("scr.bot.handlers.schedule.fetch_schedule", mock_fetch)
        await week_handler(update, context)
    update.callback_query.edit_message_text.assert_called()