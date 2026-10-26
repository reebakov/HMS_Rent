"""Просрочки (services/overdue.py): список, дни просрочки и ежедневная сводка в Mattermost."""
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.core import clock as app_clock
from app.core import workdays
from app.core.config import settings
from app.core.workdays import WorkCalendar
from app.db.session import SessionLocal
from app.models import AppSetting, Notification, NotificationKind, VirtualMachine
from app.services import notifications, overdue
from tests.sync_fakes import add_booking

TODAY = date(2026, 6, 15)
OVERDUE = TODAY - timedelta(days=5)
_vm_seq = {"n": 0}


async def add_vm(session, user, department, *, status: str = "ready", expected_return_at: date | None = OVERDUE,
                 name: str | None = None, **kw) -> VirtualMachine:
    """ВМ напрямую в БД (минуя vm-сервис и vSphere)."""
    _vm_seq["n"] += 1
    vm = VirtualMachine(name=name or f"vm-{_vm_seq['n']:03d}", cpu=2, ram_gb=4, disk_gb=50, status=status,
                        order_number=5000 + _vm_seq["n"], user_id=user.id, department_id=department.id,
                        requester_name="Пётр Петров", requester_nick="petr", expected_return_at=expected_return_at,
                        **kw)
    session.add(vm)
    await session.commit()
    return vm


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(app_clock, "today", lambda: TODAY)


@pytest.fixture
def clock(monkeypatch):
    """clock(hour, day=TODAY) — «сейчас» в локальной таймзоне портала; влияет и на today(), и на daily_digest."""
    def _set(hour: int, day: date = TODAY) -> None:
        now = datetime(day.year, day.month, day.day, hour, 30, tzinfo=ZoneInfo(settings.display_timezone))
        monkeypatch.setattr(app_clock, "now", lambda: now)
        monkeypatch.setattr(app_clock, "today", now.date)  # перекрывает автоматический fixed_today
    return _set


@pytest.fixture
def mm(monkeypatch):
    """Заданный webhook и подменённая отправка в Mattermost."""
    monkeypatch.setattr(settings, "mattermost_webhook_url", "http://mattermost.test/hook")
    send = AsyncMock()
    monkeypatch.setattr(overdue, "notify", send)
    return send


@pytest.fixture
async def owner(make_user, make_department):
    dept = await make_department("QA")
    return await make_user("ivanov", department=dept, email="ivanov@corp.test"), dept


async def digest_date() -> str | None:
    """Дата последней сводки по данным БД (отдельной сессией, мимо кэша тестовой)."""
    async with SessionLocal() as fresh:
        row = await fresh.get(AppSetting, overdue.DIGEST_KEY)
        return row.value if row else None


# ---------- list_overdue / days_overdue ----------

@pytest.mark.parametrize("due,status,counted", [
    (OVERDUE, "active", True),
    (TODAY - timedelta(days=1), "active", True),
    (TODAY, "active", False),  # срок сегодня — ещё не просрочка
    (TODAY + timedelta(days=1), "active", False),
    (None, "active", False),  # без срока
    (OVERDUE, "returned", False),
    (OVERDUE, "cancelled", False),
])
async def test_list_overdue_bookings(session, make_computer, owner, due, status, counted):
    user, dept = owner
    b = await add_booking(session, await make_computer(), user, dept, expected_return_at=due, status=status)
    bookings, vms = await overdue.list_overdue(session)
    assert [x.id for x in bookings] == ([b.id] if counted else []) and vms == []


@pytest.mark.parametrize("status,counted", [
    ("ready", True), ("failed", True),
    ("queued", False), ("creating", False), ("deleting", False), ("deleted", False),
])
async def test_list_overdue_vms_by_status(session, owner, status, counted):
    user, dept = owner
    vm = await add_vm(session, user, dept, status=status)
    _, vms = await overdue.list_overdue(session)
    assert [x.id for x in vms] == ([vm.id] if counted else [])


