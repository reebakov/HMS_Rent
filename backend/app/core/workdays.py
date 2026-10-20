"""Рабочие дни по производственному календарю (WORK_CALENDAR_FILE, по умолчанию config/work_calendar.yaml).

Суббота и воскресенье — выходные; праздники сверх них — `holidays`, рабочие выходные по переносу — `workdays`.
Файл читается при каждом вызове load(): он лежит на диске сервера и правится без перезапуска.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import yaml

from app.core.config import settings


@dataclass(frozen=True)
class WorkCalendar:
    holidays: frozenset[date] = field(default_factory=frozenset)
    workdays: frozenset[date] = field(default_factory=frozenset)

    def is_workday(self, day: date) -> bool:
        if day in self.workdays:
            return True
        return day.weekday() < 5 and day not in self.holidays

    def last_workday(self, day: date) -> date:
        """Последний рабочий день не позже `day` (сам `day`, если он рабочий)."""
        while not self.is_workday(day):
            day -= timedelta(days=1)
        return day

    def workdays_before(self, day: date, count: int) -> date:
        """Рабочий день, с которого до `day` остаётся `count` рабочих дней (сам `day` не считается)."""
        while count:
            day -= timedelta(days=1)
            if self.is_workday(day):
                count -= 1
        return day


def _dates(items: object, name: str) -> frozenset[date]:
    if items is None:
        return frozenset()
    if not isinstance(items, list):
        raise ValueError(f"{name}: нужен список дат")
    out = set()
    for item in items:
        if isinstance(item, datetime) or not isinstance(item, (date, str)):
            raise ValueError(f"{name}: «{item}» — не дата ГГГГ-ММ-ДД")
        out.add(item if isinstance(item, date) else date.fromisoformat(item))
    return frozenset(out)


def load() -> WorkCalendar:
    """Календарь из файла; файла нет — только субботы и воскресенья. Ошибка в файле — ValueError с понятным текстом."""
    path = settings.path(settings.work_calendar_file)
    if not path.exists():
        return WorkCalendar()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: ожидаются разделы holidays и workdays")
    try:
        return WorkCalendar(_dates(data.get("holidays"), "holidays"), _dates(data.get("workdays"), "workdays"))
    except ValueError as exc:
        raise ValueError(f"{path.name}: {exc}") from exc
