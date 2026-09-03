import pytest
import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from tests.conftest import create_mock_update
from scr.core.settings import BOT_TIMEZONE
from scr.core.invites import InviteManager
from scr.parsers.schedule_parser import (
    save_schedule_backup,
    load_schedule_backup,
    fetch_schedule,
    schedule_cache
)
from scr.bot.handlers.utils import format_week_schedule, format_day_schedule
from scr.bot.handlers.start import start
from scr.bot.handlers.schedule import day_handler, today_handler
from scr.bot.handlers.admin import invite_command, invites_command


# ==================== ТЕСТЫ РАЗДЕЛИТЕЛЕЙ И ФОРМАТИРОВАНИЯ ====================

def test_format_week_schedule_separation():
    week_data = {
        "Понедельник": [
            {
                "time": "09:40-11:10",
                "info": "Электроника и схемотехника\nКустов Н. Д.",
                "subgroup": "2 подгруппа",
                "classroom": 'корп. "С3" каб. "504"'
            }
        ],
        "Вторник": [
            {
                "time": "11:30-13:00",
                "info": "Безопасность сетей\nСелигеев С. В.",
                "subgroup": "2 подгруппа",
                "classroom": 'корп. "С3" каб. "507"'
            }
        ],
        "Среда": [],
        "Четверг": [],
        "Пятница": [],
        "Суббота": [],
        "Воскресенье": []
    }

    formatted = format_week_schedule(
        week_title="Неделя 1",
        week_data=week_data,
        user_subgroup="2",
        is_backup=False
    )

    # Проверяем наличие разделителей и красивых заголовков дней
    assert "━━━━━━━━━━━━━━━━━━━━" in formatted
    assert "🗓 *ПОНЕДЕЛЬНИК*" in formatted
    assert "🗓 *ВТОРНИК*" in formatted
    assert "🗓 *СРЕДА*" in formatted
    assert "✨ _Пар нет — выходной_" in formatted
    assert "Кустов Н. Д." in formatted
    assert "Селигеев С. В." in formatted


def test_format_week_schedule_backup_notice():
    week_data = {"Понедельник": []}
    formatted = format_week_schedule(
        week_title="Неделя 1",
        week_data=week_data,
        is_backup=True,
        backup_time="03.09.2026 в 20:00"
    )
    assert "⚠️ _Сайт расписания недоступен. Копия от 03.09.2026 в 20:00_" in formatted


# ==================== ТЕСТЫ РЕЗЕРВНОЙ КОПИИ РАСПИСАНИЯ ====================

def test_schedule_backup_save_and_load(tmp_path, monkeypatch):
    bak_file = tmp_path / "test_backup.json"
    monkeypatch.setattr("scr.parsers.schedule_parser.SCHEDULE_BACKUP_FILE", bak_file)

    sample_schedule = {
        "week_1": {
            "Понедельник": [{"time": "09:40-11:10", "info": "Физика", "subgroup": "1 подгруппа", "classroom": "А-101"}]
        },
        "_current_week": "week_1"
    }

    save_schedule_backup(sample_schedule)
    assert bak_file.exists()

    loaded = load_schedule_backup()
    assert loaded is not None
    assert loaded.get("_is_backup") is True
    assert "_backup_time" in loaded
    assert "week_1" in loaded
    assert loaded["week_1"]["Понедельник"][0]["info"] == "Физика"


@pytest.mark.asyncio
async def test_fetch_schedule_fallback_to_backup(tmp_path, monkeypatch):
    bak_file = tmp_path / "test_backup.json"
    monkeypatch.setattr("scr.parsers.schedule_parser.SCHEDULE_BACKUP_FILE", bak_file)
    monkeypatch.setattr("scr.parsers.schedule_parser.SCHEDULE_URL", "https://invalid-non-existent-site-123456.ru")
    schedule_cache.clear()

    # Сохраняем заведомо рабочий бэкап
    sample = {"week_2": {"Вторник": []}}
    save_schedule_backup(sample)

    # Вызов fetch_schedule должен не упасть, а загрузить бэкап
    result = await fetch_schedule(application=None)
    assert result.get("_is_backup") is True
    assert "week_2" in result


# ==================== ТЕСТЫ СИСТЕМЫ ИНВАЙТ-ССЫЛОК ====================

def test_invite_manager_lifecycle(tmp_path):
    inv_file = tmp_path / "invites.json"
    im = InviteManager(file_path=inv_file)

    # 1. Создание ссылки с лимитом 2
    inv = im.create_invite(title="Группа ИБ-22", role="user", max_uses=2)
    token = inv["token"]
    assert inv["max_uses"] == 2
    assert inv["used_count"] == 0
    assert inv["is_active"] is True

    # 2. Первое использование
    success, msg, data = im.use_invite(token, 111111, "student1")
    assert success is True
    assert data["used_count"] == 1
    assert data["is_active"] is True

    # 3. Второе использование (достигаем лимита)
    success, msg, data = im.use_invite(token, 222222, "student2")
    assert success is True
    assert data["used_count"] == 2
    assert data["is_active"] is False

    # 4. Третье использование (должно отказать)
    success, msg, data = im.use_invite(token, 333333, "student3")
    assert success is False
    assert "исчерпан" in msg or "деактивирована" in msg