@pytest.mark.parametrize("due", [None, TODAY, TODAY + timedelta(days=3)])
async def test_list_overdue_vm_without_overdue_term(session, owner, due):
    user, dept = owner
    await add_vm(session, user, dept, expected_return_at=due)
    assert await overdue.list_overdue(session) == ([], [])


async def test_list_overdue_sorted_by_due_date(session, make_computer, owner):
    user, dept = owner
    late = await add_booking(session, await make_computer(), user, dept, expected_return_at=TODAY - timedelta(days=9))
    early = await add_booking(session, await make_computer(), user, dept, expected_return_at=TODAY - timedelta(days=2))
    vm_late = await add_vm(session, user, dept, expected_return_at=TODAY - timedelta(days=7))
    vm_early = await add_vm(session, user, dept, expected_return_at=TODAY - timedelta(days=1))
    bookings, vms = await overdue.list_overdue(session)
    assert [b.id for b in bookings] == [late.id, early.id]  # самая давняя просрочка первой
    assert [v.id for v in vms] == [vm_late.id, vm_early.id]


@pytest.mark.parametrize("due,days", [
    (None, 0), (TODAY, 0), (TODAY - timedelta(days=1), 1), (OVERDUE, 5), (TODAY + timedelta(days=2), -2),
])
def test_days_overdue(due, days):
    assert overdue.days_overdue(due) == days


# ---------- daily_digest: когда не шлём ----------

async def test_digest_without_webhook_does_nothing(session, make_computer, owner, clock, mm, monkeypatch):
    monkeypatch.setattr(settings, "mattermost_webhook_url", "")
    user, dept = owner
    await add_booking(session, await make_computer(), user, dept, expected_return_at=OVERDUE)
    clock(12)
    await overdue.daily_digest(session)
    mm.assert_not_called()
    assert await digest_date() is None  # и дату не помечаем: включат webhook — сводка уйдёт


async def test_digest_before_digest_hour_does_nothing(session, make_computer, owner, clock, mm):
    user, dept = owner
    await add_booking(session, await make_computer(), user, dept, expected_return_at=OVERDUE)
    clock(overdue.DIGEST_HOUR - 1)
    await overdue.daily_digest(session)
    mm.assert_not_called()
    assert await digest_date() is None


@pytest.mark.parametrize("hour", [overdue.DIGEST_HOUR, 23])
async def test_digest_sent_from_digest_hour(session, make_computer, owner, clock, mm, hour):
    user, dept = owner
    await add_booking(session, await make_computer(), user, dept, expected_return_at=OVERDUE)
    clock(hour)
    await overdue.daily_digest(session)
    mm.assert_awaited_once()
    assert await digest_date() == TODAY.isoformat()


async def test_digest_sent_once_per_day_and_again_next_day(session, make_computer, owner, clock, mm):
    user, dept = owner
    await add_booking(session, await make_computer(), user, dept, expected_return_at=OVERDUE)
    clock(11)
    await overdue.daily_digest(session)
    await overdue.daily_digest(session)
    assert mm.await_count == 1
    clock(18)  # в тот же день позже — тоже не шлём
    await overdue.daily_digest(session)
    assert mm.await_count == 1

    tomorrow = TODAY + timedelta(days=1)
    clock(11, tomorrow)
    await overdue.daily_digest(session)
    assert mm.await_count == 2
    assert await digest_date() == tomorrow.isoformat()


@pytest.mark.parametrize("day, holidays", [
    (date(2026, 6, 13), ()),  # суббота
    (date(2026, 6, 14), ()),  # воскресенье
    (TODAY, (TODAY,)),  # праздник в будний день
])
async def test_digest_is_silent_on_days_off(session, make_computer, owner, clock, mm, monkeypatch, day, holidays):
    """Регрессия: сводка просрочек и напоминание об очистке уходили в канал и в выходные."""
    user, dept = owner
    monkeypatch.setattr(workdays, "load", lambda: WorkCalendar(holidays=frozenset(holidays)))
    await add_booking(session, await make_computer(), user, dept, expected_return_at=day - timedelta(days=5))
    clock(11, day)
    await overdue.daily_digest(session)
    mm.assert_not_called()
    assert await digest_date() == day.isoformat()  # день помечен: цикл worker'а не перечитывает данные зря


