"""Сервис бронирования (app/services/bookings.py) на реальном PostgreSQL."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core import clock
from app.core.errors import Conflict, DomainError, Forbidden, NotFound
from app.db.session import SessionLocal
from app.integrations.insight.base import InsightObject
from app.integrations.insight.factory import get_mapping
from app.models import (
    AssetEvent,
    Booking,
    BookingExtension,
    BookingStatus,
    Computer,
    ComputerStatus,
    EventType,
    UserRole,
)
from app.schemas.booking import BookingCreate, BookingExtend
from app.services import bookings, runtime
from app.services.runtime import RuntimeConfig
from tests.sync_fakes import add_booking

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
    kw.setdefault("expected_return_at", clock.today())
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
    until = clock.today() + timedelta(days=7)
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
            computer_id=9999, department_id=env.dept.id, requester_name="Иван", requester_nick="i",
            expected_return_at=clock.today()))
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
    assert (await bookings.create_booking(session, member, payload(comp2, other_dept))).status == BookingStatus.active


async def test_admin_cannot_order_for_inactive_department(session, env, make_department, make_user):
    dept = await make_department("Old", is_active=False)
    admin = await make_user("root", role=UserRole.admin.value)
    with pytest.raises(NotFound):
        await bookings.create_booking(session, admin, payload(env.comp, dept))
    assert (await db_get(Computer, env.comp.id)).status == ComputerStatus.available


async def test_admin_unknown_department_not_found(session, env, make_user):
    admin = await make_user("root", role=UserRole.admin.value)
    with pytest.raises(NotFound):
        await bookings.create_booking(session, admin, BookingCreate(
            computer_id=env.comp.id, department_id=9999, requester_name="Иван", requester_nick="i",
            expected_return_at=clock.today()))


# ---------- отдел заказа: свой отдел сотрудника ----------

async def test_order_department_defaults_to_own_when_not_given(session, env):
    booking = await bookings.create_booking(session, env.user, BookingCreate(
        computer_id=env.comp.id, requester_name="Иван", requester_nick="i", expected_return_at=clock.today()))
    assert booking.department_id == env.dept.id


async def test_user_cannot_order_for_foreign_department(session, env, make_department):
    other = await make_department("Other")
    with pytest.raises(Forbidden, match="на ваш отдел"):
        await bookings.create_booking(session, env.user, payload(env.comp, other))
    assert (await db_get(Computer, env.comp.id)).status == ComputerStatus.available


async def test_user_without_department_cannot_order(session, env, make_user):
    loner = await make_user("loner")
    with pytest.raises(Conflict, match="не назначен отдел"):
        await bookings.create_booking(session, loner, payload(env.comp, env.dept))
    assert (await db_get(Computer, env.comp.id)).status == ComputerStatus.available


async def test_user_with_inactive_own_department_cannot_order(session, env, make_department, make_user):
    off = await make_department("Off", is_active=False)
    user = await make_user("offuser", department=off)
    with pytest.raises(Conflict, match="отдел отключён"):
        await bookings.create_booking(session, user, BookingCreate(
            computer_id=env.comp.id, requester_name="Иван", requester_nick="i", expected_return_at=clock.today()))


async def test_admin_orders_for_any_department_or_own(session, env, make_user, make_department, make_computer):
    admin = await make_user("root", role=UserRole.admin.value, department=await make_department("Admins"))
    other = await make_department("Other")
    for_other = await bookings.create_booking(session, admin, payload(env.comp, other))
    assert for_other.department_id == other.id
    own = await bookings.create_booking(session, admin, BookingCreate(
        computer_id=(await make_computer(pool=env.pool)).id, requester_name="Иван", requester_nick="i",
        expected_return_at=clock.today()))
    assert own.department_id == admin.department_id


async def test_admin_without_department_must_name_one(session, env, make_user):
    admin = await make_user("root", role=UserRole.admin.value)
    with pytest.raises(DomainError, match="Укажите отдел"):
        await bookings.create_booking(session, admin, BookingCreate(
            computer_id=env.comp.id, requester_name="Иван", requester_nick="i", expected_return_at=clock.today()))


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
        *(_book_in_own_session(u, payload(c, env.dept)) for u, c in zip(users, comps, strict=True)), return_exceptions=True)

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


async def test_return_by_teammate(session, booked, make_user):
    """Участник команды брони возвращает ПК так же, как арендатор; в журнале — тот, кто вернул на деле."""
    mate = await make_user("mate", department=booked.dept)
    b = await bookings.return_booking(session, mate, booked.booking.id, None)
    assert b.status == BookingStatus.returned and b.returned_by_id == mate.id and b.user_id == booked.user.id
    [ev] = await events_of(booked.comp.id, EventType.returned)
    assert ev.actor_id == mate.id


@pytest.mark.parametrize("team", ["other", "none"])
async def test_return_by_stranger_forbidden(session, booked, make_user, make_department, notify_mock, team):
    stranger = await make_user("stranger", department=await make_department("Ops") if team == "other" else None)
    notify_mock.reset_mock()
    with pytest.raises(Forbidden, match="участник его команды или администратор"):
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


# ---------- extend_booking ----------

async def extensions_of(booking_id) -> list[BookingExtension]:
    async with SessionLocal() as s:
        q = select(BookingExtension).where(BookingExtension.booking_id == booking_id).order_by(BookingExtension.id)
        return list((await s.scalars(q)).unique().all())


def extend(days: int, comment: str | None = None) -> BookingExtend:
    return BookingExtend(expected_return_at=clock.today() + timedelta(days=days), comment=comment)


async def test_extend_by_owner(session, booked):
    new = clock.today() + timedelta(days=7)
    b = await bookings.extend_booking(session, booked.user, booked.booking.id, extend(7, "  ещё тесты  "))

    assert b.expected_return_at == new and b.status == BookingStatus.active
    assert (await db_get(Computer, booked.comp.id)).usage_until == new
    [ext] = await extensions_of(b.id)
    assert (ext.user_id, ext.old_return_at, ext.new_return_at, ext.comment) == (booked.user.id, clock.today(), new,
                                                                               "ещё тесты")
    assert ext.acknowledged_at is None and ext.acknowledged_by_id is None  # ждёт «Принято» админа
    [ev] = await events_of(booked.comp.id, EventType.extended)
    assert (ev.booking_id, ev.actor_id) == (b.id, booked.user.id)
    assert ev.message == (f"Заказ №{b.order_number}: срок продлён с {clock.today():%d.%m.%Y} "
                          f"до {new:%d.%m.%Y}: ещё тесты")


async def test_extend_by_admin_is_already_acknowledged(session, booked, make_user):
    admin = await make_user("root", role=UserRole.admin.value)
    await bookings.extend_booking(session, admin, booked.booking.id, extend(3))
    [ext] = await extensions_of(booked.booking.id)
    assert ext.user_id == admin.id and ext.acknowledged_by_id == admin.id and ext.acknowledged_at is not None


@pytest.mark.parametrize("comment", [None, "", "   "])
async def test_extend_empty_comment_becomes_none(session, booked, comment):
    await bookings.extend_booking(session, booked.user, booked.booking.id, extend(1, comment))
    [ext] = await extensions_of(booked.booking.id)
    assert ext.comment is None


@pytest.mark.parametrize("writeback", [True, False])
async def test_extend_writeback_sets_pending(session, booked, monkeypatch, writeback):
    set_writeback(monkeypatch, writeback)
    await bookings.extend_booking(session, booked.user, booked.booking.id, extend(1))
    assert (await db_get(Computer, booked.comp.id)).writeback_pending is writeback


async def test_extend_to_same_date_conflict(session, booked):
    with pytest.raises(Conflict, match="позже текущего"):
        await bookings.extend_booking(session, booked.user, booked.booking.id, extend(0))
    assert (await db_get(Booking, booked.booking.id)).expected_return_at == clock.today()
    assert await extensions_of(booked.booking.id) == []
    assert await events_of(booked.comp.id, EventType.extended) == []


async def test_extend_booking_without_date(session, booked):
    """У старых броней срока нет: продлить можно на любую дату с сегодняшней."""
    booked.booking.expected_return_at = None
    await session.commit()
    b = await bookings.extend_booking(session, booked.user, booked.booking.id, extend(0))
    assert b.expected_return_at == clock.today()
    [ext] = await extensions_of(b.id)
    assert ext.old_return_at is None
    [ev] = await events_of(booked.comp.id, EventType.extended)
    assert ev.message == f"Заказ №{b.order_number}: срок продлён до {clock.today():%d.%m.%Y}"


async def test_extend_by_teammate(session, booked, make_user):
    """Продление командой: в журнал попадает продливший, ожидает «Принято» как продление арендатора."""
    mate = await make_user("mate", department=booked.dept)
    b = await bookings.extend_booking(session, mate, booked.booking.id, extend(2))
    assert b.expected_return_at == clock.today() + timedelta(days=2) and b.user_id == booked.user.id
    [ext] = await extensions_of(b.id)
    assert ext.user_id == mate.id and ext.acknowledged_at is None


@pytest.mark.parametrize("team", ["other", "none"])
async def test_extend_by_stranger_forbidden(session, booked, make_user, make_department, team):
    stranger = await make_user("stranger", department=await make_department("Ops") if team == "other" else None)
    with pytest.raises(Forbidden, match="Продлить аренду может тот, кто бронировал ПК, участник его команды"):
        await bookings.extend_booking(session, stranger, booked.booking.id, extend(1))
    assert await extensions_of(booked.booking.id) == []
    assert (await db_get(Booking, booked.booking.id)).expected_return_at == clock.today()


async def test_extend_returned_booking_conflict(session, booked):
    await bookings.return_booking(session, booked.user, booked.booking.id, None)
    with pytest.raises(Conflict, match="закрыто"):
        await bookings.extend_booking(session, booked.user, booked.booking.id, extend(1))


async def test_extend_missing_not_found(session, env):
    with pytest.raises(NotFound):
        await bookings.extend_booking(session, env.user, 9999, extend(1))


# ---------- list_user_bookings ----------

async def test_list_user_bookings_own_only_newest_first(session, env, make_user, make_computer, make_department):
    """Без отдела — только свои; чужая команда не видна."""
    other = await make_user("petrov", department=await make_department("Ops"))
    loner = await make_user("loner")
    comps = [env.comp] + [await make_computer(pool=env.pool) for _ in range(4)]
    mine = [await add_booking(session, c, loner, env.dept) for c in comps[:3]]  # заказы до правила про отдел сотрудника
    await add_booking(session, comps[3], other, env.dept)

    rows = await bookings.list_user_bookings(session, loner)
    assert [b.id for b in rows] == [b.id for b in reversed(mine)]
    assert all(b.user_id == loner.id for b in rows)
    assert await bookings.list_user_bookings(session, await make_user("nobody")) == []


async def test_list_user_bookings_includes_team_without_duplicates(session, env, make_user, make_computer,
                                                                   make_department):
    """Свои и брони команды (в том числе закрытые), по разу каждая; бронь чужой команды не видна."""
    mate = await make_user("petrov", department=env.dept)
    foreign = await make_user("sidorov", department=await make_department("Ops"))
    comps = [env.comp] + [await make_computer(pool=env.pool) for _ in range(3)]
    own = await bookings.create_booking(session, env.user, payload(comps[0], env.dept))
    team = await bookings.create_booking(session, mate, payload(comps[1], env.dept))
    closed = await bookings.create_booking(session, mate, payload(comps[2], env.dept))
    await bookings.return_booking(session, mate, closed.id, None)
    await add_booking(session, comps[3], foreign, await make_department("Third"))

    rows = await bookings.list_user_bookings(session, env.user)
    assert [b.id for b in rows] == [closed.id, team.id, own.id]