def test_invite_manager_expiration(tmp_path):
    inv_file = tmp_path / "invites.json"
    im = InviteManager(file_path=inv_file)

    # Создаем уже просроченную ссылку
    yesterday = (datetime.datetime.now(BOT_TIMEZONE) - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    inv = im.create_invite(title="Истекшая ссылка", role="user", expires_at=yesterday)
    token = inv["token"]

    success, msg, data = im.use_invite(token, 555555, "late_student")
    assert success is False
    assert "истёк" in msg


@pytest.mark.asyncio
async def test_bot_start_with_invite_link(mock_settings, monkeypatch, tmp_path):
    inv_file = tmp_path / "invites.json"
    from scr.core import invites as invites_mod
    test_im = InviteManager(file_path=inv_file)
    monkeypatch.setattr(invites_mod, "invite_manager", test_im)
    monkeypatch.setattr("scr.bot.handlers.start.invite_manager", test_im)

    # Создаем инвайт
    inv = test_im.create_invite(title="Тест инвайт", role="user", max_uses=5)

    new_user_id = 999123456
    update, context, bot = create_mock_update(new_user_id)
    context.args = [f"inv_{inv['token']}"]

    # Мокаем build_start_payload
    async def mock_payload(*args, **kwargs):
        return "Добро пожаловать в расписание!", None

    monkeypatch.setattr("scr.bot.handlers.start.build_start_payload", mock_payload)

    await start(update, context)

    # Проверяем, что пользователю отправлено приветствие об успешной авторизации
    assert update.message.reply_text.called
    replies = [call[0][0] for call in update.message.reply_text.call_args_list]
    joined_replies = " ".join(replies)
    assert "успешно авторизованы" in joined_replies or "Добро пожаловать" in joined_replies

    # И пользователь теперь разрешен в user_manager
    from scr.core.users import user_manager
    assert user_manager.is_allowed(new_user_id) is True


@pytest.mark.asyncio
async def test_admin_invite_commands(mock_settings, monkeypatch, tmp_path):
    inv_file = tmp_path / "invites.json"
    from scr.core import invites as invites_mod
    test_im = InviteManager(file_path=inv_file)
    monkeypatch.setattr(invites_mod, "invite_manager", test_im)

    owner_id = mock_settings["owner_id"]
    update, context, bot = create_mock_update(owner_id)
    context.args = ["Для", "старосты", "10"]

    await invite_command(update, context)
    assert update.message.reply_text.called
    reply_text = update.message.reply_text.call_args[0][0]
    assert "Ссылка-приглашение успешно создана" in reply_text
    assert "Для старосты" in reply_text
    assert "10 раз(а)" in reply_text

    # Проверяем команду /invites
    update2, context2, bot2 = create_mock_update(owner_id)
    await invites_command(update2, context2)
    assert update2.message.reply_text.called
    list_text = update2.message.reply_text.call_args[0][0]
    assert "Список ссылок-приглашений" in list_text
    assert "Для старосты" in list_text


# ==================== ТЕСТЫ МАРШРУТОВ ВЕБ-ПАНЕЛИ ====================

def test_web_panel_invites_flow(mock_settings, monkeypatch, tmp_path):
    from scr.admin_panel.app import app
    inv_file = tmp_path / "invites.json"
    from scr.core import invites as invites_mod
    test_im = InviteManager(file_path=inv_file)
    monkeypatch.setattr(invites_mod, "invite_manager", test_im)
    monkeypatch.setattr("scr.admin_panel.app.invite_manager", test_im)

    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    client = app.test_client()

    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["role"] = "admin"
        sess["username"] = "admin_tester"

    # GET /invites
    resp = client.get("/invites")
    assert resp.status_code == 200
    assert "Ссылки-приглашения" in resp.get_data(as_text=True)

    # POST /invites/create
    resp_create = client.post("/invites/create", data={
        "title": "Веб-инвайт",
        "role": "user",
        "max_uses": "3",
        "expires_at": ""
    }, follow_redirects=True)
    assert resp_create.status_code == 200
    assert "Веб-инвайт" in resp_create.get_data(as_text=True)

    all_invs = test_im.get_all_invites()
    assert len(all_invs) == 1
    tok = all_invs[0]["token"]

    # POST /invites/toggle/<token>
    client.post(f"/invites/toggle/{tok}", follow_redirects=True)
    assert test_im.get_invite(tok)["is_active"] is False

    # POST /invites/delete/<token>
    client.post(f"/invites/delete/{tok}", follow_redirects=True)
    assert test_im.get_invite(tok) is None
