import logging
import pytest
from unittest.mock import patch
from scr.core.logger import TelegramFilter
from scr.core.settings import lookup_campus
from scr.admin_panel.app import app, is_safe_url, send_owner_login_alert
from scr.bot.handlers.calendar_export import escape_ical_text


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_security_headers_present(client):
    response = client.get("/login")
    assert response.status_code == 200
    headers = response.headers

    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-XSS-Protection") == "1; mode=block"
    assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "default-src" in headers.get("Content-Security-Policy", "")


def test_telegram_token_filter():
    filter_obj = TelegramFilter()

    # Log record with token
    record = logging.LogRecord(
        name="test",
        level=logging.WARNING,
        pathname="",
        lineno=0,
        msg="Error connecting to https://api.telegram.org/bot1234567890:ABCdefGhIjkLmNoPqRsTuVwXyZ123456789/sendMessage with token 1234567890:ABCdefGhIjkLmNoPqRsTuVwXyZ123456789",
        args=(),
        exc_info=None
    )

    filter_obj.filter(record)
    assert "1234567890:ABCdefGhIjkLmNoPqRsTuVwXyZ123456789" not in record.msg
    assert "<BOT_TOKEN_REDACTED>" in record.msg or "bot<REDACTED>" in record.msg


def test_owner_login_alert_format_success(mock_settings, monkeypatch):
    sent_messages = []

    class MockResponse:
        is_success = True
        text = "ok"

    def mock_post(self, *args, **kwargs):
        json_data = kwargs.get("json")
        if json_data and "text" in json_data:
            sent_messages.append(json_data)
        return MockResponse()

    monkeypatch.setattr("httpx.Client.post", mock_post)
    monkeypatch.setattr("scr.core.settings.TOKEN", "test_bot_token")
    monkeypatch.setattr("scr.core.settings.OWNER_ID", 1000000000)

    send_owner_login_alert(
        is_success=True,
        username="Baillora",
        ip="64.188.70.197",
        host="117650.snk.wtf"
    )

    assert len(sent_messages) == 1
    text = sent_messages[0]["text"]
    assert sent_messages[0]["chat_id"] == 1000000000
    assert "Panel Info #2: ✅ Успешный вход в панель." in text
    assert "💻 Хост: 117650.snk.wtf" in text
    assert "👤 Имя пользователя: Baillora" in text
    assert "🌐 IP: 64.188.70.197" in text
    assert "⏰ Время:" in text


def test_owner_login_alert_format_failure(mock_settings, monkeypatch):
    sent_messages = []

    class MockResponse:
        is_success = True
        text = "ok"

    def mock_post(self, *args, **kwargs):
        json_data = kwargs.get("json")
        if json_data and "text" in json_data:
            sent_messages.append(json_data)
        return MockResponse()

    monkeypatch.setattr("httpx.Client.post", mock_post)
    monkeypatch.setattr("scr.core.settings.TOKEN", "test_bot_token")
    monkeypatch.setattr("scr.core.settings.OWNER_ID", 1000000000)

    send_owner_login_alert(
        is_success=False,
        username="Baillora",
        ip="64.188.70.197",
        host="117650.snk.wtf",
        reason="invalid credentials"
    )

    assert len(sent_messages) == 1
    text = sent_messages[0]["text"]
    assert sent_messages[0]["chat_id"] == 1000000000
    assert "Panel Info #2: ❗️ Ошибка входа в панель." in text
    assert "💻 Хост: 117650.snk.wtf" in text
    assert "❗️ Причина: invalid credentials" in text
    assert "👤 Имя пользователя: Baillora" in text
    assert "🌐 IP: 64.188.70.197" in text
    assert "⏰ Время:" in text


def test_is_safe_url():
    assert is_safe_url("https://timetable.pallada.sibsau.ru/timetable/group/13974")
    assert is_safe_url("http://example.com/plan.pdf")
    assert not is_safe_url("javascript:alert(1)")
    assert not is_safe_url("file:///etc/passwd")
    assert not is_safe_url("data:text/html,<script>alert(1)</script>")


def test_ical_escape_text():
    raw = "Test; special, char\\ and \r\n newline"
    escaped = escape_ical_text(raw)
    assert "\\;" in escaped
    assert "\\," in escaped
    assert "\\\\" in escaped
    assert "\r" not in escaped
