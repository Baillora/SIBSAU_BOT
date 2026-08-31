import pytest
from unittest.mock import AsyncMock
from telegram import Update, User, InlineQuery
from tests.conftest import create_mock_update
from scr.core.users import UserManager
from scr.bot.handlers.utils import render_progress_bar, format_lessons
from scr.bot.handlers.calendar_export import generate_ical, export_calendar_command
from scr.bot.handlers.inline import inline_query_handler


def test_user_subgroup_preference(temp_dir):
    f_path = temp_dir / "users_subgroup.json"
    um = UserManager(owner_id=1, file_path=f_path)
    um.add_user(100, "user")

    assert um.get_subgroup(100) == "all"
    um.set_subgroup(100, "1")
    assert um.get_subgroup(100) == "1"

    um.set_subgroup(100, "2")
    assert um.get_subgroup(100) == "2"

    um.set_subgroup(100, "invalid")
    assert um.get_subgroup(100) == "all"


def test_user_notifications_toggle(temp_dir):
    f_path = temp_dir / "users_notif.json"
    um = UserManager(owner_id=1, file_path=f_path)
    um.add_user(100, "user")

    assert not um.get_notifications(100)
    um.set_notifications(100, True)
    assert um.get_notifications(100)


def test_progress_bar_calculation():
    # 09:40 (580 min) to 11:10 (670 min)
    start_m = 9 * 60 + 40
    end_m = 11 * 60 + 10

    bar_mid = render_progress_bar(start_m + 45, start_m, end_m, length=10)
    assert "50%" in bar_mid
    assert "█" in bar_mid

    bar_start = render_progress_bar(start_m, start_m, end_m, length=10)
    assert "0%" in bar_start

    bar_end = render_progress_bar(end_m, start_m, end_m, length=10)
    assert "100%" in bar_end


def test_subgroup_filtering_in_schedule():
    sample_lessons = [
        {"time": "08:00-09:30", "info": "Лекция общая", "subgroup": None},
        {"time": "09:40-11:10", "info": "Лаба 1", "subgroup": "1️⃣ подгруппа"},
        {"time": "09:40-11:10", "info": "Лаба 2", "subgroup": "2️⃣ подгруппа"},
    ]

    # Filter for subgroup 1
    res_sub1 = format_lessons(sample_lessons, user_subgroup="1")
    assert "Лекция общая" in res_sub1
    assert "Лаба 1" in res_sub1
    assert "Лаба 2" not in res_sub1

    # Filter for subgroup 2
    res_sub2 = format_lessons(sample_lessons, user_subgroup="2")
    assert "Лекция общая" in res_sub2
    assert "Лаба 1" not in res_sub2
    assert "Лаба 2" in res_sub2

    # All
    res_all = format_lessons(sample_lessons, user_subgroup="all")
    assert "Лаба 1" in res_all
    assert "Лаба 2" in res_all


def test_ical_export_generation():
    sample_schedule = {
        "week_1": {
            "Понедельник": [
                {
                    "time": "09:40-11:10",
                    "info": "Электроника и схемотехника\nКустов Н. Д.",
                    "subgroup": "2 подгруппа",
                    "classroom": "корп. С3 каб. 504"
                }
            ]
        },
        "week_2": {
            "Понедельник": [
                {
                    "time": "11:30-13:00",
                    "info": "Электроника\nХанов В. Х.",
                    "subgroup": None,
                    "classroom": "корп. С3 каб. 506"
                }
            ]
        }
    }

    ics_all = generate_ical(sample_schedule, user_subgroup="all", weeks_count=2)
    assert "BEGIN:VCALENDAR" in ics_all
    assert "Электроника и схемотехника" in ics_all
    assert "корп. С3 каб. 504" in ics_all
    assert "END:VCALENDAR" in ics_all

    # Subgroup 1 should filter out 2 подгруппа
    ics_sub1 = generate_ical(sample_schedule, user_subgroup="1", weeks_count=2)
    assert "Электроника и схемотехника" not in ics_sub1
    assert "Ханов В. Х." in ics_sub1


@pytest.mark.asyncio
async def test_inline_query(mock_settings, monkeypatch):
    owner_id = mock_settings["owner_id"]

    user = User(id=owner_id, is_bot=False, first_name="Owner", username="owner")
    inline_q = AsyncMock(spec=InlineQuery)
    inline_q.from_user = user
    inline_q.query = ""
    inline_q.answer = AsyncMock()

    update = AsyncMock(spec=Update)
    update.inline_query = inline_q

    context = AsyncMock()

    async def mock_fetch(*args, **kwargs):
        return {
            "week_1": {
                "Понедельник": [
                    {"time": "09:40-11:10", "info": "Математика\nИванов", "subgroup": None, "classroom": "каб. 101"}
                ]
            }
        }

    monkeypatch.setattr("scr.bot.handlers.inline.fetch_schedule", mock_fetch)

    # Empty query
    await inline_query_handler(update, context)
    inline_q.answer.assert_called()
    results = inline_q.answer.call_args[0][0]
    assert len(results) >= 3

    # Search query
    inline_q.query = "математика"
    await inline_query_handler(update, context)
    inline_q.answer.assert_called()
    results_search = inline_q.answer.call_args[0][0]
    assert len(results_search) >= 1
    assert "Математика" in results_search[0].input_message_content.message_text
