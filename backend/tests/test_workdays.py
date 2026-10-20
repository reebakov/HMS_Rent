"""Производственный календарь (core/workdays.py): рабочие дни, отсчёт назад и чтение файла."""
from datetime import date

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
