"""Сервис бронирования (app/services/bookings.py) на реальном PostgreSQL."""
import asyncio
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.errors import Conflict, Forbidden, NotFound
from app.db.session import SessionLocal
from app.integrations.insight.base import InsightObject
from app.integrations.insight.factory import get_mapping
from app.models import (AssetEvent, Booking, BookingStatus, Computer, ComputerStatus, Department, EventType,
                        UserRole)
from app.schemas.booking import BookingCreate
from app.services import bookings, runtime
from app.services.runtime import RuntimeConfig


# ---------- Фикстуры и хелперы ----------

@pytest.fixture(autouse=True)
def notify_mock(monkeypatch):
    """Уведомления в Mattermost не отправляем, но проверяем вызовы."""
    mock = AsyncMock()
    monkeypatch.setattr(bookings, "notify", mock)
    return mock


@pytest_asyncio.fixture
async def env(session, make_department, make_user, make_pool, make_computer):
    """Отдел, открытый пул, обычный пользователь и один свободный ПК в пуле (статус в Insight «Свободен»:
    после возврата статус ПК определяется по insight_status, пустой дал бы unknown)."""
    dept = await make_department("QA")
    pool = await make_pool("Main")
    user = await make_user("ivanov", department=dept)
    comp = await make_computer(pool=pool, insight_status="Свободен")
    return SimpleNamespace(dept=dept, pool=pool, user=user, comp=comp)


def payload(comp, dept, **kw) -> BookingCreate:
    kw.setdefault("requester_name", "Иван Иванов")
    kw.setdefault("requester_nick", "ivan")
    return BookingCreate(computer_id=comp.id, department_id=dept.id, **kw)


async def db_get(model, obj_id):
    """Свежая запись из БД через отдельную сессию (объекты в test-сессии могут быть устаревшими)."""
    async with SessionLocal() as s:
        return await s.get(model, obj_id)


async def events_of(comp_id, event_type=None):
    async with SessionLocal() as s:
        q = select(AssetEvent).where(AssetEvent.computer_id == comp_id).order_by(AssetEvent.id)
        if event_type:
            q = q.where(AssetEvent.event_type == event_type)
        return list((await s.scalars(q)).unique().all())


async def count_bookings(**filters) -> int:
    async with SessionLocal() as s:
        q = select(func.count(Booking.id))
        for k, v in filters.items():
            q = q.where(getattr(Booking, k) == v)
        return await s.scalar(q)


def set_writeback(monkeypatch, value: bool):
    monkeypatch.setattr(runtime, "_cache", (0.0, RuntimeConfig(insight_writeback=value)))


# ---------- create_booking: успех ----------

async def test_create_booking_success(session, env):
    until = date.today() + timedelta(days=7)
    b = await bookings.create_booking(session, env.user, payload(env.comp, env.dept, purpose="Тесты", expected_return_at=until))

    assert b.status == BookingStatus.active
    assert b.order_number == 1
    assert (b.user_id, b.department_id, b.computer_id) == (env.user.id, env.dept.id, env.comp.id)
    assert b.expected_return_at == until and b.purpose == "Тесты"

    comp = await db_get(Computer, env.comp.id)
    assert comp.status == ComputerStatus.booked
    assert (comp.department_id, comp.usage_until, comp.order_number) == (env.dept.id, until, 1)

    [ev] = await events_of(env.comp.id, EventType.booked)
    assert (ev.booking_id, ev.actor_id) == (b.id, env.user.id)
    assert (ev.from_status, ev.to_status) == (ComputerStatus.available, ComputerStatus.booked)


async def test_create_booking_notifies(session, env, notify_mock):
    await bookings.create_booking(session, env.user, payload(env.comp, env.dept))
    notify_mock.assert_awaited_once()
    assert env.comp.name in notify_mock.await_args.args[0]