async def test_digest_resumes_on_first_workday_after_weekend(session, make_computer, owner, clock, mm):
    user, dept = owner
    await add_booking(session, await make_computer(), user, dept, expected_return_at=OVERDUE)
    clock(11, date(2026, 6, 14))  # воскресенье
    await overdue.daily_digest(session)
    mm.assert_not_called()
    clock(11, TODAY)  # понедельник
    await overdue.daily_digest(session)
    mm.assert_awaited_once()


async def test_digest_without_overdue_sends_nothing_but_marks_day(session, make_computer, owner, clock, mm):
    user, dept = owner
    # не просрочено: срок сегодня, возвращённая бронь, ВМ в очереди
    await add_booking(session, await make_computer(), user, dept, expected_return_at=TODAY)
    await add_booking(session, await make_computer(), user, dept, expected_return_at=OVERDUE, status="returned")
    await add_vm(session, user, dept, status="queued")
    clock(12)
    await overdue.daily_digest(session)
    mm.assert_not_called()
    assert await digest_date() == TODAY.isoformat()

    # просрочка появилась позже в тот же день — сводка уже «отработала», до завтра не шлём
    await add_booking(session, await make_computer(), user, dept, expected_return_at=OVERDUE)
    await overdue.daily_digest(session)
    mm.assert_not_called()


# ---------- daily_digest: формат ----------

async def test_digest_message_format(session, make_computer, owner, clock, mm):
    user, dept = owner
    pc = await make_computer("PC-007")
    b = await add_booking(session, pc, user, dept, expected_return_at=OVERDUE, requester_name="Иван Иванов")
    vm = await add_vm(session, user, dept, name="vm-build", status="failed", expected_return_at=TODAY - timedelta(days=2))
    clock(12)
    await overdue.daily_digest(session)
    (text,), _ = mm.await_args
    header, pc_line, vm_line = text.split("\n")
    assert header == "⏰ **Просрочки HMS Rent на 15.06.2026**: ПК — 1, виртуалок — 1"
    assert pc_line == f"- ПК **PC-007** (заказ №{b.order_number}) — QA, Иван Иванов, срок 10.06, +5 дн."
    assert vm_line == f"- ВМ **vm-build** (заказ №{vm.order_number}) — QA, Пётр Петров, срок 13.06, +2 дн."


@pytest.mark.parametrize("pcs,vms", [(1, 0), (0, 1)])
async def test_digest_only_one_kind(session, make_computer, owner, clock, mm, pcs, vms):
    user, dept = owner
    for _ in range(pcs):
        await add_booking(session, await make_computer(), user, dept, expected_return_at=OVERDUE)
    for _ in range(vms):
        await add_vm(session, user, dept)
    clock(12)
    await overdue.daily_digest(session)
    (text,), _ = mm.await_args
    assert text.splitlines()[0].endswith(f"ПК — {pcs}, виртуалок — {vms}")
    assert len(text.splitlines()) == 2


async def test_digest_truncates_lists_to_30_but_counts_all(session, make_computer, owner, clock, mm):
    user, dept = owner
    for _ in range(31):
        await add_booking(session, await make_computer(), user, dept, expected_return_at=OVERDUE)
        await add_vm(session, user, dept)
    clock(12)
    await overdue.daily_digest(session)
    (text,), _ = mm.await_args
    lines = text.splitlines()
    assert "ПК — 31, виртуалок — 31" in lines[0]
    assert sum(ln.startswith("- ПК") for ln in lines) == 30 and sum(ln.startswith("- ВМ") for ln in lines) == 30


# ---------- daily_reminders: уведомления заказчику о конце срока ----------

