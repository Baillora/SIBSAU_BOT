import pytest
import datetime
from unittest.mock import patch, AsyncMock
from scr.parsers.schedule_parser import (
    extract_time,
    get_current_week_and_day,
    get_tomorrow_week_and_day,
    fetch_schedule,
    get_current_and_next_lesson,
    schedule_cache
)
from scr.parsers.teacher_parser import fetch_teachers, teachers_cache
from scr.bot.handlers.utils import format_lessons, format_day_schedule


def test_extract_time():
    assert extract_time("08:00-09:30") == "08:00-09:30"
    assert extract_time("  Пара 10:00-11:30 в каб  ") == "10:00-11:30"
    assert extract_time("12:00") == "12:00"
    assert extract_time("Текст без времени") == "Текст без времени"


def test_week_calculation():
    date_str, day_name, current_week = get_current_week_and_day()
    assert date_str is not None
    assert day_name is not None
    assert current_week in ("week_1", "week_2")

    t_date_str, t_day_name, t_week = get_tomorrow_week_and_day()
    assert t_date_str is not None
    assert t_day_name is not None
    assert t_week in ("week_1", "week_2")


def test_format_lessons():
    lessons = [
        {
            "time": "08:00-09:30",
            "info": "Информатика\nИванов И.И.",
            "subgroup": "1️⃣ подгруппа",
            "classroom": "каб. А-101"
        }
    ]
    formatted = format_lessons(lessons)
    assert "⏰ 08:00-09:30" in formatted
    assert "1️⃣ подгруппа" in formatted
    assert "📚 *Информатика*" in formatted
    assert "Иванов И.И." in formatted
    assert "📍 каб. А-101" in formatted

    # Test empty
    assert format_lessons([]) == ""


def test_format_day_schedule():
    text = format_day_schedule("Понедельник", [])
    assert "🔹 Понедельник:" in text
    assert "Нет пар." in text


@pytest.mark.asyncio
async def test_fetch_schedule_mock(monkeypatch):
    schedule_cache.clear()

    sample_html = """
    <html>
        <body>
            <div id="week_1_tab">
                <div class="day monday today">
                    <div class="line">
                        <div class="time">08:00-09:30</div>
                        <div class="discipline">
                            <li class="bold num_pdgrp">1 подгруппа</li>
                            Физика<br>каб. Л-100
                        </div>
                    </div>
                </div>
            </div>
        </body>
    </html>
    """

    class MockResponse:
        content = sample_html.encode("utf-8")
        def raise_for_status(self): pass

    async def mock_get(*args, **kwargs):
        return MockResponse()

    monkeypatch.setattr("httpx.AsyncClient.get", mock_get)
    monkeypatch.setattr("scr.parsers.schedule_parser.SCHEDULE_URL", "https://example.com/timetable")

    result = await fetch_schedule()
    assert "week_1" in result
    assert "Понедельник" in result["week_1"]
    lessons = result["week_1"]["Понедельник"]
    assert len(lessons) == 1
    assert lessons[0]["time"] == "08:00-09:30"
    assert "Физика" in lessons[0]["info"]
    assert lessons[0]["classroom"] == "каб. Л-100"