async def test_create_booking_writeback_sets_pending(session, env, monkeypatch):
    set_writeback(monkeypatch, True)
    await bookings.create_booking(session, env.user, payload(env.comp, env.dept))
    assert (await db_get(Computer, env.comp.id)).writeback_pending is True


async def test_order_numbers_sequential(session, env, make_computer):
    comp2 = await make_computer(pool=env.pool)
    b1 = await bookings.create_booking(session, env.user, payload(env.comp, env.dept))
    b2 = await bookings.create_booking(session, env.user, payload(comp2, env.dept))
    assert (b1.order_number, b2.order_number) == (1, 2)


async def test_create_booking_trims_fields(session, env):
    b = await bookings.create_booking(
        session, env.user,
        payload(env.comp, env.dept, requester_name="  Иван Иванов  ", requester_nick="  ivan  ", purpose="  тест  "))
    assert (b.requester_name, b.requester_nick, b.purpose) == ("Иван Иванов", "ivan", "тест")


@pytest.mark.parametrize("purpose", [None, "", "   "])
async def test_empty_purpose_becomes_none(session, env, purpose):
    b = await bookings.create_booking(session, env.user, payload(env.comp, env.dept, purpose=purpose))
    assert b.purpose is None


# ---------- create_booking: ошибки ----------

@pytest.mark.parametrize("status", [ComputerStatus.booked, ComputerStatus.in_use, ComputerStatus.maintenance,
                                    ComputerStatus.retired, ComputerStatus.unknown])
async def test_unavailable_computer_conflict(session, env, make_computer, status, notify_mock):
    comp = await make_computer(pool=env.pool, status=status.value)
    with pytest.raises(Conflict):
        await bookings.create_booking(session, env.user, payload(comp, env.dept))
    assert await count_bookings() == 0
    notify_mock.assert_not_awaited()


async def test_already_booked_conflict(session, env, make_user):
    await bookings.create_booking(session, env.user, payload(env.comp, env.dept))
    other = await make_user("petrov", department=env.dept)
    with pytest.raises(Conflict):
        await bookings.create_booking(session, other, payload(env.comp, env.dept))
    assert await count_bookings(status="active") == 1


async def test_missing_computer_not_found(session, env, notify_mock):
    with pytest.raises(NotFound):
        await bookings.create_booking(session, env.user, BookingCreate(
            computer_id=9999, department_id=env.dept.id, requester_name="Иван", requester_nick="i"))
    notify_mock.assert_not_awaited()


async def test_archived_computer_not_found(session, env, make_computer):
    comp = await make_computer(pool=env.pool, is_archived=True)
    with pytest.raises(NotFound):
        await bookings.create_booking(session, env.user, payload(comp, env.dept))


async def test_computer_without_pool_not_found(session, env, make_computer):
    comp = await make_computer(pool=None)
    with pytest.raises(NotFound):
        await bookings.create_booking(session, env.user, payload(comp, env.dept))


async def test_unpublished_pool_not_found(session, env, make_pool, make_computer):
    comp = await make_computer(pool=await make_pool("Hidden", is_published=False))
    with pytest.raises(NotFound):
        await bookings.create_booking(session, env.user, payload(comp, env.dept))


async def test_pool_of_other_department(session, env, make_department, make_pool, make_computer, make_user):
    other_dept = await make_department("Other")
    pool = await make_pool("Closed", departments=[other_dept])
    comp, comp2 = await make_computer(pool=pool), await make_computer(pool=pool)
    with pytest.raises(NotFound):
        await bookings.create_booking(session, env.user, payload(comp, env.dept))
    # админ видит любой опубликованный пул, сотрудник нужного отдела — свой
    admin = await make_user("root", role=UserRole.admin.value)
    assert (await bookings.create_booking(session, admin, payload(comp, env.dept))).status == BookingStatus.active
    member = await make_user("member", department=other_dept)
    assert (await bookings.create_booking(session, member, payload(comp2, env.dept))).status == BookingStatus.active


