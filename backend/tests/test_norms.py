"""Нормативы исполнителей (services/norms.py): «не взята за час», нарушение срока, пауза на «Заморожено».

Время подменяется: рабочие часы зависят от момента запуска, а тесты должны давать один результат. Неделя октября 2026:
понедельник 26-е, вторник 27-е, пятница 30-е; рабочее время 10:00–18:00 GMT+7.
"""
import itertools
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.db.session import SessionLocal
from app.integrations import servicedesk as real_sd
from app.models import ServiceRequest
from app.services import norms, service_requests

TZ = timezone(timedelta(hours=7))
_users = itertools.count(1)


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


@pytest.fixture
def clock(monkeypatch):
    """clock(момент) — «сейчас» для norms.check."""
    def _set(moment: datetime):
        class Fixed(datetime):
            @classmethod
            def now(cls, tz=None):
                return moment.astimezone(tz) if tz else moment
        monkeypatch.setattr(norms, "datetime", Fixed)
    return _set


@pytest.fixture
def channel(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(norms, "notify", mock)
    for key, value in dict(sd_jira_url="https://jira.test", sd_token="tok", sd_username="").items():
        monkeypatch.setattr(settings, key, value)
    return mock


async def task(session, make_user, *, created, kind="prepare", status="Backlog", category="new", key="DR-7", **kw):
    user = await make_user(f"owner{next(_users)}")
    req = ServiceRequest(kind=kind, user_id=user.id, summary="HMS Rent: подготовить ПК A032 (заказ №1042)", description="d",
                         issue_key=key, status=status, status_category=category, created_at=created, **kw)
    session.add(req)
    await session.commit()
    return req


async def fresh(req_id) -> ServiceRequest:
    async with SessionLocal() as s:
        return await s.get(ServiceRequest, req_id)


def texts(channel) -> list[str]:
    return [c.args[0] for c in channel.await_args_list]


# ---------- не взята за час ----------

async def test_not_taken_in_an_hour_is_reported_once(session, make_user, clock, channel):
    req = await task(session, make_user, created=at(27, 10))
    clock(at(27, 11, 30))
    await norms.check(session)
    assert len(texts(channel)) == 1
    assert "не взята за 1 рабочий час" in texts(channel)[0]
    assert "[DR-7](https://jira.test/browse/DR-7)" in texts(channel)[0] and "подготовить ПК A032" in texts(channel)[0]
    assert (await fresh(req.id)).take_alerted_at is not None
    await norms.check(session)
    assert len(texts(channel)) == 1  # повторно не сообщаем


async def test_within_the_hour_nothing_is_reported(session, make_user, clock, channel):
    await task(session, make_user, created=at(27, 10))
    clock(at(27, 10, 59))
    await norms.check(session)
    channel.assert_not_awaited()


@pytest.mark.parametrize("now, reported", [(at(28, 10, 20), False), (at(28, 10, 40), True)])
async def test_night_and_weekend_do_not_count(session, make_user, clock, channel, now, reported):
    """Создана за полчаса до конца дня: ночь не считается, час набегает только на следующее утро."""
    await task(session, make_user, created=at(27, 17, 30))
    clock(now)
    await norms.check(session)
    assert bool(channel.await_count) is reported


async def test_weekend_is_skipped(session, make_user, clock, channel):
    await task(session, make_user, created=at(30, 17, 30))  # пятница, за полчаса до конца дня
    clock(at(31, 12))  # суббота
    await norms.check(session)
    channel.assert_not_awaited()
    clock(at(2 + 28, 10, 40) + timedelta(days=3))  # понедельник 2 ноября 10:40
    await norms.check(session)
    assert len(texts(channel)) == 1


@pytest.mark.parametrize("status", ["In Progress", "Validation", "Escalated", "Frozen", "В работе"])
async def test_taken_task_is_not_reported_as_not_taken(session, make_user, clock, channel, status):
    await task(session, make_user, created=at(27, 10), status=status, category="indeterminate")
    clock(at(27, 15))
    await norms.check(session)
    channel.assert_not_awaited()


@pytest.mark.parametrize("status", ["To Do", "Сделать"])
async def test_to_do_counts_as_not_taken(session, make_user, clock, channel, status):
    await task(session, make_user, created=at(27, 10), status=status)
    clock(at(27, 12))
    await norms.check(session)
    assert "не взята" in texts(channel)[0]


# ---------- нарушение норматива ----------

@pytest.mark.parametrize("kind, vm, ok_at, late_at, label", [
    ("prepare", None, at(27, 17, 59), at(28, 10, 1), "1 рабочий день"),    # ПК из пула: 8 рабочих часов
    ("return", None, at(27, 17, 59), at(28, 10, 1), "1 рабочий день"),     # возврат физического сервера
    ("build", None, at(29, 17, 59), at(30, 10, 1), "3 рабочих дня"),       # сборка: 24 рабочих часа (вт–чт)
])
async def test_norm_by_kind(session, make_user, clock, channel, kind, vm, ok_at, late_at, label):
    await task(session, make_user, created=at(27, 10), kind=kind, status="In Progress", category="indeterminate")
    clock(ok_at)
    await norms.check(session)
    channel.assert_not_awaited()
    clock(late_at)
    await norms.check(session)
    (text,) = texts(channel)
    assert "Нарушен норматив" in text and f"норматив {label}" in text and "время заморозки не считается" in text


async def test_vm_check_norm_is_two_hours(session, make_user, clock, channel, make_department):
    from app.models import VirtualMachine
    user = await make_user("owner")
    dept = await make_department("QA")
    vm = VirtualMachine(name="A1007", cpu=1, ram_gb=1, disk_gb=10, status="checking", order_number=1, user_id=user.id,
                        department_id=dept.id, requester_name="И", requester_nick="i", attrs={})
    session.add(vm)
    await session.commit()
    req = ServiceRequest(kind="prepare", user_id=user.id, vm_id=vm.id, summary="HMS Rent: подготовить ВМ A1007", description="d",
                         issue_key="DR-8", status="In Progress", status_category="indeterminate", created_at=at(27, 10))
    session.add(req)
    await session.commit()
    clock(at(27, 11, 59))
    await norms.check(session)
    channel.assert_not_awaited()
    clock(at(27, 12, 1))
    await norms.check(session)
    assert "норматив 2 рабочих часа" in texts(channel)[0]


async def test_late_and_not_taken_are_reported_separately_and_once(session, make_user, clock, channel):
    req = await task(session, make_user, created=at(27, 10))
    clock(at(28, 10, 30))  # час прошёл, и день тоже
    await norms.check(session)
    assert len(texts(channel)) == 2 and "не взята" in texts(channel)[0] and "Нарушен норматив" in texts(channel)[1]
    saved = await fresh(req.id)
    assert saved.take_alerted_at is not None and saved.norm_alerted_at is not None
    await norms.check(session)
    assert len(texts(channel)) == 2


@pytest.mark.parametrize("kind", ["problem", "diagnose"])
async def test_kinds_without_norm_get_only_the_take_alert(session, make_user, clock, channel, kind):
    req = await task(session, make_user, created=at(27, 10), kind=kind, status="In Progress", category="indeterminate")
    clock(at(30, 10))
    await norms.check(session)
    channel.assert_not_awaited()  # взята — «не взята» нет, норматива у вида нет
    assert (await fresh(req.id)).norm_alerted_at is None


async def test_problem_tasks_are_not_watched_at_all(session, make_user, clock, channel):
    await task(session, make_user, created=at(27, 10), kind="problem")
    clock(at(30, 10))
    await norms.check(session)
    channel.assert_not_awaited()


# ---------- пауза на «Заморожено» ----------

async def test_frozen_time_does_not_count_against_the_norm(session, make_user, clock, channel):
    """Создана вт 10:00, заморожена с 11:00; к ср 15:00 прошло 13 рабочих часов, из них 12 на паузе — норматив цел."""
    await task(session, make_user, created=at(27, 10), status="Frozen", category="indeterminate", frozen_since=at(27, 11))
    clock(at(28, 15))
    await norms.check(session)
    channel.assert_not_awaited()
    clock(at(29, 18))  # к чт 18:00 набежало 31 рабочий час, на паузе 28 → 3 часа
    await norms.check(session)
    channel.assert_not_awaited()


async def test_accumulated_freeze_is_subtracted(session, make_user, clock, channel):
    await task(session, make_user, created=at(27, 10), status="In Progress", category="indeterminate",
               frozen_work_seconds=6 * 3600)
    clock(at(28, 15))  # прошло 13 рабочих часов, минус 6 заморозки = 7 < 8
    await norms.check(session)
    channel.assert_not_awaited()
    clock(at(28, 17))  # 15 − 6 = 9 > 8
    await norms.check(session)
    assert "Нарушен норматив" in texts(channel)[0] and "прошло 9 рабочих ч" in texts(channel)[0]


def test_track_freeze_accumulates_working_time_between_polls():
    req = ServiceRequest(status="Frozen", frozen_work_seconds=0)
    service_requests.track_freeze(req, at(27, 11))
    assert req.frozen_since == at(27, 11)
    service_requests.track_freeze(req, at(27, 12))  # всё ещё заморожена — ничего не меняется
    assert (req.frozen_since, req.frozen_work_seconds) == (at(27, 11), 0)
    req.status = "In Progress"
    service_requests.track_freeze(req, at(28, 11))  # вт 11–18 = 7 ч и ср 10–11 = 1 ч
    assert (req.frozen_since, req.frozen_work_seconds) == (None, 8 * 3600)
    service_requests.track_freeze(req, at(28, 15))  # не заморожена и не была — без изменений
    assert req.frozen_work_seconds == 8 * 3600


def test_translated_frozen_status_counts_as_frozen():
    req = ServiceRequest(status="Заморожено", frozen_work_seconds=None)
    service_requests.track_freeze(req, at(27, 11))
    assert req.frozen_since == at(27, 11)
    req.status = "В работе"
    service_requests.track_freeze(req, at(27, 13))
    assert req.frozen_work_seconds == 2 * 3600  # None считается нулём


async def test_sync_status_tracks_freeze(session, make_user, monkeypatch):
    """Опрос Jira сам ведёт паузу: заморозили — начало отсчёта, разморозили — рабочее время в копилку."""
    class Sd:
        status = real_sd.SdStatus("Frozen", "indeterminate")
        ServiceDeskError = real_sd.ServiceDeskError

        async def get_status(self, key):
            return self.status

        async def get_comments(self, key):
            return []

    fake = Sd()
    monkeypatch.setattr(service_requests, "sd", fake)
    req = await task(session, make_user, created=at(27, 10), status="In Progress", category="indeterminate")
    await service_requests.sync_status(req)
    assert req.frozen_since is not None
    fake.status = real_sd.SdStatus("In Progress", "indeterminate")
    await service_requests.sync_status(req)
    assert req.frozen_since is None and req.frozen_work_seconds >= 0


# ---------- что не наблюдается ----------

async def test_done_tasks_and_tasks_without_key_are_ignored(session, make_user, clock, channel):
    await task(session, make_user, created=at(27, 10), status="Done", category="done", key="DR-1")
    await task(session, make_user, created=at(27, 10), key=None)
    clock(at(30, 10))
    await norms.check(session)
    channel.assert_not_awaited()


async def test_nothing_happens_without_service_desk(session, make_user, clock, channel, monkeypatch):
    req = await task(session, make_user, created=at(27, 10))
    monkeypatch.setattr(settings, "sd_token", "")
    clock(at(30, 10))
    await norms.check(session)
    channel.assert_not_awaited()
    assert (await fresh(req.id)).take_alerted_at is None


async def test_status_without_category_is_still_watched(session, make_user, clock, channel):
    await task(session, make_user, created=at(27, 10), status=None, category=None)
    clock(at(28, 10, 30))
    await norms.check(session)
    assert len(texts(channel)) == 1 and "Нарушен норматив" in texts(channel)[0]  # статус неизвестен — это не «закрыта»
