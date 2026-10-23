"""Производственный календарь (core/workdays.py): рабочие дни, отсчёт назад и чтение файла."""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.core import workdays
from app.core.config import settings
from app.core.workdays import WorkCalendar

# июнь 2026: 12-е (пт) — праздник, 13–14 — выходные
CAL = WorkCalendar(holidays=frozenset({date(2026, 6, 12)}), workdays=frozenset({date(2026, 6, 20)}))


@pytest.mark.parametrize("day,expected", [
    (date(2026, 6, 11), True),    # четверг
    (date(2026, 6, 12), False),   # праздник в пятницу
    (date(2026, 6, 13), False),   # суббота
    (date(2026, 6, 14), False),   # воскресенье
    (date(2026, 6, 20), True),    # рабочая суббота по переносу
])
def test_is_workday(day, expected):
    assert CAL.is_workday(day) is expected


@pytest.mark.parametrize("day,expected", [
    (date(2026, 6, 11), date(2026, 6, 11)),  # сам рабочий день
    (date(2026, 6, 14), date(2026, 6, 11)),  # воскресенье → четверг (пятница — праздник)
    (date(2026, 6, 21), date(2026, 6, 20)),  # воскресенье → рабочая суббота
])
def test_last_workday(day, expected):
    assert CAL.last_workday(day) == expected


@pytest.mark.parametrize("day,count,expected", [
    (date(2026, 6, 22), 5, date(2026, 6, 16)),   # пн 22 → вт 16: 20 (раб. сб), 19, 18, 17, 16
    (date(2026, 6, 16), 2, date(2026, 6, 11)),   # 15 (пн), 11 (чт); праздник и выходные пропущены
    (date(2026, 6, 15), 1, date(2026, 6, 11)),
    (date(2026, 6, 15), 0, date(2026, 6, 15)),
])
def test_workdays_before(day, count, expected):
    assert CAL.workdays_before(day, count) == expected


def test_empty_calendar_knows_only_weekends():
    cal = WorkCalendar()
    assert cal.is_workday(date(2026, 6, 12)) and not cal.is_workday(date(2026, 6, 13))


def test_load_repo_calendar():
    cal = workdays.load()
    assert date(2026, 11, 4) in cal.holidays and date(2026, 12, 31) in cal.holidays
    assert not cal.is_workday(date(2026, 11, 4)) and cal.is_workday(date(2026, 11, 5))


def test_load_missing_file_gives_weekends_only(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "work_calendar_file", str(tmp_path / "нет.yaml"))
    assert workdays.load() == WorkCalendar()


def test_load_reads_holidays_and_workdays(monkeypatch, tmp_path):
    path = tmp_path / "cal.yaml"
    path.write_text("holidays: [2026-06-12, '2026-06-15']\nworkdays:\n  - 2026-06-20\n", encoding="utf-8")
    monkeypatch.setattr(settings, "work_calendar_file", str(path))
    assert workdays.load() == WorkCalendar(frozenset({date(2026, 6, 12), date(2026, 6, 15)}),
                                           frozenset({date(2026, 6, 20)}))


@pytest.mark.parametrize("text,error", [
    ("holidays: 2026-06-12", "нужен список дат"),
    ("holidays: [не-дата]", "Invalid isoformat|не дата"),
    ("holidays: [2026-06-12 10:00:00]", "не дата"),
    ("holidays: [42]", "не дата"),
    ("- 2026-06-12", "ожидаются разделы"),
], ids=["not-list", "garbage", "datetime", "number", "not-dict"])
def test_load_broken_file_gives_clear_error(monkeypatch, tmp_path, text, error):
    path = tmp_path / "cal.yaml"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(settings, "work_calendar_file", str(path))
    with pytest.raises(ValueError, match=error):
        workdays.load()


def test_empty_file_gives_weekends_only(monkeypatch, tmp_path):
    path = tmp_path / "cal.yaml"
    path.write_text("", encoding="utf-8")
    monkeypatch.setattr(settings, "work_calendar_file", str(path))
    assert workdays.load() == WorkCalendar()


# ---------- рабочее время: 10:00–18:00 GMT+7 ----------

def at(day: int, hour: int, minute: int = 0, month: int = 6) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=timezone(timedelta(hours=7)))


@pytest.mark.parametrize("start, end, hours", [
    (at(11, 11), at(11, 14, 30), 3.5),                # внутри рабочего дня
    (at(11, 6), at(11, 22), 8),                       # вне 10–18 не считается
    (at(11, 17), at(15, 11), 2),                      # чт 17–18, пт (праздник) и выходные пропущены, пн 10–11
    (at(11, 18), at(12, 10), 0),                      # только нерабочее время
    (at(19, 17), at(22, 11), 10),                     # пт 17–18, рабочая сб 20-го 10–18, вс выходной, пн 10–11
])
def test_working_seconds(start, end, hours):
    assert CAL.working_seconds(start, end) == hours * 3600


def test_working_seconds_is_zero_for_empty_or_reversed_interval():
    assert CAL.working_seconds(at(11, 12), at(11, 12)) == 0
    assert CAL.working_seconds(at(11, 15), at(11, 12)) == 0


def test_working_seconds_converts_other_timezones():
    utc = timezone.utc
    # 03:00–11:00 UTC — это 10:00–18:00 GMT+7
    assert CAL.working_seconds(datetime(2026, 6, 11, 3, tzinfo=utc), datetime(2026, 6, 11, 11, tzinfo=utc)) == 8 * 3600
    assert CAL.working_seconds(datetime(2026, 6, 11, 11, tzinfo=utc), datetime(2026, 6, 12, 3, tzinfo=utc)) == 0