async def test_inactive_department_not_found(session, env, make_department):
    dept = await make_department("Old", is_active=False)
    with pytest.raises(NotFound):
        await bookings.create_booking(session, env.user, payload(env.comp, dept))
    assert (await db_get(Computer, env.comp.id)).status == ComputerStatus.available


async def test_missing_department_not_found(session, env):
    with pytest.raises(NotFound):
        await bookings.create_booking(session, env.user, BookingCreate(
            computer_id=env.comp.id, department_id=9999, requester_name="Иван", requester_nick="i"))


# ---------- Проверка Insight «прямо сейчас» ----------

class FakeInsight:
    """Подделка InsightSource: get_object возвращает/бросает заданное, close запоминается."""

    def __init__(self, result=None, error: Exception | None = None):
        self.mapping = get_mapping()
        self.result, self.error = result, error
        self.get_object = AsyncMock(side_effect=self._get)
        self.closed = False

    async def _get(self, object_id):
        if self.error:
            raise self.error
        return self.result

    async def close(self):
        self.closed = True


def insight_obj(status: str) -> InsightObject:
    return InsightObject(id=100, key="PC-100", label="A001", object_type="Компьютер", attributes={"Статус": status})


@pytest.fixture
def use_insight(monkeypatch):
    def _use(fake: FakeInsight) -> FakeInsight:
        monkeypatch.setattr(bookings, "create_insight_source", lambda: fake)
        return fake
    return _use


@pytest_asyncio.fixture
async def insight_comp(env, make_computer):
    return await make_computer(pool=env.pool, insight_object_id=100, insight_status="Свободен")


async def test_insight_busy_blocks_and_updates_db(session, env, insight_comp, use_insight, notify_mock):
    fake = use_insight(FakeInsight(insight_obj("В использовании")))
    with pytest.raises(Conflict, match="Insight"):
        await bookings.create_booking(session, env.user, payload(insight_comp, env.dept))
    fake.get_object.assert_awaited_once_with(100)
    assert fake.closed
    comp = await db_get(Computer, insight_comp.id)
    assert (comp.insight_status, comp.status) == ("В использовании", ComputerStatus.in_use)
    assert await count_bookings() == 0
    notify_mock.assert_not_awaited()


async def test_insight_free_allows_booking(session, env, insight_comp, use_insight):
    fake = use_insight(FakeInsight(insight_obj("Свободен")))
    b = await bookings.create_booking(session, env.user, payload(insight_comp, env.dept))
    assert b.status == BookingStatus.active and fake.closed


async def test_insight_error_does_not_block(session, env, insight_comp, use_insight):
    fake = use_insight(FakeInsight(error=RuntimeError("Insight недоступен")))
    b = await bookings.create_booking(session, env.user, payload(insight_comp, env.dept))
    assert b.status == BookingStatus.active and fake.closed


async def test_insight_factory_error_does_not_block(session, env, insight_comp, monkeypatch):
    def boom():
        raise RuntimeError("JIRA_URL не задан")
    monkeypatch.setattr(bookings, "create_insight_source", boom)
    b = await bookings.create_booking(session, env.user, payload(insight_comp, env.dept))
    assert b.status == BookingStatus.active


async def test_insight_object_missing_does_not_block(session, env, insight_comp, use_insight):
    fake = use_insight(FakeInsight(result=None))
    b = await bookings.create_booking(session, env.user, payload(insight_comp, env.dept))
    assert b.status == BookingStatus.active and fake.closed


async def test_insight_skipped_when_writeback_pending(session, env, make_computer, use_insight):
    comp = await make_computer(pool=env.pool, insight_object_id=100, writeback_pending=True)
    fake = use_insight(FakeInsight(insight_obj("В использовании")))
    b = await bookings.create_booking(session, env.user, payload(comp, env.dept))
    fake.get_object.assert_not_awaited()
    assert b.status == BookingStatus.active


