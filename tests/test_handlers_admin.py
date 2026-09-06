import pytest
from tests.conftest import create_mock_update
from scr.bot.handlers.admin import (
    adduser, removeuser, listusers_handler, mod_command, unmod_command,
    adm_command, unadm_command, broadcast, stats_command, showlog
)


@pytest.mark.asyncio
async def test_adduser_success(mock_settings):
    owner_id = mock_settings["owner_id"]
    update, context, bot = create_mock_update(owner_id, "/adduser")
    context.args = ["2000000000"]
    await adduser(update, context)
    update.message.reply_text.assert_called()
    assert "добавлен" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_adduser_no_args(mock_settings):
    owner_id = mock_settings["owner_id"]
    update, context, bot = create_mock_update(owner_id, "/adduser")
    context.args = []
    await adduser(update, context)
    assert "Использование" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_removeuser_success(mock_settings):
    owner_id = mock_settings["owner_id"]
    um = mock_settings["user_manager"]
    um.add_user(3000000000, "user")
    update, context, bot = create_mock_update(owner_id, "/removeuser")
    context.args = ["3000000000"]
    await removeuser(update, context)
    assert "удалён" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_mod_command_no_rights(mock_settings):
    user_id = 4000000000
    update, context, bot = create_mock_update(user_id, "/mod")
    context.args = ["5000000000"]
    await mod_command(update, context)
    assert "Ваш ID" in update.message.reply_text.call_args[0][0] or "нет прав" in update.message.reply_text.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_broadcast_success(mock_settings):
    owner_id = mock_settings["owner_id"]
    um = mock_settings["user_manager"]
    um.add_user(6000000000, "user")
    update, context, bot = create_mock_update(owner_id, "/broadcast")
    context.args = ["Тестовое", "сообщение"]
    await broadcast(update, context)
    assert "Рассылка завершена" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_stats_command_no_rights(mock_settings):
    user_id = 7000000000
    update, context, bot = create_mock_update(user_id, "/stats")
    await stats_command(update, context)
    update.message.reply_text.assert_called()


@pytest.mark.asyncio
async def test_showlog_success(mock_settings):
    owner_id = mock_settings["owner_id"]
    update, context, bot = create_mock_update(owner_id, "/showlog")
    context.args = ["5"]
    await showlog(update, context)
    update.message.reply_text.assert_called()


@pytest.mark.asyncio
async def test_setweek_command(mock_settings):
    from scr.bot.handlers.admin import setweek_command
    import scr.core.settings as settings
    owner_id = mock_settings["owner_id"]

    # 1. Без аргументов - справка
    update, context, bot = create_mock_update(owner_id, "/setweek")
    context.args = []
    await setweek_command(update, context)
    assert "Управление четностью недели" in update.message.reply_text.call_args[0][0]

    # 2. Установка 2-й недели
    update, context, bot = create_mock_update(owner_id, "/setweek")
    context.args = ["2"]
    await setweek_command(update, context)
    assert settings.WEEK_OVERRIDE == "week_2"
    assert "переключена на 2-ю неделю" in update.message.reply_text.call_args[0][0]

    # 3. Сброс на auto
    update, context, bot = create_mock_update(owner_id, "/setweek")
    context.args = ["auto"]
    await setweek_command(update, context)
    assert settings.WEEK_OVERRIDE == ""
    assert "Сброшено на автоопределение недели" in update.message.reply_text.call_args[0][0]