@pytest.fixture
def cal(monkeypatch):
    """cal(holidays...) — календарь для напоминаний; по умолчанию только субботы и воскресенья."""
    def _set(*holidays: date) -> None:
        monkeypatch.setattr(workdays, "load", lambda: WorkCalendar(holidays=frozenset(holidays)))
    _set()
    return _set


async def notes() -> list[Notification]:
    """Уведомления в БД, старые сверху (отдельной сессией, мимо кэша тестовой)."""
    async with SessionLocal() as fresh:
        return list((await fresh.scalars(select(Notification).order_by(Notification.id))).all())


async def titles() -> list[str]:
    return [n.title for n in await notes()]


async def reminders_date() -> str | None:
    async with SessionLocal() as fresh:
        row = await fresh.get(AppSetting, overdue.REMINDERS_KEY)
        return row.value if row else None


MON_22 = date(2026, 6, 22)  # за 5 рабочих дней до него — TODAY (пн 15 июня)


async def test_reminders_before_hour_do_nothing(session, make_computer, owner, clock, cal):
    user, dept = owner
    await add_booking(session, await make_computer(), user, dept, expected_return_at=MON_22)
    clock(overdue.DIGEST_HOUR - 1)
    await overdue.daily_reminders(session)
    assert await notes() == []


async def test_reminders_go_to_author_and_not_to_channel(session, make_computer, owner, clock, cal, mm):
    user, dept = owner
    soon = await add_booking(session, await make_computer("PC-005"), user, dept, expected_return_at=MON_22)
    vm = await add_vm(session, user, dept, name="A1005", expected_return_at=TODAY)
    clock(12)
    await overdue.daily_reminders(session)
    ending, last = await notes()
    assert (ending.user_id, ending.kind) == (user.id, NotificationKind.term_ending)
    assert ending.title == "Через 5 рабочих дней заканчивается аренда ПК PC-005"
    assert f"Заказ №{soon.order_number}" in ending.body and "22.06.2026" in ending.body
    assert (last.user_id, last.kind) == (user.id, NotificationKind.term_ending)
    assert last.title == "Сегодня последний день аренды ВМ A1005" and f"Заказ №{vm.order_number}" in last.body
    mm.assert_not_called()  # канал только для исполнителей
    assert await reminders_date() == TODAY.isoformat()


async def test_reminders_skip_closed_and_other_dates(session, make_computer, owner, clock, cal):
    user, dept = owner
    # пт 19-го — до него 5 рабочих дней начались в пт 12-го; вт 23-го — с 16-го; вт 16-го — завтра, не последний день
    for due in (date(2026, 6, 19), MON_22 + timedelta(days=1), TODAY + timedelta(days=1)):
        await add_booking(session, await make_computer(), user, dept, expected_return_at=due)
    await add_booking(session, await make_computer(), user, dept, expected_return_at=MON_22, status="returned")
    await add_vm(session, user, dept, status="queued", expected_return_at=MON_22)
    await add_vm(session, user, dept, status="deleted", expected_return_at=TODAY)
    clock(12)
    await overdue.daily_reminders(session)
    assert await notes() == []
    assert await reminders_date() == TODAY.isoformat()  # день отработан, хоть и без уведомлений


async def test_reminders_count_holidays_as_non_working(session, make_computer, owner, clock, cal):
    cal(date(2026, 6, 17))  # праздник в среду: пять рабочих дней до вт 23 июня начинаются сегодня
    user, dept = owner
    await add_booking(session, await make_computer("PC-023"), user, dept, expected_return_at=date(2026, 6, 23))
    await add_booking(session, await make_computer("PC-022"), user, dept, expected_return_at=MON_22)
    clock(12)
    await overdue.daily_reminders(session)
    assert await titles() == ["Через 5 рабочих дней заканчивается аренда ПК PC-023"]