async def test_insight_skipped_without_object_id(session, env, use_insight):
    fake = use_insight(FakeInsight(insight_obj("В использовании")))
    await bookings.create_booking(session, env.user, payload(env.comp, env.dept))
    fake.get_object.assert_not_awaited()


# ---------- Гонки и уникальный индекс ----------

async def _book_in_own_session(user, data):
    async with SessionLocal() as s:
        return await bookings.create_booking(s, user, data)


@pytest.mark.parametrize("n", [2, 5, 10])
async def test_race_same_computer_one_winner(env, make_user, n):
    users = [await make_user(f"racer{i}", department=env.dept) for i in range(n)]
    results = await asyncio.gather(
        *(_book_in_own_session(u, payload(env.comp, env.dept)) for u in users), return_exceptions=True)

    wins = [r for r in results if isinstance(r, Booking)]
    errors = [r for r in results if not isinstance(r, Booking)]
    assert len(wins) == 1
    assert len(errors) == n - 1 and all(isinstance(e, Conflict) for e in errors), errors
    assert await count_bookings(computer_id=env.comp.id, status="active") == 1
    comp = await db_get(Computer, env.comp.id)
    assert comp.status == ComputerStatus.booked and comp.order_number == wins[0].order_number


async def test_race_different_computers_unique_order_numbers(env, make_user, make_computer):
    n = 8
    users = [await make_user(f"racer{i}", department=env.dept) for i in range(n)]
    comps = [await make_computer(pool=env.pool) for _ in range(n)]
    results = await asyncio.gather(
        *(_book_in_own_session(u, payload(c, env.dept)) for u, c in zip(users, comps)), return_exceptions=True)

    assert all(isinstance(r, Booking) for r in results), results
    numbers = [r.order_number for r in results]
    assert len(set(numbers)) == n
    assert await count_bookings(status="active") == n


async def test_unique_index_active_booking_per_computer(session, env, make_user):
    await bookings.create_booking(session, env.user, payload(env.comp, env.dept))
    other = await make_user("petrov")
    session.add(Booking(computer_id=env.comp.id, department_id=env.dept.id, user_id=other.id, order_number=99,
                        requester_name="X Y", requester_nick="xy", status=BookingStatus.active.value))
    with pytest.raises(IntegrityError, match="uq_bookings_active_computer"):
        await session.commit()
    await session.rollback()


async def test_unique_index_allows_returned_duplicates(session, env, make_user):
    """Индекс частичный: закрытые брони на тот же ПК не мешают."""
    b = await bookings.create_booking(session, env.user, payload(env.comp, env.dept))
    await bookings.return_booking(session, env.user, b.id, None)
    session.add(Booking(computer_id=env.comp.id, department_id=env.dept.id, user_id=env.user.id, order_number=99,
                        requester_name="X Y", requester_nick="xy", status=BookingStatus.active.value))
    await session.commit()


# ---------- return_booking ----------

@pytest_asyncio.fixture
async def booked(session, env):
    b = await bookings.create_booking(session, env.user, payload(env.comp, env.dept))
    env.booking = b
    return env


async def test_return_by_owner(session, booked, notify_mock):
    notify_mock.reset_mock()
    b = await bookings.return_booking(session, booked.user, booked.booking.id, "  всё ок  ")

    assert b.status == BookingStatus.returned
    assert b.returned_by_id == booked.user.id and b.returned_at is not None
    assert b.return_comment == "всё ок"
    comp = await db_get(Computer, booked.comp.id)
    assert comp.status == ComputerStatus.available
    assert (comp.department_id, comp.usage_until, comp.order_number) == (None, None, None)

    [ev] = await events_of(booked.comp.id, EventType.returned)
    assert (ev.booking_id, ev.actor_id) == (b.id, booked.user.id)
    assert (ev.from_status, ev.to_status) == (ComputerStatus.booked, ComputerStatus.available)
    notify_mock.assert_awaited_once()


