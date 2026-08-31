import pytest
from bs4 import BeautifulSoup
from scr.parsers.schedule_parser import fetch_schedule, schedule_cache
from scr.parsers.teacher_parser import fetch_teachers, teachers_cache

REAL_HTML = """<!DOCTYPE html>
<html data-website-id="1" lang="ru-RU" data-oe-company-name="СибГУ им. М.Ф. Решетнева">
<head><title>Расписание КБ24-01</title></head>
<body>
<div class="container">
    <h3 class="text-center bold">"КБ24-01"<br/>1 семестр 2026-2027г.</h3>
    <h4 class="text-center bold">31.08.2026 - 1 неделя</h4>
    <div id="timetable_tab">
        <div id="week_1_tab">
            <div class="day monday today">
                <div class="header"><div class="name text-center"><div>Понедельник</div></div></div>
                <div class="body">
                    <div class="line">
                        <div class="time text-center"><div class="hidden-xs">09:40-11:10</div></div>
                        <div class="discipline">
                            <div class="col-md-12"><ul class="list-unstyled">
                                <li><span class='name'>ЭЛЕКТРОНИКА И СХЕМОТЕХНИКА</span> (Лабораторная работа)</li>
                                <li><a href="/timetable/professor/15251">Кустов Н. Д.</a></li>
                                <li><a href="#" title="ул. Семафорная, д 123">корп. "С3" каб. "504"</a></li>
                                <li>2 подгруппа</li>
                            </ul></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        <div id="week_2_tab">
            <div class="day monday">
                <div class="header"><div class="name text-center"><div>Понедельник</div></div></div>
                <div class="body">
                    <div class="line">
                        <div class="time text-center"><div class="hidden-xs">11:30-13:00</div></div>
                        <div class="discipline">
                            <div class="col-md-12"><ul class="list-unstyled">
                                <li><span class='name'>ЭЛЕКТРОНИКА И СХЕМОТЕХНИКА</span> (Лекция)</li>
                                <li><a href="/timetable/professor/4119">Ханов В. Х.</a></li>
                                <li><a href="#">корп. "С3" каб. "506"</a></li>
                            </ul></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    <div id="session_tab">
        <div class="empty_info_msg"><h3>Расписание сессии временно отсутствует</h3></div>
    </div>
</div>
</body>
</html>
"""

@pytest.mark.asyncio
async def test_real_html_parsing(monkeypatch):
    schedule_cache.clear()
    teachers_cache.clear()

    class MockResponse:
        content = REAL_HTML.encode("utf-8")
        text = REAL_HTML
        def raise_for_status(self): pass

    async def mock_get(*args, **kwargs):
        return MockResponse()

    monkeypatch.setattr("httpx.AsyncClient.get", mock_get)
    monkeypatch.setattr("scr.parsers.schedule_parser.SCHEDULE_URL", "https://timetable.pallada.sibsau.ru/timetable/group/13974")
    monkeypatch.setattr("scr.parsers.teacher_parser.SCHEDULE_URL", "https://timetable.pallada.sibsau.ru/timetable/group/13974")

    sched = await fetch_schedule()
    assert "week_1" in sched
    assert "week_2" in sched
    assert "Понедельник" in sched["week_1"]
    w1_mon = sched["week_1"]["Понедельник"]
    assert len(w1_mon) == 1
    assert w1_mon[0]["time"] == "09:40-11:10"
    assert "ЭЛЕКТРОНИКА И СХЕМОТЕХНИКА" in w1_mon[0]["info"]
    assert "Кустов Н. Д." in w1_mon[0]["info"]
    assert w1_mon[0]["classroom"] == 'корп. "С3" каб. "504"'
    assert w1_mon[0]["subgroup"] == "2️⃣ подгруппа"

    teachers = await fetch_teachers()
    assert "15251" in teachers
    assert teachers["15251"]["name"] == "Кустов Н. Д."
    assert "4119" in teachers
    assert teachers["4119"]["name"] == "Ханов В. Х."