async def test_reminders_term_ending_on_weekend_reminded_on_friday(session, make_computer, owner, clock, cal):
    friday = date(2026, 6, 19)
    user, dept = owner
    await add_booking(session, await make_computer("PC-SUN"), user, dept, expected_return_at=date(2026, 6, 21))
    clock(12, friday)
    await overdue.daily_reminders(session)
    assert await titles() == ["Сегодня последний день аренды ПК PC-SUN"]


@pytest.mark.parametrize("due, today, expected", [
    (date(2026, 6, 15), date(2026, 6, 16), True),   # срок вышел вчера
    (date(2026, 6, 12), date(2026, 6, 15), True),   # срок в пятницу, первый рабочий день после — понедельник
    (date(2026, 6, 13), date(2026, 6, 15), True),   # срок в субботу — понедельник
    (date(2026, 6, 15), date(2026, 6, 17), False),  # второй рабочий день просрочки: уведомление уже было
    (date(2026, 6, 1), date(2026, 6, 16), False),   # давняя просрочка не будит заказчика снова
])
async def test_reminders_overdue_notice_only_on_first_workday_after_term(
        session, make_computer, owner, clock, cal, due, today, expected):
    user, dept = owner
    await add_booking(session, await make_computer("PC-LATE"), user, dept, expected_return_at=due)
    clock(12, today)
    await overdue.daily_reminders(session)
    assert [t for t in await titles() if "закончился" in t] == (["Срок аренды ПК PC-LATE закончился"] if expected else [])


async def test_reminders_on_day_off_send_nothing_but_mark_day(session, make_computer, owner, clock, cal):
    saturday = date(2026, 6, 13)
    user, dept = owner
    await add_booking(session, await make_computer(), user, dept, expected_return_at=saturday)
    clock(12, saturday)
    await overdue.daily_reminders(session)
    assert await notes() == [] and await reminders_date() == saturday.isoformat()


async def test_reminders_sent_once_per_day(session, make_computer, owner, clock, cal):
    user, dept = owner
    await add_booking(session, await make_computer(), user, dept, expected_return_at=MON_22)
    clock(11)
    await overdue.daily_reminders(session)
    clock(17)
    await overdue.daily_reminders(session)
    assert len(await notes()) == 1


async def test_digest_and_reminders_are_marked_separately(session, make_computer, owner, clock, mm, cal):
    user, dept = owner
    await add_booking(session, await make_computer(), user, dept, expected_return_at=OVERDUE)
    await add_booking(session, await make_computer(), user, dept, expected_return_at=MON_22)
    clock(12)
    await overdue.daily_digest(session)
    await overdue.daily_reminders(session)
    assert mm.await_count == 1 and len(await notes()) == 1  # сводка в канал, напоминание в колокольчик


async def test_reminders_prune_old_notifications(session, make_computer, owner, clock, cal):
    user, _ = owner
    old = Notification(user_id=user.id, kind=NotificationKind.vm_ready.value, title="старое")
    fresh = Notification(user_id=user.id, kind=NotificationKind.vm_ready.value, title="свежее")
    session.add_all([old, fresh])
    await session.commit()
    old.created_at = app_clock.now() - timedelta(days=notifications.KEEP_DAYS + 1)
    await session.commit()
    clock(12)
    await overdue.daily_reminders(session)
    assert await titles() == ["свежее"]


async def test_digest_reports_pcs_waiting_for_cleaning_over_a_day(session, make_computer, owner, clock, mm):
    user, dept = owner
    old = await make_computer("PC-OLD", status="cleaning")
    fresh = await make_computer("PC-NEW", status="cleaning")
    for comp, hours in ((old, 30), (fresh, 3)):
        b = await add_booking(session, comp, user, dept, status="returned", expected_return_at=TODAY + timedelta(days=30))
        b.returned_at = app_clock.now() - timedelta(hours=hours)
    await session.commit()
    clock(12)
    await overdue.daily_digest(session)
    text = "\n".join(call.args[0] for call in mm.await_args_list)
    assert "ждут очистки дольше суток" in text and "PC-OLD" in text and "PC-NEW" not in text