async def test_return_by_admin(session, booked, make_user):
    admin = await make_user("root", role=UserRole.admin.value)
    b = await bookings.return_booking(session, admin, booked.booking.id, None)
    assert b.status == BookingStatus.returned and b.returned_by_id == admin.id
    assert b.user_id == booked.user.id


@pytest.mark.parametrize("comment", [None, "", "   "])
async def test_return_empty_comment_becomes_none(session, booked, comment):
    b = await bookings.return_booking(session, booked.user, booked.booking.id, comment)
    assert b.return_comment is None


async def test_return_by_stranger_forbidden(session, booked, make_user, notify_mock):
    stranger = await make_user("stranger", department=booked.dept)
    notify_mock.reset_mock()
    with pytest.raises(Forbidden):
        await bookings.return_booking(session, stranger, booked.booking.id, None)
    assert (await db_get(Booking, booked.booking.id)).status == BookingStatus.active
    assert (await db_get(Computer, booked.comp.id)).status == ComputerStatus.booked
    notify_mock.assert_not_awaited()


async def test_return_twice_conflict(session, booked):
    await bookings.return_booking(session, booked.user, booked.booking.id, None)
    with pytest.raises(Conflict):
        await bookings.return_booking(session, booked.user, booked.booking.id, None)
    assert len(await events_of(booked.comp.id, EventType.returned)) == 1


async def test_return_missing_not_found(session, env):
    with pytest.raises(NotFound):
        await bookings.return_booking(session, env.user, 9999, None)


async def test_rebook_after_return(session, booked, make_user):
    await bookings.return_booking(session, booked.user, booked.booking.id, None)
    other = await make_user("petrov", department=booked.dept)
    b2 = await bookings.create_booking(session, other, payload(booked.comp, booked.dept))
    assert b2.status == BookingStatus.active and b2.order_number == 2
    assert await count_bookings(computer_id=booked.comp.id, status="active") == 1


@pytest.mark.parametrize("writeback, insight_status, expected", [
    (False, "Свободен", ComputerStatus.available),
    (False, "В использовании", ComputerStatus.in_use),   # без writeback «занят» в Insight — не наш, остаётся
    (True, "В использовании", ComputerStatus.available),  # с writeback «занят» поставили мы сами
    (True, "Свободен", ComputerStatus.available),
    (True, "В ремонте", ComputerStatus.maintenance),
    (False, "Списан", ComputerStatus.retired),
    (False, "Что-то новое", ComputerStatus.unknown),
    (False, None, ComputerStatus.unknown),
])
async def test_status_after_return(session, env, make_computer, monkeypatch, writeback, insight_status, expected):
    comp = await make_computer(pool=env.pool, insight_status=insight_status)
    b = await bookings.create_booking(session, env.user, payload(comp, env.dept))
    set_writeback(monkeypatch, writeback)
    await bookings.return_booking(session, env.user, b.id, None)

    db = await db_get(Computer, comp.id)
    assert db.status == expected
    assert db.writeback_pending is writeback
    [ev] = await events_of(comp.id, EventType.returned)
    assert ev.to_status == expected


# ---------- list_user_bookings ----------

async def test_list_user_bookings_own_only_newest_first(session, env, make_user, make_computer):
    other = await make_user("petrov", department=env.dept)
    comps = [env.comp] + [await make_computer(pool=env.pool) for _ in range(3)]
    mine = [await bookings.create_booking(session, env.user, payload(c, env.dept)) for c in comps[:3]]
    await bookings.create_booking(session, other, payload(comps[3], env.dept))

    rows = await bookings.list_user_bookings(session, env.user)
    assert [b.id for b in rows] == [b.id for b in reversed(mine)]
    assert all(b.user_id == env.user.id for b in rows)
    assert await bookings.list_user_bookings(session, await make_user("nobody")) == []
