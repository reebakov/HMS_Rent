"""Единое «сегодня» (core/clock.py): день считается по DISPLAY_TIMEZONE, а не по поясу сервера."""
from datetime import date, datetime, timezone

import pytest

from app.core import clock
from app.core.config import settings
from app.models import Booking
from app.schemas.booking import BookingCreate
from app.schemas.vm import VmCreate
from app.services import inventory
from tests.sync_fakes import add_booking

# 22:30 UTC: в Москве уже 16 июня, в Лос-Анджелесе ещё 15-е
INSTANT = datetime(2026, 6, 15, 22, 30, tzinfo=timezone.utc)
JUNE_15, JUNE_16 = date(2026, 6, 15), date(2026, 6, 16)


@pytest.fixture
def at_instant(monkeypatch):
    """at_instant(tz) — «сейчас» это INSTANT, а портал живёт в часовом поясе tz."""
    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return INSTANT.astimezone(tz) if tz else INSTANT

    def _set(tz: str) -> None:
        monkeypatch.setattr(settings, "display_timezone", tz)
        monkeypatch.setattr(clock, "datetime", FakeDatetime)
    return _set


@pytest.mark.parametrize("tz, expected", [("Europe/Moscow", JUNE_16), ("America/Los_Angeles", JUNE_15), ("UTC", JUNE_15)])
def test_today_follows_display_timezone(at_instant, tz, expected):
    at_instant(tz)
    assert clock.today() == expected
    assert clock.now().tzinfo is not None and clock.now().date() == expected


BOOKING = {"computer_id": 1, "department_id": 1, "requester_name": "Иван", "requester_nick": "iv"}
VM = {"name": "box-1", "cpu": 2, "ram_gb": 4, "disk_gb": 50, "department_id": 1, "requester_name": "Иван",
      "requester_nick": "iv"}


@pytest.mark.parametrize("schema, base", [(BookingCreate, BOOKING), (VmCreate, VM)], ids=["booking", "vm"])
@pytest.mark.parametrize("tz, day, ok", [
    ("Europe/Moscow", JUNE_15, False),  # в Москве 15-е уже вчера
    ("Europe/Moscow", JUNE_16, True),
    ("America/Los_Angeles", JUNE_15, True),  # в Лос-Анджелесе 15-е ещё сегодня
])
def test_return_date_not_in_past_uses_portal_day(at_instant, schema, base, tz, day, ok):
    at_instant(tz)
    if ok:
        assert schema(**base, expected_return_at=day).expected_return_at == day
    else:
        with pytest.raises(ValueError, match="в прошлом"):
            schema(**base, expected_return_at=day)


@pytest.mark.parametrize("tz, overdue", [("Europe/Moscow", True), ("America/Los_Angeles", False)])
async def test_overdue_issue_uses_portal_day(at_instant, make_computer, tz, overdue):
    at_instant(tz)
    comp = await make_computer("A1")
    issues = inventory.computer_issues(comp, Booking(expected_return_at=JUNE_15))
    assert any("Просрочен возврат" in i for i in issues) is overdue


@pytest.mark.parametrize("tz, count", [("Europe/Moscow", 1), ("America/Los_Angeles", 0)])
async def test_stats_overdue_counter_uses_portal_day(at_instant, session, make_computer, make_user, make_department,
                                                     tz, count):
    at_instant(tz)
    comp, user, dept = await make_computer("A1"), await make_user("emp"), await make_department("QA")
    await add_booking(session, comp, user, dept, expected_return_at=JUNE_15)
    assert (await inventory.get_stats(session)).overdue == count
