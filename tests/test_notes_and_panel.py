import pytest
from unittest.mock import AsyncMock, patch
from scr.core.notes import NotesManager
from scr.core.settings import lookup_campus
from scr.admin_panel.app import app
from tests.conftest import create_mock_update
from scr.bot.handlers.schedule import day_handler, today_handler


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_notes_manager(temp_dir):
    notes_file = temp_dir / "test_notes.json"
    nm = NotesManager(file_path=notes_file)

    # Add note
    nid1 = nm.add_note(12345, "Электроника", "Сдать отчет к среде")
    nid2 = nm.add_note(12345, "Физика", "Подготовиться к тесту")

    user_notes = nm.get_user_notes(12345)
    assert len(user_notes) == 2
    assert user_notes[0]["subject"] == "Электроника"
    assert user_notes[0]["text"] == "Сдать отчет к среде"

    # Search by subject
    elec_notes = nm.get_notes_for_subject(12345, "электроника")
    assert len(elec_notes) == 1
    assert elec_notes[0]["id"] == nid1

    # Persistence
    nm2 = NotesManager(file_path=notes_file)
    assert len(nm2.get_user_notes(12345)) == 2

    # Delete
    assert nm2.delete_note(12345, nid1)
    assert len(nm2.get_user_notes(12345)) == 1
    assert not nm2.delete_note(12345, "non_existing_id")


def test_lookup_campus():
    info_c3 = lookup_campus("С3-504")
    assert info_c3 is not None
    assert "Семафорная" in info_c3["address"]

    info_latin_c3 = lookup_campus("C3-504")
    assert info_latin_c3 is not None
    assert "Семафорная" in info_latin_c3["address"]

    info_n = lookup_campus("Н-304")
    assert info_n is not None
    assert "Красноярский рабочий" in info_n["address"]

    info_dvs = lookup_campus("ДВС")
    assert info_dvs is not None
    assert "Центральный" in info_dvs["address"]

    assert lookup_campus("Неизвестный корпус 999") is None


@pytest.mark.asyncio
async def test_day_handler_with_notes_and_pagination(mock_settings, monkeypatch):
    owner_id = mock_settings["owner_id"]
    update, context, bot = create_mock_update(owner_id, is_callback=True)
    update.callback_query.data = "week_1_Понедельник"

    from scr.core.notes import notes_manager
    notes_manager.add_note(owner_id, "Математика", "Сделать домашку №5")

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
    assert "Сделать домашку №5" in call_args["text"]
    # Check pagination keyboard
    markup = call_args["reply_markup"]
    assert len(markup.inline_keyboard) == 2
    assert "◀️" in markup.inline_keyboard[0][0].text
    assert "▶️" in markup.inline_keyboard[0][2].text


def test_admin_panel_schedule_view(client, mock_settings):
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["username"] = "admin"

    response = client.get("/schedule")
    assert response.status_code == 200
    assert "Расписание занятий" in response.get_data(as_text=True)


def test_admin_panel_settings_view_and_post(client, mock_settings):
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["username"] = "admin"

    # GET
    response = client.get("/settings_panel")
    assert response.status_code == 200
    assert "Настройки системы" in response.get_data(as_text=True)

    # POST
    post_resp = client.post("/settings_panel", data={
        "schedule_url": "https://example.com/new_timetable",
        "plan_url": "https://example.com/new_plan",
        "semester_start": "2026-09-01",
        "log_level": "DEBUG"
    }, follow_redirects=True)
    assert post_resp.status_code == 200
    assert "Настройки обновлены" in post_resp.get_data(as_text=True)

    import scr.core.settings as s
    assert s.SCHEDULE_URL == "https://example.com/new_timetable"
    assert s.LOG_LEVEL == "DEBUG"


def test_admin_panel_logs_download_and_clear(client, mock_settings, temp_dir):
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["username"] = "admin"

    log_file = mock_settings["log"]
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("2026-08-31 - WARNING - Test log line\n")

    # Download
    dl_resp = client.get("/logs/download")
    assert dl_resp.status_code == 200
    assert "Test log line" in dl_resp.get_data(as_text=True)

    # Clear
    clear_resp = client.post("/logs/clear", follow_redirects=True)
    assert clear_resp.status_code == 200
    assert "Лог-файл успешно очищен" in clear_resp.get_data(as_text=True)

    with open(log_file, "r", encoding="utf-8") as f:
        assert f.read() == ""


def test_admin_panel_send_user_message(client, mock_settings, monkeypatch):
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["username"] = "admin"

    monkeypatch.setattr("scr.core.settings.TOKEN", "mock_bot_token_123")

    class MockResponse:
        is_success = True
        text = "ok"

    def mock_post(*args, **kwargs):
        return MockResponse()

    monkeypatch.setattr("httpx.Client.post", mock_post)

    response = client.post("/users/message/12345", data={"text": "Привет от админа!"}, follow_redirects=True)
    assert response.status_code == 200
    assert "Сообщение отправлено" in response.get_data(as_text=True)
